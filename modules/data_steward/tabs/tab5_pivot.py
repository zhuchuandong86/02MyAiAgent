import re
import streamlit as st

from modules.data_steward.db_engine import execute_safe_query, get_table_schema
from modules.data_steward.ai_engine import call_ai_sql_coder, extract_sql
from modules.data_steward.utils import get_business_tables, fast_df_to_csv

def render_manual_pivot_tab():
    tables = get_business_tables()
    if not tables:
        st.warning("请先入库数据！")
        return
        
    st.markdown("### 🖱️ 智能手工全量透视表 (支持计算字段与范围圈选)")
    mode = st.radio("🔍 透视范围：", ["📄 单表透视", "🕸️ 跨表透视 (字段混选，AI动态关联)"], horizontal=True, key="pivot_scope_radio")
    
    selected_tables = []
    if mode == "📄 单表透视":
        sel_tbl = st.selectbox("👉 选择表：", tables, key="pivot_sel_tbl")
        selected_tables = [sel_tbl]
        with st.expander(f"👀 查看 `{sel_tbl}` 的前 5 行预览", expanded=False): 
            st.dataframe(execute_safe_query(f"SELECT * FROM {sel_tbl} LIMIT 5"), hide_index=True)
        table_cols = get_table_schema(sel_tbl)['column_name'].tolist()
    else:
        st.info("💡 跨表模式：请选择需要参与跨表的实体表，AI 会仅围绕您选定的表推演 JOIN 逻辑。")
        selected_tables = st.multiselect("👉 选择参与跨表的实体表：", tables, default=tables[:2] if len(tables)>=2 else tables, key="pivot_multi_tbl")
        
        all_schemas_info = ""
        table_cols = []
        if selected_tables:
            with st.expander("📚 已选表的可用字典", expanded=True):
                for t in selected_tables:
                    cols = get_table_schema(t)['column_name'].tolist()
                    all_schemas_info += f"Table: `{t}` | Cols: {', '.join(cols)}\n"
                    for c in cols: table_cols.append(f"[{t}] {c}")
                    st.markdown(f"**`{t}`**: `" + "` , `".join(cols) + "`")

    if not selected_tables:
        return

    with st.form("pivot_config_form", clear_on_submit=False):
        col_f, col_r, col_c, col_v = st.columns(4)
        
        with col_f:
            pivot_filters = st.multiselect("👉 【筛选】(可选)：", table_cols, key="pivot_f")
            st.caption("配合下方填写具体条件")
        with col_r: 
            pivot_rows = st.multiselect("👉 【行】(可选)：", table_cols, key="pivot_r")
        with col_c: 
            pivot_cols = st.multiselect("👉 【列】(可选)：", table_cols, key="pivot_c")
        with col_v:
            pivot_vals = st.multiselect("👉 【基础值】(可选)：", table_cols, key="pivot_v")
            pivot_agg = st.selectbox("📐 基础聚合：", ["SUM", "COUNT", "COUNT DISTINCT", "AVG", "MAX", "MIN"], key="pivot_agg")

        custom_calcs_input = st.text_input("➕ 添加计算字段 (例如: SUM(收入)/SUM(成本) AS 利润率)：", placeholder="支持直接写 SQL 表达式，多个字段用逗号分隔...", key="pivot_calc_input")
        nl_condition = st.text_area("🗣️ 附加业务需求与条件筛选 (大白话自由输入)：", placeholder="例如：1. 过滤条件（只要华为和中兴）；2. 复杂业务逻辑（算完后只取排名前3的记录，或者按某种规则计算同环比等）...", key="pivot_nl_cond")

        submitted = st.form_submit_button("🚀 立即全量透视", type="primary", use_container_width=True)

    if submitted:
        with st.spinner("AI 意图解析与底层运算中..."):
            try:
                where_clause = ""
                if (nl_condition.strip() or pivot_filters) and mode == "📄 单表透视":
                    if pivot_filters and not nl_condition.strip():
                        st.warning("⚠️ 您选择了【筛选】字段但未填写过滤条件，请在下方说明框描述筛选规则（例如：城市只要北京和上海）。")
                        return
                    else:
                        user_intent = nl_condition.strip()
                        sys_p = f"Table: {sel_tbl}\nCols: {table_cols}\nTarget Filter Columns: {pivot_filters}\nTask: Convert User Intent to a valid SQL WHERE clause. ONLY output the pure SQL condition. DO NOT output the word WHERE. NO markdown formatting."
                        raw_where = call_ai_sql_coder(sys_p, [{"role":"user","content":user_intent}], "透视条件翻译")
                        clean_where, _ = extract_sql(raw_where)
                        if not clean_where: clean_where = raw_where.replace("```sql", "").replace("```", "").strip()
                        clean_where = re.sub(r'(?i)^\s*WHERE\s+', '', clean_where).strip()
                        where_clause = clean_where
                    st.info(f"🤖 AI 生成过滤逻辑：`{where_clause}`")

                val_exprs = [f"COUNT(DISTINCT \"{v}\") AS \"{v}_去重\"" if "DISTINCT" in pivot_agg else f"{pivot_agg.split(' ')[0]}(\"{v}\") AS \"{v}_聚合\"" for v in pivot_vals]
                if custom_calcs_input.strip(): val_exprs.append(custom_calcs_input.strip())
                if not val_exprs: val_exprs = ["COUNT(*) AS \"记录数\""]

                v_sql = ", ".join(val_exprs)

                if mode == "📄 单表透视":
                    s_sql = f'"{sel_tbl}"'
                    if where_clause: s_sql = f"(SELECT * FROM {s_sql} WHERE {where_clause})"
                    
                    if pivot_cols:
                        p_cols = ", ".join([f'"{c}"' for c in pivot_cols])
                        if pivot_rows:
                            r_grp = f"GROUP BY {', '.join([f'\"{c}\"' for c in pivot_rows])}"
                            final_sql = f"PIVOT {s_sql} ON {p_cols} USING {v_sql} {r_grp}"
                        else:
                            final_sql = f"PIVOT (SELECT '全量汇总' AS \"_全局汇总\", * FROM {s_sql}) ON {p_cols} USING {v_sql} GROUP BY \"_全局汇总\""
                    else:
                        if pivot_rows:
                            r_cols = ", ".join([f'"{c}"' for c in pivot_rows])
                            final_sql = f"SELECT {r_cols}, {v_sql} FROM {s_sql} GROUP BY {r_cols} ORDER BY {r_cols}"
                        else:
                            final_sql = f"SELECT {v_sql} FROM {s_sql}"
                else:
                    sys_p = f"""SCHEMA:\n{all_schemas_info}\nRows:{pivot_rows}, Cols:{pivot_cols}, Base Vals:{pivot_vals}(Agg:{pivot_agg}), Target Filter Cols:{pivot_filters}, Custom Calculated Fields:[{custom_calcs_input}], Additional Business Intent:{nl_condition}
Task: Write DuckDB SQL. USE PIVOT if cols requested.
CRITICAL RULES:
1. Include Custom Calculated Fields. Prevent Division by Zero using NULLIF.
2. Handle NULLs with COALESCE(). Cast ints to float.
3. COMPLEX JOINS: Use DuckDB string functions (LIKE, REGEXP_EXTRACT, SPLIT_PART) in the ON clause.
4. Output raw SQL in ```sql."""
                    ai_resp = call_ai_sql_coder(sys_p, [{"role":"user","content":"Generate SQL"}], "跨表透视生成")
                    final_sql, _ = extract_sql(ai_resp)
                    st.info(f"🤖 底层执行 SQL：\n```sql\n{final_sql}\n```")

                res_df = execute_safe_query(final_sql)
                st.markdown(f"##### 📊 全量完成 (命中 {len(res_df)} 条)")
                csv_data = fast_df_to_csv(res_df, final_sql)
                
                if len(res_df) > 10000:
                    st.info("💡 探测到超过 1 万行的超大数据集！为防止浏览器卡死，已为您折叠预览界面，请直接下载文件。")
                    st.download_button(label="📦 一键下载超大透视结果 (CSV)", data=csv_data, file_name="pivot_results.csv", mime="text/csv", key="pivot_download_huge")
                else:
                    st.download_button(label="📥 导出完整透视结果 (CSV)", data=csv_data, file_name="pivot_results.csv", mime="text/csv", key="pivot_download")
                    if len(res_df) > 500:
                        st.warning("⚠️ UI 仅截断前 500 行展示，完整数据请点击上方导出按钮。")
                        st.dataframe(res_df.head(500), use_container_width=True)
                    else:
                        st.dataframe(res_df, use_container_width=True)
            except Exception as e: st.error(f"透视执行或语法生成失败：{e}")