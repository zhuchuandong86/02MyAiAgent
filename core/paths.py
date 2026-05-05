# core/paths.py
import sys
import os
from pathlib import Path

# 👇 【新增这两行】：彻底解决 Windows 下 Numpy/Pandas 的 OMP 冲突假死问题
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
# 1. 获取项目的绝对根目录 (AI_Platform)
# resolve() 获取绝对路径，parent.parent 退回到 AI_Platform 这一级
ROOT_DIR = Path(__file__).resolve().parent.parent

# 将根目录加入系统环境变量，这样任意层级的代码都能直接 import 其他模块！
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 2. 定义全局标准目录
GLOBAL_DATA_DIR = ROOT_DIR / "global_data"
DB_DIR = GLOBAL_DATA_DIR / "databases"        # 存放 .duckdb, .faiss 等
UPLOAD_DIR = GLOBAL_DATA_DIR / "user_uploads" # 存放用户上传和生成的图片、文档
CONFIG_DIR = ROOT_DIR / "config"              # 存放各类 yaml 配置文件

# 全局 .env 文件路径
ENV_FILE = ROOT_DIR / ".env"

# 3. 自动创建必备的文件夹（如果不存在的话）
DB_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# 4. 提供几个便捷获取路径的方法供其他模块调用
def get_db_path(db_name: str) -> str:
    """获取数据库文件的绝对路径"""
    return str(DB_DIR / db_name)

def get_upload_path(filename: str) -> str:
    """获取上传/下载文件的绝对路径"""
    return str(UPLOAD_DIR / filename)

def get_config_path(config_name: str) -> str:
    """获取配置文件的绝对路径"""
    return str(CONFIG_DIR / config_name)