import requests
import time
import json
from core.settings import settings       
from core.token_tracker import log_usage 

RETRY_TIMES = 3
RETRY_DELAY = 2

def call_api(messages, model_name, stream=False, silent_stream=False):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.API_KEY}"
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.1,
        "stream": stream
    }
    
    if stream:
        payload["stream_options"] = {"include_usage": True}

    request_url = settings.API_BASE
    if not request_url.endswith("/chat/completions"):
        request_url = request_url.rstrip("/") + "/chat/completions"

    current_timeout = 600 if "deepseek" in model_name.lower() or "72b" in model_name.lower() or "30b" in model_name.lower() else 120
    
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            response = requests.post(request_url, headers=headers, json=payload, stream=stream, timeout=current_timeout)
            
            if stream and response.status_code == 200:
                full_content = ""
                total_tokens = 0
                if not silent_stream: print("\n" + "="*50)
                    
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8')
                        if decoded_line.startswith('data: '):
                            data_str = decoded_line[6:]
                            if data_str.strip() == '[DONE]': break
                            try:
                                data_json = json.loads(data_str)
                                if "usage" in data_json and data_json["usage"]:
                                    total_tokens = data_json["usage"].get("total_tokens", 0)
                                    
                                chunk = data_json.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                if chunk:
                                    if not silent_stream: print(chunk, end='', flush=True) 
                                    full_content += chunk
                            except json.JSONDecodeError:
                                continue
                                
                if not silent_stream: print("\n" + "="*50 + "\n")
                
                if total_tokens == 0:
                    total_tokens = int((len(str(messages)) + len(full_content)) * 1.2)
                log_usage("多模态总结与横评", model_name, total_tokens) 
                
                return full_content
                
            elif not stream and response.status_code == 200:
                res_json = response.json()
                total_tokens = res_json.get("usage", {}).get("total_tokens", 0)
                if total_tokens == 0:
                    total_tokens = int((len(str(messages)) + len(str(res_json))) * 1.2)
                log_usage("多模态总结与横评", model_name, total_tokens)
                return res_json["choices"][0]["message"]["content"]
            
            if response.status_code == 429 or response.status_code >= 500:
                current_delay = RETRY_DELAY * attempt * 3 
                print(f"⚠️ 网关限流或超时 ({response.status_code})。后端压力过大，等待 {current_delay} 秒后重试 (第 {attempt} 次)...")
                time.sleep(current_delay)
                continue
                
            print(f"❌ 服务器明确拒绝请求！状态码: {response.status_code}\n详情: {response.text}")
            break
            
        except requests.exceptions.Timeout:
            current_delay = RETRY_DELAY * attempt * 3
            print(f"⏳ 请求网关物理超时 504！等待 {current_delay} 秒后尝试重连...")
            time.sleep(current_delay)
        except requests.exceptions.ConnectionError as e:
            # 🌟 核心拦截 10054 ConnectionResetError
            current_delay = RETRY_DELAY * attempt * 3
            print(f"📡 TCP 连接被远端网关粗暴切断 (ConnectionError)! 等待 {current_delay} 秒后发起重连机制...")
            time.sleep(current_delay)
        except Exception as e:
            current_delay = RETRY_DELAY * attempt * 3
            print(f"📡 发生未预期网络异常: {e}。等待 {current_delay} 秒后重试...")
            time.sleep(current_delay)
            
    return "--- ⚠️ 本次提取彻底失败 ---"