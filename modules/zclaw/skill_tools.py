"""
skill_tools.py — 技能装载引擎 + 自成长核心

双轨技能说明：
  A 轨：skills/*.py → load_skill_functions() → TOOL_DISPATCHER → LLM 直接调用
  B 轨：skills/<名称>/SKILL.md → invoke_skill_guide() → 注入 prompt

list_skills() 同时展示两轨，用法一目了然。
install_new_tool() 是自成长核心，使用 get_openai_client 统一 LLM 调用入口。
"""

import os
import ast
import json
import inspect
import typing
import importlib.util
import streamlit as st
import core.paths
from core.settings import settings


# ══════════════════════════════════════════════════════════════
# § 1  路径
# ══════════════════════════════════════════════════════════════

def _user_skills_dir() -> str:
    user = st.session_state.get("zclaw_user", "public")
    p    = os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"zclaw_workspace_{user}", "skills")
    os.makedirs(p, exist_ok=True)
    return p


def _classic_skills_dir() -> str:
    p = os.path.join(os.getcwd(), "modules", "zclaw", "skills")
    os.makedirs(p, exist_ok=True)
    return p


# ══════════════════════════════════════════════════════════════
# § 2  动态装载引擎（A 轨：Python 可调用技能）
# ══════════════════════════════════════════════════════════════

def load_skill_functions() -> dict:
    """
    扫描 classic 和 applied 两个目录，加载所有 Python 可调用技能。
    只加载单文件(.py) 或 folder/folder.py 结构的技能。
    SKILL.md 类型的 B 轨指南技能由 invoke_skill_guide 处理，不在此加载。
    """
    funcs = {}
    dirs  = [("classic", _classic_skills_dir()), ("applied", _user_skills_dir())]

    for category, scan_dir in dirs:
        for item in sorted(os.listdir(scan_dir)):
            item_path  = os.path.join(scan_dir, item)
            skill_name = None
            entry_file = None

            if os.path.isfile(item_path) and item.endswith(".py") and not item.startswith("__"):
                skill_name = item[:-3]
                entry_file = item_path
            elif os.path.isdir(item_path) and not item.startswith("__"):
                # ⚠️ 有 SKILL.md 的目录是 B 轨，A 轨不碰它
                if os.path.exists(os.path.join(item_path, "SKILL.md")):
                    continue
                candidate = os.path.join(item_path, f"{item}.py")
                if os.path.exists(candidate):
                    skill_name = item
                    entry_file = candidate

            if not (skill_name and entry_file):
                continue

            try:
                spec = importlib.util.spec_from_file_location(skill_name, entry_file)
                mod  = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, skill_name) and callable(getattr(mod, skill_name)):
                    funcs[skill_name] = getattr(mod, skill_name)
            except Exception as e:
                print(f"⚠️ {category} 技能加载失败 [{skill_name}]: {e}")

    return funcs


# ══════════════════════════════════════════════════════════════
# § 3  自动 Schema 生成
# ══════════════════════════════════════════════════════════════

_TYPE_MAP = {
    str: "string", int: "integer", float: "number",
    bool: "boolean", list: "array", dict: "object"
}


def generate_schema_from_func(func) -> dict:
    """通过反射自动生成 OpenAI Function Schema，支持类型注解推断参数类型。"""
    if hasattr(func, "__custom_schema__"):
        return func.__custom_schema__

    sig   = inspect.signature(func)
    hints = {}
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        pass

    doc         = inspect.getdoc(func) or f"工具: {func.__name__}"
    description = doc.split("\n")[0].strip()[:200]
    properties  = {}
    required    = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue
        hint   = hints.get(name, str)
        origin = getattr(hint, "__origin__", None)
        if origin is typing.Union:
            args = [a for a in hint.__args__ if a is not type(None)]
            hint = args[0] if args else str
        json_type = _TYPE_MAP.get(hint, "string")

        param_desc = f"{name} 参数"
        for line in doc.split("\n"):
            line = line.strip()
            if f":param {name}:" in line:
                param_desc = line.split(f":param {name}:")[-1].strip()
                break

        properties[name] = {"type": json_type, "description": param_desc}
        if param.default == inspect.Parameter.empty:
            required.append(name)

    return {
        "name":        func.__name__,
        "description": description,
        "parameters":  {"type": "object", "properties": properties, "required": required},
    }


# ══════════════════════════════════════════════════════════════
# § 4  list_skills — 双轨统一展示
# ══════════════════════════════════════════════════════════════

def list_skills() -> str:
    """
    列出所有可用技能，明确区分 A 轨和 B 轨，让使用方式一目了然。
    """
    lines = ["### 🧩 ZClaw 技能全景\n"]

    # ── A 轨：Python 可调用工具（始终在线）──────────────────
    funcs = load_skill_functions()
    lines.append("**A 轨 — Python 工具（始终可用，直接描述任务即可）**")
    if funcs:
        for name, func in sorted(funcs.items()):
            doc        = inspect.getdoc(func) or "无描述"
            first_line = doc.split("\n")[0].strip()[:80]
            lines.append(f"  🔧 `{name}` — {first_line}")
    else:
        lines.append("  （暂无，将 .py 文件放入 skills/ 目录即可添加）")

    lines.append("")

    # ── B 轨：SKILL.md 指南技能（斜杠激活）─────────────────
    classic_dir = _classic_skills_dir()
    guides = [
        d for d in sorted(os.listdir(classic_dir))
        if os.path.isdir(os.path.join(classic_dir, d))
        and os.path.exists(os.path.join(classic_dir, d, "SKILL.md"))
    ]
    lines.append("**B 轨 — 指南技能（用 `/名称 任务` 显式激活，含操作手册和脚本）**")
    if guides:
        for g in guides:
            lines.append(f"  📖 `/{g}`")
    else:
        lines.append("  （暂无，将含 SKILL.md 的文件夹放入 modules/zclaw/skills/ 即可添加）")

    lines.append("")
    lines.append("---")
    lines.append(
        "**用法速查**\n"
        "- 直接描述任务 → A 轨工具自动调用\n"
        "- `/skill名 任务` → 强制激活 B 轨指南（适合测试新 Skill）\n"
        "- `/list` → 刷新此列表\n"
        "- `install_new_tool` → AI 自主编写并热注册新工具（扩展 A 轨）"
    )
    return "\n".join(lines)


def scan_skills() -> str:
    """供侧栏调用的简版统计，只返回数字摘要。"""
    funcs   = load_skill_functions()
    classic = _classic_skills_dir()
    guides  = [
        d for d in os.listdir(classic)
        if os.path.isdir(os.path.join(classic, d))
        and os.path.exists(os.path.join(classic, d, "SKILL.md"))
    ]
    return (
        f"A 轨 Python 工具: {len(funcs)} 个\n"
        f"B 轨指南技能: {len(guides)} 个"
        + (f"（{', '.join(guides[:4])}{'…' if len(guides) > 4 else ''}）" if guides else "")
        + "\n输入 /list 查看详情"
    )


# ══════════════════════════════════════════════════════════════
# § 5  install_new_tool — 自成长核心
#
# 修复：统一使用 get_openai_client，移除 LangChain 依赖
# 审计：允许 subprocess（沙箱内合理使用），阻断真正危险的系统级调用
# ══════════════════════════════════════════════════════════════

# 真正危险的模块（直接底层系统操作，无需开放）
_FORBIDDEN_MODULES  = {"pty", "ctypes", "pickle", "marshal", "builtins"}

# 危险内置函数
_FORBIDDEN_BUILTINS = {"eval", "exec", "compile", "__import__", "globals", "locals", "vars"}

# 危险的 OS 级方法（os.system/popen 是 shell 注入入口，execve/fork 是进程劫持入口）
_FORBIDDEN_ATTRS    = {"system", "popen", "execve", "fork", "spawn"}


def _audit(code: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _FORBIDDEN_MODULES:
                    return False, f"禁止导入: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in _FORBIDDEN_MODULES:
                return False, f"禁止导入: {node.module}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_BUILTINS:
                return False, f"禁止调用: {node.func.id}()"
            if isinstance(node.func, ast.Attribute) and node.func.attr in _FORBIDDEN_ATTRS:
                return False, f"禁止方法: .{node.func.attr}()"

    return True, "通过"


def install_new_tool(tool_name: str, requirement: str) -> str:
    """
    【自成长核心】发现能力缺口时，动态编写并安装新工具，热注册到运行时。
    安装后下一轮推理即可直接调用，无需重启。

    :param tool_name:   工具函数名，合法 Python 标识符
    :param requirement: 工具的详细功能需求描述
    """
    if not tool_name or not tool_name.isidentifier() or tool_name.startswith("_"):
        return f"❌ 工具名 [{tool_name!r}] 不合法"

    # ── 统一使用 get_openai_client，不依赖 LangChain ────────
    from core.llm_factory import get_openai_client
    client     = get_openai_client()
    model_name = getattr(settings, "MODEL_CODER", settings.MODEL_TEXT)

    skills_dir = _user_skills_dir()
    tool_path  = os.path.join(skills_dir, f"{tool_name}.py")

    code_prompt = (
        f"请编写名为 `{tool_name}` 的 Python 工具函数。\n\n"
        f"需求：{requirement}\n\n"
        "要求：\n"
        f"1. 文件首行注释说明功能：# {tool_name}: 功能描述\n"
        f"2. 顶层函数名必须是 `{tool_name}`，参数加类型注解\n"
        "3. 函数 docstring 第一行是简短功能描述（供自动生成工具说明用）\n"
        "4. 只输出代码，用 Markdown 代码块包裹。"
    )

    try:
        resp = client.chat.completions.create(
            model=model_name,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "你是高级Python工程师。只输出纯代码，用 ```python 代码块包裹。"},
                {"role": "user",   "content": code_prompt},
            ],
        )
        raw = resp.choices[0].message.content or ""
        if "```python" in raw:
            code = raw.split("```python")[1].split("```")[0].strip()
        else:
            code = raw.replace("```", "").strip()
    except Exception as e:
        return f"❌ LLM 生成代码失败: {e}"

    # AST 安全审计
    passed, reason = _audit(code)
    if not passed:
        return f"❌ 安全审计未通过: {reason}"

    # 写文件
    header = (
        f"# Auto-installed: {tool_name}\n"
        f"# {__import__('datetime').datetime.now().isoformat()}\n\n"
    )
    with open(tool_path, "w", encoding="utf-8") as f:
        f.write(header + code + "\n")

    # importlib 加载
    try:
        spec = importlib.util.spec_from_file_location(tool_name, tool_path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        try:
            os.remove(tool_path)
        except OSError:
            pass
        return f"❌ 模块加载失败（已回滚）: {e}"

    if not (hasattr(mod, tool_name) and callable(getattr(mod, tool_name))):
        os.remove(tool_path)
        return f"❌ 未找到函数 `{tool_name}()`，请确保函数名与 tool_name 一致"

    func = getattr(mod, tool_name)

    # 热注册到运行时
    from modules.zclaw._registry import TOOL_DISPATCHER, ZCLAW_TOOLS_SCHEMA
    is_update = tool_name in TOOL_DISPATCHER
    TOOL_DISPATCHER[tool_name] = func
    schema = {"type": "function", "function": generate_schema_from_func(func)}
    if is_update:
        for i, s in enumerate(ZCLAW_TOOLS_SCHEMA):
            if s.get("function", {}).get("name") == tool_name:
                ZCLAW_TOOLS_SCHEMA[i] = schema
                break
    else:
        ZCLAW_TOOLS_SCHEMA.append(schema)

    return (
        f"✅ 工具 [{tool_name}] {'热更新' if is_update else '安装成功'}！\n"
        f"   路径: {tool_path}\n"
        f"   当前 A 轨工具总数: {len(TOOL_DISPATCHER)}\n"
        f"   下一轮推理即可直接调用。"
    )


# ── Schema ────────────────────────────────────────────────────

SCHEMA = [
    {
        "name": "list_skills",
        "description": (
            "【任务开始前调用】列出所有可用技能：\n"
            "A 轨 Python 工具（始终可用）+ B 轨 SKILL.md 指南技能（/名称 激活）。"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "install_new_tool",
        "description": (
            "【自成长核心】发现能力缺口时，动态编写并安装新 A 轨工具，热注册到运行时。"
            "安装后下一轮推理即可直接调用，无需重启。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name":   {"type": "string", "description": "工具函数名，合法 Python 标识符"},
                "requirement": {"type": "string", "description": "工具的详细功能需求"},
            },
            "required": ["tool_name", "requirement"],
        },
    },
]