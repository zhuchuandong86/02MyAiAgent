# pages/06_💬_AI辩论.py
import streamlit as st
from openai import OpenAI
import os
from dotenv import load_dotenv
import time

# 【必加1】：引入全局路径管家
import core.paths
# 【必加2】：从新模块导入流式调用函数
from modules.debate.core import stream_llm

# ================= 加载全局配置 =================
load_dotenv(core.paths.ENV_FILE) 

# 统一使用全局的 API 配置 (兼容你原来的 OPENAI_xxx 命名)
BASE_URL = os.getenv("INTERNAL_API_BASE") or os.getenv("OPENAI_BASE_URL")
API_KEY = os.getenv("INTERNAL_API_KEY") or os.getenv("OPENAI_API_KEY")
INTERNAL_URL=os.getenv("INTERNAL_URL")
os.environ['NO_PROXY'] = INTERNAL_URL

# 辩论专属模型配置 (如果 .env 里没有配，默认给 deepseek-v3-0324)
PRO_MODEL = os.getenv("PRO_MODEL", "deepseek-v3-0324")
CON_MODEL = os.getenv("CON_MODEL", "deepseek-v3-0324")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "deepseek-v3-0324")

# ================= 页面配置 =================
st.set_page_config(page_title="AI 大模型流式辩论赛", layout="wide")

# ================= 🌟 核心 UI 优化 (CSS 注入) =================
st.markdown("""
<style>
.custom-title {
    font-size: 32px !important;
    font-weight: 700;
    margin-bottom: 10px;
    border-bottom: 2px solid #f0f2f6;
    padding-bottom: 10px;
}
div[data-testid="stMarkdownContainer"] p {
    margin-bottom: 0.35rem !important;
    line-height: 1.6;
}
[data-testid="column"]:nth-of-type(1) {
    border-right: 2px dashed #e6e6e6;
    padding-right: 1.5rem;
}
[data-testid="column"]:nth-of-type(2) {
    padding-left: 1.5rem;
}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="custom-title">⚖️ AI 大模型流式辩论赛</div>', unsafe_allow_html=True)

# ================= 侧边栏 =================
with st.sidebar:
    st.header("📜 辩论规则")
    rounds = st.number_input("辩论轮数", min_value=1, max_value=10, value=3)
    word_limit = st.number_input("单次发言字数限制", min_value=50, max_value=500, value=150)
    
    st.markdown("---")
    st.markdown("### 当前出战阵容")
    st.markdown(f"- **🔵 正方**: `{PRO_MODEL}`")
    st.markdown(f"- **🔴 反方**: `{CON_MODEL}`")
    st.markdown(f"- **🧑‍⚖️ 裁判**: `{JUDGE_MODEL}`")

# ================= 主界面 =================
topic = st.text_input("📢 请输入辩题 (例如: 自动驾驶技术现在应该全面普及吗？)", placeholder="输入辩题后点击下方开始...")

if st.button("🚀 开始辩论", type="primary"):
    if not API_KEY or not topic:
        st.warning("请检查根目录的 .env 文件是否配置了 API_KEY，并在上方输入辩题！")
        st.stop()
        
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    
    col_pro, col_con = st.columns(2)
    with col_pro:
        st.markdown("### 🔵 正方")
    with col_con:
        st.markdown("### 🔴 反方")
        
    st.markdown("---")
    debate_history = []

    # ================= 辩论环节 =================
    for i in range(rounds):
        # 1. 正方发言
        pro_system = f"你是辩论赛的【正方】。你的核心任务是坚决支持正方立场。语言要犀利、有逻辑。请严格将发言字数控制在 {word_limit} 字以内，且尽量少分段。"
        pro_prompt = f"辩题是：【{topic}】。\n当前辩论记录：\n{debate_history}\n\n现在轮到你（正方）发言，请给出你的观点或反驳对方："
        
        with col_pro:
            with st.container(border=True):
                st.markdown(f"**第 {i+1} 轮发言:**")
                pro_reply = st.write_stream(stream_llm(client, PRO_MODEL, pro_system, pro_prompt))
                debate_history.append(f"【第{i+1}轮 - 正方】: {pro_reply}")
            
        time.sleep(0.5)
            
        # 2. 反方发言
        con_system = f"你是辩论赛的【反方】。你的核心任务是坚决反对正方立场，寻找漏洞并进行反击。请严格将发言字数控制在 {word_limit} 字以内，且尽量少分段。"
        con_prompt = f"辩题是：【{topic}】。\n当前辩论记录：\n{debate_history}\n\n现在轮到你（反方）发言，请给出你的观点或反驳对方："
        
        with col_con:
            with st.container(border=True):
                st.markdown(f"**第 {i+1} 轮发言:**")
                con_reply = st.write_stream(stream_llm(client, CON_MODEL, con_system, con_prompt))
                debate_history.append(f"【第{i+1}轮 - 反方】: {con_reply}")
            
        time.sleep(0.5)

    # ================= 裁判环节 =================
    st.divider()
    st.markdown("### 🧑‍⚖️ 裁判总结")
    
    judge_system = "你是一位客观、公正、专业的辩论赛评委。你需要根据双方的逻辑严密性、论据充分性以及语言感染力来评判谁赢得了比赛。排版需紧凑。"
    judge_prompt = f"辩题是：【{topic}】。\n以下是双方的完整辩论记录：\n{debate_history}\n\n请你作为裁判，简单总结双方的表现，明确宣布谁是最终获胜方以及获胜理由。"
    
    with st.container(border=True):
        judge_reply = st.write_stream(stream_llm(client, JUDGE_MODEL, judge_system, judge_prompt))