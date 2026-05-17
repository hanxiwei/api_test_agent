import os
from parser import parse_openapi
from scenario_builder import build_all_scenarios
from executor import run_tests
from healer import heal_testcase, apply_fix
from memory import save_long_memory, generate_error_signature


def run_pipeline(openapi_path='data/petstore.yaml', max_rounds=3, logger=print):
    """
    执行完整的 Agent 流程：
    解析 → 生成 → 执行 → 诊断失败类别 → 修复/bug标记 → 写入记忆
    """
    logger("========================================")
    logger("      API 测试自愈 Agent 主流程启动       ")
    logger("========================================")

    # ── 阶段 1/2：解析 OpenAPI 并生成测试用例 ──
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

    # ── 阶段 3：执行测试 ──
    logger("\n>>> 步骤 2: 首次执行测试用例")
    failed_tests = run_tests("generated_tests")

    if not failed_tests:
        logger("[OK] 所有测试首次执行即全部通过！")
        return {"status": "success", "message": "所有测试首次执行全部通过"}

    logger(f"[Warning] 发现 {len(failed_tests)} 个失败的测试文件，进入分析修复流程。")

    # 记录疑似后端 bug 的测试（这些不修复，标记 xfail 后跳过）
    backend_bugs = []

    # ── 阶段 4：自愈循环 ──
    for round_num in range(1, max_rounds + 1):
        logger(f"\n>>> 步骤 3: 自愈循环 - 第 {round_num} 轮")

        attempted_fixes = {}
        still_test_bugs = {}

        for file_path, error_log in failed_tests.items():
            logger(f"  正在分析文件: {file_path}")

            with open(file_path, "r", encoding="utf-8") as f:
                original_code = f.read()

            # heal_testcase 内部会先诊断，再决定修不修
            result = heal_testcase(file_path, original_code, error_log, round_num)

            if result["action"] == "backend_bug":
                # 后端问题：已标记 xfail，不进入修复循环
                backend_bugs.append({
                    "file": file_path,
                    "reason": result["reason"],
                    "round": round_num
                })
                continue

            if result["action"] == "test_bug":
                apply_fix(file_path, result["code"])
                attempted_fixes[file_path] = {
                    "error_log": error_log,
                    "error_signature": generate_error_signature(error_log),
                    "fixed_code": result["code"]
                }

        if not attempted_fixes:
            logger("  本轮无需修复的测试代码 bug，结束自愈循环。")
            break

        # 重新执行
        logger(f"\n  [自愈验证] 重新执行测试...")
        new_failed_tests = run_tests("generated_tests")

        # 保存长期记忆：修复成功才写入
        for file_path, info in attempted_fixes.items():
            if file_path not in new_failed_tests:
                logger(f"  [Memory] 验证通过！将 {file_path} 的修复经验写入长期记忆。")
                save_long_memory(info["error_log"], info["error_signature"], info["fixed_code"])

        # 过滤掉 backend_bug 的测试，只保留 test_bug 的进入下一轮
        still_test_bugs = {}
        for fp, err in new_failed_tests.items():
            if not any(b["file"] == fp for b in backend_bugs):
                still_test_bugs[fp] = err

        failed_tests = still_test_bugs

        if not failed_tests:
            logger(f"\n[OK] 在第 {round_num} 轮修复后，所有可修复的测试全部通过！")
            break
        else:
            logger(f"  第 {round_num} 轮后，仍有 {len(failed_tests)} 个测试代码 bug 待修复。")

    # ── 汇总结果 ──
    result = {"status": "success", "message": "所有测试已处理完毕"}
    if backend_bugs:
        result["backend_bugs"] = backend_bugs
        logger(f"\n[Report] 发现 {len(backend_bugs)} 个疑似后端 Bug（已标记 xfail，跳过修复）：")
        for b in backend_bugs:
            logger(f"  - {os.path.basename(b['file'])} (第{b['round']}轮): {b['reason'][:60]}")
    if failed_tests:
        result["status"] = "partial_success"
        result["failed_tests"] = list(failed_tests.keys())
        logger(f"\n[Report] {len(failed_tests)} 个测试代码 bug 未能完全修复。")

    logger("\n========================================")
    logger("           Agent 执行流程结束             ")
    logger("========================================")
    return result

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
