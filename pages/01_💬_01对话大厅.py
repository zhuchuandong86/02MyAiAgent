import streamlit as st
import json
from openai import OpenAI

# 统一从全局设置导入，剔除 os.getenv
from core.settings import settings
from core.token_tracker import log_usage
from modules.zclaw._registry import ZCLAW_TOOLS_SCHEMA, TOOL_DISPATCHER

st.set_page_config(page_title="AI 双核对话大厅", page_icon="💬", layout="wide")

# =========================================================
# 🛡️ 竞技场配置：选取两个对打的模型与基础工具 (统一使用 settings 单例)
# =========================================================
MODEL_A = settings.MODEL_BLUE
MODEL_B = settings.MODEL_RED 

# 只保留安全的基础工具，防止大模型在聊天时误删代码
ALLOWED_TOOL_NAMES = ["search_web", "read_webpage", "ask_vision", "read_file", "search_memory"]
LOBBY_TOOLS = [t for t in ZCLAW_TOOLS_SCHEMA if t["function"]["name"] in ALLOWED_TOOL_NAMES]

LOBBY_SYSTEM_PROMPT = """你现在处于【AI 双核对话大厅】。
你的目标是与用户进行流畅的对话，解答疑问。如果需要，请随时调用网络搜索或文件读取工具查证事实。
请保持回答结构清晰、见解独到。如果用户要求进行高阶的物理交付（如生成Word），请引导其前往其他专业模块。
"""

st.markdown("### 💬 AI 跨模态对话大厅 (双核竞技场)")
st.caption(f"🔥 当前在线：**🔵 左脑 ({MODEL_A})** VS  **🔴 右脑 ({MODEL_B})** | 具备独立上下文记忆与工具调度能力。")

# =========================================================
# 🧠 初始化三路记忆（UI显示记忆 + A/B模型的独立底层记忆）
# =========================================================
if "display_msgs" not in st.session_state:
    st.session_state.display_msgs = []
if "history_A" not in st.session_state:
    st.session_state.history_A = [{"role": "system", "content": LOBBY_SYSTEM_PROMPT}]
if "history_B" not in st.session_state:
    st.session_state.history_B = [{"role": "system", "content": LOBBY_SYSTEM_PROMPT}]

# 自动清理过长记忆，防止 Token 爆炸（保留系统提示词 + 最近 10 条消息 = 5轮）
def prune_memory(history_list, max_len=11):
    if len(history_list) > max_len:
        return [history_list[0]] + history_list[-(max_len-1):]
    return history_list

# =========================================================
# 🎨 渲染历史消息
# =========================================================
for msg in st.session_state.display_msgs:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    else:
        col1, col2 = st.columns(2)
        with col1:
            with st.chat_message("assistant", avatar="🔵"):
                st.markdown(msg.get("content_A", ""))
        with col2:
            with st.chat_message("assistant", avatar="🔴"):
                st.markdown(msg.get("content_B", ""))

# =========================================================
# ⚙️ 核心特工执行器 (增加 JSON 容错与异常拦截)
# =========================================================
def run_lobby_agent(client, model, messages, tools, ui_container, avatar, icon):
    with ui_container:
        with st.chat_message("assistant", avatar=avatar):
            status = st.status(f"{icon} {model} 正在思考与执行...", expanded=True)
            res_box = st.empty()
            final_text = "⚠️ 生成失败"
            
            for step in range(4): # 最多允许连续 4 次工具调用
                try:
                    res = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=tools if tools else None,
                        temperature=0.7
                    )
                except Exception as e:
                    status.update(label="❌ API 调用异常", state="error")
                    res_box.error(f"模型请求失败: {str(e)}")
                    return f"系统异常: {str(e)}"

                msg = res.choices[0].message
                
                # 安全地将对象转为字典存入记忆
                msg_dict = msg.model_dump(exclude_none=True)
                messages.append(msg_dict)
                
                if msg.tool_calls:
                    for tool in msg.tool_calls:
                        func_name = tool.function.name
                        raw_args = tool.function.arguments
                        
                        # [优化点]：增加极其重要的 JSON 解析容错，防止大模型幻觉导致程序崩溃
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            err_msg = f"无法解析工具参数，请重新生成合法的 JSON 格式。你输出的参数为: {raw_args}"
                            status.write(f"⚠️ 工具参数解析错误: `{func_name}`")
                            messages.append({
                                "role": "tool", 
                                "tool_call_id": tool.id, 
                                "content": err_msg
                            })
                            continue # 将错误信息塞回给模型，让它在下一轮自我纠正
                            
                        status.write(f"⚙️ 调度工具: `{func_name}`")
                        
                        # 执行工具捕获异常，防止工具内部崩溃波及主线程
                        try:
                            action_res = TOOL_DISPATCHER.get(func_name, lambda **kw: "无权限调用此工具")(**args)
                        except Exception as ex:
                            action_res = f"工具执行内部报错: {str(ex)}"
                            status.write(f"❌ `{func_name}` 执行失败")
                        
                        # 把工具结果塞回上下文
                        messages.append({
                            "role": "tool", 
                            "tool_call_id": tool.id, 
                            "content": str(action_res)
                        })
                    continue # 携带所有工具的结果进行下一轮推理
                else:
                    status.update(label=f"✅ {model} 响应完毕", state="complete", expanded=False)
                    res_box.markdown(msg.content)
                    final_text = msg.content
                    
                    # 记账 (复用全局统一的 settings 里的 token 跟踪)
                    if hasattr(res, 'usage') and res.usage:
                        log_usage("对话大厅", model, res.usage.total_tokens)
                    break
                    
            return final_text

# =========================================================
# 🚀 触发双脑并发对话
# =========================================================
if prompt := st.chat_input("问点什么... (支持搜索、图片解析、上下文追问)"):
    # 1. 记录用户消息并展示
    st.session_state.display_msgs.append({"role": "user", "content": prompt})
    st.session_state.history_A.append({"role": "user", "content": prompt})
    st.session_state.history_B.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
        
    # 统一使用配置单例初始化客户端
    client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
    col1, col2 = st.columns(2)
    
    # 2. 激活左脑 (蓝军)
    ans_A = run_lobby_agent(client, MODEL_A, st.session_state.history_A, LOBBY_TOOLS, col1, "🔵", "🔵")
    st.session_state.history_A.append({"role": "assistant", "content": ans_A})
    
    # 3. 激活右脑 (红军)
    ans_B = run_lobby_agent(client, MODEL_B, st.session_state.history_B, LOBBY_TOOLS, col2, "🔴", "🔴")
    st.session_state.history_B.append({"role": "assistant", "content": ans_B})
    
    # 4. 记录双轨结果到 UI
    st.session_state.display_msgs.append({
        "role": "assistant", 
        "content_A": ans_A,
        "content_B": ans_B
    })
    
    # 5. 记忆剪枝维护
    st.session_state.history_A = prune_memory(st.session_state.history_A)
    st.session_state.history_B = prune_memory(st.session_state.history_B)