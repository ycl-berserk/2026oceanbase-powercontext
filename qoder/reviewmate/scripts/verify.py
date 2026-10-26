#!/usr/bin/env python3
"""ReviewMate 可复现验收：seekdb 混合检索 + PowerContext 记忆复用。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reviewmate.config import Settings  # noqa: E402
from reviewmate.service import ReviewMateService  # noqa: E402

QUESTION = "LRU 和 FIFO 有什么区别？为什么 FIFO 会出现 Belady 异常？"


class Checks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.evidence: dict[str, Any] = {}

    def check(self, name: str, ok: bool, detail: str) -> bool:
        self.rows.append({"check": name, "ok": bool(ok), "detail": detail})
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}: {detail}")
        return bool(ok)

    @property
    def failed(self) -> bool:
        return any(not row["ok"] for row in self.rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ReviewMate end-to-end verification")
    parser.add_argument("--session", default=None, help="固定验证会话 ID")
    parser.add_argument("--json", default=None, help="报告输出路径")
    args = parser.parse_args()

    settings = Settings.load()
    service = ReviewMateService(settings)
    session_id = args.session or f"verify-{datetime.now():%Y%m%d-%H%M%S}"
    checks = Checks()
    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id,
        "db_path": str(settings.db_path),
        "powercontext_url": settings.powercontext_url,
        "checks": checks.rows,
        "evidence": {},
    }

    try:
        health = service.health()
        checks.check(
            "环境就绪",
            health["status"] == "ok" and health["seekdb"]["ready"],
            f"seekdb={health['seekdb']['db_path']}，PowerContext={settings.powercontext_url}",
        )
    except Exception as exc:  # noqa: BLE001 - 验收脚本需要给出可读失败信息
        checks.check("环境就绪", False, f"初始化失败：{exc}")
        return _finish(checks, report, args.json)

    pc = health["powercontext"]
    checks.check(
        "PowerContext 健康检查",
        bool(pc.get("available") and pc.get("ready")),
        "ready" if pc.get("available") and pc.get("ready") else f"不可用：{pc.get('error')}",
    )

    if health["seekdb"]["chunks"] == 0:
        print("知识库为空，导入 data/samples ...")
        service.ingest_samples()
    stats = service.store.stats()
    checks.check(
        "seekdb 知识库",
        stats["documents"] >= 4 and stats["chunks"] >= 20,
        f"{stats['documents']} 篇笔记 / {stats['chunks']} 个片段 / {len(stats['courses'])} 门课程",
    )
    report["evidence"]["seekdb_stats"] = stats

    if pc.get("available"):
        scope_seen = service.memory_entries(session_id)
        checks.check(
            "PowerContext scope 建立",
            bool(scope_seen.get("available") and scope_seen.get("scope_id")),
            f"scope={scope_seen.get('scope_id')}",
        )
        report["evidence"]["scope_id"] = scope_seen.get("scope_id")

    result = service.ask(QUESTION, session_id=session_id, course="操作系统", top_k=6)
    retrieval = result.trace["retrieval"]
    channels = retrieval["channels"]
    used = [item for item in result.citations if item["used"]]
    checks.check(
        "混合检索命中两路",
        channels["fulltext"] >= 1 and channels["vector"] >= 1,
        f"全文 {channels['fulltext']} 条，向量 {channels['vector']} 条，"
        f"保留全文 {retrieval['retained']['fulltext']} / 向量 {retrieval['retained']['vector']}",
    )
    anchored = [
        item
        for item in used
        if item["title"] == "虚拟内存与页面置换" and item["page_no"] == 4
    ]
    checks.check(
        "引用可回到原文",
        bool(anchored),
        "《虚拟内存与页面置换》第 4 页 · LRU 与 FIFO 的对比"
        if anchored
        else "未命中预期原文段落",
    )
    checks.check(
        "回答带可用引用",
        bool(used) and bool(result.answer.strip()),
        f"模式={result.answer_mode}，直接引用 {len(used)}/{len(result.citations)} 条",
    )
    report["evidence"]["ask"] = {
        "qa_id": result.qa_id,
        "answer_mode": result.answer_mode,
        "retrieval": retrieval,
        "citations": [
            {
                "index": item["index"],
                "title": item["title"],
                "heading": item["heading"],
                "page_no": item["page_no"],
                "used": item["used"],
                "fts_rank": item["fts_rank"],
                "vector_rank": item["vector_rank"],
            }
            for item in result.citations
        ],
    }
    checks.check(
        "自动记录提问",
        bool(result.trace["powercontext"].get("recorded")),
        f"entry={result.trace['powercontext'].get('recorded_entry_id')}",
    )

    weak = service.mark_weak_point(
        session_id,
        "虚拟内存与页面置换 · LRU 与 FIFO 的对比",
        "FIFO 的 Belady 异常与 LRU 近似实现",
    )
    entries = service.memory_entries(session_id)["entries"]
    kinds = {entry["kind"] for entry in entries}
    checks.check(
        "薄弱点写入并保留",
        bool(weak.get("memory", {}).get("entry_id"))
        and "weak-point" in kinds
        and "study-progress" in kinds,
        f"记忆 {len(entries)} 条，类型={','.join(sorted(kinds))}",
    )
    report["evidence"]["memory_entries"] = entries

    follow_up = service.ask(
        "再讲讲我之前标记的 LRU 与 Belady 异常", session_id=session_id, course="操作系统"
    )
    reused = follow_up.memory_status.get("hits", 0)
    checks.check(
        "后续提问复用记忆",
        reused >= 1,
        f"PowerContext 检索命中 {reused} 条历史记忆",
    )
    report["evidence"]["memory_reuse_hits"] = reused

    plan = service.review_plan(session_id, course="操作系统")
    weak_in_plan = "LRU" in plan["plan"]
    checks.check(
        "复习计划读取薄弱点",
        len(plan["weak_points"]) >= 1 and weak_in_plan,
        f"薄弱点 {len(plan['weak_points'])} 条，覆盖 {len(plan['documents'])} 篇笔记，"
        f"模式={plan['mode']}",
    )
    report["evidence"]["plan"] = {
        "mode": plan["mode"],
        "weak_points": len(plan["weak_points"]),
        "documents": [item["title"] for item in plan["documents"]],
        "excerpt": plan["plan"][:400],
    }

    history = service.history(session_id, limit=5)
    checks.check(
        "QA 日志可追溯",
        len(history) >= 2,
        f"本会话 {len(history)} 条问答记录，最新 qa_id={history[0]['qa_id']}",
    )

    service.close()
    return _finish(checks, report, args.json)


def _finish(checks: Checks, report: dict[str, Any], json_path: str | None) -> int:
    report["checks"] = checks.rows
    report["passed"] = sum(1 for row in checks.rows if row["ok"])
    report["failed"] = sum(1 for row in checks.rows if not row["ok"])
    target = Path(json_path) if json_path else ROOT / "data" / "verification" / "report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果：{report['passed']} 通过 / {report['failed']} 失败")
    print(f"报告：{target}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
