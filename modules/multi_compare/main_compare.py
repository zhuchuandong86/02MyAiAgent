# modules/multi_compare/main_compare.py
import time

from core.settings import settings
from core.llm_factory import get_llm
from core.prompts import COMPARE_EXTRACT, COMPARE_EDITOR_SYSTEM, COMPARE_EDITOR_USER

# [统一工具层]
from modules.multi_compare.utils import sanitize_llm_output


def _extract_single_company(company_name, text, user_req=""):
    """Map 阶段：带上用户的「有色眼镜」对单家公司数据进行降噪提纯。"""
    chunk_size = 20000
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    print(f"📦 【{company_name}】长文本共 {len(text)} 字符，已切割为 {len(chunks)} 个数据块...")
    all_extracted_parts = []

    for idx, chunk in enumerate(chunks):
        print(f"   -> 🔍 正在扫描提纯第 {idx + 1}/{len(chunks)} 块 (流式保活中)...")

        prompt = COMPARE_EXTRACT.format(company_name=company_name, safe_text=chunk)
        if user_req:
            prompt = (
                f"【🌟 客户专属分析侧重点】：\n{user_req}\n\n"
                f"请极度优先提取与上述侧重点相关的所有真实数据！\n\n"
                + prompt
            )

        messages = [("user", prompt)]

        llm = get_llm(model_name=settings.MODEL_TEXT, temperature=0.1, streaming=True)
        part_res = ""
        try:
            for res_chunk in llm.stream(messages):
                if res_chunk.content:
                    part_res += res_chunk.content
        except Exception as e:
            part_res = f"[⚠️ 提取第 {idx + 1} 块时大模型服务异常: {str(e)}]"

        all_extracted_parts.append(part_res)
        time.sleep(1)

    return "\n\n".join(all_extracted_parts)


def generate_compare_summary(company_data_dict: dict, status_ui=None):
    """Reduce 阶段：多公司升维对抗，输出竞品横评报告。"""
    msg = "\n🤖 [多模态竞品大脑] 启动！正在串行穿透各家数据..."
    print(msg)
    if status_ui:
        status_ui.write(msg)

    # [修复] 浅拷贝保护调用方字典，避免 pop 副作用污染外部引用
    data = dict(company_data_dict)
    user_req          = data.pop("_USER_REQ_", "")
    style_instruction = data.pop("_STYLE_INSTRUCTION_", "")

    extracted_results = {}
    for name, text in data.items():
        step_msg = f"⏳ 正在为【{name}】进行专属数据降噪提纯..."
        if status_ui:
            status_ui.write(step_msg)

        extracted_results[name] = _extract_single_company(name, text, user_req)

        if status_ui:
            status_ui.write(f"✅ 【{name}】数据就绪。")

    final_msg = "✍️ 正在进行「非对称」对抗分析，首席主编出稿中..."
    if status_ui:
        status_ui.write(final_msg)

    combined_context = ""
    for name, extracted in extracted_results.items():
        combined_context += f"\n\n{'=' * 20}\n【{name} 核心提纯内容】：\n{extracted}\n{'=' * 20}"

    editor_messages = [
        ("system", COMPARE_EDITOR_SYSTEM),
        ("user", style_instruction + "\n\n" + COMPARE_EDITOR_USER.format(combined_context=combined_context))
    ]

    llm_editor = get_llm(model_name=settings.MODEL_EDITOR, temperature=0.1, streaming=True)
    final_summary = ""

    res_box = status_ui.empty() if status_ui else None

    try:
        count = 0
        for chunk in llm_editor.stream(editor_messages):
            if chunk.content:
                final_summary += chunk.content
                count += 1
                # 节流渲染，防前端假死
                if res_box and count % 8 == 0:
                    res_box.markdown(final_summary + " ▌")

        if res_box:
            res_box.markdown(final_summary)

    except Exception as e:
        error_msg = (
            f"❌ 多文档对比主编大模型调用失败"
            f"（通常是合并后的文本超过了模型上下文限制）：\n\n{str(e)}"
        )
        print(error_msg)
        if res_box:
            res_box.error(error_msg)
        return f"<h3>⚠️ 生成中断</h3><p>{error_msg}</p>"

    # [统一清洗] 消除横评报告里可能残留的 think 标签
    return sanitize_llm_output(final_summary)