# 🤖 API Test Auto-Healing Agent

> 基于 LLM 大语言模型与记忆库检索增强 (RAG) 的 API 自动化测试代码生成与自愈引擎。

## 🌟 项目简介

在真实的后端研发流水线中，API 接口字段的频繁变更（如参数更名、新增必填项）会导致现有的自动化测试脚本大面积报错，测试人员需要耗费大量时间去排查日志并手动维护测试代码。

本项目旨在打造一个“免维护”的测试底座：
1. **通用解析**：支持上传任意项目的 OpenAPI (Swagger) 规范文档。
2. **智能生成**：基于依赖推断，自动生成 CRUD 场景 + **异步轮询**场景测试代码。生成时自动注入 UUID 标识符实现测试数据隔离，支持通过 `x-async` 扩展字段标注异步接口。
3. **智能诊断 + 闭环自愈**：当测试执行失败时，Agent 先调用 LLM **诊断根因**（是测试代码写错了，还是后端接口有 Bug？）。测试代码问题自动重写修复；后端问题则标记 `@pytest.mark.xfail` 并跳过修复，避免”把对的代码改错”。
4. **经验记忆库 (RAG)**：引入短期内存字典与 ChromaDB 本地向量数据库。只有**真实跑通**的修复方案才会被写入长期记忆。当下次遇到类似报错时，通过向量相似度检索历史经验作为 Few-shot 示例喂给 LLM，实现”秒级修复”，越用越聪明。

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

## 🤖 Claude Code Skill (一键式体验)

本项目内置了 **Claude Code Skill**，在 Claude Code 中打开项目后即可使用：

```bash
/api-test-heal <openapi_file>      # 完整流水线：解析→生成→执行→自愈修复
/api-test-generate <openapi_file>   # 仅生成测试代码，不执行
```

**示例：**
```
/api-test-heal data/petstore.yaml
```

只需一行命令，Agent 自动完成全部工作，无需手动敲 CLI 参数。Skill 定义在 `.claude/skills/api-test-heal/SKILL.md`，随项目一起提交到 GitHub，克隆即用。

---

## 📂 项目核心结构

```text
api_test_agent/
├── .claude/skills/        # Claude Code Skill 定义 (项目共享)
├── .env                   # 敏感环境变量 (不上传Git)
├── config.yaml            # 全局非敏感配置 (重试次数、temperature等)
├── app.py                 # Streamlit Web 前端交互入口
├── cli.py                 # Click 命令行交互入口
├── pipeline.py            # 核心流水线（解析→生成→执行→诊断→修复/标记→记忆沉淀）
├── parser.py              # OpenAPI 文档解析器 (含 x-async 扩展字段提取)
├── scenario_builder.py    # 场景代码生成器 (同步 CRUD + 异步轮询 + UUID 隔离)
├── generator.py           # 单接口测试用例生成器 (每端点一个函数)
├── executor.py            # Pytest 执行与错误日志捕获器
├── healer.py              # LLM 诊断 + 自愈引擎 (异步错误也能精准分类)
├── memory.py              # 短期记忆字典 + ChromaDB 长期向量记忆
├── llm_client.py          # 统一 LLM 调用客户端 (单例 + 指数退避重试)
├── data/                  # 测试用 OpenAPI 文档 (petstore + async_example)
└── generated_tests/       # (自动生成) Agent 编写和修复的测试脚本存放处
```

---

## 💡 核心机制原理解析

### 智能诊断：先判根因，再行动

传统方案看到测试失败就修代码，但如果失败是因为**后端没启动**或**接口本身有 Bug**，修测试代码反而会把对的改错。

本项目的自愈流程分两步走：

```
测试失败 → diagnose_failure() → LLM 诊断根因
    ├── TEST_BUG（测试代码写错了）→ LLM 修复代码 → 重新跑 → 通过后写入记忆库
    └── BACKEND_BUG（后端接口有问题）→ 标记 @pytest.mark.xfail → 跳过修复，保留正确代码
```

诊断 Prompt 使用 `temperature=0.1`（低随机性），要求 LLM 只输出两行：`<TEST_BUG|BACKEND_BUG>` + `<理由>`。判断依据：
- **TEST_BUG**：断言条件错误、URL 路径拼错、缺少必填参数、请求体构造错误
- **BACKEND_BUG**：后端返回 500/503、响应字段缺失或类型不匹配、ConnectionError（后端根本没启动）

### 为什么需要记忆库 (ChromaDB)？
传统的 LLM 修复存在两个痛点：每次报错都要调用 API 耗费 Token，且遇到复杂报错时单次修复成功率低。
本项目在 `pipeline.py` 中加入了验证机制：只有当修复后的代码**真实跑通**后，才会将 `(Error Traceback -> Fixed Code)` 存入 ChromaDB。
在后续的自愈循环中，`healer.py` 会优先对报错信息进行向量相似度检索。如果找到相似历史，则作为 Few-shot 示例喂给 LLM，大幅提升修复精准度，实现知识沉淀。

---

### 异步接口支持 (x-async)

真实业务中大量存在异步接口（AI 推理、报表导出、文件处理等）。普通的"请求-断言"模式无法处理这类接口。

本项目的解决思路：

1. **文档约定**：在 OpenAPI 规范中用 `x-async` 扩展字段标注异步接口的轮询策略
```yaml
POST /images/generate:
  x-async:
    poll_path: /images/generate/{task_id}
    status_field: status
    success_value: done
    failure_value: failed
    poll_interval: 2
    poll_timeout: 60
    result_fields: [image_url, thumbnail_url]
```

2. **解析识别**：`parser.py` 自动提取 `x-async` 元数据，与普通接口区分对待

3. **代码生成**：`scenario_builder.py` 为异步接口生成专门的轮询测试：
   - 发 POST 提交任务 → 断言 202 → 提取 task_id
   - while 循环轮询 GET，检查 status 字段
   - done → 断言所有 result_fields → 跳出
   - failed → `pytest.fail("任务失败: {error}")`
   - 超时 → `pytest.fail("轮询超时: ...")`

4. **错误诊断**：`healer.py` 能区分轮询超时是"阈值设太短"还是"后端任务卡住"，不做盲目修复

### 测试数据隔离 (UUID)

每次运行 CRUD 全链路测试都会在数据库留下测试数据。如果不做隔离，残留数据会因为唯一约束冲突导致下次运行失败。

**防御策略**：生成代码时，每个测试函数开头生成 `test_run_id = uuid.uuid4().hex[:8]`，创建资源时注入到 name 字段（如 `f"test-pet-{test_run_id}"`）。即使上次清理失败，新运行也不会冲突。

配合 `try/finally` 清理机制，实现"运行内清理 + 跨运行不冲突"的双重保障。

---

## 📝 证书与开源协议
MIT License
