# modules/multi_compare/template_service.py
import os
import streamlit as st
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
import core.paths
from core.settings import settings

OUTPUT_DIR = str(core.paths.GLOBAL_DATA_DIR)
TEMPLATE_MD_DIR = os.path.join(OUTPUT_DIR, "templates_md")
TEMPLATE_DB_DIR = os.path.join(OUTPUT_DIR, "template_faiss")
os.makedirs(TEMPLATE_MD_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DB_DIR, exist_ok=True)

def get_embeddings():
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL, 
        api_key=settings.API_KEY,
        base_url=settings.API_BASE,
        check_embedding_ctx_length=False
    )

def get_available_templates():
    return [f for f in os.listdir(TEMPLATE_MD_DIR) if f.endswith('.md')]

@st.cache_data(show_spinner=False, ttl=86400)
def compress_template(template_name, content):
    """利用缓存提取排版骨架，将 3000 字压缩为 400 字"""
    llm = ChatOpenAI(model=settings.MODEL_TEXT or "deepseek-v3-0324", api_key=settings.API_KEY, base_url=settings.API_BASE, temperature=0.1)
    prompt = f"""你是一个高级研报骨架提取器。任务：分析这篇优秀范例【{template_name}】，提取它的：
1. 大纲层级与排版逻辑（保留它优秀的二级/三级标题名称格式）。
2. 行文风格、专业语气、高频使用的行业黑话。
警告：彻底丢弃具体公司名称、财务数值。将提取出的“纯粹方法论”压缩在 400 字以内！
=== 原文片段 ===
{content[:4000]}"""
    try: return llm.invoke(prompt).content
    except Exception: return content[:800] 

def get_style_templates(query_text, selected_strategy, status_ui):
    templates_to_inject = []
    ai_thinking_log = None
    try:
        if selected_strategy.startswith("🤖"):
            embeddings = get_embeddings()
            db_path = os.path.join(TEMPLATE_DB_DIR, "index.faiss")
            if os.path.exists(db_path):
                vectorstore = FAISS.load_local(TEMPLATE_DB_DIR, embeddings, allow_dangerous_deserialization=True)
                status_ui.write("🔍 1. 底层 FAISS 引擎进行第一轮向量海选...")
                matched_docs = vectorstore.similarity_search(query_text[:1000], k=4)
                candidate_filenames = list(set([d.metadata.get("source") for d in matched_docs]))
                
                if candidate_filenames:
                    status_ui.write("🧠 2. 大模型主编正在评估候选模板并做出决断...")
                    llm_router = ChatOpenAI(model=settings.MODEL_TEXT or "deepseek-v3-0324", api_key=settings.API_KEY, base_url=settings.API_BASE, temperature=0.7)
                    
                    router_prompt = (
                        "你是一个眼光毒辣、极具【跨界思维】的顶级投行主编。有一份新文档需要解读，前500字如下：\n"
                        f"<new_doc>\n{query_text[:500]}\n</new_doc>\n\n"
                        f"系统基于向量检索初步捞出了以下候选池：{candidate_filenames}\n\n"
                        "请综合跨界思维，自主挑选最适合作为排版和行文参考的 2 到 3 个范例（必须参考多个，集百家之长）。\n"
                        "请严格按照以下格式输出：\n"
                        "【主编思考】：(一句话简述理由)\n"
                        "【最终选择】：(仅填入选中文件名，逗号分隔)"
                    )
                    
                    router_res = llm_router.invoke(router_prompt).content
                    ai_thinking_log = router_res 
                    
                    final_selected = [f for f in candidate_filenames if f in router_res]
                    if not final_selected: final_selected = candidate_filenames[:2] 
                    
                    for fname in final_selected:
                        file_path = os.path.join(TEMPLATE_MD_DIR, fname)
                        if os.path.exists(file_path):
                            with open(file_path, "r", encoding="utf-8") as f:
                                compressed_bone = compress_template(fname, f.read())
                                templates_to_inject.append(f"【参考范例骨架：{fname}】\n{compressed_bone}")
                    status_ui.write(f"🎉 成功锁定最佳范例并完成方法论提取！")
                else: status_ui.write("ℹ️ 当前经验库为空，使用默认逻辑。")
            else: status_ui.write("ℹ️ 当前经验库未建立，使用默认逻辑。")
        else:
            file_path = os.path.join(TEMPLATE_MD_DIR, selected_strategy)
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    compressed_bone = compress_template(selected_strategy, f.read())
                    templates_to_inject.append(f"【指定范例骨架：{selected_strategy}】\n{compressed_bone}")
                status_ui.write(f"🎯 已精准锁定并提取风格模板：`{selected_strategy}`")
    except Exception as e: status_ui.write(f"⚠️ 经验库检索跳过: {e}")
        
    templates_str = "\n\n".join(templates_to_inject) if templates_to_inject else ""
    return templates_str, ai_thinking_log