import re

def natural_sort_key(s):
    """
    自然排序算法
    解决 10.jpg 排在 2.jpg 前面的痛点
    """
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]



def get_safe_text_for_model(text: str, model_name: str) -> str:
    """按模型名称动态裁剪文本，防止超长导致 504 网关超时。"""
    limit = 30000
    name_lower = model_name.lower()
    if "deepseek-v3" in name_lower:
        limit = 20000
    elif "deepseek-r1" in name_lower:
        limit = 20000
    elif "72b" in name_lower or "30b" in name_lower or "256k" in name_lower:
        limit = 20000
 
    if len(text) > limit:
        print(f"✂️ [防 504 截断] {model_name} 触发阈值，动态截断至 {limit} 字符...")
        return text[:limit] + f"\n\n...[警告：为防网关超时，尾部已安全截断]..."
    return text
 
 
def sanitize_llm_output(text: str) -> str:
    """
    将大模型输出中的 <think> 系列标签转换为前端可折叠的 HTML <details> 块。
 
    处理两种场景：
      1. 完整闭合的标签：<think>...</think> / <thinking>...</thinking> / <thought_process>...</thought_process>
      2. 未闭合的标签（流式中断、模型漏写闭合标签等边界情况）
    """
 
    # ── 阶段 1：处理完整闭合的 think 标签 ────────────────────────────────────
    pattern = r"<(think|thinking|thought_process)>(.*?)</\1>"
 
    def _thought_replacer(match: re.Match) -> str:
        content = match.group(2).strip()
        # 为每行加 blockquote 前缀，保留 Markdown 引用样式
        quoted = "\n".join("> " + line for line in content.splitlines())
        return (
            "\n<details>\n"
            "<summary>🧠 <b>点击展开：查看 AI 深度推演过程</b></summary>\n\n"
            f"{quoted}\n"
            "\n</details>\n\n"
        )
 
    text = re.sub(pattern, _thought_replacer, text, flags=re.DOTALL | re.IGNORECASE)
 
    # ── 阶段 2：处理未闭合的 think 标签（逐一配对，找出剩余的开标签）────────
    open_positions = [m.start() for m in re.finditer(r"(?i)<think>", text)]
    close_count = len(re.findall(r"(?i)</think>", text))
    unclosed_count = len(open_positions) - close_count
 
    if unclosed_count > 0:
        # 取最后 unclosed_count 个开标签中的第一个作为截断起点
        split_pos = open_positions[-unclosed_count]
        before = text[:split_pos]
        think_content = re.sub(r"(?i)<think>", "", text[split_pos:], count=1).strip()
        quoted = "\n".join("> " + line for line in think_content.splitlines())
        text = (
            before
            + "\n<details>\n"
            + "<summary>🧠 <b>点击展开：AI 深度思考（输出不完整）</b></summary>\n\n"
            + f"{quoted}\n"
            + "\n</details>\n"
        )
 
    return text