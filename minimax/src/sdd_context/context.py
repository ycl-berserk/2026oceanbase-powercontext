"""组装任务上下文。"""

from __future__ import annotations

from typing import Any

from .config import Settings
from .db import Store
from .retrieve import select
from .state import PowerContextState, StateUnavailable


def build_context(
    settings: Settings,
    task: str,
    task_id: str,
    state: PowerContextState | None = None,
    per_kind: int = 5,
) -> dict[str, Any]:
    with Store(settings.db_path) as store:
        hits = select(store, task, per_kind=per_kind)
        stats = store.stats()

    status: dict[str, Any] = {
        "available": False,
        "scope_id": None,
        "todo": [],
        "done": [],
        "verified": [],
    }
    if state is not None:
        try:
            status = state.status(task_id)
        except StateUnavailable as exc:
            status["error"] = str(exc)

    return {
        "task_id": task_id,
        "task": task,
        "index": stats,
        "specs": hits["spec"],
        "code": hits["code"],
        "tests": hits["test"],
        "status": status,
    }


def render_markdown(context: dict[str, Any]) -> str:
    def snippet(row: dict[str, Any], length: int = 160) -> str:
        text = " ".join(str(row.get("text") or "").split())
        return f"  > {text[:length]}…" if len(text) > length else f"  > {text}"

    lines = [f"# 任务：{context['task']}", f"任务 ID：`{context['task_id']}`", ""]

    lines.append("## 适用规格")
    for row in context["specs"]:
        lines.append(f"- [{row['symbol']}] {row['heading']}  ({row['source']}, 分数 {row['score']})")
        if row.get("text"):
            lines.append(snippet(row))
    if not context["specs"]:
        lines.append("- 未检索到规格")

    lines.append("")
    lines.append("## 相关代码")
    for row in context["code"]:
        lines.append(f"- `{row['symbol']}`  ({row['source']}, 分数 {row['score']})")
        if row.get("text"):
            lines.append(snippet(row, 120))
    if not context["code"]:
        lines.append("- 未检索到代码符号")

    lines.append("")
    lines.append("## 验证测试")
    for row in context["tests"]:
        lines.append(f"- `{row['symbol']}`  ({row['source']}, 分数 {row['score']})")
    if not context["tests"]:
        lines.append("- 未检索到测试")

    lines.append("")
    lines.append("## 任务状态")
    status = context["status"]
    if not status.get("available"):
        lines.append(f"- PowerContext 不可用：{status.get('error', '未连接')}")
    else:
        lines.append(f"- scope：`{status['scope_id']}`")
        for label in ("todo", "done", "verified"):
            items = status.get(label) or []
            lines.append(f"- {label}：{'；'.join(items) if items else '（空）'}")
    return "\n".join(lines) + "\n"
