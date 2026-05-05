import os
import pandas as pd
import streamlit as st

from modules.data_steward.db_engine import (
    execute_write, execute_safe_query, get_all_tables,
    get_table_count, get_db_connection, db_lock, invalidate_schema_cache
)
from modules.data_steward.ai_engine import call_ai_architect_stream
from modules.data_steward.utils import get_business_tables

def render_profile_tab():
    st.markdown("### 🗂️ 数据资产大盘与智能体检")
    tables = get_business_tables()
    
    # 🔴 插入这段“垃圾清理卫士”代码
    all_raw_tables = get_all_tables()
    garbage_tables = [t for t in all_raw_tables if t.startswith('ai_step_')]
    if garbage_tables:
        st.warning(f"🧹 系统扫描到硬盘中残留了 **{len(garbage_tables)}** 个历史 AI 中间表。")
        if st.button("🗑️ 一键抹除中间表"):
            with st.spinner("正在执行底层物理删除..."):
                conn = get_db_connection()
                with db_lock:
                    for gt in garbage_tables:
                        try:
                            conn.execute(f"DROP TABLE IF EXISTS {gt}")
                        except Exception: pass
            invalidate_schema_cache()  # ★ 删表后清缓存
            st.success("✅ 清理完毕！硬盘空间已释放。")
            st.rerun()
    # 🔴 清理代码结束

    if not tables:
        st.warning("📭 仓库为空，请先前往【接入数据源】装载数据。")
        return

    cache_file_path = os.path.join("global_data", "data_warehouse", "ai_profile_cache.md")

    # ================= 1. AI 智能体检报告区 =================
    st.markdown("#### 🤖 AI 智能体检报告")
    
    # 尝试加载缓存的报告
    if not st.session_state.get("data_profile_cache") and os.path.exists(cache_file_path):
        try:
            with open(cache_file_path, "r", encoding="utf-8") as f:
                content = f.read()
                if content.startswith(f""):
                    st.session_state.data_profile_cache = content.split("\n", 1)[1]
        except Exception: pass

    col_btn, _ = st.columns([3, 1])
    with col_btn:
        if st.button("🚀 AI 扫描全库：生成分表体检与综合评价", use_container_width=True, key="profile_ai_btn"):
            with st.status("🕵️‍♂️ 启动全库深度扫描...", expanded=True) as status:
                prompt_payload = ""
                for i, t in enumerate(tables):
                    st.write(f"⏳ 正在深度解剖表结构: `{t}` ({i+1}/{len(tables)})...")
                    try:
                        count = execute_safe_query(f"SELECT COUNT(*) FROM {t}").iloc[0,0]
                        summary_df = execute_safe_query(f"SUMMARIZE {t}")
                        prompt_payload += f"### 表: `{t}` (行数: {count})\n字段特征: "
                        
                        k_cols = []
                        for _, row in summary_df.iterrows():
                            c_name = row['column_name']
                            u_cnt = row['approx_unique']
                            null_pct = row.get('null_percentage', '0%')
                            if pd.notna(u_cnt):
                                k_cols.append(f"{c_name}(唯一:{int(u_cnt)}, 空值率:{null_pct})")
                        prompt_payload += ", ".join(k_cols) + "\n\n"
                    except Exception as e: 
                        st.error(f"⚠️ 扫描表 `{t}` 时遇到问题: {e}")
                
                prompt_payload_trunc = prompt_payload[:8000] + "\n...(已截断)" if len(prompt_payload) > 8000 else prompt_payload
                
                status.update(label="🧠 底层特征提取完毕！开始实时流式生成报告...")
                st.markdown("---")
                st.markdown("##### 📝 正在逐字撰写架构师报告：")
                
                sys_prompt = (
                    f"扫描以下数据库结构：\n{prompt_payload_trunc}\n"
                    "请你作为首席数据架构师，给出深度评估报告，参考以下三个部分：\n"
                    "1. 【各表体检报告】：逐一列出每张表的名字，并点评其数据质量（重点指出异常的空值率或字段分布特点）。\n"
                    "2. 【综合资产评价】：总结整体数据仓库的健康度。\n"
                    "3. 【高价值业务挖掘】：结合这些表的字段特征，建议如何进行分析或关联才能产生最大业务价值。\n"
                    "要求：纯文字段落描述，使用 markdown 标题区隔。语言必须纯正【简体中文】。严禁重复输出巨大表格！"
                )
                
                # 流式输出
                ai_advice = st.write_stream(call_ai_architect_stream(sys_prompt, "全库画像"))
                
                # 写入缓存
                st.session_state.data_profile_cache = ai_advice
                try:
                    os.makedirs(os.path.dirname(cache_file_path), exist_ok=True)
                    with open(cache_file_path, "w", encoding="utf-8") as f:
                        f.write(f"\n" + st.session_state.data_profile_cache)
                except Exception: pass
                
                status.update(label="✅ AI 深度体检报告生成完毕！", state="complete")

    # 渲染已缓存的报告
    if st.session_state.get("data_profile_cache"):
        with st.container(border=True):
            st.markdown(st.session_state.data_profile_cache)
            st.caption("ℹ️ 上方报告已持久化缓存。如对库表做了增删，请手动点击上方按钮重新扫描。")
            
    st.markdown("---")
    
    # ================= 2. 数据字典与管理区 =================
    st.markdown("#### 📚 详细数据字典与资产管理")
    st.caption("💡 提示：点击展开各个数据表，可查看多达 7 维的底层统计特征（包含非空率与数值极值）以及数据预览。")
    
    for t in tables:
        try:
            count = get_table_count(t)  
            with st.expander(f"🗂️ 实体表：**{t}** (总记录数：`{count}` 行)", expanded=False):
                tab_dict, tab_preview, tab_action = st.tabs(["📊 字段极速体检字典", "👀 数据预览", "⚙️ 管理"])
                
                with tab_dict:
                    summary_key = f"summary_loaded_{t}"
                    if not st.session_state.get(summary_key):
                        st.caption("字段详情尚未加载，点击下方按钮触发（每张表仅需一次）。")
                        if st.button(f"🔍 加载 `{t}` 的字段体检详情", key=f"load_summary_{t}"):
                            st.session_state[summary_key] = True
                            st.rerun()
                    else:
                        summary_df = execute_safe_query(f"SUMMARIZE {t}")
                        display_md = "| 字段名称 | 字段类型 | 预估唯一值 | 空值率 | 主键候选 |\n"
                        display_md += "| :--- | :--- | :--- | :--- | :--- |\n"
                        for _, row in summary_df.iterrows():
                            c_name = row['column_name']
                            c_type = str(row['column_type']).upper()
                            u_cnt = row['approx_unique']
                            null_pct = row.get('null_percentage', '0%')
                            is_pk = ""
                            if pd.notna(u_cnt):
                                is_pk = "🔑 是" if u_cnt >= count * 0.95 and count > 10 else ""
                                display_md += f"| `{c_name}` | `{c_type}` | {int(u_cnt)} | {null_pct} | {is_pk} |\n"
                            else:
                                display_md += f"| `{c_name}` | `{c_type}` | - | {null_pct} | - |\n"
                        st.markdown(display_md, unsafe_allow_html=True)
                
                with tab_preview:
                    st.dataframe(execute_safe_query(f"SELECT * FROM {t} LIMIT 5"), hide_index=True, use_container_width=True)
                
                with tab_action:
                    st.warning("⚠️ 此操作将直接从底层 DuckDB 中抹除该表及其所有数据。")
                    if st.button(f"🗑️ 彻底删除数据表 [{t}]", key=f"del_btn_{t}"):
                        execute_write(f"DROP TABLE {t}")
                        invalidate_schema_cache()  
                        st.session_state.pop(f"summary_loaded_{t}", None)
                        st.session_state.data_profile_cache = ""
                        st.rerun()
        except Exception as e: 
            st.error(f"加载表 {t} 失败：{e}")