---
name: api-test-heal
description: 一键运行 API 测试自愈流水线——解析 OpenAPI 文档，生成 pytest 测试，执行并自动修复失败用例
metadata:
  version: "1.0.0"
---

# API 测试自愈 Agent

基于 LLM + 经验记忆的 API 自动化测试生成与自愈工具。

## 快速使用

用户提供 OpenAPI/Swagger 文件（YAML 或 JSON），即可一键完成：
1. 解析 API 接口定义
2. 按资源分组，生成多步骤 CRUD 场景测试代码
3. 执行 pytest 测试
4. 失败用例自动调用 LLM 修复（最多 3 轮）
5. 修复经验存入 ChromaDB 记忆库

## 命令

### `/api-test-heal` — 完整流水线

解析 OpenAPI 文档 → 生成测试 → 执行 → 自动修复失败的用例。

```
/api-test-heal <openapi_file>
```

**示例:**
```
/api-test-heal data/petstore.yaml
/api-test-heal data/my-api.json
```

**行为:**
1. 运行 `python cli.py heal -i <openapi_file> --rounds 3`
2. 实时打印每轮测试通过率
3. 汇总最终结果：通过/失败数，修复轮数，记忆库命中情况
4. 如果仍有失败，列出失败文件路径

### `/api-test-generate` — 仅生成测试（不执行）

```
/api-test-generate <openapi_file>
```

**行为:**
1. 运行 `python cli.py generate -i <openapi_file>`
2. 汇总生成了多少个测试文件，列出文件名

## 前置条件

- Python 3.10+ 环境且 `requirements.txt` 已安装
- `.env` 中配置了 `OPENAI_API_KEY`（兼容 OpenAI/DeepSeek 等）
- 项目根目录为 `d:\python\LLM-agent\api_test_agent`

## 项目文件结构

| 文件 | 作用 |
|------|------|
| `cli.py` | Click 命令行入口，含 `heal` 和 `generate` 两个命令 |
| `pipeline.py` | 总调度器：解析 → 生成 → 执行 → 修复 → 记忆 |
| `parser.py` | 解析 OpenAPI/Swagger 文档 |
| `scenario_builder.py` | 按资源分组 + 推断 CRUD 链 + 调用 LLM 生成场景测试 |
| `executor.py` | 运行 pytest，捕获失败用例及错误栈 |
| `healer.py` | 调用 LLM + 记忆库修复失败测试代码 |
| `memory.py` | 双层记忆：短期（精确匹配）+ 长期（ChromaDB 向量检索） |
| `llm_client.py` | 统一的 LLM 调用客户端（内置重试） |
| `config.py` / `config.yaml` | 全局配置 |
| `app.py` | Streamlit Web 界面 |

## 注意事项

- 生成和修复依赖 LLM，请确保 API Key 有效
- 长期记忆库存储在 `.chroma_db/`，首次运行会下载 embedding 模型
- Web 界面用 `streamlit run app.py` 启动
