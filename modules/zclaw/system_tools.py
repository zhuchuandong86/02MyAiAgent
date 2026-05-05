# modules/zclaw/system_tools.py
import os
import subprocess
import streamlit as st
import core.paths
import time


def get_user_workspace() -> str:
    user = st.session_state.get("zclaw_user", "public")
    return os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"zclaw_workspace_{user}")


# ══════════════════════════════════════════════════════════════
# § 1  基础沙箱工具
# ══════════════════════════════════════════════════════════════

def download_file(url: str, filename: str) -> str:
    """从 URL 下载二进制文件，自动重试 3 次。"""
    workspace   = get_user_workspace()
    target_path = os.path.join(workspace, filename)

    import urllib.parse
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    proxy_host = os.getenv("PROXY_HOST")
    proxies    = None
    if proxy_host:
        proxy_user = os.getenv("PROXY_USER")
        proxy_pass = os.getenv("PROXY_PASS")
        if proxy_user and proxy_pass:
            pu = urllib.parse.quote(proxy_user, safe="")
            pp = urllib.parse.quote(proxy_pass, safe="")
            proxy_url = f"http://{pu}:{pp}@{proxy_host.replace('http://', '')}"
        else:
            proxy_url = f"http://{proxy_host.replace('http://', '')}"
        proxies = {"http": proxy_url, "https": proxy_url}

    for attempt in range(3):
        try:
            resp = requests.get(url, proxies=proxies, verify=False, timeout=60, stream=True)
            resp.raise_for_status()
            with open(target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return f"✅ 下载完成: {filename}"
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
                continue
            return f"❌ 下载失败（3 次重试）: {e}"


def execute_bash(command: str, cwd: str = "") -> str:
    """
    执行 Shell 命令。cwd 不填默认在用户沙箱；填绝对路径可切换工作目录（用于 Skill 脚本目录）。
    stdout 和 stderr 都会返回，不丢弃任何输出。
    """
    workspace = get_user_workspace()
    run_dir   = cwd.strip() if cwd.strip() else workspace
    if not os.path.isdir(run_dir):
        return f"❌ 工作目录不存在: {run_dir}"
        
    # 定义智能解码器：优先尝试 UTF-8，失败则退回 Windows 默认的 GBK
    def smart_decode(byte_data):
        if not byte_data:
            return ""
        try:
            return byte_data.decode("utf-8")
        except UnicodeDecodeError:
            return byte_data.decode("gbk", errors="replace")

    try:
        # ⚠️ 修改点：移除 text=True 和 encoding="utf-8"，使其返回原始 bytes
        result = subprocess.run(
            command, shell=True, cwd=run_dir,
            capture_output=True, timeout=120,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        
        # 使用智能解码处理输出
        stdout = smart_decode(result.stdout).strip()
        stderr = smart_decode(result.stderr).strip()
        
        parts  = []
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"[stderr]\n{stderr}")
        if not parts:
            parts.append(f"✅ 无输出 (exit={result.returncode}, cwd={run_dir})")
            
        return "\n".join(parts)
        
    except subprocess.TimeoutExpired:
        return "❌ 执行超时（120s）"
    except Exception as e:
        return f"❌ 执行异常: {e}"

        

def read_file(filepath: str) -> str:
    """
    读取文本文件。支持绝对路径（直接读）和相对路径（相对沙箱）。
    不存在时返回沙箱目录清单。
    """
    workspace = get_user_workspace()
    target    = filepath if os.path.isabs(filepath) else os.path.join(workspace, filepath)
    if not os.path.exists(target):
        return f"❌ 文件不存在: {target}\n沙箱现有文件: {os.listdir(workspace)}"
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return (content[:5000] + "\n...[已截断]") if len(content) > 5000 else content
    except Exception as e:
        return f"❌ 读取失败: {e}"


def write_file(filepath: str, content: str) -> str:
    """在沙箱内写入纯文本文件（.py, .txt, .csv 等）。严禁用于写入二进制文件（docx/pdf）。"""
    workspace = get_user_workspace()
    target    = os.path.join(workspace, filepath)
    try:
        os.makedirs(os.path.dirname(target) if os.path.dirname(target) else workspace, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✅ 文件写入成功: {filepath}（{len(content)} 字符）"
    except Exception as e:
        return f"❌ 写入失败: {e}"


# ══════════════════════════════════════════════════════════════
# § 2  B 轨技能指南读取
#
# 约定：modules/zclaw/skills/<名称>/SKILL.md
#       可选：scripts/ 子目录存放可执行脚本
# ══════════════════════════════════════════════════════════════

def _get_skills_root() -> str:
    return os.path.join(os.getcwd(), "modules", "zclaw", "skills")


def invoke_skill_guide(skill_name: str) -> str:
    """
    读取 SKILL.md 操作手册，并强制寻找 .py 脚本，生成带 cd 的绝对路径执行命令。
    """
    if skill_name.strip().lower() in ("list", "ls", ""):
        return _list_skill_guides()

    # 1. 扫描全局目录和用户私有目录
    global_skills = os.path.join(os.getcwd(), "modules", "zclaw", "skills")
    user_skills = os.path.join(get_user_workspace(), "skills")
    
    # 兼容中划线和下划线的误差
    search_names = [skill_name, skill_name.replace("-", "_"), skill_name.replace("_", "-")]
    
    skill_path = None
    for root_dir in [global_skills, user_skills]:
        for name in search_names:
            p = os.path.join(root_dir, name)
            if os.path.isdir(p):
                skill_path = p
                break
        if skill_path:
            break
            
    if not skill_path:
        return f"❌ 找不到技能目录 [{skill_name}]。请检查拼写或使用 /list 确认。\n{_list_skill_guides()}"

    # 2. 读取 SKILL.md
    guide_text = ""
    for fname in ("SKILL.md", "README.md"):
        guide_path = os.path.join(skill_path, fname)
        if os.path.exists(guide_path):
            with open(guide_path, "r", encoding="utf-8") as f:
                guide_text = f.read()[:5000]
            break

    if not guide_text:
        guide_text = "（当前技能没有提供 SKILL.md 指南，请直接使用下方提供的脚本）"

    # 3. 暴搜该技能文件夹下所有的 .py 脚本
    script_files = []
    for root, _, files in os.walk(skill_path):
        for fname in files:
            if fname.endswith(".py") and not fname.startswith("__"):
                full_path = os.path.join(root, fname)
                full_path = full_path.replace("\\", "/") # 统一正斜杠防转义Bug
                dir_path = os.path.dirname(full_path)
                
                # 🌟 核心杀招：直接帮大模型把 cd 目录和运行命令拼好！
                cmd = f"cd \"{dir_path}\" && python {fname}"
                script_files.append(f"  ✔️ {cmd}")

    scripts_info = ""
    if script_files:
        scripts_info = (
            "\n\n🛠️ 【系统强制执行约束】以下是该技能内的物理脚本路径：\n"
            "⚠️ 大模型请注意：你必须调用 `execute_bash` 工具，并**直接复制下方带 cd 的完整命令**去执行！严禁自行猜测路径或省略 cd！\n"
        ) + "\n".join(script_files)

    return f"📖 [{skill_name}] 技能手册:\n{guide_text}{scripts_info}"

def _list_skill_guides() -> str:
    """列出所有含 SKILL.md 的技能文件夹"""
    global_skills = os.path.join(os.getcwd(), "modules", "zclaw", "skills")
    user_skills = os.path.join(get_user_workspace(), "skills")
    
    guides = []
    for root_dir in [global_skills, user_skills]:
        if os.path.isdir(root_dir):
            for d in sorted(os.listdir(root_dir)):
                if os.path.isdir(os.path.join(root_dir, d)) and os.path.exists(os.path.join(root_dir, d, "SKILL.md")):
                    prefix = "系统全局" if "modules" in root_dir else "用户沙箱"
                    guides.append(f"  📦 {d} ({prefix})")
                    
    if not guides:
        return "（未找到任何含 SKILL.md 的技能文件夹）"
    return "可用指南技能库:\n" + "\n".join(guides)

# ── Schema ────────────────────────────────────────────────────

SCHEMA = [
    {
        "name": "download_file",
        "description": "下载二进制文件（PDF/Zip/图片等）到沙箱，支持代理和自动重试。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url":      {"type": "string", "description": "完整下载链接，含 https://"},
                "filename": {"type": "string", "description": "保存到沙箱的文件名"},
            },
            "required": ["url", "filename"],
        },
    },
    {
        "name": "execute_bash",
        "description": (
            "执行 Shell 命令。"
            "cwd 不填默认在沙箱；填 Skill 脚本的绝对路径可直接在该目录执行（无需 cd &&）。"
            "stdout 和 stderr 都会返回。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell 命令"},
                "cwd":     {"type": "string", "description": "可选：工作目录绝对路径，如 Skill 脚本所在目录"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "读取沙箱内的文本文件内容。文件不存在时自动返回目录清单。",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "相对于沙箱根目录的文件路径"}
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "write_file",
        "description": "在沙箱内写入纯文本文件（.py/.txt/.csv/.json 等）。严禁写入 docx/pdf 等二进制文件。",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "相对于沙箱根目录的文件路径"},
                "content":  {"type": "string", "description": "要写入的完整文件内容"},
            },
            "required": ["filepath", "content"],
        },
    },
    {
        "name": "invoke_skill_guide",
        "description": (
            "读取 B 轨技能的 SKILL.md 操作手册。"
            "处理 PDF/Word/Excel/PPT 等专业任务前必须先调用，获取最佳实践和脚本路径。"
            "传入 'list' 查看所有可用 B 轨技能名称。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "B 轨技能名称（如 pdf/pptx/docx/xlsx），传 list 查看全部可用技能",
                }
            },
            "required": ["skill_name"],
        },
    },
]