# pages/00_💰_用量总览.py
import streamlit as st
import sqlite3
import pandas as pd
import core.paths

st.set_page_config(page_title="Token 用量中心", page_icon="💰", layout="wide")
st.title("💰 平台 API 调用与 Token 用量监控")
st.markdown("实时监控各应用的底层大模型消耗成本。")

DB_PATH = core.paths.get_db_path("token_usage.db")

try:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM token_logs", conn)
        
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # 1. 核心看板
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info(f"🚀 **总调用次数**\n### {len(df):,} 次")
        with col2:
            st.warning(f"🔋 **总消耗 Tokens**\n### {df['total_tokens'].sum():,} 个")
        with col3:
            # 假设按照 0.01元/千Token 的均价估算，你可以自行修改费率
            cost_estimate = (df['total_tokens'].sum() / 1000) * 0.01 
            st.success(f"💸 **折合预估成本**\n### ¥ {cost_estimate:.2f}")
            
        st.divider()
        
        # 2. 图表分析
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.markdown("##### 📊 各模型使用占比")
            model_usage = df.groupby('model_name')['total_tokens'].sum().reset_index()
            st.bar_chart(model_usage.set_index('model_name'))
            
        with col_chart2:
            st.markdown("##### 📈 每日消耗趋势")
            df['date'] = df['timestamp'].dt.date
            daily_usage = df.groupby('date')['total_tokens'].sum().reset_index()
            st.line_chart(daily_usage.set_index('date'))
        
        # 3. 详细明细流水
        st.markdown("##### 📜 详细调用账单流水")
        st.dataframe(df.sort_values('timestamp', ascending=False), use_container_width=True)
    else:
        st.info("💡 暂无 Token 消耗记录。请去运行一次【横评总结】应用，数据将立刻出现在这里！")
except Exception as e:
    st.error(f"无法读取数据库: {e}")