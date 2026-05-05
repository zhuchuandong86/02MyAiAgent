# pages/10_🛠️_JSON解析器.py
import streamlit as st
import json
import re  # 仅新增这一行用于后续的正则提取
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import JSON_CLEANER_PROMPT
from core.llm_factory import get_llm

st.set_page_config(page_title="JSON 智能解析", page_icon="🛠️", layout="wide")

st.title("🛠️ JSON 智能解析与格式化")
st.markdown("不仅支持标准 JSON 的美化，还能利用 AI 将 **不规则的开发日志、Python 对象字符串（如 ChatCompletion）** 自动清洗并重构为标准的可折叠 JSON 层级。")

# ==========================================
# 界面布局：左侧输入，右侧输出
# ==========================================
col1, col2 = st.columns(2)

with col1:
    raw_input = st.text_area(
        "📥 原始数据输入", 
        height=500, 
        placeholder="请在此粘贴您的 JSON 文本，或者像 ChatCompletion(...) 这样带有类名和单引号的不规则格式文本..."
    )
    
    st.write("") # 留点间距
    c1, c2 = st.columns(2)
    btn_standard = c1.button("⚡ 标准 JSON 格式化 (极速)", use_container_width=True)
    btn_ai = c2.button("🧠 AI 智能清洗与解析", type="primary", use_container_width=True)

with col2:
    st.markdown("### 📤 解析与分层结果")
    
    # -----------------------------------------
    # 模式一：标准极速解析 (纯本地，不耗 Token)
    # -----------------------------------------
    if btn_standard:
        if raw_input.strip():
            try:
                parsed = json.loads(raw_input)
                st.success("✅ 标准 JSON 解析成功！")
                st.json(parsed)
            except Exception as e:
                st.error(f"❌ 解析失败，这似乎不是标准的 JSON 格式：\n\n`{e}`\n\n👉 **强烈建议尝试点击左侧蓝色的【AI 智能清洗与解析】功能！**")
        else:
            st.warning("请输入要解析的内容。")
            
    # -----------------------------------------
    # 模式二：AI 智能重构 (专治各种不服)
    # -----------------------------------------
    if btn_ai:
        if raw_input.strip():
            # ⬇️ 这里开始是本次修改的核心部分 ⬇️
            st.info("🧠 正在调动 AI 理解层级，清洗不规范字符，请观察下方实时输出...")
            
            # 创建占位符，用来实时显示打字机效果
            stream_container = st.empty() 
            result = "" 
            
            try:
                prompt = ChatPromptTemplate.from_template(JSON_CLEANER_PROMPT)
                llm = get_llm(model_name=settings.MODEL_TEXT, temperature=0)

                with get_openai_callback() as cb:
                    # 改动 1：使用 stream() 替代 invoke()，实现流式输出
                    for chunk in (prompt | llm).stream({"text": raw_input}):
                        result += chunk.content
                        stream_container.code(result + "▌", language="json")
                    
                    # 运行完毕后清空占位符的光标和文本
                    stream_container.empty()
                    
                    # 改动 2：使用 chr(96) 动态生成反引号，配合正则精准提取，彻底避开前端崩溃 Bug
                    md_marker = chr(96) * 3
                    pattern = rf"{md_marker}(?:json)?(.*?){md_marker}"
                    match = re.search(pattern, result, re.DOTALL | re.IGNORECASE)
                    
                    if match:
                        result = match.group(1).strip()
                    else:
                        result = result.strip()
                    
                    parsed_json = json.loads(result)
                    st.success("🎉 AI 清洗重构成功！")
                    st.json(parsed_json, expanded=True)
                    
                    # 计费拦截 (原封不动保留)
                    tokens = cb.total_tokens
                    if tokens == 0:
                        tokens = int((len(raw_input) + len(result)) * 1.2)
                    log_usage("JSON智能清洗", settings.MODEL_TEXT, tokens)
                    
            except Exception as e:
                # 异常处理原封不动保留，仅为了安全把大括号内的 result 去掉了自带的 Markdown 标记
                st.error(f"❌ AI 解析失败: {e}\n\n可能数据结构过于混乱，AI 返回的原文如下:\n{result}")
            # ⬆️ 核心改动结束 ⬆️
        else:
            st.warning("请输入要解析的内容。")