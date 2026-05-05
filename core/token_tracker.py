# core/token_tracker.py
import sqlite3
from datetime import datetime
import core.paths

# Token 账本存放在全局数据库目录
DB_PATH = core.paths.get_db_path("token_usage.db")

def setup_db():
    """初始化 Token 统计表（由 app.py 在启动时统一调用一次）"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS token_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    app_name TEXT,
                    model_name TEXT,
                    total_tokens INTEGER
                )
            ''')
    except Exception as e:
        print(f"⚠️ Token 账本数据库初始化失败: {e}")

def log_usage(app_name: str, model_name: str, total_tokens: int):
    """向账本写入一笔 Token 消耗记录"""
    if total_tokens and total_tokens > 0:
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn: # 增加 timeout 防止高并发时死锁
                conn.execute(
                    "INSERT INTO token_logs (timestamp, app_name, model_name, total_tokens) VALUES (?, ?, ?, ?)",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), app_name, model_name, int(total_tokens))
                )
        except Exception as e:
            print(f"⚠️ Token 账本记录写入失败: {e}")