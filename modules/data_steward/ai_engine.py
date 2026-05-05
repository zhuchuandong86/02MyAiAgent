import re
import streamlit as st
from openai import OpenAI
from core.settings import settings
from core.token_tracker import log_usage

def call_ai_architect(prompt, action_name="架构诊断"):
    """通用的文本诊断/分析接口 (非流式)"""
    client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
    res = client.chat.completions.create(
        model=settings.MODEL_TEXT, 
        messages=[{"role": "user", "content": prompt}], 
        temperature=0.2,
        timeout=300.0
    )
    # 🔴 统一归口到主模块，适配 00_用量总览
    log_usage("14_数据管家", settings.MODEL_TEXT, res.usage.total_tokens)
    return res.choices[0].message.content


# ==========================================
# 🔴 新增：流式输出的 AI 架构师调用
# ==========================================
def call_ai_architect_stream(prompt, action_name="架构诊断"):
    """流式输出的文本诊断/分析接口，配合 st.write_stream 使用"""
    client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
    response = client.chat.completions.create(
        model=settings.MODEL_TEXT, 
        messages=[{"role": "user", "content": prompt}], 
        temperature=0.2,
        stream=True  # 开启流式传输
    )
    
    full_text = ""
    # 逐字/逐块解析并 yield（生成器模式）
    for chunk in response:
        if chunk.choices and len(chunk.choices) > 0:
            content = chunk.choices[0].delta.content
            if content:
                full_text += content
                yield content
                
    # 流式输出结束后，粗略估算 Token 消耗并记录日志 
    # (中文语境下，1个汉字/字符 大约相当于 0.8~1 个 Token)
    estimated_tokens = int((len(prompt) + len(full_text)) * 0.8)
    log_usage("14_数据管家", settings.MODEL_TEXT, estimated_tokens)


def call_ai_sql_coder(system_prompt, messages, action_name="SQL生成"):
    """专业的 SQL Coder 接口，自动注入 UI 左侧侧边栏的【业务知识库】"""
    client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
    
    business_context = st.session_state.get("business_dictionary", "")
    if business_context.strip():
        system_prompt += f"\n\n[CRITICAL BUSINESS JARGON & RULES (MUST OBEY)]:\n{business_context}"
        
    full_msgs = [{"role": "system", "content": system_prompt}] + messages
    res = client.chat.completions.create(
        model=settings.MODEL_CODER, 
        messages=full_msgs, 
        temperature=0.1,
        timeout=300.0  # 建议这里也加上超时保护
    )
    # 🔴 统一归口到主模块，适配 00_用量总览
    log_usage("14_数据管家", settings.MODEL_CODER, res.usage.total_tokens)
    return res.choices[0].message.content

def extract_sql(response_text):
    """从 AI 回复中安全提取 SQL 代码块及解释文本"""
    sql_match = re.search(r'```sql\n(.*?)\n```', response_text, re.DOTALL)
    if sql_match:
        clean_sql = sql_match.group(1).strip()
        explanation = response_text.replace(sql_match.group(0), "").strip()
        return clean_sql, explanation
    return "", response_text