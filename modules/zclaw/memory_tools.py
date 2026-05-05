"""
memory_tools.py — 结构化记忆引擎

存储格式：JSONL（每行一条 JSON，带标签/时间戳/使用计数）
去重：    Jaccard 相似度 > 70% 自动跳过，防止记忆污染
检索：    按关键词相关性 + 使用频次加权，返回 top-k（早期经验不会消失）
剪枝：    按时间 + 使用频次精准清理，零 token 消耗
兼容：    同步维护 experience_log.md 供人工查阅
"""

import os
import json
import time
from datetime import datetime, timedelta
import streamlit as st
import core.paths


def get_user_workspace() -> str:
    user = st.session_state.get("zclaw_user", "public")
    ws   = os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"zclaw_workspace_{user}")
    os.makedirs(ws, exist_ok=True)
    return ws


def _get_paths() -> tuple[str, str]:
    ws = get_user_workspace()
    return (
        os.path.join(ws, "memory.jsonl"),       # 机读：结构化记忆库
        os.path.join(ws, "experience_log.md"),  # 人读：Markdown 版本
    )

# ── 内部 IO ───────────────────────────────────────────────────

def _load() -> list[dict]:
    db, _ = _get_paths()
    if not os.path.exists(db):
        return []
    memories = []
    with open(db, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    memories.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return memories


def _save(memories: list[dict]) -> None:
    db, _ = _get_paths()
    with open(db, "w", encoding="utf-8") as f:
        for m in memories:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")


def _jaccard(a: str, b: str) -> float:
    """词汇 Jaccard 相似度，用于去重判断。"""
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)

# ── 公开工具函数 ──────────────────────────────────────────────

def append_memory(lesson: str) -> str:
    """
    写入一条经验记忆。
    自动去重：完全相同 或 Jaccard > 70% 则跳过，防止记忆污染。
    """
    memories = _load()
    lesson   = lesson.strip()

    for m in memories:
        if m["lesson"].strip() == lesson:
            return "✅ 完全相同的记忆已存在，跳过。"
        if len(lesson.split()) > 5 and _jaccard(m["lesson"], lesson) > 0.70:
            return (
                f"✅ 发现高度相似记忆（重叠率 {_jaccard(m['lesson'], lesson):.0%}），已跳过。\n"
                f"  └─ 已有: {m['lesson'][:80]}"
            )

    entry = {
        "id":         int(time.time() * 1000),
        "lesson":     lesson,
        "use_count":  0,
        "last_used":  None,
        "created_at": datetime.now().isoformat(),
    }
    memories.append(entry)
    _save(memories)

    _, md = _get_paths()
    with open(md, "a", encoding="utf-8") as f:
        f.write(f"\n- {lesson}")

    return f"✅ 经验已写入记忆库\n  └─ {lesson[:100]}"


def search_memory(query: str, top_k: int = 8) -> str:
    """
    检索与当前任务最相关的历史经验。
    按关键词相关性 + 使用频次加权排序，只返回 top_k 条。
    """
    memories = _load()
    if not memories:
        return "（记忆库为空，尚无历史经验）"

    qw     = set(query.lower().split())
    scored: list[tuple[float, dict]] = []

    for m in memories:
        lw        = set(m["lesson"].lower().split())
        overlap   = len(qw & lw)
        use_bonus = min(m.get("use_count", 0) * 0.15, 3.0)
        score     = overlap + use_bonus
        if score > 0:
            scored.append((score, m))

    if not scored:
        return "（未找到与当前任务相关的历史经验）"

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [m for _, m in scored[:top_k]]

    # 被检索到的记忆，use_count++
    top_ids = {m["id"] for m in top}
    for m in memories:
        if m["id"] in top_ids:
            m["use_count"] = m.get("use_count", 0) + 1
            m["last_used"] = datetime.now().isoformat()
    _save(memories)

    return "\n".join(f"- {m['lesson']}" for m in top)


def evaluate_and_prune_memory() -> str:
    """
    精简记忆库。
    规则：超过 90 天未引用 且 use_count < 2 的低价值记忆直接删除，零 token 消耗。
    """
    memories = _load()
    if not memories:
        return "记忆库为空，无需清理。"

    cutoff      = datetime.now() - timedelta(days=90)
    kept, pruned = [], []

    for m in memories:
        try:
            created   = datetime.fromisoformat(m.get("created_at", datetime.now().isoformat()))
            last_used = datetime.fromisoformat(m["last_used"]) if m.get("last_used") else created
        except ValueError:
            kept.append(m)
            continue

        if last_used < cutoff and m.get("use_count", 0) < 2:
            pruned.append(m)
        else:
            kept.append(m)

    _save(kept)

    _, md = _get_paths()
    user = st.session_state.get("zclaw_user", "public")
    with open(md, "w", encoding="utf-8") as f:
        f.write(f"# 【{user}】的专属经验\n\n")
        for m in kept:
            f.write(f"- {m['lesson']}\n")

    return (
        f"✅ 记忆剪枝完成：保留 {len(kept)} 条，"
        f"清除 {len(pruned)} 条（超 90 天未引用且使用次数 < 2）。"
    )


SCHEMA = [
    {
        "name": "search_memory",
        "description": "【任务开始前必须调用】检索与当前任务最相关的历史经验，避免重蹈覆辙。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词，描述当前任务"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "append_memory",
        "description": "将重要经验永久写入记忆库。带自动去重，任务完成闭环后调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "lesson": {"type": "string", "description": "经验正文，清晰描述 what/why/how"}
            },
            "required": ["lesson"]
        }
    },
    {
        "name": "evaluate_and_prune_memory",
        "description": "清理低价值记忆，防止记忆库膨胀。按使用频次和时间精准删除，零 token 消耗。",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]