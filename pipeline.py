import os
from parser import parse_openapi
from scenario_builder import build_all_scenarios
from executor import run_tests
from healer import heal_testcase, apply_fix
from memory import save_long_memory, generate_error_signature

def run_pipeline(openapi_path='data/petstore.yaml', max_rounds=3, logger=print):
    """
    执行完整的 Agent 流程，并支持外部传入 logger 函数以实时获取日志。
    """
    logger("========================================")
    logger("      API 测试自愈 Agent 主流程启动       ")
    logger("========================================")
    
    # 1. 阶段 1/2：解析 OpenAPI 并生成测试用例
    logger("\n>>> 步骤 1: 解析 API 规范与生成测试场景")
    endpoints = parse_openapi(openapi_path)
    if not endpoints:
        logger("未找到任何接口定义，退出。")
        return {"status": "error", "message": "解析 OpenAPI 失败或无端点"}
        
    generated_files = build_all_scenarios(endpoints)
    if not generated_files:
        logger("未生成任何场景用例，退出。")
        return {"status": "error", "message": "生成场景用例失败"}
        
    logger(f"\n共生成 {len(generated_files)} 个测试文件。")
    
    # 2. 阶段 3：执行测试
    logger("\n>>> 步骤 2: 首次执行测试用例")
    failed_tests = run_tests("generated_tests")
    
    if not failed_tests:
        logger("[OK] 太棒了！所有测试首次执行即全部通过！")
        return {"status": "success", "message": "所有测试首次执行全部通过"}
        
    logger(f"[Warning] 发现 {len(failed_tests)} 个失败的测试文件，进入自愈循环。")
    
    # 3. 阶段 3：自愈循环
    for round_num in range(1, max_rounds + 1):
        logger(f"\n>>> 步骤 3: 自愈循环 - 第 {round_num} 轮")
        
        # 为了长期记忆，我们需要记录这轮修复了哪些文件以及它们当时的错误日志
        attempted_fixes = {}
        
        # 针对每个失败的文件进行修复
        for file_path, error_log in failed_tests.items():
            logger(f"  正在尝试修复文件: {file_path}")
            
            # 读取当前（失败的）代码
            with open(file_path, "r", encoding="utf-8") as f:
                original_code = f.read()
                
            # 调用大模型生成修复代码
            fixed_code = heal_testcase(file_path, original_code, error_log, round_num)
            
            # 记录尝试修复的信息，用于稍后存入长期记忆
            attempted_fixes[file_path] = {
                "error_log": error_log,
                "error_signature": generate_error_signature(error_log),
                "fixed_code": fixed_code
            }
            
            # 写入修复后的代码
            apply_fix(file_path, fixed_code)
            
        # 本轮修复完成后，重新执行失败的文件所在的目录
        logger(f"\n  [自愈验证] 重新执行测试...")
        new_failed_tests = run_tests("generated_tests")
        
        # --- 阶段 4：保存长期记忆 ---
        # 如果一个文件在 attempted_fixes 里，但不在 new_failed_tests 里，说明它被成功修复了！
        for file_path, info in attempted_fixes.items():
            if file_path not in new_failed_tests:
                logger(f"  [Memory] 验证通过！将 {file_path} 的修复经验写入长期记忆。")
                save_long_memory(info["error_log"], info["error_signature"], info["fixed_code"])
                
        failed_tests = new_failed_tests
        # -----------------------------
        
        if not failed_tests:
            logger(f"\n[OK] 恭喜！在第 {round_num} 轮修复后，所有测试全部通过！")
            break
        else:
            logger(f"  第 {round_num} 轮修复后，仍有 {len(failed_tests)} 个测试失败。")
            
    if failed_tests:
        logger("\n[Error] 自愈循环结束。已达到最大重试次数，以下用例未能修复：")
        for f in failed_tests.keys():
            logger(f"  - {f}")
        return {"status": "partial_success", "failed_tests": list(failed_tests.keys())}
            
    logger("\n========================================")
    logger("           Agent 执行流程结束             ")
    logger("========================================")
    return {"status": "success", "message": "所有测试已通过自愈循环修复并成功"}

def main():
    run_pipeline()

if __name__ == "__main__":
    # 确保依赖环境已就绪
    try:
        import pytest_jsonreport
    except ImportError:
        print("错误: 缺少 pytest-json-report 插件。请运行: pip install pytest-json-report")
        exit(1)
        
    main()
