import streamlit as st
import os
import uuid
import json
import time
from datetime import datetime
from openai import OpenAI
from modules.zclaw.web_tools import search_web, read_webpage
from modules.zclaw.skill_tools import scan_skills


import core.paths
from core.settings import settings
from core.token_tracker import log_usage
from modules.zclaw._registry import ZCLAW_TOOLS_SCHEMA, TOOL_DISPATCHER

# 页面配置
st.set_page_config(page_title="全网深度研究员", page_icon="🌍", layout="wide")
st.title("🌍 全网深度研究员 (状态机沙箱版)")
st.markdown("突破单次搜索限制，Agent 将自主拆解课题、创建 `STATE.md` 打卡记录、并发调用浏览器工具，最终合成带独立来源引用的深度研报。")

# =========================================================
# 1. 🏗️ 核心基建：为每次研究动态分配专属沙箱 (多租户隔离)
# =========================================================
if "task_id" not in st.session_state:
    st.session_state.task_id = f"task_{uuid.uuid4().hex[:8]}"

workspace_dir = os.path.join(core.paths.GLOBAL_DATA_DIR, "workspaces", st.session_state.task_id)
os.makedirs(workspace_dir, exist_ok=True)

st.sidebar.markdown("### 🗂️ 任务沙箱状态")
st.sidebar.info(f"**Task ID**: `{st.session_state.task_id}`\n\n**隔离物理目录**: \n`{workspace_dir}`")

# =========================================================
# 2. 🧠 注入灵魂：融合了你的溯源要求 + 状态机约束
# =========================================================
current_time_str = datetime.now().strftime("%Y年%m月%d日")

RESEARCH_SYSTEM_PROMPT = f"""你是一个顶级的全网深度研究员与情报分析师。
你拥有极强的规划能力和执行力。你当前被分配的独立物理工作区是：{workspace_dir}
系统当前真实物理时间：{current_time_str}

【🛑 极度重要：状态机工作流 SOP】
在处理用户的复杂研究需求时，你必须严格遵循以下步骤：
1. **初始化状态**：任务开始的第一步，必须立即调用 `write_file` 工具，在你的工作区内创建一个名为 `STATE.md` 的文件。在里面列出你接下来的拆解步骤（例如：1.调用 search_web 查行业现状，2.查核心竞品，3.交叉验证，4.撰写并保存报告）。
2. **打卡机制**：每完成一个子步骤，你必须再次使用 `write_file` 更新 `STATE.md`，把完成的步骤打上 `[x]`，并记录核心数据点。
3. **精准时空与溯源**：在多次调用 `search_web` 和 `read_webpage` 获取情报时，严审时间，拒绝陈旧信息。
4. **物理交付**：所有的中间资料、引用的网页正文、以及最终的研报，都必须作为文件保存在你的专属工作区内。
   
【🎯 最终报告格式强制要求】：
1. 引用的新闻事件或数据旁，必须使用标准 Markdown 生成可点击的超链接。格式严格为：`[[来源:网站名]](完整的URL链接)`。注意：中括号和小括号之间绝对不能有空格！
2. 文末必须单独开辟 `### 📚 参考资料` 模块，格式严格为：`- [文章原标题](完整的URL链接)`。

【🔥 纪律红线（严禁口头承诺）】：
如果在调用工具（如搜索）时遇到网络报错或失败，你必须立刻思考，并**在同一轮回复中继续调用工具**（如更换关键词或重试）。**绝对不允许**只用文字回答“我将尝试其他方法”然后停止不前！只要任务没有真正获得数据并写完报告，你就必须源源不断地输出工具调用指令！

如果你意外崩溃或重启，请先用 `read_file` 读取 `STATE.md`，看看自己上次干到了哪里。
"""

# =========================================================
# 3. 💻 UI 交互与 Agent 调度主循环
# =========================================================
topic = st.text_input("🎯 请输入您想研究的课题 (例如：查一下今天的南非科技新闻)：")

if st.button("🚀 启动深度研究循环", type="primary"):
    if not topic.strip():
        st.warning("⚠️ 请输入研究课题！")
        st.stop()
        
    st.markdown("---")
    
    # 建立左右两栏：左边看 AI 的动作日志，右边实时偷窥它的物理 STATE.md
    col_log, col_state = st.columns([2, 1])
    
    with col_log:
        status_box = st.status("🧠 研究引擎点火中，正在分配沙箱...", expanded=True)
    with col_state:
        st.markdown("#### 📋 实时状态机 (STATE.md)")
        state_display = st.empty()
        state_display.code("等待 Agent 在沙箱内创建打卡文件...", language="markdown")

    client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
    
    messages = [
        {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
        {"role": "user", "content": f"请为我深度研究以下课题：{topic}。记住：第一步必须先用 write_file 在沙箱里创建 STATE.md 规划你的搜索步骤！"}
    ]
    
    # 允许 Agent 在后台死磕最多 15 轮（足够它拆解、搜网、读网页、写总结）
    max_loops = 15
    final_report = ""
    
    for step in range(max_loops):
        status_box.write(f"⏱️ 正在进行第 {step+1}/{max_loops} 轮独立思考与搜索...")
        
        response = client.chat.completions.create(
            model=settings.MODEL_EDITOR,
            messages=messages,
            tools=ZCLAW_TOOLS_SCHEMA,
            temperature=0.2
        )
        
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        
        # 🌟 偷窥者模式：实时读取硬盘上的状态文件并展示在右侧
        state_file_path = os.path.join(workspace_dir, "STATE.md")
        if os.path.exists(state_file_path):
            with open(state_file_path, "r", encoding="utf-8") as f:
                state_display.code(f.read(), language="markdown")
        
        # 如果 Agent 决定不调用工具了，说明它认为任务完成了，直接输出报告
        if not msg.tool_calls:
            status_box.update(label="✅ 深度研究与封装完毕！", state="complete", expanded=False)
            st.success("🎉 研究任务已结束，最终研报如下：")
            st.markdown(msg.content)
            final_report = msg.content
            
            # 记账
            if hasattr(response, 'usage'):
                log_usage("全网研究-Agent状态机版", os.getenv("MODEL_EDITOR", "deepseek"), response.usage.total_tokens)
            break
            
        # 遍历执行 Agent 调用的工具
        for tool in msg.tool_calls:
            func_name = tool.function.name
            
            # 🛡️ 增强型 JSON 解析 (防大模型双重转义)
            try:
                args = json.loads(tool.function.arguments)
                if isinstance(args, str):  # 补丁：如果大模型套了双层引号，再解析一次脱壳！
                    args = json.loads(args)
                if not isinstance(args, dict): # 极限兜底
                    args = {}
            except Exception:
                args = {}
            
            # 🛡️ 路径安全劫持机制 (Path Hijacking)：
            # 🛡️ 绝对物理锁 (Absolute Path Hijacking)：
            # 无论 Agent 给的是绝对路径还是相对路径，强行将其剥离，只取文件名，死死锁在沙箱内！
            if func_name in ["write_file", "read_file"]:
                if "filepath" in args:
                    # 兼容处理 Windows 的反斜杠和 Linux 的正斜杠
                    safe_filename = os.path.basename(args["filepath"].replace("\\", "/"))
                    args["filepath"] = os.path.join(workspace_dir, safe_filename)
            status_box.write(f"   ⚙️ 调度物理工具: `{func_name}` | 参数摘要: `{str(args)[:60]}...`")
            
            try:
                action_res = TOOL_DISPATCHER.get(func_name, lambda **kw: "⚠️ 系统缺失此工具")(**args)
            except Exception as e:
                action_res = f"⚠️ 工具执行报错: {e}"
                status_box.write(action_res)
                
            messages.append({
                "role": "tool",
                "tool_call_id": tool.id,
                "content": str(action_res)
            })
            time.sleep(1) # 缓冲一下，防止搜索 API 频率超限触发反爬
            
    else:
        status_box.update(label="⚠️ 达到最大思考轮数 (15轮)，引擎强制刹车保护", state="error")

    # 提供下载按钮
    if final_report:
        st.download_button(
            label="⬇️ 导出 Markdown 研报", 
            data=final_report, 
            file_name=f"状态机研报_{st.session_state.task_id}.md",
            type="primary"
        )