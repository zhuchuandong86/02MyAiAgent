# modules/rag/config.py
import os
import core.paths

class Config:
    # ==========================================
    # 【核心升级】：底层资产路径与全平台打通！
    # ==========================================
    # 向量库放在全局数据库目录下
    DB_DIR = os.path.join(core.paths.GLOBAL_DATA_DIR, "databases", "rag_faiss_bm25")
    PROCESSED_RECORD_FILE = os.path.join(core.paths.GLOBAL_DATA_DIR, "databases", "rag_records.json")
    
    # 🌟 神级复用：直接将 MD 缓存目录指向全局的 md_cache，实现多应用资产互通！
    DEBUG_MD_DIR = os.path.join(core.paths.GLOBAL_DATA_DIR, "md_cache") 

    # RAG 专属超参数
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 100
    RETRIEVER_TOP_K = 15
    RERANK_TOP_K = 5