import os
import re
from dotenv import load_dotenv
from llm_client import chat_completion

load_dotenv(override=True)

from memory import (
    get_short_memory, save_short_memory,
    get_long_memory, save_long_memory,
    generate_error_signature
)


def diagnose_failure(error_log, original_code):
    """
    调用 LLM 分析失败根因，判断是测试代码 bug 还是后端接口 bug。
    返回: {"category": "test_bug"|"backend_bug", "reason": "..."}
    """
    prompt = f"""你是一个资深的测试开发工程师。分析以下 pytest 测试失败的根本原因，判断失败类别。

【错误日志】：
{error_log}

【原始测试代码】：
{original_code}

判断标准：
- TEST_BUG: 测试代码本身有逻辑问题（断言条件错误、URL路径拼错、缺少必填参数、请求体构造错误、轮询超时时间设置过短、轮询间隔不合理、task_id 提取路径错误、status 字段名拼错等）
- BACKEND_BUG: 被测后端接口有问题（返回500/503错误、响应字段缺失或类型不匹配、接口行为与API文档不一致、ConnectionError说明后端根本没启动等）

【异步接口特别注意】：
如果测试代码包含轮询逻辑（while循环 + time.sleep），额外注意以下区分：
- 轮询超时（pytest.fail "轮询超时"）→ 优先看超时阈值是否合理:
  * 若代码中 timeout 明显偏短（如 < 10s 而文档要求 60s+）→ TEST_BUG
  * 若 timeout 设置合理但后端始终返回 processing → BACKEND_BUG（后端任务卡住）
- status 字段取值报错（如 KeyError: 'status'）→ 检查轮询接口是否真的返回了该字段:
  * 若轮询接口文档承诺返回 status 但实际没返回 → BACKEND_BUG
  * 若测试代码取错了字段名 → TEST_BUG
- task_id 未找到（如 POST 返回 200 而非 202，或响应中无 task_id）→ BACKEND_BUG（接口行为与文档不一致）
- 结果字段缺失（如 done 状态下无 image_url）→ BACKEND_BUG

请严格按以下格式输出（两行，不要多余内容）：
<类别>
<理由（一句话）>

其中类别必须是 TEST_BUG 或 BACKEND_BUG。"""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": "你是一个精确的测试失败分析专家。只输出两行结果。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')
        category = lines[0].strip().upper()
        reason = lines[1].strip() if len(lines) > 1 else ""

        if "BACKEND" in category:
            return {"category": "backend_bug", "reason": reason}
        else:
            return {"category": "test_bug", "reason": reason}
    except Exception as e:
        print(f"  [诊断] LLM 诊断失败: {e}，默认按 test_bug 处理")
        return {"category": "test_bug", "reason": "诊断异常，回退到默认修复流程"}


def mark_as_backend_bug(file_path, reason):
    """给测试函数添加 xfail 标记，标识为后端疑似 bug，不要强行修复"""
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()

    short_reason = reason[:100] if reason else "后端接口异常，待人工确认"
    xfail_marker = f'@pytest.mark.xfail(reason="疑似后端Bug: {short_reason}", strict=False)\n'

    if '@pytest.mark.xfail' not in code:
        code = re.sub(r'^(def test_\w+)', xfail_marker + r'\1', code, flags=re.MULTILINE)

    backup_path = file_path + ".bak"
    if not os.path.exists(backup_path):
        os.rename(file_path, backup_path)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)
    print(f"  [Healer] 疑似后端 Bug，已标记 xfail 并跳过修复: {file_path}")


def heal_testcase(file_path, original_code, error_log, round_num=1):
    """
    先诊断失败根因，再决定是修复测试代码还是标记为后端 bug。
    返回: {"action": "test_bug"|"backend_bug", ...}
    """
    print(f"\n[Healer] 开始处理: {file_path} (第 {round_num} 轮)")

    error_signature = generate_error_signature(error_log)
    print(f"  [Healer] 错误签名: {error_signature}")

    # ── 新增：诊断失败根因 ──
    diagnosis = diagnose_failure(error_log, original_code)
    print(f"  [诊断] 类别: {diagnosis['category']}, 理由: {diagnosis['reason']}")

    if diagnosis['category'] == 'backend_bug':
        mark_as_backend_bug(file_path, diagnosis['reason'])
        return {"action": "backend_bug", "reason": diagnosis['reason']}
    # ── 诊断结束，下面只处理 test_bug ──

    # 查短期记忆
    short_term_fix = get_short_memory(error_signature)
    if short_term_fix:
        print("  [Memory] 短期记忆命中，直接复用。")
        return {"action": "test_bug", "code": short_term_fix}

    # 查长期记忆
    long_term_examples = get_long_memory(error_log, top_k=2)
    example_prompt = ""
    if long_term_examples:
        example_prompt = "\n    【参考经验】：你之前遇到过类似错误并成功修复，可以参考以下历史修复方案：\n"
        for i, example in enumerate(long_term_examples, 1):
            example_prompt += f"    --- 历史错误 {i} ---\n    {example['past_error']}\n"
            example_prompt += f"    --- 历史修复代码 {i} ---\n    {example['past_fixed_code']}\n\n"
        print(f"  [Memory] 长期记忆命中 {len(long_term_examples)} 条相似经验。")

    prompt = f"""
你是一个资深的自动化测试专家。
以下是一个 pytest 测试脚本在执行时遇到的错误日志。请分析错误原因，并输出修复后的完整 Python 代码。

【原始代码】：
{original_code}

【当前错误日志】：
{error_log}
{example_prompt}
修复要求：
1. 保持原有的测试意图和 CRUD 流程。
2. 如果是因为缺少必要参数，请补充符合规范的默认值。
3. 如果是因为断言逻辑错误（比如断言的字段名不对、期望状态码不合理），请修正断言。
4. 如果是因为请求体/参数格式不符合接口要求，请修正请求构造逻辑。
5. 【严格遵守】只输出修复后的纯 Python 代码，不要有 Markdown 标签，不要解释。
"""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": "你是一个自动修复 Python 测试代码的机器人。只输出代码。"},
                {"role": "user", "content": prompt}
            ]
        )

        code = response.choices[0].message.content.strip()

        if code.startswith("```python"):
            code = code[len("```python"):]
        if code.startswith("```"):
            code = code[len("```"):]
        if code.endswith("```"):
            code = code[:-len("```")]

        code = code.strip()
        save_short_memory(error_signature, code)
        return {"action": "test_bug", "code": code}

    except Exception as e:
        print(f"[Healer] 调用 LLM 失败: {e}")
        return {"action": "test_bug", "code": original_code}


def apply_fix(file_path, new_code):
    """将修复后的测试代码写回文件"""
    backup_path = file_path + ".bak"
    if not os.path.exists(backup_path):
        os.rename(file_path, backup_path)

    with open(file_path, "w", encoding="utf-8") as f:
        if "import requests" not in new_code:
            f.write("import requests\n")
        if "import pytest" not in new_code:
            f.write("import pytest\n\n")
        f.write(new_code)
    print(f"[Healer] 修复代码已写入: {file_path}")

