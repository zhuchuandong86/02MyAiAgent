# modules/multi_compare/ui_prompts.py

UI_COGNITIVE_SINGLE = """
<COGNITIVE_PROTOCOL>
【顶级投行深度思考与防幻觉协议】
在输出正式研报前，你必须先在 `<thought_process>` 中理清逻辑。
1. 强制深度推演：禁止数值罗列！用投行视角穿透数据（如：反映了什么战略？有何隐性风险？）。
2. 零幻觉底线：无数据就划掉，不准瞎编。
</COGNITIVE_PROTOCOL>
"""

UI_COGNITIVE_COMPARE = """
<COGNITIVE_PROTOCOL>
【顶级投行错位竞争与非对称横向对比协议 (最高优先级)】
在动笔前，必须先在 `<thought_process>` 中规划如何“升维打击”：
1. 🚨 拒绝机械填表：严禁出现“公司A：有数据；公司B：数据缺失”这种低级对比！如果B没提某项数据，你应将其视为一种“战略上的沉默”或“重心不在于此”，通过分析A的激进来反衬B的保守或缺失。
2. 🚨 穿透口径差异：当两家公司说法不一（如：一家说算力，一家说云网），你必须从战略分歧的高度进行论述，而不是说无法对比。
3. 🚨 深度论述要求：每一个对比维度下，必须有至少 200 字的深度逻辑拆解，分析竞争压迫感。
</COGNITIVE_PROTOCOL>
"""

UI_COGNITIVE_TREND = """
<COGNITIVE_PROTOCOL>
【顶级投行生命周期与时间轴推演协议】
1. 时间轴铁律：严禁单一年份孤立成段，必须以【演进轨迹】为核心。
2. 寻找拐点：重点指出哪一年发生了战略转向，其底层诱因是什么。
</COGNITIVE_PROTOCOL>
"""

def GET_USER_PRIORITY(req):
    if not req.strip(): return ""
    return f"\n<USER_ABSOLUTE_PRIORITY>\n【用户最高指令：你必须首要回答以下问题】\n{req}\n</USER_ABSOLUTE_PRIORITY>\n"

def GET_STYLE_FUSION(templates_str, report_type="single"):
    if not templates_str: return ""
    
    # 针对不同场景，防止模板结构污染
    pollution_prevention = ""
    if report_type != "single":
        pollution_prevention = "🚨 致命提醒：当前是多文档横评/趋势任务，你提取的范例大概率是单篇报告。你必须只学习范例的语气，绝对禁止照抄它的单体标题（如“经营成果”），必须使用对抗性的横评标题！"

    return f"""
<STYLE_FUSION>
【跨界风格融合指令】
请综合借鉴以下多个【金牌范例骨架】。
{pollution_prevention}
=== 金牌范例骨架 ===
{templates_str}
</STYLE_FUSION>
"""

UI_CHART_MERMAID = """
<CHART_GENERATION>
【强制图表指令】
在对比数据时，必须使用 Mermaid 语法绘制可视化图表。
</CHART_GENERATION>
"""