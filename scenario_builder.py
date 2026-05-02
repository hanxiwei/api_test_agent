"""
阶段2: 多步骤场景生成器

功能:
1. 将解析出的 API 端点按"资源"分组
2. 推断 CRUD 依赖链 (POST → GET → PUT → DELETE)
3. 调用 LLM 生成包含多个步骤的 pytest 场景函数
"""
import os
from openai import OpenAI
from dotenv import load_dotenv
from config import get_config

load_dotenv(override=True)

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL")
)

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
2. 严格按照步骤顺序执行: 创建资源 → 提取返回的 id → 用 id 查询 → 用 id 更新 → 用 id 删除。
3. 每个步骤都要有断言:
   - 创建: assert status_code == 201, assert "id" in response.json()
   - 查询: assert status_code == 200, assert 返回的 id 与创建的一致
   - 更新: assert status_code == 200
   - 删除: assert status_code == 204 (或 200)
4. 使用 requests 库，URL 用 f"{{base_url}}/path" 拼接。
5. 使用 try/finally 做清理: 即使中间步骤失败，finally 中也要尝试删除已创建的资源。
6. 在 try 之前初始化 created_id = None，创建成功后赋值。
7. 【严格遵守】只输出纯 Python 代码，不要 ```python ``` 标记，不要任何解释文字。

参考示例（不同 API，但结构相同）:

import requests

def test_example_crud():
    base_url = "http://localhost:8080"
    created_id = None
    try:
        resp = requests.post(f"{{base_url}}/items", json={{"name": "test-item"}})
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        created_id = data["id"]

        resp = requests.get(f"{{base_url}}/items/{{created_id}}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created_id

        resp = requests.put(f"{{base_url}}/items/{{created_id}}", json={{"name": "updated"}})
        assert resp.status_code == 200

        resp = requests.delete(f"{{base_url}}/items/{{created_id}}")
        assert resp.status_code == 204
    finally:
        if created_id is not None:
            requests.delete(f"{{base_url}}/items/{{created_id}}")
"""
    return prompt


# ── 步骤4: 调用 LLM 生成场景代码 ───────────────────────────────

def generate_scenario_code(prompt):
    """调用 LLM 并返回生成的 Python 代码字符串"""
    model_name = os.getenv("LLM_MODEL") or get_config("llm", "model", "gpt-4o-mini")
    temp = get_config("llm", "temperature", 0.2)
    
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "你是一个资深的 Python 测试开发工程师，请生成高质量的场景测试代码。"},
            {"role": "user", "content": prompt}
        ],
        temperature=temp
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
        f.write("import pytest\nimport requests\n\n\n")
        f.write(code)

    print(f"[OK] 场景用例已保存至: {filepath}")
    return filepath


# ── 主流程: 从端点列表到生成场景 ──────────────────────────────────

def build_all_scenarios(endpoints, base_url="http://localhost:8080"):
    """
    一键流程: 分组 → 排序 → 生成 prompt → 调 LLM → 保存文件
    返回生成的所有场景文件路径列表
    """
    groups = group_endpoints_by_resource(endpoints)
    print(f"共识别出 {len(groups)} 个可构建场景的资源: {list(groups.keys())}")

    generated_files = []

    for resource_name, group in groups.items():
        crud_chain = infer_crud_chain(group)

        methods = [ep['method'] for ep in crud_chain]
        if 'POST' not in methods:
            print(f"[跳过] 资源 '{resource_name}' 没有 POST 端点，无法创建资源")
            continue

        print(f"\n=== 为资源 '{resource_name}' 生成 CRUD 场景 ===")
        chain_desc = ' → '.join(f"{ep['method']} {ep['path']}" for ep in crud_chain)
        print(f"执行链: {chain_desc}")

        prompt = build_scenario_prompt(resource_name, crud_chain, base_url)
        print("正在调用 LLM 生成场景代码...")
        code = generate_scenario_code(prompt)
        filepath = save_scenario(code, resource_name)
        generated_files.append(filepath)

    return generated_files


# ── 本地测试入口 ──────────────────────────────────────────────────


