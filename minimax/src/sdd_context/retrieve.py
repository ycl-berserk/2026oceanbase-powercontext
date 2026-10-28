"""按任务检索规格、代码与测试。"""

from __future__ import annotations

import re
from typing import Any

from .db import Store

KINDS = ("spec", "code", "test")
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def keywords(task: str) -> list[str]:
    return list(dict.fromkeys(TOKEN.findall(task)))


def select(store: Store, task: str, per_kind: int = 5) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    lowered = task.lower()
    for kind in KINDS:
        rows = store.search(kind, task, per_kind)
        if not rows:
            fallback = " ".join(keywords(task))
            if fallback:
                rows = store.search(kind, fallback, per_kind)
        for row in rows:
            symbol = str(row.get("symbol") or "").lower()
            if symbol and symbol in lowered:
                row["score"] = round(float(row["score"]) * 1.5, 6)
            row["source"] = f"{row['path']}:{row['start_line']}-{row['end_line']}"
            row["text"] = str(row.pop("content", ""))[:800]
        rows.sort(key=lambda item: (-float(item["score"]), item["doc_key"]))
        result[kind] = rows
    return result
