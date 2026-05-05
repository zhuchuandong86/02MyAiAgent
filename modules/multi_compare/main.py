# modules/multi_compare/main.py
import os
import time
import json
import re

import core.paths
from core.settings import settings
from core.llm_factory import get_llm
from core.parsers.vision_engine import encode_and_compress_image
from core.prompts import DOC_VISION_EXTRACT, DOC_BLUE_AGENT, DOC_RED_AGENT, DOC_EDITOR_SYSTEM, DOC_EDITOR_USER

# [统一工具层] get_safe_text_for_model 与 sanitize_llm_output 均来自同层 utils
from modules.multi_compare.utils import get_safe_text_for_model, sanitize_llm_output


def process_single_page(image_path, page_num):
    print(f"👉 {settings.MODEL_VISION}正在深度解析并清洗页面 {page_num}: {os.path.basename(image_path)}...")
    try:
        base64_img = encode_and_compress_image(image_path)
    except Exception as e:
        return f"--- ⚠️ 图片预处理失败: {e} ---"

    messages = [{"role": "user", "content": [
        {"type": "text", "text": DOC_VISION_EXTRACT.format(page_num=page_num)},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
    ]}]

    llm = get_llm(model_name=settings.MODEL_VISION, temperature=0.1, streaming=True)
    res = ""
    for chunk in llm.stream(messages):
        if chunk.content:
            res += chunk.content
    return res.strip()


def _call_specialist_agent(role_prompt, full_text, model_name, agent_name, status_ui=None):
    msg_start = f"[{agent_name}] 启动独立阅卷，开始无损穿透阅读..."
    print(msg_start)
    if status_ui:
        status_ui.write(f"🕵️‍♂️ {msg_start}")

    chunk_size = 20000
    chunks = [full_text[i:i + chunk_size] for i in range(0, len(full_text), chunk_size)]

    all_reports = []
    for idx, chunk in enumerate(chunks):
        msg_chunk = f"   -> 🔍 [{agent_name}] 正在深挖第 {idx + 1}/{len(chunks)} 块核心数据 (流式保活中)..."
        print(msg_chunk)
        if status_ui:
            status_ui.write(msg_chunk)

        messages = [
            {"role": "system", "content": role_prompt},
            {"role": "user", "content": (
                f"【当前阅读进度: 第 {idx + 1}/{len(chunks)} 部分】\n"
                f"请严格按照你的角色设定，深挖以下数据中的问题与细节（务必标明页码）：\n\n{chunk}"
            )}
        ]

        try:
            llm = get_llm(model_name=model_name, temperature=0.1, streaming=True)
            part_res = ""
            for res_chunk in llm.stream(messages):
                if res_chunk.content:
                    part_res += res_chunk.content

            if not part_res or part_res.strip() == "":
                part_res = f"⚠️ {agent_name} 未能返回有效分析。"

            # 清洗 Agent 底稿中可能残留的 think 标签
            all_reports.append(sanitize_llm_output(part_res))
        except Exception as e:
            error_msg = f"⚠️ {agent_name} 在处理该区块时触发 API 限制或超时: {str(e)}"
            print(error_msg)
            if status_ui:
                status_ui.write(error_msg)
            all_reports.append(error_msg)

        time.sleep(2)

    return "\n\n".join(all_reports)


def _call_quick_agent(full_text, model_name, status_ui=None):
    msg = "⚡ 正在执行快速扫描解析..."
    print(msg)
    if status_ui:
        status_ui.write(msg)

    safe_text = get_safe_text_for_model(full_text, model_name)
    messages = [
        {"role": "system", "content": "你是一个高效的文档分析助手。请对提供的文本进行快速结构化解读，提取核心要点、关键数据和潜在风险，无需进行多轮推演。"},
        {"role": "user", "content": f"请对以下文档进行快速解读：\n\n{safe_text}"}
    ]

    llm = get_llm(model_name=model_name, temperature=0.1, streaming=True)
    res = ""
    for chunk in llm.stream(messages):
        if chunk.content:
            res += chunk.content
    return res


def _detect_doc_type(full_text, model_name):
    sample = full_text[:2000]
    messages = [{
        "role": "user",
        "content": (
            f'请用 JSON 格式输出以下文档的元信息，不要任何多余文字：\n'
            f'{{"industry": "所属行业", "doc_type": "文档类型", "reader": "核心读者", "key_focus": "一句话核心点"}}\n'
            f'文档样本：\n{sample}'
        )
    }]
    try:
        llm = get_llm(model_name=model_name, temperature=0.1, streaming=False)
        result = llm.invoke(messages).content
        json_str = re.search(r'\{.*\}', result, re.DOTALL)
        return json.loads(json_str.group()) if json_str else {}
    except Exception:
        return {}


def generate_final_summary(full_text, user_req="", style_instruction="", status_ui=None, mode="deep"):
    if status_ui:
        status_ui.write(f"\n🤖 [AI 启动] 模式：{mode}研判 | 正在准备引擎...")
    print(f"\n🤖 [AI 启动] 模式：{mode}研判 | 正在唤醒虚拟专家团队...")

    # ── 1. 文档定性 ──────────────────────────────────────────────────────────
    doc_meta = _detect_doc_type(full_text, settings.MODEL_TEXT)
    industry  = doc_meta.get("industry", "通用")
    doc_type  = doc_meta.get("doc_type", "报告")
    reader    = doc_meta.get("reader", "管理层")
    key_focus = doc_meta.get("key_focus", "")

    if status_ui:
        status_ui.write(f"✅ 定性完成：{industry}行业 | {doc_type}")

    doc_context = (
        f"行业={industry}，类型={doc_type}，核心读者={reader}，核心价值点={key_focus}\n"
        f"请基于以上定性结论，自动切换为最匹配的专业分析视角！"
    )

    user_directive_editor = ""
    if user_req and user_req.strip():
        user_directive_editor = (
            f'【🌟 客户核心需求】：\u201c{user_req.strip()}\u201d。'
            f'请在报告中优先、重点回应。\n\n'
        )

    blue_report = ""
    red_report  = ""

    # ── 2. 逻辑分流 ──────────────────────────────────────────────────────────
    if mode == "quick":
        if status_ui:
            status_ui.write("🚀 正在跨过红蓝军演练，执行高效直接解读...")
        quick_report = _call_quick_agent(full_text, settings.MODEL_EDITOR, status_ui)
        editor_safe_text = get_safe_text_for_model(full_text, settings.MODEL_EDITOR)
        editor_messages = [
            {"role": "system", "content": DOC_EDITOR_SYSTEM},
            {"role": "user", "content": (
                style_instruction
                + "\n\n请参考以下快速解析初稿，结合原文件，生成最终报告：\n"
                + f"【快速解析初稿】：\n{quick_report}\n\n"
                + f"【原文件底稿】：\n{editor_safe_text}\n\n"
                + user_directive_editor
            )}
        ]
    else:
        # 深度研判：红蓝军对抗
        user_directive_agent = (
            f'\n\n【🌟 客户核心需求】：\u201c{user_req.strip()}\u201d。'
            if user_req else ""
        )
        agent_style_hint = ""
        if style_instruction:
            agent_style_hint = (
                f"\n\n【🏆 金牌分析框架指引】："
                f"\n最终的主编会采用以下框架和视角来撰写报告。请你在阅读原文档时，"
                f"务必带上这些视角，优先提取能支撑该框架的核心数据、矛盾点与论据：\n"
                f"---框架内容---\n{style_instruction[:1500]}\n------------"
            )

        blue_prompt = DOC_BLUE_AGENT + f"\n\n【文档定性结论】：{doc_context}" + user_directive_agent + agent_style_hint
        red_prompt  = DOC_RED_AGENT  + f"\n\n【文档定性结论】：{doc_context}" + user_directive_agent + agent_style_hint

        blue_report = _call_specialist_agent(blue_prompt, full_text, settings.MODEL_BLUE, "🔵 蓝军风控官", status_ui)
        if status_ui:
            status_ui.write("⏳ 蓝军查阅完毕，缓冲避震中...")
        time.sleep(5)
        red_report = _call_specialist_agent(red_prompt, full_text, settings.MODEL_RED, "🔴 红军战略官", status_ui)

        editor_safe_text = get_safe_text_for_model(full_text, settings.MODEL_EDITOR)
        editor_messages = [
            {"role": "system", "content": DOC_EDITOR_SYSTEM},
            {"role": "user", "content": (
                style_instruction
                + "\n\n"
                + DOC_EDITOR_USER.format(
                    editor_safe_text=editor_safe_text,
                    blue_report=blue_report,
                    red_report=red_report,
                    user_directive_editor=user_directive_editor,
                    doc_context=doc_context
                )
            )}
        ]

    # ── 3. 首席主编统一输出 ───────────────────────────────────────────────────
    if status_ui:
        status_ui.write("👨‍⚖️ 正在进行最终研判融合输出...")

    llm_editor = get_llm(model_name=settings.MODEL_EDITOR, temperature=0.1, streaming=True)
    final_summary = ""
    for chunk in llm_editor.stream(editor_messages):
        if chunk.content:
            final_summary += chunk.content
            print(chunk.content, end="", flush=True)
    print()

    if "⚠️ 本次提取彻底失败" in final_summary:
        return final_summary, None

    # ── 4. 统一清洗 think 标签（quick / deep 均走此处）────────────────────────
    final_summary = sanitize_llm_output(final_summary)

    # ── 5. 深度模式：拼接专家组底稿（已在 Agent 阶段完成各自清洗）────────────
    preserved_agent_reports = ""
    if mode == "deep":
        preserved_agent_reports = (
            f"\n\n---\n### 📑 专家组独立研判底稿 (Multi-Agent 对抗记录)\n"
            f"> 💡 点击下方页签可查看 AI 专家团在生成报告前的原始碰撞过程。\n\n"
            f"<details>\n"
            f"<summary>🔍 <b>展开查看：🔵 蓝军风控官 - 深度挑刺报告</b></summary>\n\n"
            f"{blue_report}\n\n"
            f"</details>\n\n"
            f"<details>\n"
            f"<summary>🔍 <b>展开查看：🔴 红军战略官 - 增长建议报告</b></summary>\n\n"
            f"{red_report}\n\n"
            f"</details>\n"
        )

    return final_summary + preserved_agent_reports, None


# 🌟 修改后的 revise_report 函数
def revise_report(current_report, user_feedback, original_docs="", status_ui=None):
    safe_original = get_safe_text_for_model(original_docs, settings.MODEL_EDITOR) if original_docs else "无底层数据参考"
    
    messages = [
        {"role": "system", "content": "你是一位顶级商业分析主编。你的任务是根据客户的最新指示，对现有的研究报告进行精准的修改、润色、增删或重写。请保持原有的专业排版风格（Markdown），并直接输出修改后的【完整报告正文】，不要说多余的废话。"},
        {"role": "user", "content": (
            f"【原始底层数据参考】：\n{safe_original}\n\n"
            f"====================\n"
            f"【当前版本的报告】：\n{current_report}\n"
            f"====================\n"
            f"【客户的修改指示】：\n“{user_feedback}”\n\n"
            f"请严格遵照指示修改，并输出最新版本的完整报告（包含未修改的部分，保持结构完整）。"
        )}
    ]
    
    llm = get_llm(model_name=settings.MODEL_EDITOR, temperature=0.1, streaming=True)
    revised_summary = ""
    count = 0
    
    # 🌟 核心修改：流式输出到前端容器
    for chunk in llm.stream(messages):
        if chunk.content:
            revised_summary += chunk.content
            count += 1
            # 每收到几个 token 就刷新一次前端画面，带有光标跳动效果
            if status_ui and count % 5 == 0:
                status_ui.markdown(revised_summary + " ▌")
                
    # 完毕后，清洗掉大模型的 <thought_process> 思考标签
    revised_summary = sanitize_llm_output(revised_summary)
    
    # 🌟 生成完毕后，清空这个流式容器（因为前端随后会执行 st.rerun() 来展示清洗后的最终完美版）
    if status_ui:
        status_ui.empty()
            
    return revised_summary