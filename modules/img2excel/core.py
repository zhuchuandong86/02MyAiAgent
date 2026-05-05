# modules/img2excel/core.py
import base64
import pandas as pd
from openai import OpenAI
import concurrent.futures
import time
import re
from PIL import Image
import io
from core.token_tracker import log_usage

from core.prompts import IMG2EXCEL_EXTRACT_PROMPT, IMG2EXCEL_REVIEWER_PROMPT

def _call_vision_model(client: OpenAI, image_base64: str, model_name: str, prompt_text: str, max_retries: int = 3) -> str:
    last_exception = None
    
    # 👇 核心改进：智能判断，如果是 deepseek-ocr，强行替换为官方专属魔法指令！
    is_deepseek_ocr = "deepseek-ocr" in model_name.lower()
    if is_deepseek_ocr:
        # 去掉触发坐标框的底层控制符，直接用最简明扼要的英文指令
        prompt_text = "Extract the table from the image and output in Markdown format."
        print(f"💡 [智能拦截] 检测到 {model_name}，已切换为专属极简指令！")
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }],
                temperature=0.1, 
                max_tokens=4096
            )
            content = response.choices[0].message.content
            
            # 👇 核心兜底：DeepSeek-OCR 极大概率不会乖乖写 <table_output> 标签，我们帮它套上！
            if is_deepseek_ocr and "<table_output>" not in content:
                content = f"<table_output>\n{content}\n</table_output>"
            
            if hasattr(response, 'usage') and response.usage:
                tokens = response.usage.total_tokens
            else:
                tokens = int(len(content) * 1.2 + 1000)
                
            log_usage("图片转Excel", model_name, tokens)
            return content
        except Exception as e:
            last_exception = e
            print(f"[警告] 模型 {model_name} 第 {attempt + 1} 次调用失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                
    raise Exception(f"模型 {model_name} 连续 {max_retries} 次请求失败: {last_exception}")

def parse_markdown_to_df(md_text: str) -> pd.DataFrame:
    print("\n" + "="*50)
    print("🔍 [DEBUG] 开始解析大模型返回的 Markdown")
    
    if not md_text:
        raise Exception("模型返回结果为空")
        
    match = re.search(r'<table_output>(.*?)</table_output>', md_text, re.DOTALL)
    if match:
        md_text = match.group(1).strip()
        print("✅ 成功提取到 <table_output> 标签内的表格内容。")
    else:
        print("⚠️ 未找到 <table_output> 标签，将尝试直接解析全文本。")
        
    lines = [line.strip() for line in md_text.strip().split('\n')]
    table_lines = [line for line in lines if '|' in line]
    
    data_lines = []
    for line in table_lines:
        cleaned = line.replace('|', '').replace('-', '').replace(':', '').strip()
        if cleaned: 
            data_lines.append(line)
            
    if not data_lines:
        raise Exception("提取到了表格边框，但没有实质内容数据。")
        
    table_data = []
    for line in data_lines:
        if line.startswith('|'): line = line[1:]
        if line.endswith('|'): line = line[:-1]
        row = [cell.strip() for cell in line.split('|')]
        table_data.append(row)
        
    if len(table_data) <= 1:
        return pd.DataFrame([table_data[0]] if table_data else [])
        
    max_cols = max(len(row) for row in table_data) 
    header = table_data[0]
    
    if len(header) < max_cols:
        header.extend([f"未命名列_{i}" for i in range(len(header), max_cols)])
    elif len(header) > max_cols:
        header = header[:max_cols]
        
    normalized_data = []
    for row in table_data[1:]:
        if len(row) < max_cols:
            row.extend([''] * (max_cols - len(row)))
        elif len(row) > max_cols:
            row = row[:max_cols]
        normalized_data.append(row)
        
    print("✅ [解析成功]: DataFrame 构建完成！\n" + "="*50)
    return pd.DataFrame(normalized_data, columns=header)

def process_image_to_df(image_bytes: bytes, api_key: str, api_base: str, extract_models: list, reviewer_model: str = None) -> tuple:
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.thumbnail((2560, 2560)) 
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=95) 
    compressed_bytes = buffer.getvalue()
    
    base64_img = base64.b64encode(compressed_bytes).decode('utf-8')
    client = OpenAI(api_key=api_key, base_url=api_base)
    
    debug_info = {
        "extractors": {}, 
        "reviewer": None  
    }
    
    if len(extract_models) == 1 and not reviewer_model:
        md_text = _call_vision_model(client, base64_img, extract_models[0], IMG2EXCEL_EXTRACT_PROMPT)
        debug_info["extractors"][extract_models[0]] = md_text
    else:
        results = []
        successful_models = []
        last_success_res = ""
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_model = {
                executor.submit(_call_vision_model, client, base64_img, model, IMG2EXCEL_EXTRACT_PROMPT): model 
                for model in extract_models
            }
            for future in concurrent.futures.as_completed(future_to_model):
                model_name = future_to_model[future]
                try:
                    res = future.result()
                    results.append(f"### 提取结果 (来自模型 {model_name}) ###\n{res}\n")
                    successful_models.append(model_name)
                    last_success_res = res  
                    debug_info["extractors"][model_name] = res
                except Exception as e:
                    print(f"[错误] 模型 {model_name} 彻底提取失败已被跳过: {e}")
                    debug_info["extractors"][model_name] = f"❌ 提取失败: {e}"
        
        if len(successful_models) == 0:
            raise Exception("所有前置提取模型均由于网络或服务原因调用失败。")
        elif len(successful_models) == 1:
            warning_msg = f"\n\n> ⚠️ **系统提示**：原定多模型并发校验，但目前仅有 `{successful_models[0]}` 模型成功返回数据。已自动为您降级输出该单模型结果。"
            md_text = last_success_res + warning_msg
        else:
            combined_text = "\n".join(results)
            final_prompt = IMG2EXCEL_REVIEWER_PROMPT.format(extracted_results=combined_text)
            final_model = reviewer_model if reviewer_model else successful_models[0]
            md_text = _call_vision_model(client, base64_img, final_model, final_prompt)
            debug_info["reviewer"] = {"model": final_model, "result": md_text}

    df = parse_markdown_to_df(md_text)
    
    return df, md_text, debug_info