import os
import json
import streamlit as st

from modules.data_steward.db_engine import (
    execute_safe_query, get_table_schema, get_db_connection, db_lock
)
from modules.data_steward.ai_engine import call_ai_sql_coder, extract_sql
from modules.data_steward.utils import get_business_tables, fast_df_to_csv, fast_table_to_csv_bytes

def render_ai_chat_tab():
    business_tables = get_business_tables()
    if not business_tables:
        st.warning("请先入库数据！")
        return

    TEMPLATE_FILE = os.path.join("global_data", "data_warehouse", "sql_templates.json")
    md_ticks = "`" * 3

    if "chat_step" not in st.session_state: st.session_state.chat_step = 1
    if "ai_chat_history" not in st.session_state: st.session_state.ai_chat_history = []
    if "chat_sql_editor" not in st.session_state: st.session_state.chat_sql_editor = ""
    if "chat_df" not in st.session_state: st.session_state.chat_df = None
    
    if "sql_templates" not in st.session_state:
        st.session_state.sql_templates = {}
        if os.path.exists(TEMPLATE_FILE):
            try:
                with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                    st.session_state.sql_templates = json.load(f)
            except Exception: pass

    st.markdown("### 💬 AI 连续对话分析台")

    col_opt1, col_opt2 = st.columns([3, 1])
    with col_opt1:
        analysis_mode_ai = st.radio("🔍 分析范围：", ["📄 选定单表", "🕸️ 多表联合分析"], horizontal=True, key="chat_scope_radio")
    with col_opt2:
        if st.button("🧹 清空历史与上下文", type="secondary", use_container_width=True, key="chat_clear_btn"):
            st.session_state.ai_chat_history = []
            st.session_state.chat_sql_editor = ""
            st.session_state.chat_df = None
            st.rerun()

    sys_schema = ""
    sys_rules = ""
    selected_tables_for_ai = []

    if analysis_mode_ai == "📄 选定单表":
        sel_tbl = st.selectbox("👉 选择表：", business_tables, key="chat_sel_tbl")
        selected_tables_for_ai = [sel_tbl]
        with st.expander(f"👀 查看 `{sel_tbl}` 的前 5 行预览", expanded=False):
            st.dataframe(execute_safe_query(f'SELECT * FROM "{sel_tbl}" LIMIT 5'), hide_index=True)
    else:
        selected_tables_for_ai = st.multiselect("👉 勾选参与分析的表：", business_tables, default=business_tables[:2] if len(business_tables)>=2 else business_tables, key="chat_multi_tbl")
    
    if selected_tables_for_ai:
        schema_lines = []
        for t in selected_tables_for_ai:
            cols_str = ", ".join([f"{r['column_name']}({r['column_type']})" for _, r in get_table_schema(t).iterrows()])
            schema_lines.append(f"Table: `{t}` | Columns: {cols_str}")
        sys_schema = "\n".join(schema_lines)
        
        if analysis_mode_ai == "📄 选定单表":
            sys_rules = f"CRITICAL: MUST ONLY query from `{selected_tables_for_ai[0]}`. DO NOT use JOIN."
        else:
            sys_rules = f"You can use JOINs across the selected tables: {', '.join(selected_tables_for_ai)}. You also have access to previous 'ai_step' tables for intermediate results."

    with st.expander("🌟 SQL 模板库 (已开启永久本地保存)", expanded=False):
        col_t1, col_t2 = st.columns([1, 1])
        with col_t1:
            st.markdown("##### 🚀 运行已有模板")
            if st.session_state.sql_templates:
                selected_tpl = st.selectbox("选择要跑的模板：", list(st.session_state.sql_templates.keys()), label_visibility="collapsed")
                col_btn_run, col_btn_del = st.columns([3, 1])
                with col_btn_run:
                    if st.button("🤖 智能适配 (先预览代码)", type="primary", use_container_width=True):
                        raw_sql = st.session_state.sql_templates[selected_tpl]
                        adapt_prompt = (
                            f"**[预览模式] 智能适配模板：{selected_tpl}**\n\n"
                            f"请将以下 SQL 模板智能适配到我当前圈选的数据表中：\n"
                            f"1. 分析当前上下文的 Schema，自动替换掉模板中不存在的表名或字段名。\n"
                            f"2. 严格保持核心业务逻辑。\n\n"
                            f"**原始模板代码**：\n{md_ticks}sql\n{raw_sql}\n{md_ticks}"
                        )
                        if st.session_state.ai_chat_history and st.session_state.ai_chat_history[-1].get("role") == "user":
                            st.session_state.ai_chat_history.pop()
                        st.session_state.ai_chat_history.append(dict(role="user", content=adapt_prompt))
                        st.rerun()

                with col_btn_del:
                    if st.button("🗑️ 删除", use_container_width=True):
                        del st.session_state.sql_templates[selected_tpl]
                        try:
                            with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
                                json.dump(st.session_state.sql_templates, f, ensure_ascii=False, indent=2)
                        except: pass
                        st.rerun()
            else: st.info("📭 你的模板库还是空的。")

        with col_t2:
            st.markdown("##### ➕ 录入新模板")
            new_tpl_name = st.text_input("给模板起个名：", placeholder="例如：地市各频段对齐率扫描表", label_visibility="collapsed")
            new_tpl_sql = st.text_area("在此粘贴 SQL 代码：", height=120, placeholder="粘贴 SQL...", label_visibility="collapsed")
            if st.button("💾 添加到模板库", use_container_width=True):
                if new_tpl_name.strip() and new_tpl_sql.strip():
                    st.session_state.sql_templates[new_tpl_name.strip()] = new_tpl_sql.strip()
                    try:
                        os.makedirs(os.path.dirname(TEMPLATE_FILE), exist_ok=True)
                        with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
                            json.dump(st.session_state.sql_templates, f, ensure_ascii=False, indent=2)
                        st.success(f"✅ 保存成功：{new_tpl_name.strip()}")
                    except Exception as e: st.error(f"保存失败：{e}")
                    st.rerun()

    st.markdown("---")

    if not st.session_state.ai_chat_history:
        st.caption("👋 欢迎！请在最下方的输入框中提出您的第一条计算需求。")
        
    for i, msg in enumerate(st.session_state.ai_chat_history):
        msg_role = msg.get("role", "")
        with st.chat_message(msg_role):
            if msg_role == "user":
                st.markdown(msg.get("content", ""))
            else:
                st.markdown(msg.get("content", ""), unsafe_allow_html=True)
                if msg.get("sql"):
                    is_last = (i == len(st.session_state.ai_chat_history) - 1)
                    with st.expander("⚙️ 思考过程与底层 SQL (点击展开查看或修改)", expanded=is_last):
                        if is_last:
                            edited_sql = st.text_area("您可以直接在此修改代码并手动重跑：", value=msg["sql"], height=200, key=f"edit_sql_{i}")
                            if st.button("▶️ 确认修改并重跑代码", key=f"rerun_btn_{i}"):
                                with st.spinner("手动执行中..."):
                                    try:
                                        table_name = msg.get("table_name", f"ai_step_{st.session_state.chat_step}")
                                        conn = get_db_connection()
                                        with db_lock:
                                            conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                                            conn.execute(f'CREATE TEMPORARY TABLE "{table_name}" AS {edited_sql}')
                                            
                                            total_r = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
                                            if total_r > 10000:
                                                res_df = conn.execute(f'SELECT * FROM "{table_name}" LIMIT 10000').df()
                                                st.session_state.ai_chat_history[i]["is_huge"] = True
                                                st.session_state.ai_chat_history[i]["total_rows"] = total_r
                                            else:
                                                res_df = conn.execute(f'SELECT * FROM "{table_name}"').df()
                                                st.session_state.ai_chat_history[i]["is_huge"] = False
                                        
                                        st.session_state.ai_chat_history[i]["sql"] = edited_sql
                                        st.session_state.ai_chat_history[i]["df"] = res_df
                                        st.session_state.ai_chat_history[i]["error"] = None
                                        st.rerun()
                                    except Exception as e:
                                        st.session_state.ai_chat_history[i]["sql"] = edited_sql
                                        st.session_state.ai_chat_history[i]["error"] = str(e)
                                        st.session_state.ai_chat_history[i]["df"] = None
                                        st.rerun()
                        else:
                            st.code(msg["sql"], language="sql")

                if msg.get("error"):
                    st.error(f"❌ SQL 执行报错：\n{msg['error']}\n\n👉 提示：你可以直接展开上方【思考框】修改代码，或者在最下方追问框告诉 AI 怎么修。")

                if msg.get("df") is not None:
                    df = msg["df"]
                    if len(df) == 0:
                        st.warning(f"⚠️ SQL 执行成功，但结果为 0 行。生成的中间表: `{msg.get('table_name')}`。")
                    else:
                        if msg.get("is_huge"):
                            st.error(f"🚨 **UI 内存熔断保护触发**：原始结果集共有 **{msg.get('total_rows'):,}** 行数据！为防止网页卡死，内存中仅为您加载 10,000 行。")
                            with st.spinner("📦 正在底层极速打包全量 CSV 数据..."):
                                full_csv_bytes = fast_table_to_csv_bytes(msg.get("table_name"), msg.get("sql", str(i)))
                            st.download_button(
                                label=f"📦 一键下载全量结果集 (CSV, 包含完整的 {msg.get('total_rows'):,} 行)", 
                                data=full_csv_bytes, file_name=f"{msg.get('table_name')}_FULL.csv", mime="text/csv", key=f"dl_huge_{i}"
                            )
                        else:
                            st.success(f"✅ 执行成功，共命中 {len(df):,} 行。中间表名: `{msg.get('table_name')}`。")
                            csv_data = fast_df_to_csv(df, msg.get("sql", str(i))) 
                            st.download_button(label="📥 导出完整结果集 (CSV)", data=csv_data, file_name=f"{msg.get('table_name')}.csv", mime="text/csv", key=f"dl_{i}")
                        
                        if len(df) > 200:
                            st.caption("💡 UI 仅截断展示前 200 行，完整数据请点击上方下载按钮。")
                            st.dataframe(df.head(200), use_container_width=True)
                        else:
                            st.dataframe(df, use_container_width=True)

    user_q = st.chat_input("输入需求、追问指令或报错信息...", key="chat_input_box")
    if user_q:
        if st.session_state.ai_chat_history and st.session_state.ai_chat_history[-1].get("role") == "user":
            st.session_state.ai_chat_history.pop()
        st.session_state.ai_chat_history.append(dict(role="user", content=user_q))
        st.rerun()

    if st.session_state.ai_chat_history and st.session_state.ai_chat_history[-1].get("role") == "user":
        current_user_msg = st.session_state.ai_chat_history[-1].get("content", "")
        is_preview_mode = current_user_msg.startswith("**[预览模式]")

        with st.chat_message("assistant"):
            with st.spinner("AI 推演代码与自动执行中..."):
                last_sql = ""
                for m in reversed(st.session_state.ai_chat_history):
                    if m.get("sql"):
                        last_sql = m["sql"]
                        break

                sys_p = f"""You are an Expert DuckDB Data Architect. 
SCHEMA:\n{sys_schema}
RULES:\n1.{sys_rules}
2. Geospatial: acos(sin(radians(lat1))*sin(radians(lat2)) + cos(radians(lat1))*cos(radians(lat2))*cos(radians(lon2)-radians(lon1))) * 6371000
3. CTE PREFERENCE: STRONGLY prefer CTEs (WITH clause) for complex multi-step analysis.
4. ROBUSTNESS: Handle Division by Zero with NULLIF(divisor, 0). Use COALESCE for NULLs. Cast to float using 100.0 or 1.0. ROUND(val, 2).
5. WIDE TABLE OPTIMIZATION: Prefer Conditional Aggregation (SUM(CASE WHEN...)) to pivot data over multiple JOINs.
6. COMPLEX JOINS & TEXT MATCHING (CRITICAL): Use string functions directly in the JOIN ON clause if needed.
7. SYNTAX STRICTNESS: NEVER use backticks (`). MUST use double quotes (") for table and column names if they contain special characters or spaces.
8. Output raw SQL wrapped in {md_ticks}sql.
9. LANGUAGE CONSTRAINT: 你的所有思考过程、逻辑推演和最终的文字解释，必须且只能使用【简体中文】输出！"""
                
                if last_sql:
                    sys_p += f"\n\n[CRITICAL CONTEXT]:\nThe user was last working with this SQL:\n{md_ticks}sql\n{last_sql}\n{md_ticks}"

                history_for_llm = []
                for m in st.session_state.ai_chat_history:
                    msg_text = str(m.get('content', ''))
                    if m.get('error'): msg_text += f"\n(Error encountered: {m['error']})"
                    history_for_llm.append(dict(role=str(m.get('role', '')), content=msg_text))

                ai_resp = call_ai_sql_coder(sys_p, history_for_llm, "对话分析")
                clean_sql, exp = extract_sql(ai_resp)
                
                step_id = st.session_state.chat_step
                tmp_table_name = f"ai_step_{step_id}"
                res_df = None
                error_msg = None
                is_huge = False
                total_rows = 0

                if clean_sql:
                    if is_preview_mode:
                        exp = "💡 **代码已根据当前表结构为您智能适配完毕！**\n\n👇 确认无误后，请点击下方框内的 **【▶️ 确认修改并重跑代码】** 按钮执行查数。\n\n" + exp
                    else:
                        max_retries = 3
                        current_sql = clean_sql
                        current_exp = exp
                        retry_log = [] 
                        
                        for attempt in range(max_retries):
                            try:
                                conn = get_db_connection()
                                with db_lock:
                                    conn.execute(f'DROP TABLE IF EXISTS "{tmp_table_name}"')
                                    conn.execute(f'CREATE TEMPORARY TABLE "{tmp_table_name}" AS {current_sql}')
                                    total_rows = conn.execute(f'SELECT COUNT(*) FROM "{tmp_table_name}"').fetchone()[0]
                                    if total_rows > 10000:
                                        res_df = conn.execute(f'SELECT * FROM "{tmp_table_name}" LIMIT 10000').df()
                                        is_huge = True
                                    else:
                                        res_df = conn.execute(f'SELECT * FROM "{tmp_table_name}"').df()
                                        is_huge = False
                                
                                st.session_state.chat_step += 1
                                clean_sql = current_sql
                                error_msg = None
                                
                                if attempt > 0:
                                    retry_detail = "\n".join([f"**第 {j+1} 次尝试**\n- 报错：`{err}`\n- SQL：\n{md_ticks}sql\n{sql}\n{md_ticks}" for j, (sql, err) in enumerate(retry_log)])
                                    exp = f"*(🤖 架构师自动修复成功，共经历 {attempt} 次反思)*\n\n" + current_exp + f"\n\n<details><summary>🔧 点击展开修复过程（共 {attempt} 次失败）</summary>\n\n{retry_detail}\n\n</details>"
                                else: exp = current_exp
                                break 
                            except Exception as e:
                                error_msg = str(e)
                                retry_log.append((current_sql, error_msg)) 
                                if attempt < max_retries - 1:
                                    st.toast(f"🔄 AI 遇到底层报错，正在进行第 {attempt + 1} 次深度反思与自动修复...", icon="🧠")
                                    fix_prompt = f"刚才执行这句 SQL 时遇到了报错：\n{md_ticks}sql\n{current_sql}\n{md_ticks}\n报错信息：\n{error_msg}\n\n请深度思考并修正问题，然后输出修复后的最新 SQL 代码。"
                                    fix_history = list(history_for_llm)
                                    fix_history.append(dict(role="assistant", content=f"{current_exp}\n{md_ticks}sql\n{current_sql}\n{md_ticks}"))
                                    fix_history.append(dict(role="user", content=fix_prompt))
                                    ai_fix_resp = call_ai_sql_coder(sys_p, fix_history, f"自动纠错_第{attempt+1}次")
                                    new_sql, new_exp = extract_sql(ai_fix_resp)
                                    if new_sql:
                                        current_sql = new_sql
                                        current_exp = new_exp
                                    else:
                                        clean_sql = current_sql
                                        exp = current_exp
                                        break
                                else:
                                    clean_sql = current_sql
                                    exp = current_exp
                else: error_msg = "未检测到有效的 SQL 代码输出。"

                st.session_state.ai_chat_history.append(dict(
                    role="assistant", content=exp, sql=clean_sql, df=res_df, 
                    error=error_msg, table_name=tmp_table_name, is_huge=is_huge, total_rows=total_rows
                ))
                st.rerun()