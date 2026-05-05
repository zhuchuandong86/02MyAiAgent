# pages/07_📝_文案整理.py
import streamlit as st
import os
import re
import time 
import json
import concurrent.futures
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 【修改点 1】：去掉了 SPEAKER_DIARIZATION_PROMPT 的导入
from core.prompts import (
    COPYWRITING_SYSTEM_PROMPT, 
    COPYWRITING_DEFAULT_REQ, 
    RULE_ANTI_AI,
    RULE_NO_HALLUCINATION
)
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

# ==========================================
# 0. 状态初始化与数据持久化：模版存储机制
# ==========================================
TEMPLATE_FILE = "copywriting_templates.json"

def load_templates():
    if os.path.exists(TEMPLATE_FILE):
        try:
            with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_templates(templates):
    with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
        json.dump(templates, f, ensure_ascii=False, indent=2)

if "templates" not in st.session_state:
    st.session_state.templates = load_templates()

# 初始化运行状态和历史记录（用于连续对话）
if "run_state" not in st.session_state:
    st.session_state.run_state = {
        "active": False,
        "action_name": "",
        "req": "",
        "text": ""
    }
if "history_a" not in st.session_state:
    st.session_state.history_a = []
if "history_b" not in st.session_state:
    st.session_state.history_b = []

# 预设金牌提示词 (3大场景)
# 【修改点 2】：重构外部会谈纪要提示词，直接内嵌 <thinking> 思维链推演，并明确禁止输出实录
PROMPT_CLIENT_MEETING = f"""请将以下素材整理为高水准的【深度客户会谈纪要】。
由于原始素材主要是语音识别转换的文本，存在说话人标签混乱、口语化严重、包含大量寒暄和废话的情况。

【第一步：强制前置推演】
在正式输出纪要前，你必须先在 <thinking> 和 </thinking> 标签内完成以下内部逻辑推演：
1. 从语气、问答逻辑、称谓、专业术语等线索判断：这段对话大约有几位说话人;
2. 根据语境、称谓和立场，识别出“客户方”和“厂家方”的真实发言内容与核心意图。
3. 过滤掉无效的寒暄、附和（如“啊”、“对”、“是吧”）以及与核心业务无关的闲聊。
4. 提炼出客户发言中最核心的业务诉求、真实态度和排斥点。
（注：推演过程仅作内部逻辑梳理，绝对不要包含或输出原始对话记录）。

【第二步：提取与分析维度】
推演完成后，请严格按以下维度输出纪要正文（必须使用标准的 Markdown 标题和列表排版，语言极其精炼、直白）：

1. 📥 **信息传递与现状**：客户接收到了哪些方案？客户陈述了哪些当前的业务现状或背景（尽量保留核心业务数据）？
2. ⚠️ **质疑、痛点与不认可**：客户对哪些提议表达了质疑、反感、或明确拒绝？（核心重点，必须犀利指出）
3. 🎯 **方案观点认可**：客户接受了哪些方案，认可或者是非常认可哪些观点、思路和建议？
4. 💡 **新思路与共创想法**：客户在交流中提出了哪些新的想法、商业模式、或替代建议？
5. 📅 **下一步推进计划**：明确遗留问题、双方责任人及时间节点（如素材中未明确，请直接标明“待确认”）。

【要求】：
- 语气专业、客观，严禁废话。
- 绝对不要输出整理后的对话实录，只输出最终的结构化纪要。
- 必须遵循：{RULE_NO_HALLUCINATION}
- 必须遵循：{RULE_ANTI_AI}"""

PROMPT_INTERNAL_MEETING = """请将以下素材整理为结构清晰、注重执行的【内部会议纪要】。
【强制要求】：
1. 提炼一句“会议主旨”。
2. 按照核心议题进行模块化拆分，提炼各项的“关键结论”和“争议点”。
3. 必须单独列出“待办事项 (Action Items)”模块，包含具体动作和跟进人。
4. 剔除废话，语言精炼直白，使用标准的 Markdown 标题和列表排版。"""

PROMPT_OPERATIONAL = """请将以下零散的素材整理为一份高质量、结果导向的【运作纪要】（如周报/月报/项目汇报）。
【强制要求】：
1. 重点突出“核心业绩/数据产出”与“关键项目进展”。
2. 明确列出“当前风险/求助事项”与“下一步计划”。
3. 提炼核心逻辑，把流水账转化为专业职场管理语境。
4. 语言必须客观、精炼，如果某项没有内容请标注“暂无特别项”，使用标准的 Markdown 排版。"""

# 页面基本配置
st.set_page_config(page_title="智能文案整理", page_icon="📝", layout="wide")
st.title("📝 智能文案与排版引擎")
st.markdown("设定目标格式或**套用您保存的经验模版**，由 **双模型** 生成。**如果不满意，可以在下方对话框继续提出修改要求。**")

# 模型阵营
model_a = settings.MODEL_TEXT or "deepseek-v3-0324"
model_b = settings.MODEL_RED or "qwen2.5-72b-instruct"
st.info(f"💡 **当前对决引擎**： 🔵 **方案 A** (`{model_a}`) 🆚 🔴 **方案 B** (`{model_b}`)")

# ==========================================
# 1. 顶部输入区与模版管理
# ==========================================
col1, col2 = st.columns([2, 1])

with col1:
    uploaded_files = st.file_uploader(
        "📂 上传本地素材 (支持多文件合并, .txt, .md)", 
        type=["txt", "md"], 
        accept_multiple_files=True
    )
    
    manual_text = st.text_area(
        "📦 原始杂乱素材 (支持直接粘贴，或结合上方文件一起使用)", 
        placeholder="请在此粘贴您的会议记录、语音转写草稿、或者杂乱无章的碎片化灵感...", 
        height=320
    )

with col2:
    requirement = st.text_area(
        "🎯 附加要求 (可选)", 
        placeholder="例如：\n1. 加上Emoji\n2. 语气要活泼\n3. 重点标红...", 
        height=100
    )

    # 永久模版录入区
    with st.expander("💾 录入并保存新【经验模版】", expanded=False):
        new_tpl_name = st.text_input("模版名称 (必填)", placeholder="例如：阿里风技术周报")
        new_tpl_content = st.text_area("模版内容", height=120)
        if st.button("✅ 永久保存模版", use_container_width=True):
            if new_tpl_name.strip() and new_tpl_content.strip():
                st.session_state.templates[new_tpl_name.strip()] = new_tpl_content.strip()
                save_templates(st.session_state.templates)
                st.success(f"模版【{new_tpl_name}】已永久保存！")
                st.rerun()
            else:
                st.warning("⚠️ 模版名称和内容均不能为空！")
    
    with st.expander("🛠️ 高级预处理选项"):
        clean_timestamps = st.checkbox("🧹 清理录音时间戳", value=True, help="自动去除 [00:01:23] 等时间戳")
        reorder_logic = st.checkbox("🧠 智能逻辑重组", value=True, help="强制要求模型先理顺乱序时间线再排版")
        enable_compression = st.checkbox("✂️ 超长文本前置并发压缩", value=True, help="超4万字时自动多线程提炼，防爆Token")

st.write("") 

# ==========================================
# 2. 快捷指令与启动区 (含模版选择与删除)
# ==========================================
st.markdown("#### ⚡ 选择场景模式与模版，启动双核对决")
col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)

def build_final_prompt(base_prompt, current_req, ref_temp):
    inst = base_prompt
    if ref_temp:
        inst += f"\n\n【参考经验模版】(请参考此模版的排版结构进行填充)：\n{ref_temp}"
    if current_req:
        inst += f"\n\n🚨【用户最高优先级要求】：\n{current_req}"
    return inst

tpl_options = ["(不使用模版)"] + list(st.session_state.templates.keys())

def render_action_column(col, title, action_key, is_primary=False):
    with col:
        btn_clicked = st.button(title, use_container_width=True, type="primary" if is_primary else "secondary")
        selected_tpl = st.selectbox(
            f"👇 为【{title.split(' ')[1]}】配置模版", 
            options=tpl_options, 
            key=f"sel_{action_key}",
            label_visibility="collapsed"
        )
        if selected_tpl != "(不使用模版)":
            if st.button(f"🗑️ 删除该模版", key=f"del_{action_key}", help="从系统中永久删除此模版"):
                del st.session_state.templates[selected_tpl]
                save_templates(st.session_state.templates)
                st.rerun() 
        return btn_clicked, selected_tpl

c1_btn, c1_tpl = render_action_column(col_btn1, "🤝 外部会谈纪要", "btn1")
c2_btn, c2_tpl = render_action_column(col_btn2, "📋 内部会议纪要", "btn2")
c3_btn, c3_tpl = render_action_column(col_btn3, "📊 日常运作纪要", "btn3")
c4_btn, c4_tpl = render_action_column(col_btn4, "🚀 自由自定义", "btn4")

# 捕捉点击事件并设置指令
trigger = False
action_name = ""
active_instruction = ""
# 【修改点 3】：不再切换到 SPEAKER_DIARIZATION_PROMPT，全局统一使用 COPYWRITING_SYSTEM_PROMPT，由 PROMPT 自身负责把控
active_system_prompt = COPYWRITING_SYSTEM_PROMPT 
custom_req = requirement.strip()

if c1_btn:
    r_temp = st.session_state.templates.get(c1_tpl, "") if c1_tpl != "(不使用模版)" else ""
    active_instruction = build_final_prompt(PROMPT_CLIENT_MEETING, custom_req, r_temp)
    action_name = "外部会谈纪要"
    trigger = True
elif c2_btn:
    r_temp = st.session_state.templates.get(c2_tpl, "") if c2_tpl != "(不使用模版)" else ""
    active_instruction = build_final_prompt(PROMPT_INTERNAL_MEETING, custom_req, r_temp)
    action_name = "内部会议纪要"
    trigger = True
elif c3_btn:
    r_temp = st.session_state.templates.get(c3_tpl, "") if c3_tpl != "(不使用模版)" else ""
    active_instruction = build_final_prompt(PROMPT_OPERATIONAL, custom_req, r_temp)
    action_name = "日常运作纪要"
    trigger = True
elif c4_btn:
    r_temp = st.session_state.templates.get(c4_tpl, "") if c4_tpl != "(不使用模版)" else ""
    base_inst = ""
    if not custom_req and not r_temp:
        base_inst = COPYWRITING_DEFAULT_REQ
    active_instruction = build_final_prompt(base_inst, custom_req, r_temp)
    action_name = "自定义排版"
    trigger = True

# ==========================================
# 3. 数据预处理触发区
# ==========================================
if trigger:
    file_content = ""
    if uploaded_files:
        for file in uploaded_files:
            file_content += f"\n\n--- 【文件素材: {file.name}】 ---\n"
            file_content += file.getvalue().decode("utf-8", errors='ignore')
            
    raw_text = manual_text.strip() + "\n" + file_content.strip()

    if not raw_text.strip():
        st.warning("⚠️ 请输入需要整理的原始素材，或上传相关文件！")
        st.stop()

    if clean_timestamps:
        raw_text = re.sub(r'\[?\b\d{1,2}:\d{2}(:\d{2})?(\.\d{1,3})?\b\]?', '', raw_text)
        raw_text = re.sub(r'\n\s*\n', '\n\n', raw_text)

    final_instruction = active_instruction
    if reorder_logic:
        final_instruction += "\n\n【特殊处理要求】：注意，提供的素材可能是碎片化或乱序拼接的（如不同人员发言错位、A段B段顺序颠倒）。请在正式整理前，务必先通过理解上下文理顺正确的时间线和逻辑主线，拼贴重组后，再进行输出。"

    if enable_compression and len(raw_text) > 40000:
        st.divider()
        st.info("⚠️ 检测到素材内容达到超长规模，正在启动【长文本并发分片压缩】流程...")
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=25000, chunk_overlap=3000)
        chunks = text_splitter.split_text(raw_text)
        compress_llm = ChatOpenAI(model=model_a, api_key=settings.API_KEY, base_url=settings.API_BASE, temperature=0.1, model_kwargs={"request_timeout": 180})
        
        progress_bar = st.progress(0, text=f"准备处理 {len(chunks)} 个文本块...")
        compressed_chunks = [""] * len(chunks)
        
        def process_chunk(index, chunk_text):
            chunk_prompt = f"请提取以下文本的核心信息、关键数据和有效结论，去除寒暄和废话，必须保留核心业务逻辑和数据。文本：\n{chunk_text}"
            max_retries = 3 
            for attempt in range(max_retries):
                try:
                    res = compress_llm.invoke(chunk_prompt)
                    return index, f"\n\n【分段 {index+1} 核心提炼】:\n{res.content}"
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** (attempt + 1))
                        continue 
                    return index, f"\n\n【分段 {index+1} 压缩失败】:\n{chunk_text}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(process_chunk, i, chunk) for i, chunk in enumerate(chunks)]
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                progress_bar.progress(completed / len(chunks), text=f"🚀 提炼中... (已完成 {completed}/{len(chunks)} 块)")
                idx, result_text = future.result()
                compressed_chunks[idx] = result_text

        raw_text = "".join(compressed_chunks)
        log_usage("长文本预处理并发压缩", model_a, int(len(raw_text) * 0.8))
        st.success("✅ 前置压缩完成！准备进入最终排版环节...")

    # 保存状态并清空历史对话，进入生成展示模式
    st.session_state.run_state = {
        "active": True,
        "action_name": action_name,
        "req": final_instruction,
        "text": raw_text,
        "system_prompt": active_system_prompt 
    }
    st.session_state.history_a = []
    st.session_state.history_b = []

# 工具函数：将字典列表转换为 LangChain 消息对象
def dicts_to_messages(dicts):
    msgs = []
    for d in dicts:
        if d["role"] == "system": msgs.append(SystemMessage(content=d["content"]))
        elif d["role"] == "user": msgs.append(HumanMessage(content=d["content"]))
        elif d["role"] == "assistant": msgs.append(AIMessage(content=d["content"]))
    return msgs

# ==========================================
# 4. 双模型对决与连续对话渲染
# ==========================================
if st.session_state.run_state.get("active"):
    st.divider()
    curr_action = st.session_state.run_state["action_name"]
    st.markdown(f"### 🤖 当前任务: {curr_action} (支持点击发送建议，继续调优)")
    col_a, col_b = st.columns(2)

    def render_chat_column(col, model_name, title_prefix, color_emoji, history_key):
        with col:
            with st.container(border=True):
                st.markdown(f"### {color_emoji} {title_prefix}")
                st.caption(f"🧠 驱动模型: `{model_name}`")
                st.markdown("---") 
                
                req = st.session_state.run_state["req"]
                text = st.session_state.run_state["text"]
                action_name = st.session_state.run_state["action_name"]
                
                llm = ChatOpenAI(
                    model=model_name,
                    api_key=settings.API_KEY,
                    base_url=settings.API_BASE,
                    temperature=0.3,
                    model_kwargs={"stream_options": {"include_usage": True}} 
                )
                
                sys_prompt = st.session_state.run_state.get("system_prompt", COPYWRITING_SYSTEM_PROMPT)

                # 场景一：首次生成 (如果记录为空)
                if not st.session_state[history_key]:
                    with st.chat_message("assistant", avatar="🤖"):
                        placeholder = st.empty()
                        full_text = ""
                        
                        initial_user_msg = f"【整理要求】\n{req}\n\n【原始素材】\n{text}"
                        messages = [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": initial_user_msg}
                        ]
                        
                        with get_openai_callback() as cb:
                            try:
                                for chunk in llm.stream(dicts_to_messages(messages)):
                                    full_text += chunk.content
                                    placeholder.markdown(full_text + " ▌")
                                placeholder.markdown(full_text)
                                
                                tokens = cb.total_tokens if cb.total_tokens > 0 else int((len(text) + len(req) + len(full_text)) * 1.2)
                                log_usage("文案双核整理_首发", model_name, tokens)
                                
                                # 将结果落盘
                                messages.append({"role": "assistant", "content": full_text})
                                st.session_state[history_key] = messages
                                
                            except Exception as e:
                                placeholder.error(f"❌ 生成失败或响应超时:\n {e}")
                                return

                # 场景二：渲染已有历史记录 (跳过system和第一条过于冗长的原始请求)
                if st.session_state[history_key]:
                    for idx, msg in enumerate(st.session_state[history_key]):
                        if idx < 2: continue # 跳过系统提示词和首条素材文本
                        
                        if msg["role"] == "assistant":
                            with st.chat_message("assistant", avatar="🤖"):
                                st.markdown(msg["content"])
                        elif msg["role"] == "user":
                            with st.chat_message("user", avatar="👤"):
                                st.markdown(f"**修改建议：** {msg['content']}")

                # 场景三：如果最后一条是user提交的新建议，触发新一轮流式生成
                if st.session_state[history_key] and st.session_state[history_key][-1]["role"] == "user":
                    with st.chat_message("assistant", avatar="🤖"):
                        placeholder = st.empty()
                        full_text = ""
                        with get_openai_callback() as cb:
                            try:
                                for chunk in llm.stream(dicts_to_messages(st.session_state[history_key])):
                                    full_text += chunk.content
                                    placeholder.markdown(full_text + " ▌")
                                placeholder.markdown(full_text)
                                
                                tokens = cb.total_tokens if cb.total_tokens > 0 else int(len(full_text) * 1.2)
                                log_usage("文案双核整理_追问", model_name, tokens)
                                
                                # 追加新的结果并刷新页面以稳定显示
                                st.session_state[history_key].append({"role": "assistant", "content": full_text})
                                st.rerun()
                            except Exception as e:
                                placeholder.error(f"❌ 追加生成失败:\n {e}")
                                return

                ## 场景四：底部功能栏 (下载 & 继续修改)
                if st.session_state[history_key] and st.session_state[history_key][-1]["role"] == "assistant":
                    st.markdown("---")
                    latest_text = st.session_state[history_key][-1]["content"]
                    
                    # 将 columns 的划分放在 form 外面
                    col_form, col_dl = st.columns([4, 1])
                    
                    with col_form:
                        # 只有输入框和提交按钮放在 form 内部
                        with st.form(key=f"form_{history_key}", clear_on_submit=True, border=False):
                            col_input, col_btn = st.columns([3, 1])
                            with col_input:
                                user_suggestion = st.text_input(
                                    "建议", 
                                    placeholder="例如：第一段太长了，帮我精简一下 / 加上项目符号", 
                                    label_visibility="collapsed"
                                )
                            with col_btn:
                                submit_btn = st.form_submit_button("发送修改建议", use_container_width=True)
                                
                            # 触发重新生成
                            if submit_btn and user_suggestion.strip():
                                st.session_state[history_key].append({"role": "user", "content": user_suggestion.strip()})
                                st.rerun()
                                
                    with col_dl:
                        # 下载按钮放在 form 外的独立列中，视觉上依然同行
                        st.download_button(
                            label="📥 下载当前版", 
                            data=latest_text, 
                            file_name=f"{action_name}_{title_prefix}_最新版.md", 
                            mime="text/markdown", 
                            key=f"dl_{history_key}",
                            use_container_width=True
                        )

    # 左右双列渲染
    render_chat_column(col_a, model_a, "方案 A", "🔵", "history_a")
    render_chat_column(col_b, model_b, "方案 B", "🔴", "history_b")