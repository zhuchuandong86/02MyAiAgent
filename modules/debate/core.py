# modules/debate/core.py
from core.token_tracker import log_usage

def stream_llm(client, model, system_prompt, history_prompt):
    """
    核心流式大模型调用生成器
    """
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": history_prompt}
            ],
            temperature=0.7,
            stream=True,
            stream_options={"include_usage": True} # 👈【新增】：强制官方接口在最后返回 Token 数
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
                # 👇【新增】：抓取最后一条带 usage 的隐藏信息
            if hasattr(chunk, 'usage') and chunk.usage is not None:
                total_tokens = chunk.usage.total_tokens
        # 计费入库
        log_usage("AI大模型辩论", model, total_tokens)
    except Exception as e:
        yield f"请求失败: {e}"