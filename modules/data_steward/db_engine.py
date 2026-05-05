import duckdb
import threading
import os
import re
import pandas as pd
import streamlit as st

DB_DIR = os.path.join("global_data", "data_warehouse")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "company_data.db")

# 🔴 P0 级并发防御：全局读写锁，防止多页面多线程操作将 DuckDB 锁死
db_lock = threading.Lock()

@st.cache_resource
def get_db_connection():
    return duckdb.connect(database=DB_PATH, read_only=False)

def execute_write(sql):
    """用于入库、建表等写操作，严格加锁"""
    conn = get_db_connection()
    with db_lock:
        conn.execute(sql)

def execute_safe_query(sql):
    """用于 AI 或用户的查询操作，包含 P0 级高危 SQL 注入拦截"""
    forbidden_keywords = r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE)\b'
    if re.search(forbidden_keywords, sql, re.IGNORECASE):
        raise ValueError("🚨 安全拦截触发：检测到修改数据库的高危指令，已自动阻断！")
    
    conn = get_db_connection()
    with db_lock:
        return conn.execute(sql).df()

@st.cache_data(ttl=30, show_spinner=False)  # 30秒缓存，足够新鲜
def get_all_tables():
    conn = get_db_connection()
    with db_lock:
        return [row[0] for row in conn.execute("SHOW TABLES").fetchall()]

# # 新增：专门给大盘用的，缓存 COUNT 结果
# @st.cache_data(ttl=30, show_spinner=False)
# def get_table_count(table_name: str):
#     conn = get_db_connection()
#     with db_lock:
#         return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

@st.cache_data(ttl=30, show_spinner=False)
def get_table_count(table_name: str) -> int:
    """获取表行数，30秒缓存。替代每次直接 SELECT COUNT(*) 查询，消灭大盘重绘白屏。"""
    conn = get_db_connection()
    with db_lock:
        return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]


@st.cache_data(ttl=60, show_spinner=False)
def get_table_schema(table_name: str):
    """获取表结构，60秒缓存（Schema 变化慢于数据）。"""
    conn = get_db_connection()
    with db_lock:
        return conn.execute(f"DESCRIBE {table_name}").df()


def invalidate_schema_cache():
    """
    【必须在所有建表/删表/入库操作完成后调用】
    主动清除 get_all_tables / get_table_count / get_table_schema 三个缓存。
    如不调用，UI 在 TTL 过期前将持续读到过期的表列表和结构，
    导致入库后下拉框看不到新表，删表后旧表还在选项里。
    """
    get_all_tables.clear()
    get_table_count.clear()
    get_table_schema.clear()

def clean_table_name(name):
    return re.sub(r'\W|^(?=\d)', '_', name)

def peek_file_headers(file_path):
    try:
        if file_path.lower().endswith('.csv'): 
            try:
                # 优先尝试 utf-8
                df = pd.read_csv(file_path, nrows=0, encoding='utf-8') 
            except UnicodeDecodeError:
                # 如果报错，回退到国内环境常见的 gbk 编码
                df = pd.read_csv(file_path, nrows=0, encoding='gbk')
        else: 
            df = pd.read_excel(file_path, nrows=0)
        return tuple(df.columns.tolist())
    except: 
        return ("无法读取表头_可能已损坏",)