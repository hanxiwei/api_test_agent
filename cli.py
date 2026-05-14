import click
import os
import sys

# 引入核心业务逻辑
from pipeline import run_pipeline
from parser import parse_openapi
from scenario_builder import build_all_scenarios

# ----------------------------------------
# 命令行入口
# ----------------------------------------
@click.group()
def cli():
    """
    API 测试自愈 Agent 命令行工具
    
    使用本工具，你可以通过解析 OpenAPI 规范，自动生成 Python (pytest) 自动化测试脚本。
    并且能在测试执行失败时，利用 LLM 进行代码自愈和修复。
    """
    pass

# ----------------------------------------
# 命令 1: 一键自愈 (完整流程)
# ----------------------------------------
@cli.command("heal")
@click.option('--input', '-i', required=True, type=click.Path(exists=True), help="OpenAPI 文档路径 (YAML/JSON)")
@click.option('--rounds', '-r', default=3, show_default=True, type=int, help="自愈循环的最大重试次数")
def heal_command(input, rounds):
    """
    执行完整流程：解析 -> 生成 -> 执行测试 -> (如失败则)LLM自愈修复 -> 记录记忆
    
    示例: python cli.py heal -i data/petstore.yaml
    """
    click.echo(f"正在启动自愈 Agent...")
    click.echo(f"目标文档: {input}, 最大重试: {rounds} 轮\n")
    
    # 调用 pipeline 的核心方法
    result = run_pipeline(openapi_path=input, max_rounds=rounds)
    
    if result.get("status") == "error":
        sys.exit(1)

# ----------------------------------------
# 命令 2: 仅生成代码 (不执行、不自愈)
# ----------------------------------------
@cli.command("generate")
@click.option('--input', '-i', required=True, type=click.Path(exists=True), help="OpenAPI 文档路径")
def generate_command(input):
    """
    仅执行阶段1和阶段2：解析 API 文档并生成场景测试代码。不运行测试。
    
    示例: python cli.py generate -i data/petstore.yaml
    """
    click.echo(f"正在解析文档: {input} ...")
    endpoints = parse_openapi(input)
    if not endpoints:
        click.echo("未找到任何接口定义，退出。")
        sys.exit(1)
        
    click.echo(f"解析成功，开始调用 LLM 生成测试场景代码...")
    generated_files = build_all_scenarios(endpoints)
    
    if generated_files:
        click.echo(f"\n[OK] 代码生成完毕！共生成 {len(generated_files)} 个测试文件，存放于 generated_tests/ 目录。")
    else:
        click.echo("\n⚠️ 未能生成任何代码。")

if __name__ == '__main__':
    # 确保在项目根目录运行，方便相对路径查找
    # 强制让命令行参数通过 click 解析
    cli()
