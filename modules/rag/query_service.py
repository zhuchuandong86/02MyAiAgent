# modules/rag/query_service.py
import os
import pickle
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_classic.retrievers import EnsembleRetriever

# 【核心优化】：全面接入核心引擎
from core.settings import settings
from core.llm_factory import get_llm
from core.prompts import RAG_SYSTEM_PROMPT
from modules.rag.config import Config 
from modules.rag.reranker import build_rerank_retriever 

def format_docs(docs):
    formatted_texts = []
    for i, doc in enumerate(docs):
        page = doc.metadata.get('page', '1')
        source = os.path.basename(doc.metadata.get('source', '未知'))
        formatted_texts.append(f"[{i+1}] 【来源: {source} | 第{page}页】\n{doc.page_content}")
    return "\n\n".join(formatted_texts)
    
def build_query_chain():
    if not os.path.exists(Config.DB_DIR):
        raise FileNotFoundError(f"找不到数据库 {Config.DB_DIR}，请先运行 batch_ingest.py 入库！")
        
    with open(os.path.join(Config.DB_DIR, "bm25_index.pkl"), "rb") as f:
        bm25_retriever = pickle.load(f)
        bm25_retriever.k = Config.RETRIEVER_TOP_K   
        
    # 【核心优化】：改用 settings 配置向量模型
    embeddings = OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.API_KEY,
        base_url=settings.API_BASE,
        check_embedding_ctx_length=False 
    )
    vectorstore = FAISS.load_local(Config.DB_DIR, embeddings, allow_dangerous_deserialization=True)
    faiss_retriever = vectorstore.as_retriever(search_kwargs={"k": Config.RETRIEVER_TOP_K})
    
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, faiss_retriever],
        weights=[0.5, 0.5]
    )
    
    final_retriever = build_rerank_retriever(ensemble_retriever)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", RAG_SYSTEM_PROMPT),
        ("user", "{question}")
    ])
    
    # 【核心优化】：使用兵工厂返回 LangChain 对象
    llm = get_llm(model_name=settings.MODEL_TEXT, temperature=0.1, streaming=False)
    
    rag_chain = (
        {"context": final_retriever | format_docs, "question": RunnablePassthrough()}
        | prompt          
        | llm              
        | StrOutputParser() 
    )
    
    return rag_chain, final_retriever