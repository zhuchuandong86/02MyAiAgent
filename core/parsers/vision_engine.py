# core/parsers/vision_engine.py
import base64
import io
import requests
from PIL import Image, ImageOps

from core.settings import settings
from core.token_tracker import log_usage  # 👈 【新增】：引入计费探针

MAX_IMAGE_SIZE = 2048
JPEG_QUALITY = 85

def encode_and_compress_image(image_path):
    """读取、智能压缩并转换为Base64 (原多模态横评底层逻辑)"""
    Image.MAX_IMAGE_PIXELS = None 
    with Image.open(image_path) as img:
        img = ImageOps.exif_transpose(img)
        if max(img.size) > MAX_IMAGE_SIZE:
            img.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE), Image.Resampling.LANCZOS)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        byte_io = io.BytesIO()
        img.save(byte_io, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        return base64.b64encode(byte_io.getvalue()).decode('utf-8')

def parse_image_to_md(image_path, custom_prompt=None) -> str:
    """调用 VLM 将图片解析为 Markdown (带 Token 计费统计)"""
    try:
        base64_image = encode_and_compress_image(image_path)
        
        # 支持传入自定义提示词，否则使用默认严谨解析提示词
        prompt = custom_prompt or "提取图片中的文字、表格、标题，使用标准 Markdown 格式输出。严格要求：不要废话，绝不要自行编造、添加或输出任何页码信息（如'第x页'），忽略图片边缘的页脚页眉数字。"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.API_KEY}"
        }
        payload = {
            "model": settings.MODEL_VISION, 
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            "temperature": 0.0 
        }
        response = requests.post(f"{settings.API_BASE}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        
        # 👇【新增计费拦截】：解析返回的 JSON 并抓取 usage
        result_json = response.json()
        content = result_json["choices"][0]["message"]["content"].strip()
        
        total_tokens = result_json.get("usage", {}).get("total_tokens", 0)
        if total_tokens == 0:
            # 兜底估算：输入提示词 + 图片预估token(约1000) + 输出文字
            total_tokens = int(len(prompt) + 1000 + len(content) * 1.2)
            
        # 记录入账本！归属应用写为“全局视觉解析中台”
        log_usage("全局视觉解析中台", settings.MODEL_VISION, total_tokens)
        # 👆【新增结束】
        
        return content
        
    except Exception as e:
        print(f"❌ 视觉解析失败 ({image_path}): {e}")
        return ""