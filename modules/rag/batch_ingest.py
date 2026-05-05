# modules/rag/batch_ingest.py
import os
import shutil
import json
import pickle
from langchain_text_splitters import MarkdownTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever

# 【核心优化】：引入全局配置
from core.settings import settings
from modules.rag.file_processor import get_file_md5, check_duplicate, mark_as_processed, parse_file_to_md
from modules.rag.config import Config

def batch_ingest_folder(folder_path: str):
    all_docs = []
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if os.path.isfile(file_path):
            if check_duplicate(file_path): continue
            
            file_docs = parse_file_to_md(file_path)
            if file_docs: 
                all_docs.extend(file_docs)
                mark_as_processed(file_path) 

    if not all_docs: return

    text_splitter = MarkdownTextSplitter(chunk_size=Config.CHUNK_SIZE, chunk_overlap=Config.CHUNK_OVERLAP)
    chunks = text_splitter.split_documents(all_docs)
    
    if not os.path.exists(Config.DB_DIR): os.makedirs(Config.DB_DIR)

    bm25_retriever = BM25Retriever.from_documents(chunks)
    bm25_retriever.k = Config.RETRIEVER_TOP_K
    with open(os.path.join(Config.DB_DIR, "bm25_index.pkl"), "wb") as f:
        pickle.dump(bm25_retriever, f)

    # 【核心优化】：使用统一 settings
    embeddings = OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL, 
        api_key=settings.API_KEY, 
        base_url=settings.API_BASE, 
        check_embedding_ctx_length=False
    )
    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(Config.DB_DIR)

def ingest_single_file(file_path, force_overwrite=False):
    if not force_overwrite and check_duplicate(file_path):
        return "EXISTS"
    new_docs = parse_file_to_md(file_path)
    if not new_docs:
        return "FAILED"
    mark_as_processed(file_path)
    rebuild_index_from_md()      
    return "SUCCESS"

# ==========================================
# 🌟 核心修复：更强大的删除机制 (保留原版逻辑)
# ==========================================
def delete_single_file(file_identifier):
    records = {}
    if os.path.exists(Config.PROCESSED_RECORD_FILE):
        with open(Config.PROCESSED_RECORD_FILE, "r", encoding="utf-8") as f:
            records = json.load(f)

    target_md5 = None
    file_path = None

    if file_identifier in records:
        target_md5 = file_identifier
        file_path = records[file_identifier]
    else:
        for k, v in records.items():
            base_name = os.path.splitext(os.path.basename(v))[0]
            if base_name == file_identifier or v == file_identifier:
                target_md5 = k
                file_path = v
                break

    if target_md5:
        del records[target_md5]
        with open(Config.PROCESSED_RECORD_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    if file_path:
        base_name_to_del = os.path.splitext(os.path.basename(file_path))[0]
    else:
        base_name_to_del = file_identifier

    md_path = os.path.join(Config.DEBUG_MD_DIR, f"{base_name_to_del}.md")
    bak_path = os.path.join(Config.DEBUG_MD_DIR, f"{base_name_to_del}.md.bak")

    if os.path.exists(md_path):
        if os.path.exists(bak_path):
            os.remove(bak_path) 
        os.rename(md_path, bak_path)

    rebuild_index_from_md()
    return True

def rebuild_index_from_md():
    from langchain_community.document_loaders import TextLoader
    
    md_dir = Config.DEBUG_MD_DIR 
    if not os.path.exists(md_dir): return
    
    all_docs = []
    for filename in os.listdir(md_dir):
        if filename.endswith(".md"):
            md_path = os.path.join(md_dir, filename)
            loader = TextLoader(md_path, encoding="utf-8")
            docs = loader.load()
            for doc in docs:
                doc.metadata["source"] = filename.replace(".md", "")
            all_docs.extend(docs)
            
    if not all_docs:
        if os.path.exists(Config.DB_DIR):
            shutil.rmtree(Config.DB_DIR)
        return

    text_splitter = MarkdownTextSplitter(chunk_size=Config.CHUNK_SIZE, chunk_overlap=Config.CHUNK_OVERLAP)
    chunks = text_splitter.split_documents(all_docs)

    for chunk in chunks:
        source_name = chunk.metadata.get("source", "未知文档")
        chunk.page_content = f"【此片段摘自文档：{source_name}】\n" + chunk.page_content

    if os.path.exists(Config.DB_DIR):
        shutil.rmtree(Config.DB_DIR) 
    os.makedirs(Config.DB_DIR)
    
    bm25_retriever = BM25Retriever.from_documents(chunks)
    bm25_retriever.k = Config.RETRIEVER_TOP_K
    with open(os.path.join(Config.DB_DIR, "bm25_index.pkl"), "wb") as f:
        pickle.dump(bm25_retriever, f)
        
    # 【核心优化】：使用统一 settings
    embeddings = OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.API_KEY,
        base_url=settings.API_BASE,
        check_embedding_ctx_length=False 
    )
    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(Config.DB_DIR)