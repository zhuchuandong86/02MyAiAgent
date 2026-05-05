"""
_registry.py — 全自动注册中心

新增任何 *_tools.py → 自动生效，此文件永远不需要改动。
"""

import os
import glob
import importlib.util

from modules.zclaw.skill_tools import load_skill_functions, generate_schema_from_func


def _load_atomic_tools() -> dict:
    """扫描 modules/zclaw/ 下所有 *_tools.py，从 SCHEMA 列表自动注册函数。"""
    dispatcher = {}
    zclaw_dir  = os.path.dirname(os.path.abspath(__file__))

    for path in sorted(glob.glob(os.path.join(zclaw_dir, "*_tools.py"))):
        module_name = os.path.basename(path)[:-3]
        if module_name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for item in getattr(mod, "SCHEMA", []):
                fname = item.get("name")
                if fname and hasattr(mod, fname) and callable(getattr(mod, fname)):
                    dispatcher[fname] = getattr(mod, fname)
        except Exception as e:
            print(f"⚠️ 工具加载失败 [{module_name}]: {e}")

    return dispatcher


TOOL_DISPATCHER = _load_atomic_tools()
TOOL_DISPATCHER.update(load_skill_functions())   # 合并 skills/ 目录的 Python 技能

ZCLAW_TOOLS_SCHEMA = [
    {"type": "function", "function": generate_schema_from_func(func)}
    for func in TOOL_DISPATCHER.values()
]