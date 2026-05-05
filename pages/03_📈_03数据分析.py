# pages/03_📈_03数据分析.py
import streamlit as st
import pandas as pd

# 引入单一配置源
from core.settings import settings
from core.token_tracker import log_usage
from langchain_community.callbacks.manager import get_openai_callback
from modules.data_analysis.agent import run_agent_pipeline, run_followup_chat, run_auto_insights

st.set_page_config(page_title="AI 数据分析终端", page_icon="📈", layout="wide")

st.title("📈 智能数据分析与洞察终端")
st.markdown("支持**多文件上传**与**Excel多Sheet并发读取**，AI将自动进行跨表关联与全面洞察。如文件较大，刚上传后可能略慢")

if "da_report_html"   not in st.session_state: st.session_state.da_report_html   = None
if "da_report_path"   not in st.session_state: st.session_state.da_report_path   = None
if "da_context_data"  not in st.session_state: st.session_state.da_context_data  = None
if "da_chat_history"  not in st.session_state: st.session_state.da_chat_history  = []
if "quick_query"      not in st.session_state: st.session_state.quick_query       = ""

with st.sidebar:
    st.header("1. 📂 上传数据")
    uploaded_files = st.file_uploader(
        "支持 CSV 或 Excel 文件 (可多选)",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
    )

if uploaded_files:
    all_dfs = {}
    for file in uploaded_files:
        try:
            if file.name.endswith(".csv"):
                df_temp = pd.read_csv(file)
                all_dfs[file.name] = df_temp
            else:
                xls_dict = pd.read_excel(file, sheet_name=None)
                if len(xls_dict) == 1:
                    all_dfs[file.name] = list(xls_dict.values())[0]
                else:
                    for sheet_name, df_sheet in xls_dict.items():
                        all_dfs[f"{file.name} - [{sheet_name}]"] = df_sheet
        except Exception as e:
            st.sidebar.error(f"读取文件 {file.name} 失败: {e}")

    if not all_dfs:
        st.error("未能成功解析任何数据文件，请检查文件格式。")
        st.stop()

    st.write("### 📂 分析范围确认")
    selected_dataset_names = st.multiselect(
        "已自动解析以下表单，**默认全部进行联合分析**。您可以手动取消不需要的表：",
        list(all_dfs.keys()),
        default=list(all_dfs.keys()),
    )

    if not selected_dataset_names:
        st.warning("请至少保留一个表格用于分析！")
        st.stop()

    target_dfs = {name: all_dfs[name] for name in selected_dataset_names}
    st.success(f"✅ 准备就绪，共将 {len(target_dfs)} 张表送入 AI 分析引擎。")

    # =========================================================
    # 核心模块：自动生成数据画像与洞察
    # =========================================================
    file_hash = "-".join(sorted(list(target_dfs.keys())))
    if "current_file_hash" not in st.session_state or st.session_state.current_file_hash != file_hash:
        st.session_state.current_file_hash = file_hash
        st.session_state.auto_insights    = None
        st.session_state.quick_query      = ""

    if not st.session_state.auto_insights:
        with st.spinner("🤖 正在全自动对数据进行扫描与画像生成 (Auto-Profiling)..."):
            # 移除了 api 传参
            st.session_state.auto_insights = run_auto_insights(target_dfs)

    if st.session_state.auto_insights:
        insights = st.session_state.auto_insights
        with st.container(border=True):
            st.markdown("### ✨ AI 数据初探画像")
            st.info(insights.get("summary", "AI 正在思考中..."))

            st.markdown("💡 **您可以直接点击以下推荐方向开启深度分析：**")
            cols = st.columns(3)
            for i, q in enumerate(insights.get("questions", [])):
                if cols[i].button(f"🔍 {q}", key=f"btn_q_{i}", use_container_width=True):
                    st.session_state.quick_query = q
                    st.rerun()

    # =========================================================
    # 核心分析触发区
    # =========================================================
    st.markdown("---")
    st.markdown("### 🎯 设定分析目标 (或直接点击上方推荐)")
    user_query = st.text_area(
        "请输入您的具体关注点...",
        value=st.session_state.quick_query,
        placeholder="例如：将销售表和省份表关联起来，分析各省业绩。",
    )
    analyze_btn = st.button("🚀 开始智能分析", type="primary")

    if analyze_btn:
        with st.status(
            f"🤖 Multi-Agent 正在对 {len(target_dfs)} 张表进行联合思考与代码编写...",
            expanded=True,
        ) as status:
            with get_openai_callback() as cb:
                # 移除了 api 传参
                html_content, report_path, context_data = run_agent_pipeline(target_dfs, user_query)

                tokens = cb.total_tokens
                if tokens == 0:
                    col_summary = " ".join(
                        " ".join(str(c) for c in df.columns)
                        for df in target_dfs.values()
                    )
                    estimated_input_chars  = len(user_query) + len(col_summary)
                    estimated_output_chars = 3000
                    tokens = max(1000, int((estimated_input_chars + estimated_output_chars) / 3))

                log_usage("数据分析-多表模式", settings.MODEL_CODER, tokens)

            status.update(
                label="✅ 跨表数据分析流执行完毕！(点击展开查看代码与报错排查史)",
                state="complete",
                expanded=False,
            )

        st.session_state.da_report_html  = html_content
        st.session_state.da_report_path  = report_path
        st.session_state.da_context_data = context_data
        st.session_state.da_chat_history = []
else:
    st.info("👈 请先在左侧上传数据文件。")

# ==============================================================
# 报告渲染与追问模块
# ==============================================================
if st.session_state.da_report_html:
    st.success("✅ 分析完成！")
    st.components.v1.html(st.session_state.da_report_html, height=800, scrolling=True)
    st.download_button(
        "📥 下载独立 HTML 报告",
        data=st.session_state.da_report_html,
        file_name="AI_Analysis_Report.html",
        mime="text/html",
    )

    st.divider()
    st.markdown("### 💬 报告深度追问与优化")
    for msg in st.session_state.da_chat_history:
        st.chat_message(msg["role"]).write(msg["content"])

    if prompt := st.chat_input("在此输入您的追问或优化需求..."):
        st.session_state.da_chat_history.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)

        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            full_response = ""
            try:
                history = st.session_state.da_chat_history[:-1]
                with get_openai_callback() as cb:
                    # 移除了 api 传参
                    stream_generator = run_followup_chat(
                        user_query=prompt,
                        chat_history=history,
                        context_data=st.session_state.da_context_data
                    )
                    count = 0
                    for chunk in stream_generator:
                        full_response += chunk.content
                        count += 1
                        if count % 8 == 0:
                            response_placeholder.markdown(full_response + "▌")
                    response_placeholder.markdown(full_response)
            except Exception as e:
                full_response = f"追问失败: {e}"
                st.error(full_response)

        st.session_state.da_chat_history.append({"role": "assistant", "content": full_response})