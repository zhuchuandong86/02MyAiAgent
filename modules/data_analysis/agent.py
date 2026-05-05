# modules/data_analysis/agent.py
import glob
import tempfile
from contextlib import redirect_stdout
import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
import streamlit as st
from datetime import datetime
import os
import io
import re
import shutil
import json
import base64
import urllib.parse
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END

import ast
import traceback

# 统一兵工厂与配置
import core.paths
from core.settings import settings
from core.llm_factory import get_llm
from modules.data_analysis.reporter import generate_html_report
from core.schemas import CodeReflection
from core.prompts import (
    DA_PLANNER_SYSTEM, DA_CODER_SYSTEM, DA_REFLECT_SYSTEM, 
    DA_ANALYST_SYSTEM, DA_FOLLOWUP_SYSTEM
)

# ==========================================
# Harness Engineering: 代码执行保护带沙箱 (原封不动保留)
# ==========================================
class CodeExecutionHarness:
    def __init__(self):
        self.forbidden_calls = ['system', 'popen', 'rmdir', 'remove', 'eval', 'exec']

    def pre_flight_check(self, code: str) -> str:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return f"SyntaxError (代码存在基本语法错误): {e.msg} at line {e.lineno}"
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.forbidden_calls:
                    return f"SecurityError: Harness 拦截到被禁止的系统级函数调用 `{node.func.id}`，请修改代码仅进行数据处理。"
                elif isinstance(node.func, ast.Attribute) and node.func.attr in self.forbidden_calls:
                     return f"SecurityError: Harness 拦截到危险属性调用 `{node.func.attr}`。"
        return ""

    def execute(self, code: str, dfs: dict) -> tuple[str, str]:
        static_error = self.pre_flight_check(code)
        if static_error: return "", static_error
            
        first_df_name = list(dfs.keys())[0] if dfs else None
        captured_output = io.StringIO()
        
        exec_env = {
            "dfs": dfs, "df": dfs[first_df_name] if first_df_name else None, 
            "pd": pd, "os": os, "re": re, "__builtins__": __builtins__
        }
        
        try:
            import matplotlib
            matplotlib.use("Agg")
            with redirect_stdout(captured_output):
                exec(code, exec_env)
            return captured_output.getvalue(), ""
        except Exception as e:
            tb_str = traceback.format_exc()
            lines = tb_str.split('\n')
            short_tb = '\n'.join(lines[-15:]) if len(lines) > 15 else tb_str
            error_msg = f"运行时异常 {type(e).__name__}: {str(e)}\n\n--- Harness 捕获到的详细堆栈 ---\n{short_tb}"
            return captured_output.getvalue(), error_msg

# ==========================================
# 0. 自动生成洞察机制
# ==========================================
def run_auto_insights(dfs: dict) -> dict:
    llm = get_llm(temperature=0.1, streaming=False) # 关闭流式以支持 invoke
    
    dataset_info_list = []
    for name, df in dfs.items():
        cols = ", ".join(df.columns.astype(str))
        sample = df.head(3).fillna("NaN").to_string()
        dataset_info_list.append(f"表名: {name}\n字段: {cols}\n样本:\n{sample}")
    
    dataset_summary = "\n\n".join(dataset_info_list)[:6000]
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位资深AI数据产品经理。请基于提供的数据集样本，快速生成“数据画像(Data Profiling)”并推荐3个高价值的启发式分析问题。
必须返回纯JSON格式，禁止输出任何Markdown标记或其他说明文字。格式必须如下：
{{
  "summary": "简短的一段话总结这些数据包含什么维度的信息，能用于什么方向的分析。",
  "questions": ["推荐问题1", "推荐问题2", "推荐问题3"]
}}"""),
        ("user", f"【数据集信息】:\n{dataset_summary}")
    ])
    
    try:
        response = (prompt | llm).invoke({})
        content = response.content.strip()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        else:
            raise ValueError("未能从模型回复中提取 JSON。")
    except Exception as e:
        print(f"[ERROR] Auto-Insights 解析失败: {e}")
        return {"summary": "数据已就绪。您可以手动输入分析需求。", "questions": ["概括数据指标", "绘制业务趋势", "分析数据分布"]}

# ==========================================
# 1. 定义 LangGraph 全局状态字典
# ==========================================
class AgentState(TypedDict):
    dfs: dict
    dataset_summary: str
    user_query: str
    chart_dir: str
    plan: str
    generated_code: str
    execution_logs: str
    error_msg: str
    reflections: list
    attempt: int
    max_retries: int
    final_markdown: str

# ==========================================
# 2. 定义图节点 (Nodes)
# ==========================================
def node_planner(state: AgentState) -> dict:
    st.markdown("### 🗺️ Planner Agent 正在宏观审视所有表格，制定分析计划...")
    llm = get_llm(temperature=0)
    prompt = ChatPromptTemplate.from_messages([
        ("system", DA_PLANNER_SYSTEM),
        ("user", "以下是本次加载的所有数据表大纲：\n\n{dataset_summary}\n\n用户需求: {query}")
    ])
    
    analysis_plan = ""
    try:
        plan_placeholder = st.empty()
        count = 0
        for chunk in (prompt | llm).stream({"dataset_summary": state["dataset_summary"], "query": state["user_query"]}):
            analysis_plan += chunk.content
            count += 1
            if count % 8 == 0: plan_placeholder.markdown(f"```text\n{analysis_plan}▌\n```")
        plan_placeholder.markdown(f"```text\n{analysis_plan}\n```")
        st.success("✅ 多表联合分析计划制定完毕！")
    except Exception as e:
        analysis_plan = "通用关联分析：趋势、对比、数据融合"
        st.error(f"❌ Planner 调用失败：{e}")
    return {"plan": analysis_plan}

def node_coder(state: AgentState) -> dict:
    st.markdown(f"### 👨‍💻 程序员 Agent 开始跨表写代码 (第 {state['attempt']+1}/{state['max_retries']} 次)")
    llm = get_llm(temperature=0)
    
    memory_str = "无历史报错，首次尝试。"
    if state["reflections"]:
        memory_str = "\n".join([f"报错: {m['error']}\n对策: {m['fix_strategy']}" for m in state["reflections"]])

    prompt = ChatPromptTemplate.from_messages([
        ("system", DA_CODER_SYSTEM),
        ("user", "分析需求：{query}\n\n【数据集概览】：\n{dataset_summary}\n\n【UI与可视化】：建议用 Seaborn 的 whitegrid 风格。【⚠️警告】：系统底层已自动配置中文字体，代码中**绝对不要**再出现任何 `plt.rcParams['font.sans-serif']` 等配置！")
    ])

    raw_code = ""
    try:
        code_placeholder = st.empty()
        count = 0
        for chunk in (prompt | llm).stream({
            "dataset_summary": state["dataset_summary"], "analysis_plan": state["plan"],
            "memory_str": memory_str, "query": state["user_query"]
        }):
            raw_code += chunk.content
            count += 1
            if count % 8 == 0: code_placeholder.markdown(f"```python\n{raw_code}▌\n```")
        code_placeholder.markdown(f"```python\n{raw_code}\n```")
    except Exception as e:
        st.error(f"API请求异常: {e}")

    clean_code = raw_code.replace("```python", "").replace("```", "").strip()
    for zh, en in {"，": ",", "。": ".", "：": ":", "；": ";", "（": "(", "）": ")"}.items(): 
        clean_code = clean_code.replace(zh, en)
    
    # [核心修复]：动态加载项目自带中文字体，彻底绕过系统环境差异与 Matplotlib 缓存Bug
    agg_prefix = (
        "import matplotlib\nimport matplotlib.pyplot as plt\n"
        "import matplotlib.font_manager as fm\n"
        "import os as __os__\n"
        "# 尝试挂载项目级私有字体\n"
        "__font_path = __os__.path.join(__os__.getcwd(), 'core', 'fonts', 'SimHei.ttf')\n"
        "__font_name = 'SimHei'\n"
        "if __os__.path.exists(__font_path):\n"
        "    fm.fontManager.addfont(__font_path)\n"
        "    __font_name = fm.FontProperties(fname=__font_path).get_name()\n"
        "__font_list = [__font_name, 'PingFang SC', 'Microsoft YaHei', 'SimHei', 'STHeiti', 'WenQuanYi Micro Hei']\n"
        "try:\n    import seaborn as sns\n    sns.set_style('whitegrid', {'font.sans-serif': __font_list})\nexcept:\n    pass\n"
        "plt.switch_backend('agg')\n"
        "plt.rcParams['font.sans-serif'] = __font_list\n"
        "plt.rcParams['axes.unicode_minus'] = False\n"
        f"__chart_dir__ = r'{state['chart_dir']}'\n"
        "if hasattr(plt, '_original_savefig'):\n    plt.savefig = plt._original_savefig\n" 
        "plt._original_savefig = plt.savefig\n" 
        "def __patched_savefig__(fname, *a, **kw):\n"
        "    target = fname\n"
        "    if isinstance(fname, str) and not __os__.path.isabs(fname):\n"
        "        target = __os__.path.join(__chart_dir__, __os__.path.basename(fname))\n"
        "    plt._original_savefig(target, *a, **kw)\n"
        "plt.savefig = __patched_savefig__\n"
    )
    return {"generated_code": agg_prefix + clean_code}

def node_executor(state: AgentState) -> dict:
    st.markdown("### 🛡️ Harness 沙箱验证与运行代码中...")
    harness = CodeExecutionHarness()
    stdout_logs, error_msg = harness.execute(state["generated_code"], state["dfs"])
    
    if not error_msg:
        charts_found = glob.glob(os.path.join(state["chart_dir"], "chart_*.png"))
        if stdout_logs.strip() or charts_found:
            st.success(f"✅ Harness 验证通过！代码执行成功！共生成图表: {len(charts_found)} 张")
        else:
            st.warning("⚠️ Harness 提示：代码执行成功，但未输出任何分析数据，且未生成图片！")
    else:
        st.error("❌ Harness 拦截到异常！已抓取堆栈日志并抛回给 AI 反思...")
        with st.expander("查看详细报错", expanded=False):
            st.code(error_msg)
            
    return {"execution_logs": stdout_logs, "error_msg": error_msg, "attempt": state["attempt"] + 1}

def node_reflector(state: AgentState) -> dict:
    llm = get_llm(temperature=0, streaming=False) # 必须关闭流式以使用 structured_output
    prompt = ChatPromptTemplate.from_messages([
        ("system", DA_REFLECT_SYSTEM),
        ("user", "报错信息: {error}\n\n出错代码片段:\n{code}")
    ])
    
    structured_llm = llm.with_structured_output(CodeReflection)
    try:
        reflection_obj = structured_llm.invoke(
            prompt.format_messages(error=state["error_msg"], code=state["generated_code"][-2000:])
        )
        reflection = {
            "attempt": state["attempt"], "error": state["error_msg"], 
            "root_cause": reflection_obj.root_cause, "fix_strategy": reflection_obj.fix_strategy, 
            "avoid": reflection_obj.avoid
        }
    except Exception:
        reflection = {
            "attempt": state["attempt"], "error": state["error_msg"],
            "root_cause": "解析失败", "fix_strategy": "请检查变量名或使用 try-except 跳过错误", "avoid": "避免复杂链式调用"
        }
    return {"reflections": state["reflections"] + [reflection]}

def node_analyst(state: AgentState) -> dict:
    if state["error_msg"] and state["attempt"] >= state["max_retries"]:
        return {"final_markdown": f"<h2>⚠️ 数据分析中断</h2><pre>{state['error_msg']}</pre>"}
        
    st.markdown("### 🧑‍💼 分析师 Agent 正在撰写最终多表融合洞察报告...")
    llm = get_llm(temperature=0.3)
    prompt = ChatPromptTemplate.from_messages([("system", DA_ANALYST_SYSTEM), ("user", "原需求：{query}")])
    
    generated_charts = glob.glob(os.path.join(state["chart_dir"], "chart_*.png"))
    chart_status = f"生成的图表文件有：{[os.path.basename(c) for c in generated_charts]}。"
    
    final_markdown = ""
    try:
        raw_report = ""
        report_placeholder = st.empty()
        count = 0
        for chunk in (prompt | llm).stream({
            "analysis_plan": state["plan"], "data_insights": state["execution_logs"],
            "chart_status": chart_status, "query": state["user_query"]
        }):
            raw_report += chunk.content
            count += 1
            if count % 8 == 0: report_placeholder.markdown(raw_report + "▌")
        report_placeholder.markdown(raw_report)
            
        match = re.search(r'<FINAL_REPORT>\s*(.*?)\s*</FINAL_REPORT>', raw_report, re.DOTALL)
        final_markdown = match.group(1).strip() if match else raw_report.strip()
    except Exception as e:
        final_markdown = f"报告生成失败: {e}"
    return {"final_markdown": final_markdown}

def router_after_execution(state: AgentState) -> Literal["reflector", "analyst"]:
    if state["error_msg"] and state["attempt"] < state["max_retries"]: return "reflector"
    return "analyst"

# ==========================================
# 3. 核心主入口：构建与运行 Graph
# ==========================================
def run_agent_pipeline(dfs: dict, user_query: str):
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_out = os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"数据分析报告_{current_time}.html")

    cleaned_dfs = {}
    dataset_info_list = []
    # [原有清洗逻辑保留]
    for table_name, df in dfs.items():
        df.dropna(how='all', inplace=True)
        df.dropna(axis=1, how='all', inplace=True)
        df = df.loc[:, ~df.columns.astype(str).str.contains('^Unnamed')]
        df.columns = df.columns.astype(str).str.strip().str.replace('\n', '').str.replace('\r', '').str.replace('　', '')
        if df.empty or len(df.columns) == 0: continue 
            
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].replace(['-', '--', '无', 'N/A', 'NA', 'null', ''], pd.NA)
                temp_col = df[col].astype(str).str.replace(r'[¥$,\s]', '', regex=True)
                converted = pd.to_numeric(temp_col, errors='coerce')
                if converted.notna().mean() > 0.5: df[col] = converted
                    
        cleaned_dfs[table_name] = df
        cols_str = ", ".join(df.columns)
        sample_str = df.head(3).fillna("空值(NaN)").to_string()
        dataset_info_list.append(f"📦【表名】: {table_name}\n【字段】: {cols_str}\n【样本】:\n{sample_str}\n")
        
    if not cleaned_dfs:
        error_html = "<h2 style='color:red;'>❌ 数据处理失败</h2><p>表格无有效数据。</p>"
        with open(report_out, "w", encoding="utf-8") as f: f.write(error_html)
        return error_html, report_out, {}
        
    dataset_summary = "\n".join(dataset_info_list)
    if not user_query or not user_query.strip():
        user_query = "扫描所有数据表，寻找可关联挖掘的维度并输出图表。"

    chart_dir = tempfile.mkdtemp(prefix="agent_charts_")

    workflow = StateGraph(AgentState)
    workflow.add_node("planner", node_planner)
    workflow.add_node("coder", node_coder)
    workflow.add_node("executor", node_executor)
    workflow.add_node("reflector", node_reflector)
    workflow.add_node("analyst", node_analyst)
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "coder")
    workflow.add_edge("coder", "executor")
    workflow.add_conditional_edges("executor", router_after_execution, {"reflector": "reflector", "analyst": "analyst"})
    workflow.add_edge("reflector", "coder")
    workflow.add_edge("analyst", END)
    
    app = workflow.compile()

    initial_state = {
        "dfs": cleaned_dfs, "dataset_summary": dataset_summary, "user_query": user_query,
        "chart_dir": chart_dir, "plan": "", "generated_code": "", "execution_logs": "", 
        "error_msg": "", "reflections": [], "attempt": 0, "max_retries": 3, "final_markdown": ""
    }
    
    final_state = app.invoke(initial_state)
    final_markdown = final_state["final_markdown"]
    
    if final_state["error_msg"] and final_state["attempt"] >= final_state["max_retries"]:
        with open(report_out, "w", encoding="utf-8") as f: f.write(final_markdown)
        return final_markdown, report_out, {} 
        
    # [原有 HTML 生成与 Base64 注入逻辑保留]
    for src in glob.glob(os.path.join(chart_dir, "chart_*.png")):
        shutil.copy2(src, os.path.basename(src)) 

    html_string = generate_html_report(final_markdown, report_out)

    for src in glob.glob(os.path.join(chart_dir, "chart_*.png")):
        img_filename = os.path.basename(src)
        with open(src, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
        b64_src = f"data:image/png;base64,{encoded_string}"
        
        html_string = html_string.replace(img_filename, b64_src)
        html_string = html_string.replace(urllib.parse.quote(img_filename), b64_src)
        html_string = html_string.replace(f"./{img_filename}", b64_src)

    with open(report_out, "w", encoding="utf-8") as f: f.write(html_string)

    return html_string, report_out, {"plan": final_state["plan"], "data": final_state["execution_logs"]}

# ==========================================
# 4. 追问模块
# ==========================================
def run_followup_chat(user_query: str, chat_history: list, context_data: dict):
    llm_chat = get_llm(temperature=0.4)
    messages = [("system", DA_FOLLOWUP_SYSTEM.format(data=context_data.get("data", "无数据")))]
    for msg in chat_history: messages.append((msg["role"], msg["content"]))
    messages.append(("user", user_query))
    return (ChatPromptTemplate.from_messages(messages) | llm_chat).stream({})