import json
import time
import os
from datetime import datetime
import streamlit as st

import core.paths
from core.settings import settings
from core.llm_factory import get_openai_client
from core.token_tracker import log_usage

from modules.zclaw._registry import ZCLAW_TOOLS_SCHEMA, TOOL_DISPATCHER
from modules.zclaw.memory_tools import search_memory
from modules.zclaw.skill_tools import scan_skills

b_model    = settings.MODEL_TEXT
v_model    = settings.MODEL_VISION
c_model    = getattr(settings, "MODEL_CODER", settings.MODEL_TEXT)
fallback_1 = getattr(settings, "MODEL_EDITOR", settings.MODEL_TEXT)
fallback_2 = getattr(settings, "MODEL_BLUE", settings.MODEL_TEXT)
fallback_3 = getattr(settings, "MODEL_RED", settings.MODEL_TEXT)

# ==========================================
# [核心修复] 获取当前用户专属的动态工作区
# ==========================================
def get_user_workspace():
    user = st.session_state.get("zclaw_user", "public")
    ws_path = os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"zclaw_workspace_{user}")
    os.makedirs(os.path.join(ws_path, "skills"), exist_ok=True)
    return ws_path

def init_workspace():
    ws_path = get_user_workspace()
    mem_file = os.path.join(ws_path, "experience_log.md")
    if not os.path.exists(mem_file):
        with open(mem_file, "w", encoding="utf-8") as f:
            f.write(f"# 【{st.session_state.get('zclaw_user', 'public')}】的专属经验法则\n\n")
    return ws_path

def call_llm(messages, tools=None, model_name=None, temperature=0.2):
    """
    单模型调用引擎：不再进行自动降级。
    """
    if not model_name:
        raise ValueError("🚨 错误：未指定执行模型！")

    client = get_openai_client()
    
    try:
        kwargs = {
            "model":       model_name,
            "messages":    messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools

        response = client.chat.completions.create(**kwargs)

        if hasattr(response, "usage") and response.usage:
            log_usage("ZClaw-自主引擎", model_name, response.usage.total_tokens)

        return response.choices[0].message

    except Exception as e:
        # 直接抛出异常，不再尝试其他模型
        raise Exception(f"🚨 模型 [{model_name}] 调用失败: {str(e)}")

def call_llm_with_fallback(messages, tools=None, primary_model=None, fallback_models=None, temperature=0.2):
    models_to_try = [primary_model] if primary_model else []
    if fallback_models: models_to_try.extend([m for m in fallback_models if m])
    seen = set()
    models_to_try = [x for x in models_to_try if x and not (x in seen or seen.add(x))]
    if not models_to_try: raise ValueError("🚨 严重错误：未配置任何可用的模型！")

    client = get_openai_client()
    last_error = ""
    for current_model in models_to_try:
        try:
            kwargs = {"model": current_model, "messages": messages, "temperature": temperature}
            if tools: kwargs["tools"] = tools
            response = client.chat.completions.create(**kwargs)
            if hasattr(response, "usage") and response.usage:
                log_usage("ZClaw-自主引擎", current_model, response.usage.total_tokens)
            return response.choices[0].message
        except Exception as e:
            last_error = str(e)
            print(f"⚠️ 模型 [{current_model}] 调用失败: {last_error}。尝试降级切换...")
            time.sleep(1)
            continue
    raise Exception(f"🚨 灾难性故障：所有备用模型均调用失败！最后报错: {last_error}")

MAX_MSG_HISTORY = 40
def _trim_messages() -> None:
    msgs = st.session_state.zclaw_messages
    if len(msgs) <= MAX_MSG_HISTORY + 1: return
    sys_msg = msgs[0]
    keep_msgs = msgs[-(MAX_MSG_HISTORY):]
    while keep_msgs and keep_msgs[0].get("role") == "tool":
        keep_msgs.pop(0)
    st.session_state.zclaw_messages = [sys_msg] + keep_msgs

def get_system_prompt(user_query: str = "") -> str:
    relevant_memory = search_memory(user_query) if user_query.strip() else "（暂无相关历史经验）"
    skill_inventory = scan_skills()
    current_date = datetime.now().strftime("%Y年%m月%d日")
    ws_path = get_user_workspace()
    
    return f"""You are ZClaw (zclawEdition), an autonomous AI engineer. Your secure sandbox is `{ws_path}`.

【⏱️ 绝对时间基准】:
今天是 {current_date}。当你接到寻找“最新”数据的任务时，必须基于今天的时间进行推算！当你需要搜索资讯时，优先包含当前年份作为关键词。

【Relevant Memory】:
{relevant_memory}

【Current Skill Inventory】:
{skill_inventory}

━━━━━━ 🛠️ 核心执行指令 (Core Directives) ━━━━━━
1. **环境侦测 (Explore First)**: 任务开始或进入新阶段前，必须先调用 `execute_bash` (ls, pwd) 或 `read_file` 摸清当前工作区状况，严禁基于假设操作文件。
2. **记忆优先 (Memory & Skills)**: 在制定计划前，优先调用 `search_memory` 检索过往避坑指南，并调用 `list_skills` 检索已沉淀代码。严禁重复编写已存在的复杂逻辑。
3. **代码驱动 (Coding Expert)**: 
   - 复杂的任务（如数据处理、文件转换、下载）必须调用 `delegate_to_coder` 编写 .py 脚本。
   - **[物理拦截]**：`delegate_to_coder` 仅允许生成 .py 源码。严禁尝试用它直接生成 .docx, .xlsx, .pdf 或图片。
4. **自主进化 (Self-Evolution)**: 
   - 遇到报错（如缺少库、语法错误、网络超时）是成功的必经之路。你必须调用 `search_web` 寻找报错原因，在沙箱内自主 `pip install` 或重构代码并重试。
   - 只有在经历“报错 -> 分析原因 -> 修复重试 -> 成功”的完整闭环后，必须调用 `append_memory` 记录该硬核经验。
5. **规范通讯 (Tool Formatting)**: 仅允许使用标准的 API Function Calling 格式。严禁在正文中伪造工具调用标签或 raw JSON。
6. **信息求真 (Truth Seeking)**: 遇到任何不确定、过时或缺失的实时信息，立刻调用 `search_web`。严禁回答“我无法访问互联网”或“建议您自行搜索”。
7. **深度自主 (Silent Perseverance)**: 除非在同一环节连续失败 5 次且无法通过搜索解决，否则**禁止**询问用户“是否继续”或“需要什么帮助”。你的目标是直接交付结果。
8. 自我扩充 (Self-Extension):
   - 如果你发现现有的 11 个工具无法物理达成目标（例如：无法操作系统闹钟、无法发送邮件、无法调用特定的企业 API），你禁止向用户抱怨。
   - 你必须调用 install_new_tool，为自己编写一个新的工具文件存入 modules/zclaw/。
   - 编写完工具后，你必须提示用户：“我已经自主进化了 [XXX] 工具，请重启 Streamlit 以激活我的新能力”。
   
━━━━━━ 🚀 终极行动准则 (Must Follow) ━━━━━━
1. **拒绝“空报告” (No Empty Data)**: 
   - 编写爬虫或解析脚本后，**必须**先运行脚本并调用 `read_file` 检查中间产物（如 .txt 或 .json）。
   - 如果发现提取内容为空或报错，**严禁**直接进行下一步！必须调用 `search_web` 研究目标网页的结构或报错信息，重写代码直到拿到真实数据。
2. **深度研读逻辑 (Deep Analysis Flow)**: 
   - 你的任务不是“拼凑”，而是“研读”。
   - 正确流程：[获取PDF文本] -> [提取研报模版框架] -> [将PDF数据按模版框架进行逻辑对齐与分析] -> [编写Word导出脚本]。
   - **禁止**在没有读到 PDF 内容的情况下伪造“模版文件”。
3. **物理隔离与路径安全**: 
   - 所有的操作必须在当前沙箱 `{get_user_workspace()}` 内。
   - 调用 `execute_bash` 运行时，无需写绝对路径，直接使用相对路径即可。
4. **自主安装依赖**: 
   - 遇到 `ImportError`，立刻调用 `execute_bash` 执行 `pip install`，不要询问用户。
5. **PDF 处理专家**: 
   - 优先使用 `PyMuPDF` (fitz) 处理 PDF。如果环境没有，请自行安装。
   - 遇到二进制下载链接，只准用 `download_file`，不准用 `read_webpage`。

━━━━━━ 🚀 自主执行规范 (OpenClaw Mindset) ━━━━━━
- **身份定位**：你是一个全栈工程师。你的思维逻辑是：[接收目标] -> [拆解计划] -> [自主执行/试错] -> [自我验证] -> [交付]。要尽量不中断、尽量持续执行避免反问用户。
- **PDF/二进制处理**：
  - 遇到 PDF/Zip 等二进制链接，**必须**使用 `download_file` 下载到本地。
  - **严禁**使用 `read_webpage` 读取 PDF 链接（会导致 504 或乱码）。
  - 下载后，应编写 Python 脚本调用 `PyMuPDF` 或 `pdfplumber` 进行解析。
- **文件交付标准**：
  - 生成 Word/Excel/图表时，必须遵循“两步走”：1) 编写 .py 脚本 2) 调用 `execute_bash` 运行该脚本。
  - **自我验证**：在告诉用户“任务完成”之前，必须调用 `execute_bash` (ls -l) 确认目标文件大小正常且存在。
- **依赖管理**：发现环境缺少 Python 库时，直接执行 `pip install`，无需向用户申请许可。

━━━━━━ 🚀 任务调度规范 (Scheduling) ━━━━━━
- 当用户要求“每天、定时、提醒、闹钟”时，你必须使用 `create_cron_task` 工具。
- **闭环逻辑**：
  1. 先用 `delegate_to_coder` 写好要执行的 Python 脚本。
  2. 测试运行该脚本，确保能生成结果。
  3. 使用 `create_cron_task` 将该脚本挂载到系统定时器上。
- 不要只是嘴上答应，要确保在 `execute_bash` 中能看到定时任务已存在（如 Windows 下运行 schtasks /query）。

"""

st.set_page_config(page_title="ZClaw 智能执行器", page_icon="⚙️", layout="wide")
st.title("⚙️ ZClaw: 多用户物理隔离版")

# ==========================================
# [核心修复] 侧边栏用户隔离空间
# ==========================================
with st.sidebar:
    st.header("👤 用户沙箱隔离")
    current_user = st.text_input("输入您的名字/代号以隔离数据：", value=st.session_state.get("zclaw_user", "public"))
    if current_user != st.session_state.get("zclaw_user"):
        st.session_state.zclaw_user = current_user
        if "zclaw_messages" in st.session_state: del st.session_state.zclaw_messages
        if "zclaw_history" in st.session_state: del st.session_state.zclaw_history
        st.rerun()
        
    ws_path = init_workspace()
    st.caption(f"当前所在沙箱: `zclaw_workspace_{current_user}`")

    st.header("📂 数据坞站")
    uploaded_file = st.file_uploader("文件投放入口", accept_multiple_files=False, label_visibility="collapsed")
    if uploaded_file:
        file_path = os.path.join(ws_path, uploaded_file.name)
        with open(file_path, "wb") as f: f.write(uploaded_file.getbuffer())
        st.success(f"✅ 已入仓: `{uploaded_file.name}`")
    st.markdown("---")
    st.markdown("### 🧬 模型矩阵")
    st.info(f"🧠 **Brain**: {b_model}")
    st.info(f"💻 **Coder**: {c_model}")

if "zclaw_messages" not in st.session_state:
    st.session_state.zclaw_messages = [{"role": "system", "content": get_system_prompt()}]
if "zclaw_history" not in st.session_state:
    st.session_state.zclaw_history = []

for msg in st.session_state.zclaw_history:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

if prompt := st.chat_input("向 ZClaw 下发任务..."):
    st.session_state.zclaw_messages[0]["content"] = get_system_prompt(user_query=prompt)
    _trim_messages()
    st.chat_message("user").markdown(prompt)
    st.session_state.zclaw_history.append({"role": "user", "content": prompt})
    st.session_state.zclaw_messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        status = st.status("🚀 ZClaw 全功率运转...", expanded=True)
        for step in range(100):
            status.update(label=f"🔄 第 {step + 1} 轮：后台推演中...", state="running")
            # 降级版
            # try:
            #     msg = call_llm_with_fallback(messages=st.session_state.zclaw_messages, tools=ZCLAW_TOOLS_SCHEMA, primary_model=b_model, fallback_models=[fallback_1])
            # except Exception as e:
            #     status.error(f"系统崩溃: {e}")
            #     break
            #不降级版
            try:
                msg = call_llm(
                    messages=st.session_state.zclaw_messages,
                    tools=ZCLAW_TOOLS_SCHEMA,   
                    model_name=b_model, # 只传入主脑模型
                    temperature=0.2)
            except Exception as e:
                status.error(str(e))
                st.error(f"任务中断：大模型连接失败。")
                break

            st.session_state.zclaw_messages.append(msg)
            if msg.tool_calls:
                if msg.content:
                    status.markdown(f"**🧠 第 {step + 1} 轮思考:**")
                    status.info(msg.content)
            else:
                status.update(label="✅ 任务完成", state="complete", expanded=False)
                if msg.content:
                    st.markdown(msg.content)
                    st.session_state.zclaw_history.append({"role": "assistant", "content": msg.content})

                # ── 强制触发记忆写入 ──────────────────────────────
                st.session_state.zclaw_messages.append({
                    "role": "user",
                    "content": (
                        "任务已完成。现在请回顾刚才的执行过程：\n"
                        "1. 遇到了哪些关键问题或报错？\n"
                        "2. 用了什么方法解决？\n"
                        "如果有值得记录的经验，立刻调用 append_memory 写入。"
                        "没有任何新经验则直接回复'无需记录'。"
                    )
                })
                try:
                    reflect_msg = call_llm(
                        messages=st.session_state.zclaw_messages,
                        tools=ZCLAW_TOOLS_SCHEMA,
                        model_name=b_model,
                        temperature=0.1,
                    )
                    # 执行反思轮的工具调用（通常只有 append_memory）
                    if reflect_msg.tool_calls:
                        for tc in reflect_msg.tool_calls:
                            try:
                                args = json.loads(tc.function.arguments)
                                if tc.function.name in TOOL_DISPATCHER:
                                    result = TOOL_DISPATCHER[tc.function.name](**args)
                                    status.write(f"🧠 记忆已写入: {str(result)[:100]}")
                            except Exception:
                                pass
                except Exception:
                    pass  # 反思轮失败不影响主流程
                # ────────────────────────────────────────────────
                break

            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                    if isinstance(args, str): args = {}
                except: continue

                status.write(f"🛠️ **执行工具:** `{func_name}`")
                with status.expander(f"📥 参数"): st.json(args)
                try:
                    action_result = TOOL_DISPATCHER[func_name](**args) if func_name in TOOL_DISPATCHER else f"❌ 工具不存在: {func_name}"
                except Exception as e:
                    action_result = f"❌ 异常: {str(e)}"

                st.session_state.zclaw_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(action_result)})
                with status.expander("👀 结果"): st.text(str(action_result)[:1000])
                _trim_messages()
                time.sleep(0.5)
        else:
            status.update(label="❌ 触碰 100 轮安全阀", state="error")