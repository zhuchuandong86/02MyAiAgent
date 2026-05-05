import os
import re
import duckdb
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "telecom_data.duckdb")

def clean_percentage_columns(df, file_name):
    """
    【核心清洗逻辑】：自动探测并转换百分比/比率字段
    """
    cleaned_cols = []
    for col in df.columns:
        # 如果列名中包含 "率" 或 "%"
        if '率' in col or '%' in col:
            # 只有当它是字符串类型时才需要清洗（防止已经是数字的列被误操作）
            if df[col].dtype == 'object':
                # 1. 强制转为字符串，并剔除所有的 '%' 符号
                cleaned_series = df[col].astype(str).str.replace('%', '', regex=False)
                
                # 2. 将空字符串或常见的 pandas 空值占位符替换为真正的 NaN
                cleaned_series = cleaned_series.replace(['nan', 'NaN', 'None', 'null', ''], np.nan)
                
                # 3. 强制转换为浮点数 (例如 "98.5%" -> 98.5)
                df[col] = pd.to_numeric(cleaned_series, errors='coerce')
                cleaned_cols.append(col)
                
    if cleaned_cols:
        print(f"   🧹 已自动格式化 {len(cleaned_cols)} 个比率字段: {', '.join(cleaned_cols)}")
        
    return df

def build_database():
    data_dir = os.path.join(BASE_DIR, "data")
    
    if not os.path.exists(data_dir):
        print(f"❌ 错误: 找不到数据目录 -> {data_dir}")
        return

    print(f"🔄 正在连接数据库: {DB_PATH}")
    con = duckdb.connect(DB_PATH)
    
    print(f"📡 正在扫描并装载数据源: {data_dir}")
    for file_name in os.listdir(data_dir):
        if file_name.startswith('~$') or not file_name.endswith(('.csv', '.xlsx', '.xls')):
            continue
            
        file_path = os.path.join(data_dir, file_name)
        table_name = re.sub(r'[^\w]', '_', os.path.splitext(file_name)[0]).lower()
        
        print(f"\n⏳ 正在处理: {file_name} -> 表名: {table_name} ...")
        try:
            # 1. 统一使用 Pandas 读取数据（为了能够进行精细化的字段清洗）
            if file_name.endswith('.csv'):
                # 增加对中文 Windows 常见 GBK 编码的防呆兼容
                try:
                    df = pd.read_csv(file_path, encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(file_path, encoding='gbk')
            else:
                df = pd.read_excel(file_path)

            # 2. 触发数据清洗管道
            df = clean_percentage_columns(df, file_name)
            
            # 3. 写入 DuckDB 数据库
            con.execute(f"DROP TABLE IF EXISTS {table_name}")
            con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df")
                
            print(f"✅ 成功入库: {table_name} (共 {len(df)} 行)")
            
        except Exception as e:
            print(f"❌ 失败 {file_name}: {e}")
            
    print("\n🧹 正在优化数据库...")
    con.execute("VACUUM")
    con.close()
    print("🎉 数据库全量构建完成！请启动前端应用进行查询。")

if __name__ == "__main__":
    build_database()