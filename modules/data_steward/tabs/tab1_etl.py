import os
import tempfile
import pandas as pd
import streamlit as st
import gc

from modules.data_steward.db_engine import (
    execute_write, execute_safe_query, clean_table_name,
    peek_file_headers, get_db_connection, db_lock, invalidate_schema_cache
)
from modules.data_steward.ai_engine import call_ai_architect
from modules.data_steward.utils import get_business_tables

def render_etl_tab():
    col_input, col_action = st.columns([1, 1], gap="large")
    data_sources = [] 
    
    with col_input:
        st.markdown("### 1. 接入数据源")
        st.caption("💡 小提示：您可以同时使用拖拽和本地路径，系统会自动将所有文件纳入处理队列。")
        
        uploaded_files = st.file_uploader("📁 网页拖拽上传 (CSV/Excel)", accept_multiple_files=True, type=["csv", "xlsx", "xls"], key="etl_file_uploader")
        
        st.markdown("##### ➕ 或")
        
        path_input = st.text_input("🔗 本地绝对路径直连 (输入文件夹或文件路径)", placeholder="例如：D:\\data\\2025订单汇总", key="etl_path_input")
        
        # 收集拖拽文件
        if uploaded_files:
            for uf in uploaded_files:
                tmp_path = os.path.join(tempfile.gettempdir(), uf.name)
                with open(tmp_path, "wb") as f: f.write(uf.getbuffer())
                data_sources.append(tmp_path)
            st.success(f"✅ 成功缓存 {len(uploaded_files)} 个拖拽文件。")
            
        # 收集本地路径文件
        folder_name = ""
        if path_input and os.path.exists(clean_path := path_input.strip(' \'"\n\r\t')):
            folder_name = clean_table_name(os.path.basename(clean_path))
            if os.path.isdir(clean_path):
                local_files = [os.path.join(r, f) for r, _, fs in os.walk(clean_path) for f in fs if f.lower().endswith(('.csv', '.xlsx', '.xls'))]
                data_sources.extend(local_files)
            else: 
                data_sources.append(clean_path)
            if data_sources:
                st.success(f"✅ 成功扫描本地路径！提取到 {len(data_sources) - len(uploaded_files)} 个表格文件。")

    with col_action:
        st.markdown("### 2. 智能配置与入库")
        if data_sources:
            # 状态固化：避免 Schema 分组因 UI 刷新而重复计算导致卡顿
            current_ds_hash = hash(tuple(data_sources))
            if st.session_state.get('ds_hash') != current_ds_hash:
                schema_map = {}
                for f in data_sources:
                    cols = peek_file_headers(f)
                    schema_map.setdefault(cols, []).append(f)
                st.session_state.schema_map_cache = schema_map
                st.session_state.ds_hash = current_ds_hash
            schema_map = st.session_state.schema_map_cache
            
            if st.button("🤖 AI 诊断合并策略", use_container_width=True, key="etl_ai_btn"):
                with st.spinner("架构师比对中..."):
                    summary = [f"分组 {i+1}:\n> 文件数: {len(files)} 个 (例如: {os.path.basename(files[0])})\n> 字段: `[{', '.join(str(c) for c in cols)}]`" for i, (cols, files) in enumerate(schema_map.items())]
                    st.info(call_ai_architect(f"检测到 {len(schema_map)} 种不同结构的文件：\n{chr(10).join(summary)}\n请给出业务入库与表名建议，一句话说明这几个组分别代表什么业务。", "入库诊断"))

            st.markdown("---")
            st.info(f"💡 **智能分组**：根据表头将 {len(data_sources)} 个文件划分为 **{len(schema_map)}** 个业务组。")
            
            group_configs = []
            for i, (cols, files) in enumerate(schema_map.items()):
                with st.container(border=True):
                    st.markdown(f"#### 📦 分组 {i+1} (包含 {len(files)} 个同构文件自动合并)")
                    
                    file_names = [os.path.basename(f) for f in files]
                    with st.expander("👀 展开查看包含的文件及共有字段", expanded=False):
                        st.caption(f"**自动合并的文件**：`{', '.join(file_names)}`")
                        st.caption(f"**共有字段(表结构)**：`{', '.join(str(c) for c in cols)}`")
                    
                    if folder_name and len(files) > 1:
                        default_tb_name = f"{folder_name}_{i+1}" if len(schema_map) > 1 else folder_name
                    else:
                        default_tb_name = clean_table_name(os.path.splitext(file_names[0])[0])
                        if len(files) > 1: default_tb_name += "_merged"
                        
                    col_act, col_tb = st.columns([1, 1.5])
                    with col_act:
                        action = st.radio(f"组 {i+1} 策略", ["✨ 建新表", "➕ 追加", "🔄 覆盖"], key=f"act_{i}", horizontal=True)
                    with col_tb:
                        if action == "✨ 建新表":
                            tb_name = st.text_input(f"指定表名 (组 {i+1})", value=default_tb_name, key=f"tb_{i}")
                        else:
                            all_tbs = get_business_tables()
                            tb_name = st.selectbox(f"指定目标表 (组 {i+1})", all_tbs if all_tbs else [default_tb_name], key=f"tb_sel_{i}")
                    
                    group_configs.append({"files": files, "action": action, "target_table": tb_name})

            if st.button("🚀 执行批量分组入库", type="primary", use_container_width=True, key="etl_exec_btn"):
                if any(not conf["target_table"] for conf in group_configs):
                    st.error("❌ 所有的分组都必须填写目标表名！")
                    return
                    
                with st.status(f"🔄 正在执行多线程分组写入底层...", expanded=True) as status:
                    total_rows = 0
                    for grp_idx, conf in enumerate(group_configs):
                        files = conf["files"]
                        action = conf["action"]
                        curr_table = conf["target_table"]
                        
                        st.write(f"--- 🚀 正在处理 **分组 {grp_idx+1}** -> 目标表：`{curr_table}` ---")
                        
                        
                        for idx, source in enumerate(files):
                            is_first_chunk = (idx == 0)
                            st.write(f"装载: `{os.path.basename(source)}`...")
                            
                            count_before = 0
                            try: count_before = execute_safe_query(f"SELECT COUNT(*) FROM {curr_table}").iloc[0,0]
                            except Exception: pass

                            try:
                                if source.lower().endswith('.csv'):
                                    try:
                                        # DuckDB 原生读取尝试
                                        if action == "✨ 建新表" and is_first_chunk: 
                                            execute_write(f"CREATE TABLE {curr_table} AS SELECT * FROM read_csv_auto('{source}')")
                                        elif action == "🔄 覆盖" and is_first_chunk:
                                            execute_write(f"DROP TABLE IF EXISTS {curr_table}")
                                            execute_write(f"CREATE TABLE {curr_table} AS SELECT * FROM read_csv_auto('{source}')")
                                        else: 
                                            execute_write(f"INSERT INTO {curr_table} SELECT * FROM read_csv_auto('{source}')")
                                    except Exception:
                                        # DuckDB 失败后，回退到 Pandas 读取并进行清洗
                                        try: 
                                            df_new = pd.read_csv(source, encoding='utf-8')
                                        except UnicodeDecodeError: 
                                            df_new = pd.read_csv(source, encoding='gbk')
                                        
                                        df_new.columns = [clean_table_name(str(c)) for c in df_new.columns]
                                        
                                        # 💡 脏数据清洗逻辑
                                        # 尝试找出被污染的数字列，把类似 '5.5,5.5' 的奇葩数据强制转为空值(NaN)
                                        for col in df_new.columns:
                                            if df_new[col].dtype == 'object':
                                                test_numeric = pd.to_numeric(df_new[col], errors='coerce')
                                                if test_numeric.notna().sum() > (len(df_new) * 0.5): 
                                                    df_new[col] = test_numeric

                                        # 通过 Pandas 写入数据库
                                        conn = get_db_connection()
                                        with db_lock:
                                            conn.register('tmp_df', df_new)
                                            if action == "✨ 建新表" and is_first_chunk: 
                                                conn.execute(f"CREATE TABLE {curr_table} AS SELECT * FROM tmp_df")
                                            elif action == "🔄 覆盖" and is_first_chunk:
                                                conn.execute(f"DROP TABLE IF EXISTS {curr_table}")
                                                conn.execute(f"CREATE TABLE {curr_table} AS SELECT * FROM tmp_df")
                                            else: 
                                                conn.execute(f"INSERT INTO {curr_table} SELECT * FROM tmp_df")
                                            conn.unregister('tmp_df')
                                        del df_new
                                        gc.collect()
                                else:
                                    try: df_new = pd.read_excel(source, engine="calamine")
                                    except: df_new = pd.read_excel(source)
                                    df_new.columns = [clean_table_name(str(c)) for c in df_new.columns]
                                    
                                    conn = get_db_connection()
                                    with db_lock:
                                        conn.register('tmp_df', df_new)
                                        if action == "✨ 建新表" and is_first_chunk: conn.execute(f"CREATE TABLE {curr_table} AS SELECT * FROM tmp_df")
                                        elif action == "🔄 覆盖" and is_first_chunk:
                                            conn.execute(f"DROP TABLE IF EXISTS {curr_table}")
                                            conn.execute(f"CREATE TABLE {curr_table} AS SELECT * FROM tmp_df")
                                        else: conn.execute(f"INSERT INTO {curr_table} SELECT * FROM tmp_df")
                                        conn.unregister('tmp_df')
                                    del df_new
                                    gc.collect()
                            except Exception as e: 
                                st.error(f"❌ 失败: {e}")

                            count_after = 0
                            try: count_after = execute_safe_query(f"SELECT COUNT(*) FROM {curr_table}").iloc[0,0]
                            except Exception: pass
                            total_rows += max(0, count_after - count_before)
                            
                    invalidate_schema_cache()  # ★ 入库完成后清缓存，下拉框立即反映新表
                    status.update(label=f"✅ 批量入库完美收官！本次共装载数据 {total_rows} 行。", state="complete")
                    st.success("全部操作成功，请前往资产大盘查看生成的表。")