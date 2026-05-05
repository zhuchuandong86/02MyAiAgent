# AI_Platform/app.py
import streamlit as st
import os
import ssl
import warnings

# 从唯一配置源导入
from core.settings import settings
from core.token_tracker import setup_db

warnings.filterwarnings("ignore", category=ResourceWarning)

# --- 全局环境与安全设置 ---
os.environ['NO_PROXY'] = settings.INTERNAL_URL or ""

# 提示：生产环境中最好将企业自签 CA 证书写入环境变量，而不是全局关闭验证。
# 若目前为了快速跑通内网，可暂留此句。
ssl._create_default_https_context = ssl._create_unverified_context

# --- 生命周期初始化 ---
# 只在首次加载时初始化数据库，避免多页面切换时重复建表
@st.cache_resource
def init_system():
    setup_db()
    return True

init_system()

# --- UI 渲染 ---
st.set_page_config(page_title="内网 AI 工作台", layout="wide")
st.title("欢迎来到内网 AI 工作台总览")
st.write("采用公司内网，数据不出公司，不存在信息安全问题，请放心使用；")
st.write("请在左侧选择应用。")