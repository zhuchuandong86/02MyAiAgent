import os
import json
import hashlib
from modules.rag.config import Config
# 👇 从核心中台导入
from core.parsers.document_engine import smart_parse_document

def get_file_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def check_duplicate(file_path):
    file_md5 = get_file_md5(file_path)
    if not os.path.exists(Config.PROCESSED_RECORD_FILE): return False
    with open(Config.PROCESSED_RECORD_FILE, "r", encoding="utf-8") as f:
        records = json.load(f)
    return file_md5 in records

def mark_as_processed(file_path):
    file_md5 = get_file_md5(file_path)
    records = {}
    if os.path.exists(Config.PROCESSED_RECORD_FILE):
        with open(Config.PROCESSED_RECORD_FILE, "r", encoding="utf-8") as f:
            records = json.load(f)
    records[file_md5] = file_path
    with open(Config.PROCESSED_RECORD_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def parse_file_to_md(file_path):
    """RAG 流水线：调用中台解析 -> 拼接 MD -> 保存至缓存"""
    docs = smart_parse_document(file_path)
    if not docs: return []
    
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    full_md_content = f"# 文档标题：{base_name}\n\n"
    
    for doc in docs:
        full_md_content += f"## 第 {doc.metadata.get('page', 1)} 页\n{doc.page_content}\n\n"
        
    os.makedirs(Config.DEBUG_MD_DIR, exist_ok=True)
    with open(os.path.join(Config.DEBUG_MD_DIR, f"{base_name}.md"), "w", encoding="utf-8") as f:
        f.write(full_md_content)
        
    return docs