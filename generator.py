import os
from openai import OpenAI
from dotenv import load_dotenv
from config import get_config

# 加载 .env 文件中的环境变量
load_dotenv(override=True)

# 初始化 LLM 客户端
# OpenAI 官方库设计得很好，只要修改 base_url，就可以无缝对接 DeepSeek 等国产大模型！
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL")
)

def generate_test_case(endpoint_info, base_url="http://localhost:8080"):
    """
    调用大语言模型 (LLM)，为单个 API 生成一个可运行的 pytest 测试函数。
    """
    # 1. 提取 API 信息
    method = endpoint_info['method']
    path = endpoint_info['path']
    parameters = endpoint_info['parameters']
    operation_id = endpoint_info['operationId']
    
    # 2. 构造 Prompt (提示词)
    # 提示词的核心是：清晰说明任务、提供上下文、规定输出格式
    prompt = f"""
    你是一个资深的 Python 测试开发工程师。根据以下 API 信息，生成一个完整的 pytest 测试函数。
    
    API 信息：
    - 方法：{method}
    - URL 路径：{base_url}{path}
    - 参数：{parameters}
    - 接口 ID：{operation_id}
    
    要求：
    1. 函数名必须为 test_{operation_id}。
    2. 使用 requests 库发送 HTTP 请求。
    3. 如果 URL 中有 path 参数（例如 /pet/{{petId}}），请在代码中构造合理的测试数据填入 URL。
    4. 增加基本的断言：断言 HTTP 状态码为 200（或预期的成功状态码）。
    5. 【严格遵守】只输出纯 Python 代码，不要包含 Markdown 标记（例如 ```python 和 ```），不要写任何解释。
    """
    
    print(f"正在调用 LLM 为接口 [{operation_id}] 生成测试代码...")
    
    # 3. 请求 LLM
    model_name = os.getenv("LLM_MODEL") or get_config("llm", "model", "gpt-4o-mini")
    temp = get_config("llm", "temperature", 0.2)
    
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "你是一个只输出 Python 代码的测试用例生成助手。"},
            {"role": "user", "content": prompt}
        ],
        temperature=temp
    )
    
    # 4. 获取并清理生成的代码
    code = response.choices[0].message.content.strip()
    
    # 简单的后处理：万一 LLM 还是不听话加了 markdown 标签，我们用代码帮它去掉
    if code.startswith("```python"):
        code = code[len("```python"):]
    if code.startswith("```"):
        code = code[len("```"):]
    if code.endswith("```"):
        code = code[:-len("```")]
        
    return code.strip()

def save_test_case(code, filename):
    """
    将生成的测试代码保存为本地 .py 文件。
    """
    # 确保保存测试文件的文件夹存在
    os.makedirs("generated_tests", exist_ok=True)
    filepath = os.path.join("generated_tests", filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        # 在最前面自动加上 import，以防大模型忘记写
        f.write("import pytest\nimport requests\n\n")
        f.write(code)
        
    print(f"[OK] 测试用例已保存至: {filepath}")

