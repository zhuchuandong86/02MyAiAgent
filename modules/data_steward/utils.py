import os
import streamlit as st
from modules.data_steward.db_engine import get_all_tables, get_db_connection

# ==========================================
# 工具函数：过滤 AI 中间临时表 (保护业务大盘)
# ==========================================
def get_business_tables():
    return [t for t in get_all_tables() if not t.startswith('ai_step_')]

# ==========================================
# 极速 CSV 转换引擎 (绕过不可哈希的数据，使用 SQL 作为唯一缓存键)
# ==========================================
@st.cache_data(show_spinner=False, max_entries=10)
def fast_df_to_csv(_df, query_key):
    return _df.to_csv(index=False).encode('utf-8-sig')

# ==========================================
# 极速原生全量 CSV 导出引擎 (绕过 Pandas 内存杀手，直接从底层 DuckDB 写盘)
# ==========================================
@st.cache_data(show_spinner=False, max_entries=5)
def fast_table_to_csv_bytes(table_name, query_key):
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".csv")
    os.close(tmp_fd)
    try:
        conn = get_db_connection()
        # 调用 DuckDB 原生 COPY 命令，直接将几十万行数据流式写入硬盘，0 内存消耗！
        conn.execute(f"COPY (SELECT * FROM \"{table_name}\") TO '{tmp_path}' (HEADER)")
        with open(tmp_path, "rb") as f:
            return b'\xef\xbb\xbf' + f.read() # 加上 BOM 防止 Excel 乱码
    except Exception as e:
        return str(e).encode('utf-8')
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except: pass