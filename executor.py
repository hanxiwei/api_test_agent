import subprocess
import json
import os

def run_tests(test_dir="generated_tests"):
    """
    运行指定目录下的 pytest 测试，并捕获失败的测试用例及错误日志。
    返回格式: { "test_file_path": "error_log_string", ... }
    """
    print(f"正在执行测试目录: {test_dir} ...")
    
    # 确保生成 JSON 报告，我们需要依赖 pytest-json-report 插件
    # 如果没有安装，稍后我们需要在 requirements.txt 中加上并安装
    report_path = ".report.json"
    
    # 构建 pytest 命令
    # --tb=short 控制 traceback 的长度，太长 LLM 看不过来，太短看不出问题
    cmd = [
        "pytest", 
        test_dir, 
        "-v", 
        "--tb=short", 
        f"--json-report",
        f"--json-report-file={report_path}"
    ]
    
    # 运行命令 (pytest 测试失败时会返回非 0 状态码，所以 check=False)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    
    # 解析 JSON 报告
    failed_tests = {}
    if os.path.exists(report_path):
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                report = json.load(f)
                
            # 遍历每个测试项
            for test in report.get("tests", []):
                if test.get("outcome") == "failed":
                    # 获取文件路径
                    nodeid = test.get("nodeid", "")
                    # nodeid 格式通常是: generated_tests/test_xxx.py::test_func
                    file_path = nodeid.split("::")[0]
                    
                    # 获取完整的错误追踪日志 (Traceback)
                    # json-report 会将 traceback 存储在 call 阶段的 crash/traceback 中
                    call_info = test.get("call", {})
                    longrepr = call_info.get("longrepr", "No traceback found")
                    
                    # 为了防止 LLM 被过长的日志淹没，限制一下长度
                    if len(longrepr) > 1500:
                        longrepr = longrepr[-1500:]
                        
                    failed_tests[file_path] = longrepr
                    
        except Exception as e:
            print(f"解析测试报告失败: {e}")
            
    print(f"测试执行完毕。总共发现 {len(failed_tests)} 个失败的文件。")
    return failed_tests


