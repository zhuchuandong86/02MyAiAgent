import streamlit as st
from modules.data_steward.db_engine import (
    execute_write, execute_safe_query, get_table_schema, 
    get_db_connection, db_lock, invalidate_schema_cache
)
from modules.data_steward.ai_engine import call_ai_sql_coder, extract_sql
from modules.data_steward.utils import get_business_tables

def render_spatial_tab():
    st.markdown("### 🗺️ 空间地理与网格规划 (GIS引擎)")
    tables = get_business_tables()
    if len(tables) < 2:
        st.warning("⚠️ 仓库中至少需要 2 张表才能进行空间计算。")
        return

    if "gis_chat_history" not in st.session_state: st.session_state.gis_chat_history = []
    if "gis_pending_sql" not in st.session_state: st.session_state.gis_pending_sql = ""
    md_ticks = "`" * 3

    st.info("💡  LBS (基于位置服务) ：通过基站/用户的【经纬度】，去匹配微网格/行政区的【空间多边形】，实现地理归属。")

    with st.container(border=True):
        col_points, col_polygons = st.columns(2)
        
        with col_points:
            st.markdown("##### 📍 1. 坐标点表 (如基站/用户)")
            pt_tbl = st.selectbox("👉 选择坐标表：", tables, key="gis_pt_tbl")
            pt_cols = get_table_schema(pt_tbl)['column_name'].tolist()
            
            col_lon, col_lat = st.columns(2)
            with col_lon:
                lon_col = st.selectbox("🌐 经度字段 (Longitude)：", pt_cols, key="gis_lon_col")
            with col_lat:
                lat_col = st.selectbox("🌐 纬度字段 (Latitude)：", pt_cols, key="gis_lat_col")

        with col_polygons:
            st.markdown("##### 🔲 2. 多边形表 (如微网格/边界)")
            poly_idx = 1 if len(tables) > 1 and tables[1] != pt_tbl else 0
            poly_tbl = st.selectbox("👉 选择边界表：", tables, index=poly_idx, key="gis_poly_tbl")
            poly_cols = get_table_schema(poly_tbl)['column_name'].tolist()
            
            geom_col = st.selectbox("📐 多边形边界字段 (WKT/MULTIPOLYGON)：", poly_cols, key="gis_geom_col")
            
            available_ret_cols = [c for c in poly_cols if c != geom_col]
            return_cols = st.multiselect("📦 归属成功后，要提取的字段 (如：网格名称)：", available_ret_cols, key="gis_ret_cols")

    st.markdown("---")
    st.markdown("#### 💬 第一步：逻辑推演与即时质检")
    
    # 🔴 渲染聊天记录：新增折叠框展示思考与纠错过程
    for msg in st.session_state.gis_chat_history:
        m_role = msg.get("role", "")
        with st.chat_message(m_role):
            if m_role == "user":
                st.markdown(msg.get("content", ""))
            else:
                # AI 回复：主标题
                st.markdown(msg.get("content", ""))
                
                # 思考与纠错折叠面板
                if msg.get("explain_log"):
                    with st.expander("⚙️ AI 思考与底层纠错过程 (点击展开)", expanded=False):
                        st.markdown(msg["explain_log"])
                
                # SQL 代码展示
                if msg.get("sql"):
                    st.code(msg["sql"], language="sql")
                
                # 预览与质检展示
                if msg.get("preview_df") is not None:
                    st.markdown("⭐ **空间测算样本预览**：")
                    st.dataframe(msg["preview_df"], hide_index=True)
                    if msg.get("qc"):
                        qc = msg["qc"]
                        col_q1, col_q2, col_q3 = st.columns(3)
                        col_q1.metric("坐标底表行数", f"{qc['base_cnt']:,}")
                        col_q2.metric("模拟匹配后行数", f"{qc['res_cnt']:,}")
                        diff = qc['res_cnt'] - qc['base_cnt']
                        if diff > 0:
                            col_q3.metric("⚠️ 膨胀预警", f"+{diff:,}", delta_color="inverse")
                            st.error("🚨 **警告：存在空间重叠！** 说明有的点落在了重叠网格里。请指示 AI 去重（保留一条）。")
                        elif diff < 0:
                            col_q3.metric("💡 未匹配丢失", f"{diff:,}", delta_color="inverse")
                        else:
                            col_q3.metric("✅ 匹配完美", "0 差异", delta_color="normal")

    user_instr = st.text_area(
        "🗣️ 输入附加指令 (可选)：", 
        placeholder="例如：请先用 ST_Simplify(边界字段, 0.001) 简化多边形；如果匹配到多个微网格，请随便保留一个去重...", 
        height=80, key="gis_user_input"
    )

    col_btn_run, col_btn_clr = st.columns([3, 1])
    with col_btn_run:
        if st.button("🤖 推演空间关联方案 (先预览，不建表)", type="primary", use_container_width=True):
            if not return_cols:
                st.error("❌ 请在上方选择需要提取的归属字段！")
                return
            
            p_text = user_instr.strip() if user_instr.strip() else "执行标准空间包含匹配 (ST_Contains)。"
            st.session_state.gis_chat_history.append(dict(role="user", content=p_text))
            
            with st.spinner("[1/3] 🧠 AI 正在思考并编写空间计算 SQL 代码..."):
                all_schemas_info = f"Points Table A: `{pt_tbl}` | Cols: {', '.join(pt_cols)}\nPolygons Table B: `{poly_tbl}` | Cols: {', '.join(poly_cols)}"
                
                # 🔴 增加终极防幻觉指令 (ANTI-HALLUCINATION)
                sys_p = f"""You are a DuckDB Spatial GIS Expert. 
SCHEMA:\n{all_schemas_info}
Points Table (A) Lon: "{lon_col}", Lat: "{lat_col}"
Polygons Table (B) Geometry: "{geom_col}"
Return Cols from B: {return_cols}

Task: Write a COMPLETE SQL query for Spatial LEFT JOIN. 
RULES:
1. MUST select ALL columns from A (`A.*`) and ONLY the requested columns from B.
2. ALIAS ALL selected columns from B to prevent name collisions.
3. THE SPATIAL JOIN CONDITION MUST EXACTLY BE:
   `ST_Contains(ST_GeomFromText(B."{geom_col}"), ST_Point(CAST(A."{lon_col}" AS DOUBLE), CAST(A."{lat_col}" AS DOUBLE)))`
4. 🚫 ANTI-HALLUCINATION (CRITICAL): DuckDB is NOT PostGIS. DO NOT use `ST_SetSRID` or `ST_MakePoint`. These functions DO NOT EXIST in DuckDB. You MUST ONLY use `ST_Point()`.
5. Handle Deduplication if requested by the user.
6. Output your step-by-step thinking in Simplified Chinese, then output ONLY raw SQL in {md_ticks}sql."""
                
                history_data = []
                for m in st.session_state.gis_chat_history:
                    # 我们不需要把长篇大论的纠错日志喂给 AI，只喂原始对话即可
                    content = str(m.get("content", ""))
                    if m.get("sql"): content += f"\n{md_ticks}sql\n{m['sql']}\n{md_ticks}"
                    history_data.append(dict(role=str(m.get("role", "")), content=content))

                ai_resp = call_ai_sql_coder(sys_p, history_data, "空间先验")
                sql_code, explain = extract_sql(ai_resp)

            if sql_code:
                max_retries = 3
                current_sql = sql_code
                preview_df, qc_data, final_error = None, None, None
                retry_log = [] # 🔴 新增：用于记录纠错全过程

                for attempt in range(max_retries):
                    try:
                        safe_sql = current_sql.strip().rstrip(';')
                        conn = get_db_connection()
                        
                        with st.spinner("[2/3] 🔌 正在加载 DuckDB 空间扩展组件..."):
                            with db_lock:
                                # ⚠️ 如果您下载了离线包，请把这里改成 conn.execute("INSTALL 'D:/您的路径/spatial.duckdb_extension';")
                                conn.execute("INSTALL spatial;") 
                                conn.execute("LOAD spatial;")
                        
                        with st.spinner("[3/3] ⚙️ 正在启动 C++ 底层内核进行空间相交测算与行数探测..."):
                            with db_lock:
                                conn.execute("DROP VIEW IF EXISTS tmp_gis_preview")
                                conn.execute(f"CREATE TEMPORARY VIEW tmp_gis_preview AS {safe_sql}")
                                preview_df = conn.execute("SELECT * FROM tmp_gis_preview LIMIT 5").df()
                                res_cnt = conn.execute("SELECT COUNT(*) FROM tmp_gis_preview").fetchone()[0]
                                base_cnt = conn.execute(f'SELECT COUNT(*) FROM "{pt_tbl}"').fetchone()[0]
                                conn.execute("DROP VIEW IF EXISTS tmp_gis_preview")
                                
                        qc_data = dict(base_cnt=base_cnt, res_cnt=res_cnt)
                        final_error = None
                        break
                    
                    except Exception as e:
                        final_error = str(e)
                        # 记录这次报错信息
                        retry_log.append(f"❌ **第 {attempt+1} 次执行报错：**\n`{final_error}`\n**当时的错误代码：**\n```sql\n{current_sql}\n```")
                        
                        st.toast(f"🔄 空间推演报错，AI 正在重试 ({attempt+1}/3)...", icon="🧠")
                        with st.spinner(f"正在进行第 {attempt+1} 次智能自动纠错..."):
                            fix_p = f"SQL failed:\n{final_error}\n\nBroken SQL:\n{md_ticks}sql\n{current_sql}\n{md_ticks}\nFix it. Remember RULE 4: NO ST_SetSRID or ST_MakePoint. Use ST_Point()."
                            fix_resp = call_ai_sql_coder(fix_p, [{"role":"user","content":"Fix the Spatial SQL"}], "推演纠错")
                            new_sql, new_explain = extract_sql(fix_resp)
                            if new_sql: 
                                current_sql = new_sql
                                retry_log.append(f"🤖 **AI 反思与修正方案：**\n{new_explain}")
                            else: 
                                break
                
                # 🔴 包装结果展示
                if final_error:
                    st.session_state.gis_chat_history.append(dict(
                        role="assistant", 
                        content=f"❌ **空间推演最终失败**：超过最大重试次数。",
                        explain_log="### 🔧 自动纠错日志\n\n" + "\n\n---\n\n".join(retry_log),
                        sql=current_sql
                    ))
                else:
                    st.session_state.gis_pending_sql = current_sql
                    
                    # 组合主显示文本和折叠日志
                    main_msg = "💡 **空间匹配逻辑推演完毕！**"
                    if retry_log:
                        main_msg += f" *(🤖 触发防崩溃保护，历经 {len(retry_log)//2} 次底层自动纠错修复成功)*"
                    
                    full_explain_log = f"### 🤔 AI 初始思考推演\n{explain}\n\n"
                    if retry_log:
                        full_explain_log += "---\n### 🔧 底层报错与自动纠错追踪\n\n" + "\n\n".join(retry_log)
                        
                    st.session_state.gis_chat_history.append(dict(
                        role="assistant", 
                        content=main_msg, 
                        explain_log=full_explain_log,
                        sql=current_sql, 
                        preview_df=preview_df, 
                        qc=qc_data
                    ))
            else:
                st.error("❌ AI 未能识别空间代码。")
            st.rerun()

    with col_btn_clr:
        if st.button("🧹 清空记录", use_container_width=True, key="gis_clear_btn"):
            st.session_state.gis_chat_history, st.session_state.gis_pending_sql = [], ""
            st.rerun()

    # ==========================================
    # 3. 物理执行区 (确认建表)
    # ==========================================
    if st.session_state.gis_pending_sql:
        st.markdown("---")
        st.markdown("#### ✅ 第二步：确认方案并执行全量空间运算")
        
        target_name = st.text_input("💾 运算结果存为新表：", value=f"{pt_tbl}_spatial_joined", key="gis_out_name")
        final_sql = st.text_area("🔧 底层空间算法 SQL (可微调)：", value=st.session_state.gis_pending_sql, height=150, key="gis_final_editor")
        
        if st.button(f"🚀 确认无误，执行全量空间测算并建表 [{target_name}]", type="primary", use_container_width=True):
            with st.spinner("🌍 GIS 引擎全量扫表中... (如果数据量极大，请耐心等待)"):
                try:
                    safe_sql = final_sql.strip().rstrip(';')
                    conn = get_db_connection()
                    with db_lock:
                        # ⚠️ 离线安装同上修改
                        conn.execute("INSTALL spatial; LOAD spatial;")
                        conn.execute(f'DROP TABLE IF EXISTS "{target_name}"')
                        conn.execute(f'CREATE TABLE "{target_name}" AS {safe_sql}')
                        
                    st.success(f"🎉 空间归属计算完成！物理表 `[{target_name}]` 已落盘。")
                    invalidate_schema_cache()
                except Exception as e:
                    st.error(f"❌ 空间建表失败：{e}")