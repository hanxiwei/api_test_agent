"""
阶段2: 多步骤场景生成器

功能:
1. 将解析出的 API 端点按"资源"分组
2. 推断 CRUD 依赖链 (POST → GET → PUT → DELETE)
3. 调用 LLM 生成包含多个步骤的 pytest 场景函数
"""
import os
from llm_client import chat_completion

# ── 步骤1: 按资源分组 ─────────────────────────────────────────

def group_endpoints_by_resource(endpoints):
    """
    根据 path 的第一段提取资源名，把操作同一资源的端点归为一组。

    例如 /pet/{petId} -> pet, /store/order/{id} -> store

    返回: {resource_name: [endpoint, ...]}
    只保留 >= 2 个端点的组（单个端点用阶段1的生成器即可）
    """
    groups = {}
    for ep in endpoints:
        segments = [s for s in ep['path'].split('/') if s]
        resource = segments[0].strip('{}') if segments else 'root'
        groups.setdefault(resource, []).append(ep)

    return {k: v for k, v in groups.items() if len(v) >= 2}


# ── 步骤2: 按 CRUD 语义排序 ────────────────────────────────────

METHOD_ORDER = {'POST': 0, 'GET': 1, 'PUT': 2, 'PATCH': 2, 'DELETE': 3}


def infer_crud_chain(resource_group):
    """
    将一个资源组内的端点按 CRUD 语义排序:
    POST (创建) → GET (查询) → PUT/PATCH (更新) → DELETE (删除)
    """
    return sorted(resource_group, key=lambda ep: METHOD_ORDER.get(ep['method'], 99))


# ── 步骤3: 构造 few-shot prompt ─────────────────────────────────

def build_scenario_prompt(resource_name, crud_chain, base_url="http://localhost:8080"):
    """
    构造 few-shot prompt，描述 CRUD 调用链，
    让 LLM 生成包含多个步骤的 pytest 函数。
    """
    steps_desc = []
    for i, ep in enumerate(crud_chain, 1):
        method = ep['method']
        path = ep['path']
        op_id = ep['operationId']
        params = ep.get('parameters', [])
        req_body = ep.get('requestBody', {})

        line = f"步骤{i} [{method}] {path} (operationId: {op_id})"
        if params:
            param_names = [p['name'] for p in params]
            line += f"\n  路径参数: {param_names}"
        if req_body:
            try:
                schema = req_body['content']['application/json']['schema']
                required = schema.get('required', [])
                props = list(schema.get('properties', {}).keys())
                line += f"\n  请求体字段: {props}, 必填: {required}"
            except (KeyError, TypeError):
                line += "\n  请求体: 需要 JSON body"

        steps_desc.append(line)

    steps_text = "\n\n".join(steps_desc)

    prompt = f"""
你是一个资深的 Python 测试开发工程师。请根据以下 API 信息，生成一个包含多个步骤的 pytest 场景测试函数。

目标资源: {resource_name}
Base URL: {base_url}

API 调用链（按此顺序执行）:

{steps_text}

要求:
1. 函数名必须为 test_{resource_name}_crud。
2. 在函数开头生成 test_run_id = uuid.uuid4().hex[:8]。
3. 【测试数据隔离】创建资源时，将 test_run_id 注入到请求体的 name 字段（或其他可区分字段）中，格式为 "test-{resource_name}-{{test_run_id}}"。这确保不同运行之间不会因为残留数据同名而冲突。
4. 严格按照步骤顺序执行: 创建资源 → 提取返回的 id → 用 id 查询 → 用 id 更新 → 用 id 删除。
5. 每个步骤都要有断言:
   - 创建: assert status_code == 201, assert "id" in response.json()
   - 查询: assert status_code == 200, assert 返回的 id 与创建的一致
   - 更新: assert status_code == 200
   - 删除: assert status_code == 204 (或 200)
6. 使用 requests 库，URL 用 f"{{base_url}}/path" 拼接。
7. 使用 try/finally 做清理: 即使中间步骤失败，finally 中也要尝试删除已创建的资源。
8. 在 try 之前初始化 created_id = None，创建成功后赋值。
9. 【严格遵守】只输出纯 Python 代码，不要 ```python ``` 标记，不要任何解释文字。

参考示例（不同 API，但结构相同）:

import uuid
import requests

def test_example_crud():
    test_run_id = uuid.uuid4().hex[:8]
    base_url = "http://localhost:8080"
    created_id = None
    try:
        resp = requests.post(f"{{base_url}}/items", json={{"name": f"test-item-{{test_run_id}}"}})
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        created_id = data["id"]

        resp = requests.get(f"{{base_url}}/items/{{created_id}}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created_id

        resp = requests.put(f"{{base_url}}/items/{{created_id}}", json={{"name": f"updated-{{test_run_id}}"}})
        assert resp.status_code == 200

        resp = requests.delete(f"{{base_url}}/items/{{created_id}}")
        assert resp.status_code == 204
    finally:
        if created_id is not None:
            requests.delete(f"{{base_url}}/items/{{created_id}}")
"""
    return prompt


# ── 步骤3.5: 异步场景 prompt ────────────────────────────────────

def find_poll_endpoint(endpoints, poll_path):
    """根据 x-async.poll_path 找到对应的轮询端点定义"""
    for ep in endpoints:
        if ep['path'] == poll_path:
            return ep
    return None


def build_async_prompt(resource_name, async_ep, poll_ep, base_url="http://localhost:8080"):
    """构造异步接口轮询测试的 few-shot prompt"""
    x_async = async_ep['x-async']

    # 描述提交接口的请求体
    req_body_desc = ""
    req_body = async_ep.get('requestBody', {})
    if req_body:
        try:
            schema = req_body['content']['application/json']['schema']
            required = schema.get('required', [])
            props = list(schema.get('properties', {}).keys())
            req_body_desc = f"请求体字段: {props}, 必填: {required}"
        except (KeyError, TypeError):
            req_body_desc = "需要 JSON body"

    # 描述轮询接口的响应体
    poll_resp_desc = ""
    poll_responses = poll_ep.get('responses', {}) if poll_ep else {}
    if '200' in poll_responses:
        try:
            schema = poll_responses['200']['content']['application/json']['schema']
            props = list(schema.get('properties', {}).keys())
            poll_resp_desc = f"轮询响应字段: {props}"
        except (KeyError, TypeError):
            pass

    result_fields = x_async.get('result_fields', [])

    prompt = f"""
你是一个资深的 Python 测试开发工程师。请根据以下 API 信息，生成一个异步接口轮询测试函数。

目标资源: {resource_name}
Base URL: {base_url}

【异步任务提交接口】
{async_ep['method']} {async_ep['path']} (operationId: {async_ep['operationId']})
{req_body_desc}

【轮询接口】
GET {async_ep['x-async']['poll_path']}
{poll_resp_desc}
状态值: 进行中 → 由 status_field 字段表示，成功值为 "{x_async['success_value']}"，失败值为 "{x_async['failure_value']}"

【轮询策略】
- 轮询间隔: {x_async['poll_interval']} 秒
- 超时时间: {x_async['poll_timeout']} 秒
- 状态字段: {x_async['status_field']}
- 成功时需断言的结果字段: {result_fields}

要求:
1. 函数名必须为 test_{resource_name}_generate_async。
2. 在函数开头生成 test_run_id = uuid.uuid4().hex[:8]。
3. 发送 POST 提交异步任务，请求体中用 test_run_id 构造一个合理的参数值（如 prompt 字段用 f"test-prompt-{{test_run_id}}"）。
4. 断言 POST 返回 202，并从响应中提取 task_id。
5. 用 while 循环轮询 GET 接口，间隔 {x_async['poll_interval']} 秒，最多等 {x_async['poll_timeout']} 秒。
6. 轮询到 "{x_async['success_value']}" 状态时:
   - 跳出循环
   - 逐个 assert result_fields 中的字段存在于响应 JSON 中
{chr(10).join(f'   - assert {f!r} in data' for f in result_fields) if result_fields else '   - 对关键结果字段做存在性断言'}
7. 轮询到 "{x_async['failure_value']}" 状态时:
   - 调用 pytest.fail(f"任务失败: {{error_message}}")，error_message 从响应的 error 字段取
8. 超过 {x_async['poll_timeout']} 秒未完成:
   - 调用 pytest.fail(f"轮询超时: 任务 {{task_id}} 未在 {x_async['poll_timeout']}s 内完成")
9. 使用 try/finally 确保失败时打印 task_id 便于人工排查。
10. 【严格遵守】只输出纯 Python 代码，不要 ```python ``` 标记，不要任何解释文字。

参考示例（不同 API，但结构相同）:

import uuid
import time
import requests

def test_example_async():
    test_run_id = uuid.uuid4().hex[:8]
    base_url = "http://localhost:8080/v1"
    task_id = None
    try:
        resp = requests.post(f"{{base_url}}/tasks", json={{"input": f"test-input-{{test_run_id}}"}})
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        task_id = data["task_id"]

        start_time = time.time()
        while True:
            resp = requests.get(f"{{base_url}}/tasks/{{task_id}}")
            assert resp.status_code == 200
            status_data = resp.json()
            status = status_data["status"]

            if status == "done":
                assert "result_url" in status_data
                assert status_data["result_url"].startswith("http")
                break
            elif status == "failed":
                error = status_data.get("error", "unknown error")
                pytest.fail(f"Task failed: {{error}}")
            elif time.time() - start_time > 60:
                pytest.fail(f"Polling timeout for task {{task_id}}")
            time.sleep(2)
    finally:
        if task_id:
            print(f"Task ID for manual cleanup: {{task_id}}")
"""
    return prompt


# ── 步骤4: 调用 LLM 生成场景代码 ───────────────────────────────

def generate_scenario_code(prompt):
    """调用 LLM 并返回生成的 Python 代码字符串"""
    response = chat_completion(
        messages=[
            {"role": "system", "content": "你是一个资深的 Python 测试开发工程师，请生成高质量的场景测试代码。"},
            {"role": "user", "content": prompt}
        ]
    )

    code = response.choices[0].message.content.strip()

    # 万一 LLM 不听话加了 markdown 标记，去掉它
    if code.startswith("```python"):
        code = code[len("```python"):]
    if code.startswith("```"):
        code = code[len("```"):]
    if code.endswith("```"):
        code = code[:-len("```")]

    return code.strip()


# ── 步骤5: 保存场景文件 ────────────────────────────────────────

def save_scenario(code, resource_name):
    os.makedirs("generated_tests", exist_ok=True)
    filename = f"test_scenario_{resource_name}_crud.py"
    filepath = os.path.join("generated_tests", filename)

    with open(filepath, "w", encoding="utf-8") as f:
        # LLM 会按参考示例自己生成 import，这里补一份 pytest 兜底（xfail 标记需要）
        if "import pytest" not in code:
            f.write("import pytest\n")
        if "import uuid" not in code:
            f.write("import uuid\n")
        if "import requests" not in code:
            f.write("import requests\n")
        if "import pytest" not in code or "import uuid" not in code or "import requests" not in code:
            f.write("\n")
        f.write(code)

    print(f"[OK] 场景用例已保存至: {filepath}")
    return filepath


# ── 主流程: 从端点列表到生成场景 ──────────────────────────────────

def build_all_scenarios(endpoints, base_url="http://localhost:8080"):
    """
    一键流程: 分组 → 识别异步接口 → 分别生成异步轮询 / CRUD 场景测试
    返回生成的所有场景文件路径列表
    """
    groups = group_endpoints_by_resource(endpoints)
    print(f"共识别出 {len(groups)} 个可构建场景的资源: {list(groups.keys())}")

    generated_files = []

    for resource_name, group in groups.items():
        # ── 分离异步和同步端点 ──
        async_eps = [ep for ep in group if ep.get('x-async')]
        sync_eps = [ep for ep in group if not ep.get('x-async')]

        # ── 生成异步测试 ──
        for async_ep in async_eps:
            x_async = async_ep['x-async']
            poll_path = x_async['poll_path']
            poll_ep = find_poll_endpoint(group, poll_path)

            if not poll_ep:
                print(f"[警告] 异步端点 {async_ep['method']} {async_ep['path']} 的轮询接口 {poll_path} 未在规范中找到，跳过")
                continue

            print(f"\n=== 为资源 '{resource_name}' 生成异步轮询场景 ===")
            print(f"提交: {async_ep['method']} {async_ep['path']}")
            print(f"轮询: GET {poll_path}")
            print(f"超时: {x_async['poll_timeout']}s, 间隔: {x_async['poll_interval']}s")

            prompt = build_async_prompt(resource_name, async_ep, poll_ep, base_url)
            print("正在调用 LLM 生成异步测试代码...")
            code = generate_scenario_code(prompt)
            # 异步场景用 _async 后缀，避免和 CRUD 场景文件名冲突
            filepath = save_scenario(code, f"{resource_name}_async")
            generated_files.append(filepath)

        # ── 生成同步 CRUD 测试 ──
        if len(sync_eps) >= 2:
            crud_chain = infer_crud_chain(sync_eps)
            methods = [ep['method'] for ep in crud_chain]
            if 'POST' in methods:
                print(f"\n=== 为资源 '{resource_name}' 生成 CRUD 场景 ===")
                chain_desc = ' → '.join(f"{ep['method']} {ep['path']}" for ep in crud_chain)
                print(f"执行链: {chain_desc}")

                prompt = build_scenario_prompt(resource_name, crud_chain, base_url)
                print("正在调用 LLM 生成场景代码...")
                code = generate_scenario_code(prompt)
                filepath = save_scenario(code, resource_name)
                generated_files.append(filepath)
            else:
                print(f"[跳过] 资源 '{resource_name}' 同步端点无 POST，无法构建 CRUD 链")
        elif async_eps:
            # 有异步端点但同步端点不足 2 个，正常（已生成异步测试）
            pass
        else:
            print(f"[跳过] 资源 '{resource_name}' 端点不足（{len(sync_eps)} 个），无法构建场景")

    return generated_files


# ── 本地测试入口 ──────────────────────────────────────────────────


