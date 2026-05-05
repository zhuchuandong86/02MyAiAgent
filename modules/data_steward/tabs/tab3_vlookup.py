import streamlit as st
from modules.data_steward.db_engine import (
    execute_write, execute_safe_query, get_table_schema, 
    get_db_connection, db_lock, invalidate_schema_cache
)
from modules.data_steward.ai_engine import call_ai_sql_coder, extract_sql
from modules.data_steward.utils import get_business_tables

def render_join_tab():
    st.markdown("### 🧩 智能 VLOOKUP (多条件关联与即时质检)")
    tables = get_business_tables()
    if len(tables) < 2:
        st.warning("⚠️ 仓库中至少需要 2 张表才能进行关联。")
        return

    # 🔴 状态管理：支持多轮对话、暂存 SQL 及预览数据
    if "vl_chat_history" not in st.session_state: st.session_state.vl_chat_history = []
    if "vl_pending_sql" not in st.session_state: st.session_state.vl_pending_sql = ""
    md_ticks = "`" * 3

    # ==========================================
    # 1. 基础表单配置区 (支持多列关联)
    # ==========================================
    with st.container(border=True):
        col_base, col_target = st.columns(2)
        with col_base:
            st.markdown("##### 📄 1. 基础底表 (主表)")
            base_tbl = st.selectbox("👉 选择主表：", tables, key="vl_base_tbl")
            base_cols = get_table_schema(base_tbl)['column_name'].tolist()
            base_keys = st.multiselect("🔑 匹配特征列 (最多选3个)：", base_cols, max_selections=3, key="vl_base_keys")

        with col_target:
            st.markdown("##### 🎯 2. 目标来源 (去哪提取？)")
            target_idx = 1 if len(tables) > 1 and tables[1] != base_tbl else 0
            target_tbl = st.selectbox("👉 选择来源表：", tables, index=target_idx, key="vl_target_tbl")
            target_cols = get_table_schema(target_tbl)['column_name'].tolist()
            target_keys = st.multiselect("🔑 匹配对应列 (需与左侧数量一致)：", target_cols, max_selections=3, key="vl_target_keys")
            
            available_ret_cols = [c for c in target_cols if c not in target_keys]
            return_cols = st.multiselect("📦 要提取回来的字段：", available_ret_cols, key="vl_ret_cols")

    st.markdown("---")

    # ==========================================
    # 2. 连续对话与“先验”预览区
    # ==========================================
    st.markdown("#### 💬 第一步：逻辑推演与即时质检")
    
    for msg in st.session_state.vl_chat_history:
        m_role = msg.get("role", "")
        with st.chat_message(m_role):
            st.markdown(msg.get("content", ""))
            
            if msg.get("sql"):
                st.code(msg["sql"], language="sql")
            
            if msg.get("preview_df") is not None:
                st.markdown("⭐ **推演结果样本预览**：")
                st.dataframe(msg["preview_df"], hide_index=True)
                
                if msg.get("qc"):
                    qc = msg["qc"]
                    col_q1, col_q2, col_q3 = st.columns(3)
                    col_q1.metric("底表行数", f"{qc['base_cnt']:,}")
                    col_q2.metric("模拟结果行数", f"{qc['res_cnt']:,}")
                    diff = qc['res_cnt'] - qc['base_cnt']
                    if diff > 0:
                        col_q3.metric("⚠️ 膨胀预警", f"+{diff:,}", delta_color="inverse")
                        st.error("🚨 **警告：数据发生膨胀！**\n目标表存在重复键，这会引发笛卡尔积裂变。👉 **修复建议**：请在下方对话框输入指令，例如：*『右表有重复，请在 JOIN 前先对右表按特征列去重（取最新/任意一条即可）』*。")
                    else:
                        col_q3.metric("✅ 匹配健康", "0 差异", delta_color="normal")

    user_instr = st.text_area(
        "🗣️ 输入清洗/匹配指令：", 
        placeholder="例如：主表的特征列提取横杠后的6位再匹配；如果有重复请先去重...", 
        height=80, key="vl_user_input"
    )

    col_btn_run, col_btn_clr = st.columns([3, 1])
    with col_btn_run:
        if st.button("🤖 智能推演并预览样本 (不创表)", type="primary", use_container_width=True):
            if not base_keys or not target_keys:
                st.error("❌ 请先在上方选择匹配的特征列！")
                return
            if len(base_keys) != len(target_keys):
                st.error(f"❌ 匹配列数量不一致！主表选了 {len(base_keys)} 个特征列，目标表选了 {len(target_keys)} 个，必须一一对应。")
                return
            if not return_cols:
                st.error("❌ 请先勾选需要提取的字段！")
                return
            
            p_text = user_instr.strip() if user_instr.strip() else "执行标准多条件 VLOOKUP。"
            st.session_state.vl_chat_history.append(dict(role="user", content=p_text))
            
            with st.spinner("AI 正在推演并拉取样本数据..."):
                all_schemas_info = f"Base Table A: `{base_tbl}` | Cols: {', '.join(base_cols)}\nTarget Table B: `{target_tbl}` | Cols: {', '.join(target_cols)}"
                
                # 🔴 强制规范：必须全选左表，且必须给右表字段加前缀别名，防止重名导致建表崩溃
                sys_p = f"""You are a DuckDB Expert. 
SCHEMA:\n{all_schemas_info}
Base Keys (in order): {base_keys}
Target Keys (in order): {target_keys}
Return Cols: {return_cols}

Task: Write a COMPLETE SQL query for VLOOKUP (LEFT JOIN). 
RULES:
1. MUST output a valid SQL query starting with SELECT or WITH.
2. ⚠️ MUST select ALL columns from the Base Table (`SELECT A.*`) and ONLY the specified Return Cols from the Target Table (`B`).
3. ⚠️ CRITICAL ALIASING: You MUST alias the Return Cols from B (e.g., `B."col" AS "VLOOKUP_col"`) to prevent duplicate column name errors!
4. Join on ALL provided keys dynamically using AND. 
5. Use CAST to VARCHAR and TRIM for ALL keys on both sides. 
6. Address the user's specific request carefully (e.g., using CTEs for deduplication if requested).
7. Output ONLY raw SQL in {md_ticks}sql."""
                
                history_data = []
                for m in st.session_state.vl_chat_history:
                    content = str(m.get("content", ""))
                    if m.get("sql"): content += f"\n{md_ticks}sql\n{m['sql']}\n{md_ticks}"
                    history_data.append(dict(role=str(m.get("role", "")), content=content))

                ai_resp = call_ai_sql_coder(sys_p, history_data, "VLOOKUP先验")
                sql_code, explain = extract_sql(ai_resp)

                if sql_code:
                    max_retries = 3
                    current_sql = sql_code
                    preview_df, qc_data, final_error = None, None, None

                    for attempt in range(max_retries):
                        try:
                            safe_sql = current_sql.strip().rstrip(';')
                            # 🔴 核心修复：使用 TEMPORARY VIEW 取代 `SELECT * FROM ({safe_sql})`。
                            # 这样可以 100% 完美支持大模型写出的 WITH CTE 开头的查询，绝不再报 syntax 错误！
                            conn = get_db_connection()
                            with db_lock:
                                conn.execute("DROP VIEW IF EXISTS tmp_vl_preview")
                                conn.execute(f"CREATE TEMPORARY VIEW tmp_vl_preview AS {safe_sql}")
                                preview_df = conn.execute("SELECT * FROM tmp_vl_preview LIMIT 5").df()
                                res_cnt = conn.execute("SELECT COUNT(*) FROM tmp_vl_preview").fetchone()[0]
                                base_cnt = conn.execute(f'SELECT COUNT(*) FROM "{base_tbl}"').fetchone()[0]
                                conn.execute("DROP VIEW IF EXISTS tmp_vl_preview")
                                
                            qc_data = dict(base_cnt=base_cnt, res_cnt=res_cnt)
                            final_error = None
                            break
                        except Exception as e:
                            final_error = str(e)
                            st.toast(f"🔄 推演报错，AI 正在第 {attempt+1} 次自我反思修复...", icon="🧠")
                            fix_p = f"SQL failed:\n{final_error}\n\nBroken SQL:\n{md_ticks}sql\n{current_sql}\n{md_ticks}\nFix it and output raw SQL. Pay attention to CAST types, ALIASING duplicate columns, and SELECT statements."
                            fix_resp = call_ai_sql_coder(fix_p, [{"role":"user","content":"Fix the SQL"}], "推演纠错")
                            new_sql, _ = extract_sql(fix_resp)
                            if new_sql: current_sql = new_sql
                            else: break
                    
                    if final_error:
                        st.session_state.vl_chat_history.append(dict(role="assistant", content=f"❌ 推演失败：{final_error}", sql=current_sql))
                    else:
                        st.session_state.vl_pending_sql = current_sql
                        st.session_state.vl_chat_history.append(dict(
                            role="assistant", content=explain, sql=current_sql, 
                            preview_df=preview_df, qc=qc_data
                        ))
                else:
                    st.error("❌ AI 未能识别代码。")
            st.rerun()

    with col_btn_clr:
        if st.button("🧹 清空记录", use_container_width=True, key="vl_clear_btn"):
            st.session_state.vl_chat_history, st.session_state.vl_pending_sql = [], ""
            st.rerun()
    # ==========================================
    # 3. 物理执行区 (正式建表 + 新增 Agent 自动纠错)
    # ==========================================
    if st.session_state.vl_pending_sql:
        st.markdown("---")
        st.markdown("#### ✅ 第二步：确认方案并正式建表")
        
        target_name = st.text_input("💾 存为新表名：", value=f"{base_tbl}_vlookup", key="vl_out_name")
        final_sql = st.text_area("🔧 最终执行逻辑 (可手工微调)：", value=st.session_state.vl_pending_sql, height=150, key="vl_final_editor")
        
        if st.button(f"🚀 确认无误，正式创建大表 [{target_name}]", type="primary", use_container_width=True):
            with st.spinner("打包入库中 (自带防碰撞自动纠错机制)..."):
                # 🔴 核心修复：为正式建表也引入大模型纠错环
                max_retries = 3
                current_sql = final_sql
                
                for attempt in range(max_retries):
                    try:
                        safe_sql = current_sql.strip().rstrip(';')
                        conn = get_db_connection()
                        with db_lock:
                            conn.execute(f'DROP TABLE IF EXISTS "{target_name}"')
                            # 🔴 彻底脱掉括号包裹，让 CTE 自由奔跑
                            conn.execute(f'CREATE TABLE "{target_name}" AS {safe_sql}')
                            
                        if attempt > 0:
                            st.success(f"🎉 物理表 `[{target_name}]` 已持久化到硬盘！*(🤖 遭遇底层表结构冲突，已由 AI 自主修复)*")
                        else:
                            st.success(f"🎉 物理表 `[{target_name}]` 已持久化到硬盘！")
                            
                        st.session_state.vl_pending_sql = current_sql
                        invalidate_schema_cache()
                        break
                    except Exception as e:
                        error_msg = str(e)
                        if attempt < max_retries - 1:
                            st.toast(f"🔄 建表写入底层时冲突，AI 正在第 {attempt+1} 次反思修复...", icon="🧠")
                            fix_p = f"CREATE TABLE failed with error:\n{error_msg}\n\nBroken SQL:\n{md_ticks}sql\n{current_sql}\n{md_ticks}\nFix the SQL so it successfully creates a table. Make sure to alias Target Table columns if there is a duplicate column name. Output raw SQL."
                            fix_resp = call_ai_sql_coder(fix_p, [{"role":"user", "content":"Fix it."}], "建表纠错")
                            new_sql, _ = extract_sql(fix_resp)
                            if new_sql:
                                current_sql = new_sql
                            else:
                                break
                        else:
                            st.error(f"❌ 经过多次 AI 修正，底层建表仍然失败：\n{error_msg}")
                            break