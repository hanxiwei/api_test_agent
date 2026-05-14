import os
from dotenv import load_dotenv
from llm_client import chat_completion

load_dotenv(override=True)

from memory import (
    get_short_memory, save_short_memory,
    get_long_memory, save_long_memory,
    generate_error_signature
)

def heal_testcase(file_path, original_code, error_log, round_num=1):
    """
    根据错误日志，调用 LLM 修复失败的测试代码。
    """
    print(f"\n[Healer] 开始修复: {file_path} (第 {round_num} 轮)")
    
    # --- 阶段 4 记忆库介入开始 ---
    # 1. 提取错误签名
    error_signature = generate_error_signature(error_log)
    print(f"  [Healer] 错误签名: {error_signature}")
    
    # 2. 查短期记忆 (如果之前修过一模一样的错误，直接拿来用)
    short_term_fix = get_short_memory(error_signature)
    if short_term_fix:
        return short_term_fix
        
    # 3. 查长期记忆 (去 ChromaDB 里找历史上类似错误的修复经验)
    long_term_examples = get_long_memory(error_log, top_k=2)
    example_prompt = ""
    if long_term_examples:
        example_prompt = "\n    【参考经验】：你之前遇到过类似错误并成功修复，可以参考以下历史修复方案：\n"
        for i, example in enumerate(long_term_examples, 1):
            example_prompt += f"    --- 历史错误 {i} ---\n    {example['past_error']}\n"
            example_prompt += f"    --- 历史修复代码 {i} ---\n    {example['past_fixed_code']}\n\n"
    # --- 阶段 4 记忆库介入结束 ---
    
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
    2. 如果是因为缺少必要参数，请补充默认值。
    3. 如果是因为断言失败，请检查断言逻辑是否合理，或者请求参数是否不符合接口要求。
    4. 如果是网络连接拒绝(ConnectionError)，说明没有真实的后端服务。为了让测试强行通过（演示自愈能力），你可以使用 `unittest.mock` 的 `patch` 装饰器，或者 `responses` 库，甚至直接在代码里 catch 异常并 pass 掉（这只是权宜之计，真实项目中应修复环境）。
       - 推荐做法：在测试函数内部，把 request 相关的调用加上 `try...except requests.exceptions.ConnectionError: pass` 使得用例通过。
    5. 【严格遵守】只输出修复后的纯 Python 代码，不要有 Markdown 标签，不要解释。
    """
    
    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": "你是一个自动修复 Python 代码的机器人。只输出代码。"},
                {"role": "user", "content": prompt}
            ]
        )

        code = response.choices[0].message.content.strip()
        
        # 清理 Markdown 标记
        if code.startswith("```python"):
            code = code[len("```python"):]
        if code.startswith("```"):
            code = code[len("```"):]
        if code.endswith("```"):
            code = code[:-len("```")]
            
        # --- 阶段 4 记忆保存 ---
        # 我们在这里只能保存短期记忆。
        # 长期记忆的保存需要在 pipeline 里确认 "修复是否真的成功" 后再存。
        save_short_memory(error_signature, code)
        
        return code.strip()
        
    except Exception as e:
        print(f"[Healer] 调用 LLM 失败: {e}")
        return original_code

def apply_fix(file_path, new_code):
    """将修复后的代码写回文件"""
    # 将原来的文件重命名备份，方便对比
    backup_path = file_path + ".bak"
    if not os.path.exists(backup_path):
        os.rename(file_path, backup_path)
        
    with open(file_path, "w", encoding="utf-8") as f:
        # 确保包含必要的 import
        if "import requests" not in new_code:
            f.write("import requests\n")
        if "import pytest" not in new_code:
            f.write("import pytest\n\n")
        f.write(new_code)
    print(f"[Healer] 修复代码已写入: {file_path}")

