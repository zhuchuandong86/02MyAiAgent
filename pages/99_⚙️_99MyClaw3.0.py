"""
claw.py — Claw Agent OS  v2.0
启动：streamlit run claw.py

架构分层（从下到上，不互相越界）：
  § 1  Config      单一配置源：模型 / 路径 / 代理
  § 2  Proxy       代理注入，启动时写入 os.environ，全局生效
  § 3  Shell       通用 Shell 执行引擎（编码自适应，超时，cwd）
  § 4  Scheduler   定时任务引擎（APScheduler 单例，全局外置执行器）
  § 5  Memory      经验记忆（JSONL，Jaccard 去重，频次检索）
  § 6  SkillOS     Skill 扫描 / 路由 / 加载（两步懒加载）
  § 7  LLM         模型调用 + 消息裁剪
  § 8  Prompts     System prompt 构建（最小基础 + Skill 注入）
  § 9  UI          Streamlit 界面（侧栏 + 主区）
  § 10 Router      意图识别（定时 → Skill → 直接执行）
  § 11 Executor    执行循环（CoT 折叠 + 颜色分层输出）
"""

import os, re, sys, json, time, subprocess, yaml
import streamlit as st
from datetime import datetime
from openai import OpenAI
from core.settings import settings
os.environ['NO_PROXY'] = getattr(settings, "INTERNAL_URL", "")

# ══════════════════════════════════════════════════════════════════════════════
# § 1  Config — 单一配置源
# ══════════════════════════════════════════════════════════════════════════════

from core.llm_factory import get_openai_client
_CLIENT = get_openai_client()
_MODEL  = getattr(settings, "MODEL_CLAW",
            getattr(settings, "MODEL_TEXT", "qwen2.5-72b-instruct"))

_HERE       = os.path.dirname(os.path.abspath(__file__))
AGENT_ROOT  = os.path.dirname(_HERE)
SKILL_ROOT  = os.path.join(AGENT_ROOT, "skills")
WS_ROOT     = os.path.join(AGENT_ROOT, "workspace")
os.makedirs(WS_ROOT,   exist_ok=True)
os.makedirs(SKILL_ROOT, exist_ok=True)

# ── Proxy ─────────────────────────────────────────────────────────────────────
def _build_proxy_url() -> str:
    try:
        import urllib.parse as _up
        ph = getattr(settings, "PROXY_HOST", "").strip()
        pu = getattr(settings, "PROXY_USER", "").strip()
        pp = getattr(settings, "PROXY_PASS", "").strip()
        if ph:
            cred = f"{_up.quote(pu,safe='')}:{_up.quote(pp,safe='')}@" if (pu and pp) else ""
            host = ph.replace("http://","").replace("https://","")
            return f"http://{cred}{host}"
    except Exception:
        pass
    return os.environ.get("HTTP_PROXY", os.environ.get("http_proxy", ""))

PROXY_URL = _build_proxy_url()

# ══════════════════════════════════════════════════════════════════════════════
# § 2  Proxy — 启动时注入
# ══════════════════════════════════════════════════════════════════════════════

def _inject_proxy():
    if not PROXY_URL:
        return
    for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"):
        os.environ[k] = PROXY_URL
    no_proxy = "localhost,127.0.0.1,::1"
    os.environ.setdefault("NO_PROXY", no_proxy)
    os.environ.setdefault("no_proxy", no_proxy)

_inject_proxy()

def proxy_label() -> str:
    if not PROXY_URL:
        return "🔴 无代理（直连）"
    masked = re.sub(r":([^:@/]{3,})@", ":***@", PROXY_URL)
    return f"🌐 代理 `{masked}`"

# ══════════════════════════════════════════════════════════════════════════════
# § 3  Shell — 通用执行引擎
# ══════════════════════════════════════════════════════════════════════════════

def _decode(b: bytes) -> str:
    """🌟 修复1：字节流解码 - 强制优先 UTF-8，防止 GBK 误认导致的火星文乱码"""
    import locale
    sys_enc = locale.getpreferredencoding(False) or "utf-8"
    # 必须把 utf-8 放在 dict 的第一个位置优先尝试！
    for enc in dict.fromkeys(["utf-8", sys_enc, "gbk", "latin-1"]):
        try: return b.decode(enc)
        except: pass
    return b.decode("latin-1", errors="replace")

def shell(command: str, cwd: str = "") -> str:
    run_dir = cwd.strip() if cwd.strip() else get_workspace()
    if not os.path.isdir(run_dir):
        return f"❌ 目录不存在: {run_dir}"
    try:
        r = subprocess.run(
            command, shell=True, cwd=run_dir,
            capture_output=True, timeout=120,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        out = _decode(r.stdout).strip()
        err = _decode(r.stderr).strip()
        parts = []
        if out: parts.append(out)
        if err: parts.append(f"[stderr]\n{err}")
        return "\n".join(parts) or f"✅ 完成 (exit={r.returncode})"
    except subprocess.TimeoutExpired:
        return "❌ 超时（120s）"
    except Exception as e:
        return f"❌ 异常: {e}"

# ══════════════════════════════════════════════════════════════════════════════
# § 4  Scheduler — 定时任务引擎（🌟 终极监控护航版）
# ══════════════════════════════════════════════════════════════════════════════

def _scheduler_run_task(cmd: str, run_dir: str, log_file: str, task_id: str):
    import os
    import subprocess
    import locale
    import traceback
    from datetime import datetime

    def _local_decode(b: bytes) -> str:
        sys_enc = locale.getpreferredencoding(False) or "utf-8"
        for enc in dict.fromkeys(["utf-8", sys_enc, "gbk", "latin-1"]):
            try: return b.decode(enc)
            except: pass
        return b.decode("latin-1", errors="replace")

    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[{ts}][{task_id}] 🚀 触发后台执行: {cmd}\n")
        
        r = subprocess.run(
            cmd, shell=True, cwd=run_dir,
            capture_output=True, timeout=120,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        out = _local_decode(r.stdout).strip()
        err = _local_decode(r.stderr).strip()
        res = "\n".join(filter(None, [out, f"[stderr]\n{err}" if err else ""])) or f"✅ 成功 (exit={r.returncode})"
        
        ts2 = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts2}][{task_id}] 🏁 执行完成:\n{res}\n")
    except Exception as e:
        ts3 = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts3}][{task_id}] ❌ 执行异常: {e}\n{traceback.format_exc()}\n")


@st.cache_resource
def get_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    import logging
    
    # 🌟 开启控制台强制日志：在运行 streamlit 的黑色 CMD/终端框里实时播报！
    logger = logging.getLogger('apscheduler')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[APScheduler引擎] %(asctime)s - %(message)s'))
        logger.addHandler(handler)

    # 🌟 去掉时区硬编码，完全信任你本地电脑的系统时间！
    job_defaults = {
        'coalesce': True,
        'max_instances': 1,
        'misfire_grace_time': None  # 🌟 设为 None：永不过期，哪怕系统卡了，事后也会立刻补跑！
    }
    s = BackgroundScheduler(job_defaults=job_defaults)
    s.start()
    return s


def manage_scheduler(action: str, task_id: str,
                     command: str = "", cron_expr: str = "",
                     cwd: str = "") -> str:
    try:
        sch = get_scheduler()
        # 🌟 物理保活：如果检测到线程死掉，当场救活
        if sch.state == 0:
            sch.start()
    except Exception as e:
        return f"❌ 定时引擎未启动: {e}"

    log_file = os.path.join(get_workspace(), "scheduler.log")
    run_dir  = cwd.strip() if cwd.strip() else get_workspace()

    if action == "list":
        jobs = sch.get_jobs()
        return "当前无定时任务" if not jobs else \
               "定时任务：\n" + "\n".join(f"  [{j.id}] 下次: {j.next_run_time}" for j in jobs)

    if action == "remove":
        if sch.get_job(task_id):
            sch.remove_job(task_id)
            return f"✅ 任务 [{task_id}] 已移除"
        return f"❌ 未找到 [{task_id}]"

    if action == "add":
        if sch.get_job(task_id):
            sch.remove_job(task_id)

        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return "❌ cron 需5段：分 时 日 月 周，例如 '*/2 * * * *'"
        minute, hour, day, month, dow = parts

        try:
            sch.add_job(_scheduler_run_task, "cron",
                        minute=minute, hour=hour, day=day,
                        month=month, day_of_week=dow,
                        args=[command, run_dir, log_file, task_id],
                        id=task_id, 
                        replace_existing=True,
                        misfire_grace_time=None) # 永不过期

            return (f"✅ 定时任务 [{task_id}] 已挂载\n"
                    f"  Cron = {cron_expr}\n"
                    f"  命令 = {command}\n"
                    f"  日志 = {log_file}")
        except Exception as e:
            return f"❌ 添加失败: {e}"

    return f"❌ 未知 action: {action}"

# ══════════════════════════════════════════════════════════════════════════════
# § 5  Memory — 经验记忆
# ══════════════════════════════════════════════════════════════════════════════

def get_workspace() -> str:
    user = st.session_state.get("claw_user", "public")
    p    = os.path.join(WS_ROOT, f"ws_{user}")
    os.makedirs(p, exist_ok=True)
    return p

def _mem_path() -> str:
    return os.path.join(get_workspace(), "memory.jsonl")

def _load_mem() -> list[dict]:
    p = _mem_path()
    if not os.path.exists(p): return []
    out = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try: out.append(json.loads(line))
                except: pass
    return out

def _save_mem(records: list[dict]):
    with open(_mem_path(), "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def _jaccard(a: str, b: str) -> float:
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb: return 0.0
    return len(wa & wb) / len(wa | wb)

def mem_save(lesson: str) -> str:
    lesson  = lesson.strip()
    records = _load_mem()
    for r in records:
        if r["lesson"] == lesson: return "已有完全相同经验，跳过"
        if len(lesson.split()) > 4 and _jaccard(r["lesson"], lesson) > 0.7:
            return f"已有相似经验，跳过：{r['lesson'][:60]}"
    records.append({"lesson": lesson, "ts": datetime.now().isoformat(), "hits": 0})
    _save_mem(records)
    return f"✅ 经验写入：{lesson[:80]}"

def mem_search(query: str, top_k: int = 6) -> str:
    records = _load_mem()
    if not records: return ""
    qw = set(query.lower().split())
    scored = sorted(records,
                    key=lambda r: len(qw & set(r["lesson"].lower().split()))
                                  + r.get("hits", 0) * 0.1,
                    reverse=True)
    top = scored[:top_k]
    top_lessons = {r["lesson"] for r in top}
    for r in records:
        if r["lesson"] in top_lessons:
            r["hits"] = r.get("hits", 0) + 1
    _save_mem(records)
    return "\n".join(f"- {r['lesson']}" for r in top if r in scored[:top_k])

# ══════════════════════════════════════════════════════════════════════════════
# § 6  SkillOS — Skill 扫描 / 路由 / 加载
# ══════════════════════════════════════════════════════════════════════════════

def _read_frontmatter(skill_dir: str) -> dict:
    md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(md): return {}
    try:
        with open(md, encoding="utf-8", errors="replace") as f:
            text = f.read()
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        return yaml.safe_load(m.group(1)) or {} if m else {}
    except: return {}

def _read_body(skill_dir: str) -> str:
    md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(md): return ""
    with open(md, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return re.sub(r"^---.*?---\s*\n", "", text, flags=re.DOTALL).strip()

def _list_scripts(skill_dir: str) -> list[str]:
    sd = os.path.join(skill_dir, "scripts")
    if not os.path.isdir(sd): return []
    result = []
    for root, _, files in os.walk(sd):
        for f in sorted(files):
            if not f.startswith(".") and not f.endswith(".pyc"):
                result.append(os.path.join(root, f))
    return result

@st.cache_data(ttl=30)
def skill_index() -> dict[str, dict]:
    idx = {}
    if not os.path.isdir(SKILL_ROOT): return idx
    for item in sorted(os.listdir(SKILL_ROOT)):
        sd = os.path.join(SKILL_ROOT, item)
        if not os.path.isdir(sd): continue
        if not os.path.exists(os.path.join(sd, "SKILL.md")): continue
        fm = _read_frontmatter(sd)
        idx[item] = {
            "name":        fm.get("name", item),
            "description": fm.get("description", ""),
            "triggers":    fm.get("triggers", []),
            "path":        sd,
        }
    return idx

def skill_load(slug: str, idx: dict) -> tuple[str, list[str]]:
    if slug not in idx: return "", []
    sd      = idx[slug]["path"]
    body    = _read_body(sd)
    scripts = _list_scripts(sd)
    return body, scripts

def _kw_split(text: str) -> list[str]:
    parts = re.split(r"[\s，。、；：:,.;！!？?\u3000]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 2]

def route_skill(task: str, idx: dict) -> str | None:
    tl = task.lower()
    for slug, info in idx.items():
        if slug.lower() in tl: return slug
        for t in info.get("triggers", []):
            if str(t).lower() in tl: return slug
        name = info.get("name", "").lower()
        if len(name) >= 2 and name in tl: return slug
        for kw in _kw_split(info.get("description", "")):
            if kw.lower() in tl: return slug
    return None

def format_skill_list(idx: dict) -> str:
    if not idx:
        return (f"### 🧩 暂无 Skill\n\n"
                f"将 Skill 文件夹放入 `{SKILL_ROOT}/` 即可加载。\n\n"
                "**目录结构：**\n```\nskills/<slug>/\n  SKILL.md\n  scripts/\n```")
    lines = ["### 🧩 已加载 Skills\n"]
    for slug, info in idx.items():
        scripts = _list_scripts(info["path"])
        hint = f"（{len(scripts)} 个脚本）" if scripts else ""
        lines.append(f"- **`/{slug}`** — {info['name']} {hint}\n  {info['description'][:60]}")
    lines.append(f"\n📂 `{SKILL_ROOT}`\n用法：`/slug 任务` 直接激活，或描述任务自动路由")
    return "\n".join(lines)

# ══════════════════════════════════════════════════════════════════════════════
# § 7  LLM — 调用 + 消息裁剪
# ══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": (
                "执行 Shell/Terminal 命令——Claw 与系统交互的唯一方式。\n"
                "内置能力不足时：自己把脚本写到工作区文件，再用 shell 执行。\n"
                "代理已由系统自动注入环境变量，网络访问无需手动配置。\n"
                "cwd：工作目录（不填=默认用户工作区）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell 命令"},
                    "cwd":     {"type": "string", "description": "工作目录（可选）"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_scheduler",
            "description": (
                "管理定时后台任务（cron 格式）。\n"
                "后台输出会自动写入工作区的 scheduler.log 文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action":    {"type": "string", "enum": ["add","remove","list"]},
                    "task_id":   {"type": "string", "description": "任务唯一英文标识"},
                    "command":   {"type": "string", "description": "要执行的命令（add 时必填）"},
                    "cron_expr": {"type": "string", "description": "5段标准 Linux cron 表达式。例如每天上午9点: '0 9 * * *'，每隔5分钟: '*/5 * * * *'"},
                    "cwd":       {"type": "string", "description": "执行目录（可选）"},
                },
                "required": ["action", "task_id"],
            },
        },
    },
]

TOOL_MAP = {"shell": shell, "manage_scheduler": manage_scheduler}

def llm_call(messages: list, force_tool: bool = False, max_retries: int = 5):
    """
    调用 LLM (增强版：自带 429 限流重试与自动降级)
    """
    kwargs = {"model": _MODEL, "messages": messages, "temperature": 0.2, "tools": TOOLS}
    if force_tool: 
        kwargs["tool_choice"] = "required"
        
    for attempt in range(max_retries):
        try:
            resp = _CLIENT.chat.completions.create(**kwargs)
            return resp.choices[0].message
        except Exception as e:
            err_str = str(e)
            
            # 1. 拦截 429 限流 / 服务器繁忙错误
            if any(k in err_str for k in ["429", "RateLimit", "服务器繁忙", "throttling"]):
                if attempt < max_retries - 1:
                    # 指数退避：等待 3秒, 6秒, 12秒, 24秒...
                    wait_time = 3 * (2 ** attempt) 
                    st.toast(f"⏳ 节点拥挤 (429)，系统将在 {wait_time} 秒后自动重试 ({attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue # 继续下一次循环重试
                else:
                    st.error("🚨 API 节点持续拥挤，已耗尽最大重试次数。")
                    raise e
            
            # 2. 拦截不兼容 tool_choice 的错误（降级处理）
            if "tool_choice" in err_str or "Invalid" in err_str:
                kwargs.pop("tool_choice", None)
                # 降级后再试一次
                try:
                    resp = _CLIENT.chat.completions.create(**kwargs)
                    return resp.choices[0].message
                except Exception as inner_e:
                    raise inner_e
            
            # 其他未知错误，直接抛出，让外层的 Executor 红色面板捕获
            raise e

def trim_messages(msgs: list, keep: int = 40) -> list:
    if len(msgs) <= keep + 1: return msgs
    head = msgs[0]
    tail = msgs[-keep:]
    while tail and getattr(tail[0], "role", None) == "tool":
        tail.pop(0)
    return [head] + tail

# ══════════════════════════════════════════════════════════════════════════════
# § 8  Prompts — System prompt 构建
# ══════════════════════════════════════════════════════════════════════════════

_SEARCH_GUIDE = """\
## 上网搜索（必须两步走，禁止 pipe+python -c 单行）
代理已自动注入环境变量，所有脚本和 curl 都无需手动配置。

两步流程：
  第1步：写搜索脚本到工作区
    内容模板（复制修改）：
      import urllib.request, urllib.parse, re, sys, os
      proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
      handlers = [urllib.request.ProxyHandler({"http":proxy,"https":proxy})] if proxy else []
      opener = urllib.request.build_opener(*handlers)
      q = " ".join(sys.argv[1:])
      url = "https://www.bing.com/search?q=" + urllib.parse.quote(q)
      req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
      html = opener.open(req, timeout=20).read().decode("utf-8","replace")
      print(re.sub(r"<[^>]+>", " ", html)[:3000])
  第2步：shell(command="python s.py 查询词", cwd=工作区路径)

curl 备用（环境变量自动生效）：
  curl -s -L -A "Mozilla/5.0" --ssl-no-revoke "https://www.bing.com/search?q=关键词"
"""

def build_system_prompt(ws: str, skill_body: str = "",
                        skill_name: str = "", skill_scripts: list = None) -> str:
    exp      = mem_search("", top_k=5)
    exp_blk  = f"\n\n## 历史经验\n{exp}" if exp else ""
    scr_blk  = ""
    if skill_scripts:
        scr_blk = ("\n\n## Skill 脚本（完整路径，直接使用，禁止猜路径）\n"
                   + "\n".join(f"  {s}" for s in skill_scripts))

    base = f"""你是 Claw，一个极简但自主演进的 AI Agent。

## 环境
- 工作区：{ws}
- 代理：{"已配置（" + re.sub(r":([^:@/]{{3,}})@","：***@",PROXY_URL) + "）" if PROXY_URL else "无（直连）"}

## 核心工具
只有两个工具：shell（立即执行）和 manage_scheduler（定时任务）。
这已经足够——你可以用 Shell 写任何脚本、安装任何库、做任何事。

## 演进原则
1. 执行优先：需要信息或操作，必须调用 shell 执行，禁止凭记忆回答
2. 自主写脚本：内置能力不足时，写脚本文件到工作区再执行
3. 报错自愈：读 stderr → 分析 → 修正 → 重试；同一问题连续2次失败则换思路
4. 经验沉淀：任务完成后写经验到 memory.jsonl（用 Python 写，禁止 echo）
   命令：python -c "import json; f=open(r'{ws}/memory.jsonl','a',encoding='utf-8'); f.write(json.dumps({{'lesson':'经验内容'}},ensure_ascii=False)+'\\n')"
5. 路径铁律：所有文件读写必须用绝对路径；Skill 脚本在 scripts/ 子目录里

{_SEARCH_GUIDE}{exp_blk}"""

    if skill_body:
        return (
            f"{base}\n\n## ⚡ 激活 Skill：{skill_name}\n\n"
            f"{skill_body}{scr_blk}\n\n---\n严格按 Skill 手册执行。"
        )
    return base

# ══════════════════════════════════════════════════════════════════════════════
# § 9  UI — Streamlit 界面 (美观度史诗级大修)
# ══════════════════════════════════════════════════════════════════════════════

CSS = """<style>
/* 优雅的思考链卡片 */
.cl-think { 
    border-left: 4px solid #8B5CF6; padding: 12px 16px; margin: 8px 0 12px 0;
    background: #F5F3FF; border-radius: 4px 8px 8px 4px; font-size: 14px;
    color: #4C1D95; box-shadow: 0 1px 3px rgba(0,0,0,0.06); line-height: 1.6;
}
/* 清爽的代码指令框 */
.cl-cmd { 
    border-left: 4px solid #F59E0B; padding: 12px 16px; margin: 8px 0;
    background: #FFFBEB; border-radius: 4px 8px 8px 4px;
    font-family: 'Fira Code', Consolas, monospace; font-size: 13px;
    color: #92400E; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
/* 暗黑仿终端结果展示框（自动滚动，绝不撑爆屏幕） */
.cl-res {
    background: #1E1E1E; color: #D4D4D4; border-radius: 6px;
    padding: 12px 16px; font-family: 'Fira Code', Consolas, monospace; font-size: 13px;
    max-height: 350px; overflow-y: auto; margin: 4px 0 16px 0;
    border: 1px solid #333; line-height: 1.5; white-space: pre-wrap;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.2);
}
/* 定制滚动条 */
.cl-res::-webkit-scrollbar { width: 8px; height: 8px; }
.cl-res::-webkit-scrollbar-track { background: #1E1E1E; border-radius: 4px; }
.cl-res::-webkit-scrollbar-thumb { background: #555; border-radius: 4px; }
.cl-res::-webkit-scrollbar-thumb:hover { background: #777; }

/* 报错高亮 */
.cl-err { 
    border-left: 4px solid #EF4444; padding: 12px 16px; margin: 8px 0;
    background: #FEF2F2; border-radius: 4px 8px 8px 4px; font-size: 14px;
    color: #991B1B; font-weight: 500;
}
/* 成功提示 */
.cl-done { 
    background: linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%);
    border-left: 4px solid #10B981; border-radius: 4px 8px 8px 4px;
    padding: 16px; margin: 16px 0; font-weight: 600; font-size: 15px;
    color: #065F46; box-shadow: 0 2px 5px rgba(0,0,0,0.08);
}
/* 技能挂载提示 */
.cl-skill { 
    border-left: 4px solid #3B82F6; padding: 12px 16px; margin: 8px 0;
    background: #EFF6FF; border-radius: 4px 8px 8px 4px; color: #1E40AF;
    font-weight: 500;
}
</style>"""

def md(html: str):
    st.markdown(html, unsafe_allow_html=True)

st.set_page_config(page_title="Claw", page_icon="🐾", layout="wide")

# ── 侧栏 ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🐾 Claw")

    if "claw_user" not in st.session_state:
        st.session_state.claw_user = "public"

    def on_user_change():
        for k in ("msgs", "history"): st.session_state.pop(k, None)

    st.text_input("账户", key="claw_user", on_change=on_user_change)

    ws = get_workspace()
    # st.caption(f"工作区：`{ws}`")
    # st.caption(f"Skill：`{SKILL_ROOT}`")
    st.caption(proxy_label())

    st.markdown("### 📂 上传文件")
    up = st.file_uploader("拖入文件", label_visibility="collapsed")
    if up:
        with open(os.path.join(ws, up.name), "wb") as f: f.write(up.getbuffer())
        st.success(f"✅ {up.name}")


    st.markdown("### ⏱️ 定时引擎控制台")
    try:
        sch  = get_scheduler()
        
        # 🌟 指示灯与时间核对
        state_map = {0: "🛑 已停止 (假死)", 1: "🟢 运行中", 2: "⏸️ 暂停"}
        sys_time = datetime.now().strftime('%m-%d %H:%M')
        st.caption(f"引擎: {state_map.get(sch.state, '未知')} | 系统: {sys_time}")

        # 🌟 刷新与重启双保险按钮
        col1, col2 = st.columns(2)
        with col1:
            if st.button("刷新"):
                st.rerun()
        with col2:
            if st.button("重启"):
                try: sch.shutdown(wait=False)
                except: pass
                st.cache_resource.clear()
                st.rerun()

        jobs = sch.get_jobs()
        if jobs:
            for j in jobs:
                nrt = j.next_run_time
                ts  = nrt.strftime("%m-%d %H:%M") if nrt else "待触发"
                st.code(f"[{j.id}]\n下次: {ts}")
        else:
            st.caption("无活跃任务")
    except Exception as _sch_err:
        st.error(f"Scheduler 异常：{_sch_err}")

    st.divider()
    if st.button("🧹 清空对话", use_container_width=True):
        for k in ("msgs","history"): st.session_state.pop(k, None)
        st.rerun()
    st.caption(f"模型：`{_MODEL}`")

    st.markdown("### 🧩 Skills")
    idx = skill_index()
    for slug, info in idx.items():
        if st.button(f"/{slug}", help=info["description"], use_container_width=True):
            st.session_state["_skill_btn"] = slug
            st.rerun()
    if not idx:
        st.caption(f"无 Skill，放入 `{SKILL_ROOT}/`")

# ── 主界面 ────────────────────────────────────────────────────────────────────
st.title("🐾 Claw Terminal")
md(CSS) # 注入自定义样式

ws = get_workspace()
if "msgs" not in st.session_state:
    st.session_state.msgs    = [{"role":"system","content":build_system_prompt(ws)}]
if "history" not in st.session_state:
    st.session_state.history = []

for m in st.session_state.history:
    if m["role"] == "think":
        logs = m.get("logs", [m["content"]])
        with st.expander(f"🧠 推演思考链路（共 {len(logs)} 轮）", expanded=False):
            for i, t in enumerate(logs, 1):
                md(f'<div class="cl-think"><b>🔍 第 {i} 轮推演</b><br><br>{t}</div>')
    else:
        with st.chat_message(m["role"]): st.markdown(m["content"])

st.caption("`/list` 查看 Skills · `/slug 任务` 激活 Skill · 直接输入任务")

# ── 输入 ────────────────────────────────────────────────────────────────────
if "_skill_btn" in st.session_state:
    prompt = "/" + st.session_state.pop("_skill_btn")
else:
    prompt = st.chat_input("输入任务…")

if not prompt: st.stop()
task = prompt.strip()

# ══════════════════════════════════════════════════════════════════════════════
# § 10  Router — 意图识别
# ══════════════════════════════════════════════════════════════════════════════

st.chat_message("user").markdown(task)
st.session_state.history.append({"role":"user","content":task})
idx = skill_index()

if task == "/list":
    resp = format_skill_list(idx)
    with st.chat_message("assistant"): st.markdown(resp)
    st.session_state.history.append({"role":"assistant","content":resp})
    st.stop()

active_slug    = None
active_body    = ""
active_scripts = []
user_task      = task

if task.startswith("/"):
    parts    = task.split(None, 1)
    slug_raw = parts[0][1:].strip()
    slug     = next((s for s in idx if s.lower() == slug_raw.lower()), slug_raw)
    if slug in idx:
        active_slug    = slug
        active_body, active_scripts = skill_load(slug, idx)
        user_task      = parts[1] if len(parts) > 1 else "请按 Skill 手册执行标准流程"
        with st.chat_message("assistant"):
            md(f'<div class="cl-skill">🧩 挂载指令：<b>{idx[slug]["name"]}</b> '
               f'（<code>/{slug}</code>）</div>')
            with st.expander("📖 查阅 Skill 手册", expanded=False):
                st.markdown(active_body)
    else:
        st.error(f"未找到 Skill `{slug}`，输入 `/list` 查看可用列表。")
        st.stop()
else:
    SCHEDULE_RE = re.compile(r"(每天|每日|每周|每小时|每隔|定时|定期|每(\d+)分钟?|早上|上午|下午|晚上|凌晨|[\d一二三四五六七八九十]+点(半)?)")
    is_schedule = bool(SCHEDULE_RE.search(task))
    if not is_schedule:
        matched = route_skill(task, idx)
        if matched:
            active_slug    = matched
            active_body, active_scripts = skill_load(matched, idx)
            with st.chat_message("assistant"):
                md(f'<div class="cl-skill">🧩 智能路由唤醒：'
                   f'<b>{idx[matched]["name"]}</b> (<code>/{matched}</code>)</div>')

# ══════════════════════════════════════════════════════════════════════════════
# § 11  Executor — 执行循环
# ══════════════════════════════════════════════════════════════════════════════

st.session_state.msgs[0] = {
    "role": "system",
    "content": build_system_prompt(ws, active_body, active_slug or "", active_scripts),
}

skill_ctx = ""
if active_slug:
    skill_ctx = (
        f"\n【Skill 路径】"
        f"\n  目录：{idx[active_slug]['path']}"
        f"\n  脚本（完整路径，直接用，禁止猜测）：\n"
        + "\n".join(f"    {s}" for s in active_scripts)
        if active_scripts else
        f"\n【Skill 目录】{idx[active_slug]['path']}（无 scripts/）"
    )

st.session_state.msgs.append({
    "role": "user",
    "content": (f"工作区：{ws}\n时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"
                f"{skill_ctx}\n\n【任务】{user_task}")
})


MAX_OUT    = 3000
PLAN_WORDS = ["让我","我来","我将","我会","首先","接下来","帮你",
              "创建","编写","搜索","查找","Let me","I will","I'll"]
spin       = st.empty()

think_logs: list[str] = []
think_ph = st.empty()

def _flush_think():
    if not think_logs: return
    with think_ph.container():
        with st.expander(f"🧠 推演思考链路（当前已运行 {len(think_logs)} 轮）", expanded=False):
            for i, t in enumerate(think_logs, 1):
                md(f'<div class="cl-think"><b>🔍 第 {i} 轮推演</b><br><br>{t}</div>')

def _msg_to_dict(msg) -> dict:
    """
    🌟 核心修复：处理 vLLM/DeepSeek 要求的 content 必须为 None 的问题
    """
    if isinstance(msg, dict):
        d = dict(msg)
        # 如果有工具调用，content 必须显式设为 None
        if d.get("tool_calls") and (d.get("content") == ""):
            d["content"] = None
        return d

    # 处理 OpenAI Message 对象
    has_tool_calls = bool(getattr(msg, "tool_calls", None))
    raw_content = msg.content
    
    # 逻辑：如果有工具调用且内容为空，强制设为 None；否则保留原内容或空串
    final_content = raw_content if raw_content else (None if has_tool_calls else "")

    d = {
        "role": msg.role,
        "content": final_content
    }

    if has_tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            } for tc in msg.tool_calls
        ]
    return d


for step in range(100):
    spin.markdown(f"⏳ **第 {step+1} 轮分析与推演中…**")

    msg  = llm_call(st.session_state.msgs, force_tool=(step < 2))
    text = msg.content or ""
    msg_dict = _msg_to_dict(msg)
    st.session_state.msgs = trim_messages(st.session_state.msgs + [msg_dict])

    tool_calls = getattr(msg, "tool_calls", None) or msg_dict.get("tool_calls")

    if text and tool_calls:
        spin.empty()
        think_logs.append(text[:2000])
        _flush_think()

    if not tool_calls:
        spin.empty()
        if step < 3 and text and any(w in text for w in PLAN_WORDS):
            think_logs.append(f"[安全拦截：防止光说不做] {text[:500]}")
            _flush_think()
            md('<div class="cl-err">⚠️ 监测到空洞承诺，强制转入行动…</div>')
            st.session_state.msgs.append({"role":"user", "content":"【强制】你说了要做但未调用工具！立刻调用 shell 执行，不要再解释。"})
            continue

        if text: think_logs.append(f"[终局总结] {text[:500]}")
        _flush_think()

        if think_logs:
            st.session_state.history.append({"role": "think", "content": "\n\n".join(think_logs), "logs": list(think_logs)})

        md('<div class="cl-done">✨ 任务圆满完成！</div>')
        if text:
            with st.chat_message("assistant"): st.markdown(text)
            st.session_state.history.append({"role":"assistant","content":text})

        st.session_state.msgs.append({"role":"user","content":"任务完成。将有价值的经验用 shell 写入 memory.jsonl，否则回复「无经验」。"})
        try:
            r = llm_call(st.session_state.msgs)
            r_calls = getattr(r, "tool_calls", None)
            if r_calls:
                for tc in r_calls:
                    try:
                        res = TOOL_MAP[tc.function.name](**json.loads(tc.function.arguments))
                        st.caption(f"🧠 新经验已触达记忆中枢: {str(res)[:60]}")
                    except: pass
        except: pass
        break

    # ── 工具执行渲染（美化升级） ──
    raw_calls = getattr(msg, "tool_calls", None) or []
    for tc in raw_calls:
        fname = tc.function.name
        try: args = json.loads(tc.function.arguments)
        except: args = {}

        cmd  = args.get("command", json.dumps(args, ensure_ascii=False))[:400]
        cwd_ = f"<br><small style='color:#A16207'>执行目录: {args['cwd']}</small>" if args.get("cwd") else ""
        safe = cmd.replace("<","&lt;").replace(">","&gt;")
        
        # 1. 渲染代码命令（橙色块）
        md(f'<div class="cl-cmd">🛠️ 调用核心引擎: <b>{fname}</b>{cwd_}<div style="margin-top:6px; font-weight:600;">$ {safe}</div></div>')

        result     = TOOL_MAP.get(fname, lambda **_: f"❌ 未注册工具: {fname}")(**args)
        result_str = str(result)

        is_err = any(k in result_str for k in ["❌","Error","Traceback","timed out","[stderr]"])
        if is_err: result_str += "\n\n【🚨 出错！分析原因，换方案重试。连续2次失败换思路。】"
        if len(result_str) > MAX_OUT:
            h = MAX_OUT // 2
            result_str = result_str[:h] + f"\n…\n…[日志过长，截断 {len(result_str)} 字符]…\n…\n" + result_str[-h:]

        if is_err: md('<div class="cl-err">🚨 底层执行阻断 (报错日志如下)</div>')
        
        # 2. 渲染执行结果（暗黑滚动终端替代 st.code）
        safe_res = result_str.replace("<","&lt;").replace(">","&gt;")
        md(f'<div class="cl-res">{safe_res}</div>')

        st.session_state.msgs.append({"role":"tool","tool_call_id":tc.id,"content":result_str})

    st.session_state.msgs = trim_messages(st.session_state.msgs)

else:
    _flush_think()
    md('<div class="cl-err">❌ 触碰 100 轮安全保护阀，强制熔断</div>')