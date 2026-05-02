# 🤖 API Test Auto-Healing Agent

> 基于 LLM 大语言模型与记忆库检索增强 (RAG) 的 API 自动化测试代码生成与自愈引擎。

## 🌟 项目简介

在真实的后端研发流水线中，API 接口字段的频繁变更（如参数更名、新增必填项）会导致现有的自动化测试脚本大面积报错，测试人员需要耗费大量时间去排查日志并手动维护测试代码。

本项目旨在打造一个“免维护”的测试底座：
1. **通用解析**：支持上传任意项目的 OpenAPI (Swagger) 规范文档。
2. **智能生成**：基于依赖推断，自动生成包含多步骤状态传递的完整 CRUD 场景测试代码 (`pytest`)。
3. **闭环自愈**：当测试执行失败时，Agent 会自动捕获真实环境的报错堆栈，调用 LLM 进行自我反思并**重写测试代码**，直至测试通过。
4. **经验记忆库 (RAG)**：引入短期内存字典与 ChromaDB 本地向量数据库。Agent 会将成功修复的经验永久保存，当下次遇到类似报错时，通过向量相似度检索历史经验，实现“秒级修复”，越用越聪明。

---

## 🛠️ 技术栈

- **核心语言**: Python 3.10+
- **LLM 交互**: `openai` SDK (完美兼容 DeepSeek 等性价比极高的国产大模型)
- **文档解析**: `prance` (OpenAPI 3.0 / Swagger 规范解析)
- **测试框架**: `pytest`, `pytest-json-report`
- **向量数据库**: `chromadb` (用于长期经验记忆存储)
- **工程化工具**: `click` (CLI 命令行构建), `streamlit` (Web 可视化交互)

---

## 🚀 快速开始

### 1. 环境安装
克隆本项目后，进入项目目录并安装依赖：
```bash
pip install -r requirements.txt
```

### 2. 配置环境变量 (非常重要)
项目使用环境变量来管理敏感信息。请将根目录下的 `.env.example` 复制一份并重命名为 `.env`。
然后打开 `.env` 文件，填入你的大模型配置：

```env
# 例如使用 DeepSeek
OPENAI_API_KEY="sk-你的真实API-KEY"
OPENAI_BASE_URL="https://api.deepseek.com/v1"
LLM_MODEL="deepseek-chat"
```
*(注：本项目已配置 `.gitignore`，你的 `.env` 文件绝不会被上传到 GitHub)*

### 3. 运行 Web 可视化界面 (推荐)
启动 Streamlit 前端服务，在浏览器中直观地体验文档上传、日志实时监控与代码自愈的震撼过程：
```bash
streamlit run app.py
```

### 4. 命令行 CLI 模式 (适用于 CI/CD)
本项目提供了工业级的 CLI 接口，方便无缝集成到 Jenkins/GitLab 流水线中：

```bash
# 查看帮助
python cli.py --help

# 仅生成测试代码，不执行自愈
python cli.py generate -i data/petstore.yaml

# 执行完整流程（生成 -> 运行测试 -> LLM自愈 -> 写入记忆库）
python cli.py heal -i data/petstore.yaml -r 3
```

---

## 📂 项目核心结构

```text
api_test_agent/
├── .env                  # 敏感环境变量 (不上传Git)
├── config.yaml           # 全局非敏感配置 (重试次数、temperature等)
├── app.py                # Streamlit Web 前端交互入口
├── cli.py                # Click 命令行交互入口
├── pipeline.py           # 核心流水线调度器 (大管家)
├── parser.py             # OpenAPI 文档解析器
├── scenario_builder.py   # 基于依赖推断的场景代码生成器
├── executor.py           # Pytest 执行与错误日志捕获器
├── healer.py             # LLM 代码自我修复引擎 (老中医)
├── memory.py             # 基于 ChromaDB 的记忆存储检索中枢
├── data/                 # 存放测试用的 OpenAPI 文档示例
└── generated_tests/      # (自动生成) Agent 编写和修复的测试脚本存放处
```

---

## 💡 核心机制原理解析

### 为什么需要记忆库 (ChromaDB)？
传统的 LLM 修复存在两个痛点：每次报错都要调用 API 耗费 Token，且遇到复杂报错时单次修复成功率低。
本项目在 `pipeline.py` 中加入了验证机制：只有当修复后的代码**真实跑通**后，才会将 `(Error Traceback -> Fixed Code)` 存入 ChromaDB。
在后续的自愈循环中，`healer.py` 会优先对报错信息进行向量相似度检索。如果找到相似历史，则作为 Few-shot 示例喂给 LLM，大幅提升修复精准度，实现知识沉淀。

---

## 📝 证书与开源协议
MIT License
