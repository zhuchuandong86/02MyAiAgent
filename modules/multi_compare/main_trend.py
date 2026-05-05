# modules/multi_compare/main_trend.py
import time

from core.settings import settings
from core.llm_factory import get_llm
from core.prompts import TREND_EXTRACT, TREND_EDITOR_SYSTEM, TREND_EDITOR_USER

# [统一工具层] 不再跨模块从 main.py 引入，彻底解耦
from modules.multi_compare.utils import get_safe_text_for_model, sanitize_llm_output


def _extract_single_year(year_label, text, user_req=""):
    """Map 阶段：独立提取单年核心数据，支持无限长文本分块安全读取。"""
    chunk_size = 20000
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    print(f"📦 【{year_label}】年长文本共 {len(text)} 字符，已切割为 {len(chunks)} 个数据块进行安全穿透读取...")

    all_extracted_parts = []
    for idx, chunk in enumerate(chunks):
        print(f"   -> 🔍 正在扫描提纯第 {idx + 1}/{len(chunks)} 块 (流式保活中)...")

        prompt = TREND_EXTRACT.format(year_label=year_label, safe_text=chunk)
        if user_req:
            prompt = (
                f"【🌟 客户专属推演侧重点】：\n{user_req}\n\n"
                f"请极度优先提取与上述侧重点相关的所有真实数据！\n\n"
                + prompt
            )

        messages = [{"role": "user", "content": prompt}]

        llm = get_llm(model_name=settings.MODEL_TEXT, temperature=0.1, streaming=True)
        part_res = ""
        for res_chunk in llm.stream(messages):
            if res_chunk.content:
                part_res += res_chunk.content

        all_extracted_parts.append(part_res)
        time.sleep(1)

    return "\n\n".join(all_extracted_parts)


def generate_trend_summary(yearly_data_dict: dict, status_ui=None):
    """Reduce 阶段：按时间轴进行历史连贯性推演，输出纵向趋势报告。"""
    msg = "\n🤖 [历史趋势大脑] 启动！正在串行梳理历年数据 (防 504 熔断)..."
    print(msg)
    if status_ui:
        status_ui.write(msg)

    # [修复] 浅拷贝保护调用方字典，避免 pop 副作用污染外部引用
    data = dict(yearly_data_dict)
    user_req          = data.pop("_USER_REQ_", "")
    style_instruction = data.pop("_STYLE_INSTRUCTION_", "")

    extracted_results = {}
    for year, text in data.items():
        step_msg = f"⏳ 正在独立清洗【{year}】年的历史数据 (流式保活中)..."
        print(step_msg)
        if status_ui:
            status_ui.write(step_msg)

        extracted_results[year] = _extract_single_year(year, text, user_req)

        done_msg = f"✅ 【{year}】年数据清洗完毕！"
        print(done_msg)
        if status_ui:
            status_ui.write(done_msg)
        time.sleep(2)

    final_msg = "✍️ 历年时间轴梳理完毕，资深分析师开始推演..."
    print(final_msg)
    if status_ui:
        status_ui.write(final_msg)

    sorted_years = sorted(extracted_results.keys())
    combined_context = ""
    for year in sorted_years:
        combined_context += f"\n\n{'=' * 20}\n【{year} 年度提取数据】：\n{extracted_results[year]}\n{'=' * 20}"

    editor_messages = [
        {"role": "system", "content": TREND_EDITOR_SYSTEM},
        {"role": "user", "content": (
            style_instruction
            + "\n\n"
            + TREND_EDITOR_USER.format(combined_context=combined_context)
        )}
    ]

    llm_editor = get_llm(model_name=settings.MODEL_EDITOR, temperature=0.1, streaming=True)
    final_summary = ""

    # [修复] 补充前端实时流式渲染，与 main_compare.py 保持一致，消除生成阶段黑屏
    res_box = status_ui.empty() if status_ui else None

    count = 0
    for chunk in llm_editor.stream(editor_messages):
        if chunk.content:
            final_summary += chunk.content
            count += 1
            print(chunk.content, end="", flush=True)
            if res_box and count % 8 == 0:
                res_box.markdown(final_summary + " ▌")

    print()

    if res_box:
        res_box.markdown(final_summary)

    # [统一清洗] 消除趋势报告里可能残留的 think 标签
    return sanitize_llm_output(final_summary)