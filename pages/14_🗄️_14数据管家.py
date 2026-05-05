# pages/14_🗄️_14数据管家.py
import streamlit as st
import os

# 强制系统调起 Chrome
os.environ["BROWSER"] = "chrome"

st.set_page_config(page_title="AI 数据中台系统", page_icon="🗄️", layout="wide")

# =========================================================
# 状态机全局初始化 (必须在渲染任何 UI 前执行)
# =========================================================
if "last_source_hash" not in st.session_state: st.session_state.last_source_hash = ""
if "ai_advice_text" not in st.session_state: st.session_state.ai_advice_text = ""
if "join_analysis_text" not in st.session_state: st.session_state.join_analysis_text = ""
if "data_profile_cache" not in st.session_state: st.session_state.data_profile_cache = ""
if "ai_chat_history" not in st.session_state: st.session_state.ai_chat_history = []
if "pending_sql" not in st.session_state: st.session_state.pending_sql = ""
if "pending_exp" not in st.session_state: st.session_state.pending_exp = ""
if "business_dictionary" not in st.session_state: st.session_state.business_dictionary = ""

# 引入重构后的核心 UI 模块（严格按照 1~6 顺序引入）
from modules.data_steward.tabs.tab1_etl import render_etl_tab
from modules.data_steward.tabs.tab2_profile import render_profile_tab
from modules.data_steward.tabs.tab3_vlookup import render_join_tab
from modules.data_steward.tabs.tab4_chat import render_ai_chat_tab
from modules.data_steward.tabs.tab5_pivot import render_manual_pivot_tab
from modules.data_steward.tabs.tab6_spatial import render_spatial_tab

# =========================================================
# 全局业务知识库 (Data Lineage & Jargon)
# =========================================================
with st.sidebar:
    st.markdown("### 🧠 企业业务字典")
    st.info("💡 将术语定义、指标公式写在这里。AI 在对话和透视中会自动参考。")
    business_dict = st.text_area(
        "业务术语与常识记录：", 
        placeholder="例如：\n1. 渗透率 = A列 / B列\n2. 华南区包含广东和广西\n3. 距离计算请使用地球曲率公式", 
        height=300,
        value=st.session_state.business_dictionary
    )
    if st.button("💾 更新企业 AI 大脑", use_container_width=True):
        st.session_state.business_dictionary = business_dict
        st.toast("知识库已热更新并注入全部大模型逻辑链！")

# =========================================================
# 页面顶级路由分发
# =========================================================
st.title("🗄️ 企业级 AI 数据中台")

# 严格按照 1 到 6 的命名顺序排列 Tab
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📥 1. 数据入库引擎", 
    "🗂️ 2. 资产大盘", 
    "🧩 3. 智能 VLOOKUP", 
    "💬 4. 连续分析推理台", 
    "🖱️ 5. 智能透视工作台",
    "🗺️ 6. 空间与网格规划"
])

# 依次挂载渲染函数
with tab1:
    render_etl_tab()
with tab2:
    render_profile_tab()
with tab3:
    render_join_tab()
with tab4:
    render_ai_chat_tab()
with tab5:
    render_manual_pivot_tab()
with tab6:
    render_spatial_tab()