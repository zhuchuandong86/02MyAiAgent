# pages/08_💻_代码助手.py
import streamlit as st
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_community.callbacks.manager import get_openai_callback

# 引入全局配置与统一兵工厂
from core.settings import settings
from core.token_tracker import log_usage
from core.llm_factory import get_llm
from core.prompts import CODE_ARCHITECT_PROMPT

st.set_page_config(page_title="专家级代码助手", page_icon="💻", layout="wide")

st.title("💻 专家级架构师与代码助手")
st.markdown("直接拖入多个文件或整个项目文件夹，大模型将为您解析调用链、进行 Code Review 并提供优化重构方案。遇到 Bug 也可以直接贴入报错日志让 AI 排查。")

# ==========================================
# 1. 侧边栏：配置与文件上传
# ==========================================
with st.sidebar:
    # st.header("⚙️ 引擎配置")
    coder_model = st.text_input("当前生效的内网代码模型", value=settings.MODEL_CODER)
    
    st.header("📁 载入项目库")
    # st.info("💡 提示：您可以点击浏览，或直接把电脑上的整个项目文件夹/多个文件拖拽到下方区域。")
    uploaded_files = st.file_uploader(
        "拖拽文件夹或多选文件", 
        accept_multiple_files=True,
        help="系统会自动过滤掉图片、视频和二进制编译文件，只保留代码供 AI 分析。"
    )

# ==========================================
# 2. 核心功能：智能过滤与上下文构建
# ==========================================
def is_valid_code_file(filename):
    """过滤无关文件，防止将二进制或无意义的日志喂给大模型"""
    valid_exts = ('.py', '.java', '.js', '.ts', '.go', '.cpp', '.c', '.h', '.cs', 
                  '.php', '.rb', '.html', '.css', '.vue', '.jsx', '.tsx', 
                  '.json', '.yaml', '.yml', '.md', '.sql', '.sh', '.xml', '.txt')
    ignore_exts = ('.png', '.jpg', '.jpeg', '.gif', '.mp4', '.pdf', '.exe', '.dll', 
                   '.pyc', '.class', '.o', '.so', '.zip', '.tar', '.gz', '.lock')
    return filename.endswith(valid_exts) and not filename.endswith(ignore_exts)

def build_project_context(files):
    context = ""
    valid_count, ignored_count = 0, 0
    
    for file in files:
        if is_valid_code_file(file.name):
            try:
                content = file.getvalue().decode("utf-8")
                # [增强能力保留]：为每一行代码自动注入行号，极其利于 AI 精准报错！
                numbered_lines = "\n".join([f"{i+1:04d} | {line}" for i, line in enumerate(content.splitlines())])
                context += f"### 文件: `{file.name}`\n```\n{numbered_lines}\n```\n\n"
                valid_count += 1
            except Exception:
                ignored_count += 1 # 解码失败直接跳过
        else:
            ignored_count += 1
            
    return context, valid_count, ignored_count

project_context = ""
valid_count, ignored_count = 0, 0
is_context_ready = False

if uploaded_files:
    project_context, valid_count, ignored_count = build_project_context(uploaded_files)
    if valid_count > 0:
        is_context_ready = True

# ==========================================
# 3. 主界面：功能区与聊天区
# ==========================================
if is_context_ready:
    with st.expander(f"👀 成功加载 {valid_count} 个代码文件 (已跳过 {ignored_count} 个非代码文件)，点击查看合并后的代码上下文", expanded=False):
        st.markdown(project_context)

    st.divider()
    quick_action = None

    # [原有能力保留] 报错排查区
    with st.expander("🚨 遇到 Bug？贴入错误日志让 AI 帮你排查", expanded=False):
        error_log = st.text_area("在此粘贴您的终端报错信息或异常堆栈 (Stack Trace)：", height=150, placeholder="例如: NullPointerException, SyntaxError...")
        if st.button("🔍 分析报错并提供修复建议", type="primary"):
            if error_log.strip():
                quick_action = f"我在运行项目时遇到了以下报错，请结合你读取的代码上下文帮我分析原因，指出错误出在哪个文件哪一行，并给出具体的代码修复建议：\n\n```text\n{error_log}\n```"
            else:
                st.warning("请先粘贴报错内容再点击分析哦！")

    st.markdown("---")
    
    # [原有能力保留] 快捷指令区
    st.markdown("**💡 快捷指令**")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🗺️ 分析项目架构与调用关系", use_container_width=True):
            quick_action = "请根据我提供的项目代码，详细梳理出系统的核心调用链路和数据流向。请总结各模块的核心职责，并指出谁调用了谁。"
    with col2:
        if st.button("🛠️ 全局 Code Review", use_container_width=True):
            quick_action = "请以顶级架构师的视角，对提供的代码进行全面的 Code Review。跨文件指出潜在的 Bug、不优雅的硬编码、以及不符合设计模式的地方。"
    with col3:
        if st.button("⚡ 深度重构与优化方案", use_container_width=True):
            quick_action = "请评估上述整个项目的性能和可扩展性。针对存在瓶颈的文件或类，直接给出优化后的、带有详细注释的重构代码对比（请使用独立的代码块或 diff 语法，不要使用表格）。"

    if "coder_chat_history" not in st.session_state:
        st.session_state.coder_chat_history = []
        
    prompt = quick_action if quick_action else st.chat_input("或直接在这里向 AI 提问，例如：'项目中哪里处理了数据入库？'")

    for msg in st.session_state.coder_chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt:
        st.session_state.coder_chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            full_response = ""
            
            messages = [SystemMessage(content=CODE_ARCHITECT_PROMPT.format(project_context=project_context))]
            
            for msg in st.session_state.coder_chat_history[:-1]:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                else:
                    messages.append(AIMessage(content=msg["content"]))
                    
            messages.append(HumanMessage(content=prompt))
            
            # [核心重构] 使用统一的兵工厂
            llm_coder = get_llm(model_name=coder_model, temperature=0.1)
            
            with get_openai_callback() as cb:
                try:
                    # 💡 探针 1：打印发送前的状态
                    print(f"\n[DEBUG] 👉 准备发送请求到大模型，合并后的代码长度: {len(project_context)} 字符")
                    
                    count = 0
                    # 开始请求流式输出
                    for chunk in llm_coder.stream(messages):
                        # if count == 0:
                        #     # 💡 探针 2：只要能打印出这句话，说明网关通了！
                        #     print("[DEBUG] ✅ 成功收到网关返回的第一个数据包！网络握手成功！")
                            
                        if chunk.content:
                            full_response += chunk.content
                            count += 1
                            # 节流渲染：每 8 个 token 更新一次 UI，防止浏览器被刷爆
                            if count % 8 == 0:
                                response_placeholder.markdown(full_response + " ▌")
                    
                    # 结束后输出完整内容
                    response_placeholder.markdown(full_response)
                    
                    # # 💡 探针 3：确认全部结束
                    # print(f"[DEBUG] 🎉 流式输出全部完成，共计 {len(full_response)} 字符。")
                    
                    # Token 计费兜底
                    tokens = cb.total_tokens if cb.total_tokens > 0 else int((len(project_context) + len(full_response)) * 1.2)
                    log_usage("架构与代码助手", coder_model, tokens)
                    
                except Exception as e:
                    # 💡 探针 4：捕获最深层的异常
                    error_msg = f"❌ 运行异常: {type(e).__name__} - {str(e)}"
                    print(f"[DEBUG] {error_msg}")
                    st.error(f"模型服务连接中断或报错，请查看后台终端日志。具体报错: {error_msg}")
                    
        if full_response:
            st.session_state.coder_chat_history.append({"role": "assistant", "content": full_response})
            
else:
    if uploaded_files:
        st.warning("⚠️ 没有识别到有效的代码文件，请确认您上传了代码文件而不是纯图片或二进制文件。")
    else:
        st.info("👈 请先在左侧侧边栏拖拽或选择您的项目文件，以构建代码上下文。")