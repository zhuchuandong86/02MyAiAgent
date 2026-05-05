# core/llm_factory.py
from openai import OpenAI
from langchain_openai import ChatOpenAI
from core.settings import settings

def get_openai_client() -> OpenAI:
    """
    [新增] 全局统一的原生 OpenAI 客户端工厂
    适用于：Agent Tool Calling、高并发异步推理等底层场景
    """
    return OpenAI(
        api_key=settings.API_KEY,
        base_url=settings.API_BASE
    )

def get_llm(model_name: str = None, temperature: float = 0.1, streaming: bool = True) -> ChatOpenAI:
    # 自动选择模型，优先使用传入的，否则回退到 settings 中的默认配置
    target_model = model_name or settings.MODEL_TEXT
    
    # 统一封装底层参数
    model_kwargs = {}
    if streaming:
        # 强制内网网关在流式输出时返回 Token 使用量
        model_kwargs["stream_options"] = {"include_usage": True}

    # 实例化并返回
    return ChatOpenAI(
        model=target_model,
        api_key=settings.API_KEY,
        base_url=settings.API_BASE,
        temperature=temperature,
        streaming=streaming,  # 👈 【核心修复】：必须显式传递此参数激活底层流式句柄
        model_kwargs=model_kwargs
    )