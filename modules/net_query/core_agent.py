# core_agent.py
import os
import re
import yaml
import json
import duckdb
import csv
import requests  # 新增：用于发送纯 HTTP 请求到内网模型
from typing import List
from datetime import datetime
from langchain_openai import ChatOpenAI
from core.paths import get_db_path, get_config_path
from core.schemas import Text2SQLOutput

# 引入向量库相关组件（FAISS 在本地运行，不需要外网）
from langchain_community.vectorstores import FAISS        
from langchain_core.documents import Document     
from langchain_core.embeddings import Embeddings  
from core.token_tracker import log_usage
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import NET_QUERY_SYSTEM_PROMPT

# ==========================================
# 1. 核心配置与常量
# ==========================================

from dotenv import load_dotenv
load_dotenv()
INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "未配置API_BASE")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "未配置API_KEY")
INTERNAL_URL=os.getenv("INTERNAL_URL")
os.environ['NO_PROXY'] = INTERNAL_URL


# 【新增】：内网 Embedding 模型的配置
EMBEDDING_API_BASE = INTERNAL_API_BASE 
EMBEDDING_API_KEY = INTERNAL_API_KEY   
EMBEDDING_MODEL_NAME = "bge-m3"  

from core.paths import get_db_path, get_upload_path, get_config_path
DB_PATH = get_db_path("telecom_data.duckdb")
LOG_PATH = get_upload_path("query_logs.csv")

# ==========================================
# 2. 自定义内网 Embedding 调用类
# ==========================================
class IntranetEmbeddings(Embeddings):
    """自定义的 Embedding 类，纯 HTTP 请求，绝对不会触发本地下载和 tiktoken 校验"""
    def __init__(self, api_url: str, api_key: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        if not self.api_url.endswith("/embeddings"):
            self.api_url += "/embeddings" if self.api_url.endswith("/v1") else "/v1/embeddings"
        self.api_key = api_key
        self.model_name = model_name

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {"input": texts, "model": self.model_name}
        try:
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]
        except Exception as e:
            print(f"❌ 内网 Embedding API 调用失败: {e}")
            return [[0.0] * 1024 for _ in texts] 

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

# ==========================================
# 3. 通用安全与日志拦截器
# ==========================================
def sanitize_sql(sql):
    if re.search(r'(?i)\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE)\b', sql):
        raise ValueError("安全拦截：禁止执行此类破坏性 SQL！")
    if not re.search(r'(?i)\b(SUM|COUNT|AVG|MAX|MIN|GROUP BY)\b', sql) and not re.search(r'(?i)\bLIMIT\b', sql):
        sql = sql.strip().rstrip(';') + " LIMIT 1000"
    return sql

def log_query_action(question, sql, status, error_msg=""):
    try:
        file_exists = os.path.isfile(LOG_PATH)
        with open(LOG_PATH, mode='a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            if not file_exists: 
                writer.writerow(["时间", "用户问题", "执行SQL", "状态", "报错信息"])
            writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), question, sql, status, error_msg])
    except Exception as e:
        pass

# ==========================================
# 4. 核心 Agent 大脑
# ==========================================
class VisualTelecomAnalyst:
    def __init__(self):
        self.llm = ChatOpenAI(
            openai_api_key=INTERNAL_API_KEY,
            openai_api_base=INTERNAL_API_BASE,
            model_name="deepseek-v3-0324",
            temperature=0.0  
        )
        
        self.embeddings = IntranetEmbeddings(
            api_url=EMBEDDING_API_BASE,
            api_key=EMBEDDING_API_KEY,
            model_name=EMBEDDING_MODEL_NAME
        )
        
        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(f"找不到数据库 {DB_PATH}，请先运行 build_db.py！")
        self.con = duckdb.connect(DB_PATH, read_only=True)
        
        yaml_path = get_config_path("schema.yaml")
             
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
                self.golden_sqls = self.config.get("golden_sqls", [])
        except FileNotFoundError:
            print(f"❌ 严重警告：找不到任何 YAML 配置文件，AI 将失去参考记忆！")
            self.config = {}
            self.golden_sqls = []
        except Exception as e:
            print(f"❌ YAML 文件解析失败: {e}")
            self.config = {}
            self.golden_sqls = []

        self.vector_store = None
        if self.golden_sqls:
            faiss_dir = get_db_path("telecom_golden_sql_faiss")
            if os.path.exists(faiss_dir):
                self.vector_store = FAISS.load_local(faiss_dir, self.embeddings, allow_dangerous_deserialization=True)
            else:
                print("⏳ [无线问数] 首次启动：正在调用内网模型计算 SQL 向量库...")
                docs = [Document(page_content=item['question'], metadata={"sql": item['sql']}) for item in self.golden_sqls]
                self.vector_store = FAISS.from_documents(docs, self.embeddings)
                self.vector_store.save_local(faiss_dir)

    def get_real_schema(self):
        tables = self.con.execute("SHOW TABLES").df()['name'].tolist()
        context = ""
        for t in tables:
            cols = self.con.execute(f"DESCRIBE {t}").df()['column_name'].tolist()
            context += f"表名: {t} | 列名: {', '.join(cols)}\n"
        return context

    def retrieve_golden_sqls(self, user_query, top_k=2):
        if not self.vector_store: return "无历史参考案例。"
        similar_docs = self.vector_store.similarity_search(user_query, k=top_k)
        best_examples = ""
        for i, doc in enumerate(similar_docs):
            best_examples += f"[案例 {i+1}]\n问题: {doc.page_content}\nSQL: {doc.metadata['sql']}\n\n"
        return best_examples.strip()

    def get_latest_table(self, prefix="join_all_kpi_table_region"):
        try:
            tables = self.con.execute("SHOW TABLES").df()['name'].tolist()
            target_tables = [t for t in tables if t.startswith(prefix)]
            if not target_tables:
                return prefix + "202511" 
            latest_table = sorted(target_tables)[-1]
            return latest_table
        except Exception:
            return prefix + "202511"

    def run_workflow(self, user_query, history=[]):
        current_schema = self.get_real_schema()
        few_shot_examples = self.retrieve_golden_sqls(user_query)
        latest_kpi_table = self.get_latest_table()
        
        system_prompt = NET_QUERY_SYSTEM_PROMPT.format(
            current_schema=current_schema,
            few_shot_examples=few_shot_examples,
            latest_kpi_table=latest_kpi_table
        )

        # 👇 核心重构：绕过 API 限制，使用 LangChain 原生的 Pydantic 解析器！
        from langchain_core.output_parsers import PydanticOutputParser
        from core.schemas import Text2SQLOutput
        
        # 1. 初始化解析器
        parser = PydanticOutputParser(pydantic_object=Text2SQLOutput)
        
        # 2. 拿到 Pydantic 自动生成的极其严密的 JSON 格式说明
        format_instructions = parser.get_format_instructions()
        
        # 3. 把格式说明强行拼接到 System Prompt 的最后面，命令大模型遵守
        system_prompt += f"\n\n【极其重要：输出格式要求】\n{format_instructions}"

        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_query}]
        
        with get_openai_callback() as cb:
            # 4. 像以前一样，只请求普通的纯文本字符串，绝对不传 response_format 参数
            raw_result_str = self.llm.invoke(messages).content.strip()
            
            # 计费入库
            log_usage("无线网络问数", "deepseek-v3-0324", cb.total_tokens)
            
            try:
                # 5. 在本地用解析器将纯文本字符串转化为 Pydantic 对象！
                result_obj = parser.invoke(raw_result_str)
            except Exception as e:
                print(f"❌ 大模型未按 JSON 格式输出，解析失败: {e}\n原文: {raw_result_str}")
                # 终极兜底：如果大模型彻底发疯没输出 JSON，我们手动伪造一个对象返回，防止前端白屏
                result_obj = Text2SQLOutput(
                    thinking="解析失败，触发系统兜底保护机制。",
                    sql="SELECT * FROM join_all_kpi_table_region202511 LIMIT 10;", 
                    chart_type="none",
                    chart_title="数据解析失败",
                    comment="由于内网大模型未按照严格格式输出，触发安全兜底拦截。"
                )
                
        return result_obj