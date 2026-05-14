
## 项目全貌（回顾）
**基于LLM + 经验记忆的API测试自愈Agent**  
核心流程：  
`输入(OpenAPI/流量/diff)` → `生成多步骤pytest用例` → `执行` → `捕获失败` → `检索记忆库` → `LLM修复` → `重试` → `记录并更新记忆库` → `输出报告`

---

## 路线图总览（建议6~8周，可并行或压缩）

| 阶段 | 名称 | 主要产出 | 预估时间 |
|------|------|----------|----------|
| 1 | 基础底座 & 单用例生成 | Swagger解析 + 生成单个API的pytest函数 | 1周 |
| 2 | 多步骤场景生成 | 支持依赖链（CRUD顺序）的测试场景生成 | 1周 |
| 3 | 执行 & 基础自愈 | 运行pytest、捕获错误、LLM修复单轮 | 1.5周 |
| 4 | 记忆库（长期+短期） | Chroma向量存储 + 检索增强修复 | 1.5周 |
| 5 | 工程化 & 报告 | CLI/Web界面、配置、并发、输出报告 | 1.5周 |
| 6 | 实验 & 文档 | 对比实验、README、博客 | 0.5周 |

下面逐步拆解，并提供**代码骨架示例**。

---

## 阶段1：基础底座 & 单用例生成

### 目标
- 能够读取一个OpenAPI（Swagger）文件，解析出每个endpoint（method, path, parameters, requestBody）。
- 调用LLM生成一个**可运行的pytest测试函数**，请求该API并做基本断言。

### 核心任务
1. **环境准备**  
   ```bash
   pip install openai pyyaml pytest requests prance click streamlit chromadb gitpython
   ```
   （后续用到再装，一次性也可以）

2. **解析OpenAPI**  
   使用`prance`解析yaml/json，提取paths。示例代码：
   ```python
   from prance import ResolvingParser
   parser = ResolvingParser('petstore.yaml')
   spec = parser.specification
   for path, methods in spec['paths'].items():
       for method, details in methods.items():
           # 提取 method, path, parameters, requestBody
   ```

3. **构造生成Prompt**  
   设计few-shot模板。先只做**单个API**的生成：
   ```python
   prompt = f"""
   你是一个测试专家。根据以下API信息生成一个pytest测试函数。
   API信息：
   - 方法：{method}
   - URL：{base_url}{path}
   - 参数：{parameters}
   - 请求体示例：{request_body_example}
   要求：
   1. 函数名 test_{operation_id}。
   2. 使用 requests 库。
   3. 断言状态码为200（或预期的成功码）。
   4. 如果响应是JSON，断言存在某个关键字段（如 id）。
   只输出Python代码，不要解释。
   """
   ```

4. **调用LLM并保存文件**  
   调用OpenAI API（可用DeepSeek更便宜），得到代码字符串，写入`generated_tests/test_xxx.py`。

5. **手动运行验证**  
   `pytest generated_tests/ -v` 确保生成的无语法错误。

### 产出
- `parser.py`：解析OpenAPI。
- `generator.py`：生成单用例。
- 一个演示用的OpenAPI文件（如Petstore）。
- 能生成5~10个单个API的测试文件，且能手动执行通过（至少通过率>0）。

---

## 阶段2：多步骤场景生成（依赖链）

### 目标
- 识别API之间的依赖（例如：创建资源→查询→更新→删除）。
- 生成一个完整的**测试场景**（一个pytest函数内包含多个步骤，步骤间传递数据）。

### 核心任务
1. **依赖推断**  
   简单方法：人工定义一个依赖配置文件（yaml），指明创建、读取、更新、删除的endpoint顺序。  
   或者自动：根据operationId命名规则（`createXXX`, `getXXX`, `updateXXX`, `deleteXXX`）或路径特征推断。

2. **场景生成Prompt**  
   给LLM展示一个**多步骤的例子**（few-shot）：
   ```
   示例场景：创建一个pet，然后查询这个pet，然后更新它的name，最后删除它。
   生成的代码结构：
   def test_pet_crud():
       # 1. 创建
       create_resp = requests.post(...)
       pet_id = create_resp.json()['id']
       # 2. 查询
       get_resp = requests.get(f'/pet/{pet_id}')
       assert get_resp.status_code == 200
       # 3. 更新
       update_resp = requests.put(...)
       # 4. 删除
       delete_resp = requests.delete(...)
   ```
   然后让LLM根据你的API列表，自动生成类似的场景。

3. **处理变量传递**  
   生成的代码中要包含从上一个步骤提取变量（如`pet_id`）传递给下一个步骤。

4. **保存场景用例**  
   将生成的场景代码存入`generated_tests/test_scenario_xxx.py`。

### 产出
- `scenario_builder.py`：依赖识别 + 场景生成。
- 至少生成3个完整的CRUD场景用例。
- 手动执行部分场景，确保至少能创建成功（如失败，记录下来用于自愈测试）。

---

## 阶段3：执行 & 基础自愈循环

### 目标
- 自动执行生成的测试文件，捕获失败用例及其错误日志。
- 调用LLM单轮修复（重新生成代码）并覆盖原文件。
- 记录修复前后的通过率。

### 核心任务
1. **执行与捕获**  
   使用`pytest.main()`或`subprocess`运行pytest，收集失败信息。
   ```python
   import pytest
   result = pytest.main(['-v', '--tb=short', 'generated_tests/'])
   # 捕获输出需要借助 capsys 或 subprocess，推荐 subprocess
   ```
   简单起见：用`subprocess.run`运行`pytest --tb=line --json-report`，解析json报告获得失败列表。

2. **单轮修复函数**  
   ```python
   def heal_testcase(original_code, error_log, round=1):
       prompt = f"""
       原始测试代码运行失败，错误日志如下：
       {error_log}
       请分析原因并输出修正后的完整pytest代码。只输出代码。
       原始代码：
       {original_code}
       """
       return call_llm(prompt)
   ```

3. **循环重试**  
   对每个失败文件，最多尝试3次。每次替换文件内容，重新执行同一个文件（只测该文件，提高速度）。

4. **记录结果**  
   保存每轮修复后的通过率。

### 产出
- `executor.py`：运行测试并捕获失败。
- `healer.py`：单轮修复逻辑。
- `pipeline.py`：自动化跑通一次完整流程（不包含记忆库）。
- 实验：对阶段2生成的场景运行，记录初始通过率和修复一轮后的通过率。预期提升明显。

---

## 阶段4：记忆库（短期 + 长期）

### 目标
- 短期记忆：同一个session内，对于相同错误类型，直接复用之前的修复方案，不再调用LLM。
- 长期记忆：使用Chroma存储历史修复成功的(错误签名, 修复代码)，新错误先检索top-k相似错误，将检索到的修复示例放入prompt，提升修复成功率。

### 核心任务
1. **错误签名生成**  
   定义一种简单的错误签名：提取错误日志中的异常类型 + 关键断言行。  
   例如：`AssertionError: 404` 或 `KeyError: 'id'`。  
   更精确：用正则提取错误的前两行作为签名。

2. **短期记忆实现**  
   在`healer.py`中维护一个字典 `short_memory = {}`，key为错误签名，value为上次修复成功的代码。  
   修复前先查短期记忆，如果命中，直接替换，不调用LLM。

3. **长期记忆（Chroma）**  
   - 创建集合 `repairs`，每个文档的正文是`error_log`，metadata存储`fixed_code`和`error_signature`。
   - 修复成功后，将`(error_log, fixed_code)`存入Chroma。
   - 修复前，用当前错误日志作为query，检索最相似的top-3文档，把它们的`fixed_code`作为示例放入修复prompt中（“参考以下类似错误的修复方案”）。

4. **效果评估**  
   分别测试无记忆、仅短期、短期+长期三种配置下的修复成功率（在相同测试集上）。  
   记录数字（例如：无记忆63%，加长期81%），写入报告。

### 产出
- `memory.py`：短期记忆字典 + Chroma封装。
- `healer_with_memory.py`：集成记忆的修复逻辑。
- 实验结果（表格/截图）。

---

## 阶段5：工程化 & 报告

### 目标
- 提供命令行工具（click）和Web界面（Streamlit）。
- 支持并发执行（多线程运行测试文件）。
- 支持通过yaml配置模型、重试次数、API base URL等。
- 生成详细修复报告（Markdown/HTML）。

### 核心任务
1. **CLI（click）**  
   ```bash
   python -m agent --input petstore.yaml --mode generate   # 仅生成
   python -m agent --input petstore.yaml --mode heal       # 生成+自愈
   python -m agent --input har/recording.har --mode heal   # 支持har录制文件
   ```
   解析参数，调用不同模块。

2. **Streamlit界面**  
   简单的几个组件：
   - 上传OpenAPI文件或har文件。
   - 选择是否启用记忆库。
   - 点击按钮运行，实时显示日志。
   - 展示最终报告和通过率趋势图。

3. **并发执行**  
   使用`concurrent.futures.ThreadPoolExecutor`同时对多个测试文件执行pytest。注意资源竞争（每个线程独立临时目录？简化：直接在内存中运行每个文件的代码，可以使用`pytest.main`但需要隔离）。  
   *简化方案*：顺序执行也可以，先不追求并发，把功能做完后再优化。

4. **配置化**  
   `config.yaml`：
   ```yaml
   llm:
     provider: openai
     model: gpt-4o-mini
     temperature: 0
   healing:
     max_rounds: 3
   execution:
     timeout: 30
   api_base: https://api.example.com
   ```

5. **输出报告**  
   生成`report.md`，包含：
   - 测试概述（总用例数、初始通过数、最终通过数）
   - 每轮修复的通过率变化
   - 失败用例详情（错误类型、修复轮数、是否借助记忆库）
   - 记忆库命中率

### 产出
- `cli.py`，`app.py`（Streamlit）
- `config.yaml`
- `reporter.py`
- 完整可运行的项目结构。

---

## 阶段6：实验 & 文档

### 目标
- 用真实或公开API（GitHub REST API）做完整实验，获取漂亮数字。
- 写README，包含项目背景、架构图、快速开始、实验结果、后续计划。
- 可选：写一篇技术博客。

### 核心任务
1. **选择目标API**  
   推荐GitHub REST API（需要token，但公开数据足够）。挑选15~20个常用endpoint（users, repos, issues），编写依赖场景（例如：创建repo → 创建issue → 更新issue → 删除repo）。

2. **运行完整流程**  
   - 无记忆
   - 短期记忆
   - 长期记忆
   分别记录初始通过率、最终通过率、平均修复轮数。

3. **整理数字**  
   例如：初始通过率45%，短期记忆后65%，长期记忆后83%。记忆库命中率35%。

4. **写README**  
   - 标题与徽章
   - 架构流程图（mermaid）
   - 安装与使用步骤
   - 实验结果（表格+图表）
   - 后续改进（如支持更多协议、分布式执行等）

5. **录制演示视频**（可选但加分）  
   用Loom或OBS录制2分钟操作展示：上传yaml -> 运行 -> 查看报告。

---

## 关键技术点提示

### 1. LLM调用封装
建议统一一个`llm_client.py`，支持切换OpenAI/DeepSeek/本地模型。使用`tenacity`实现重试。

### 2. 解析错误日志
pytest的错误输出格式比较规整，可以用正则提取`E       AssertionError: ...`行。  
对于更复杂的错误（如requests超时），直接取最后几行作为签名。

### 3. 生成代码的安全检查
- 使用`ast.parse`检查语法。
- 禁止危险操作（如`os.system`），可以在prompt中约束，并在后处理时过滤。

### 4. 测试隔离
生成的测试文件应该独立于项目的其他测试。每个场景文件最好有`setup/teardown`清理资源（例如删除创建的repo）。

### 5. 记忆库的相似度
错误日志作为文本，直接用Chroma默认的`all-MiniLM-L6-v2` embedding即可。不需要特别处理。

---

## 接下来你可以做的

1. **从阶段1开始**，先实现Swagger解析 + 单用例生成。  
2. 每完成一个阶段，提交一次git，方便回溯。  
3. 遇到具体技术问题（如怎么解析OpenAPI的requestBody示例），欢迎随时问我，我会提供更细的代码示例。  
4. 全部完成后，我会帮你审定简历描述和面试话术。

**只要你不赶时间，按这个路线稳扎稳打，最终产出一个完整的开源项目，大厂测开实习offer概率会大大增加。