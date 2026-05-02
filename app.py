import streamlit as st
import os
import tempfile
import time
from pipeline import run_pipeline

# 设置页面配置
st.set_page_config(
    page_title="API 测试自愈 Agent",
    page_icon="🤖",
    layout="wide"
)

# 页面标题和说明
st.title("🤖 API 测试自愈 Agent")
st.markdown("""
这是一个基于大语言模型（LLM）的 API 自动化测试用例生成与自愈工具。
它能读取 OpenAPI 文档，生成测试代码，自动执行测试，并利用 LLM 修复失败的用例，同时把经验存入记忆库！
""")

# 侧边栏配置
with st.sidebar:
    st.header("⚙️ 配置面板")
    
    # 检查环境变量
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key == "your_api_key_here":
        st.error("未检测到有效的 API Key！请检查 `.env` 文件。")
    else:
        st.success("API Key 已就绪")
        
    st.divider()
    
    st.markdown("### 2. 📂 上传 API 文档")
    uploaded_file = st.file_uploader("选择 OpenAPI 规范文件 (YAML 或 JSON)", type=["yaml", "yml", "json"])

    st.markdown("### 3. ⚙️ 运行配置")
    max_rounds = st.slider("最大自愈重试次数", min_value=1, max_value=5, value=3)
    
# 主界面
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. 启动 Agent")
    if uploaded_file:
        st.write(f"当前选择的文档: `{uploaded_file.name}`")
    else:
        st.write("请先在左侧边栏上传文档")
    
    start_button = st.button("🚀 开始一键生成与自愈", use_container_width=True, type="primary")

with col2:
    st.subheader("2. 实时执行日志")
    log_container = st.empty()

# 如果点击了启动按钮
if start_button:
    # 用于收集日志的列表
    logs = []
    
    # 自定义一个 logger 函数，用来替换 pipeline.py 里的 print
    # 这样就可以把日志实时推送到 Streamlit 网页上了
    def streamlit_logger(msg):
        # 使用安全的打印方式，防止控制台编码报错
        try:
            # sys.stdout 可能被重定向，如果仍有编码问题，忽略它
            msg_str = str(msg)
            print(msg_str.encode('gbk', 'ignore').decode('gbk'))
        except Exception:
            pass
            
        # 添加到网页日志列表
        logs.append(str(msg))
        # 拼接成一个完整的字符串，展示在网页的代码块中
        log_text = "\n".join(logs)
        log_container.code(log_text, language="shell")
        # 稍微停顿一下，让视觉上有打字机的感觉
        time.sleep(0.1)

    # 显示一个加载状态
    with st.spinner("Agent 正在拼命干活中..."):
        try:
            # 1. 如果用户没有上传文件，提示错误
            if uploaded_file is None:
                streamlit_logger("[Error] 请先在左侧边栏上传 OpenAPI (YAML/JSON) 文件！")
                st.error("未找到文件，请上传！")
                st.stop()
            
            # 2. 将上传的文件保存到一个临时目录中
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_file_path = tmp_file.name
                
            streamlit_logger(f"✅ 成功接收上传文件: {uploaded_file.name}")
            
            # 3. 运行流水线
            result = run_pipeline(openapi_path=tmp_file_path, max_rounds=max_rounds, logger=streamlit_logger)
            
            st.divider()
            if result.get("status") == "success":
                st.balloons()
                st.success("全部测试自愈通过！", icon="✅")
            else:
                st.error("达到最大重试次数，仍有测试失败。请查看日志分析原因。", icon="❌")
        except Exception as e:
            streamlit_logger(f"[Error] 运行过程中发生异常: {str(e)}")
        finally:
            # 4. 清理临时文件
            if 'tmp_file_path' in locals() and os.path.exists(tmp_file_path):
                try:
                    os.remove(tmp_file_path)
                except:
                    pass
