from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .service import ReviewMateService, build_service


def _print_ask(result: dict) -> None:
    print(result["answer"])
    print("\n来源：")
    for citation in result["citations"]:
        channel = []
        if citation["fts_rank"]:
            channel.append(f"全文 #{citation['fts_rank']}")
        if citation["vector_rank"]:
            channel.append(f"向量 #{citation['vector_rank']}")
        page = f"第 {citation['page_no']} 页 · " if citation["page_no"] else ""
        print(
            f"[{citation['index']}] 《{citation['title']}》· {citation['heading']}"
            f"（{page}{citation['course']}） {' / '.join(channel)}"
        )
    memory_status = result["memory_status"]
    if memory_status["available"]:
        print(f"\nPowerContext：命中 {memory_status['hits']} 条学习记忆")
    else:
        print(f"\nPowerContext：不可用（{memory_status['error']}）")
    timing = result["trace"]["timing_ms"]
    print(f"耗时：检索 {timing['retrieval']} ms，回答 {timing['answer']} ms，总计 {timing['total']} ms")


def _cmd_ingest(service: ReviewMateService, args: argparse.Namespace) -> int:
    paths = [Path(item) for item in args.paths] if args.paths else [service.settings.samples_dir]
    results = service.ingest(paths, course_override=args.course)
    for item in results:
        print(f"已导入 {item['doc_id']}：{item['title']}（{item['course']}，{item['chunks']} 段）")
    print(f"共导入 {len(results)} 篇资料。")
    return 0


def _cmd_ask(service: ReviewMateService, args: argparse.Namespace) -> int:
    result = service.ask(
        args.question,
        session_id=args.session,
        course=args.course,
        top_k=args.top_k,
    ).to_dict()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_ask(result)
    return 0


def _cmd_stats(service: ReviewMateService, args: argparse.Namespace) -> int:
    print(json.dumps(service.health(), ensure_ascii=False, indent=2))
    return 0


def _cmd_memory(service: ReviewMateService, args: argparse.Namespace) -> int:
    payload = service.memory_entries(args.session)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not payload["available"]:
        print(f"PowerContext 不可用：{payload['error']}")
        return 1
    print(f"Scope：{payload['scope_id']}")
    if not payload["entries"]:
        print("暂无学习记忆。")
    for entry in payload["entries"]:
        print(f"- [{entry['kind']}] {entry['text']}")
    return 0


def _cmd_weak(service: ReviewMateService, args: argparse.Namespace) -> int:
    payload = service.mark_weak_point(args.session, args.topic, args.detail)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_plan(service: ReviewMateService, args: argparse.Namespace) -> int:
    payload = service.review_plan(args.session, args.course)
    print(payload["plan"])
    if not payload["powercontext"]["available"]:
        print(f"\nPowerContext 不可用：{payload['powercontext']['error']}")
    return 0


def _cmd_history(service: ReviewMateService, args: argparse.Namespace) -> int:
    rows = service.history(args.session, args.limit)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviewmate",
        description="温故 ReviewMate：课程笔记混合检索与学习记忆助手",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="导入 Markdown / 文本笔记")
    ingest.add_argument("paths", nargs="*", help="文件或目录；省略时导入 data/samples")
    ingest.add_argument("--course", help="覆盖资料中的课程名")
    ingest.set_defaults(func=_cmd_ingest)

    ask = sub.add_parser("ask", help="基于笔记提问")
    ask.add_argument("question")
    ask.add_argument("--session", default="demo")
    ask.add_argument("--course")
    ask.add_argument("--top-k", type=int, default=None)
    ask.add_argument("--json", action="store_true")
    ask.set_defaults(func=_cmd_ask)

    stats = sub.add_parser("stats", help="查看系统与知识库状态")
    stats.set_defaults(func=_cmd_stats)

    memory = sub.add_parser("memory", help="查看 PowerContext 学习记忆")
    memory.add_argument("--session", default="demo")
    memory.add_argument("--json", action="store_true")
    memory.set_defaults(func=_cmd_memory)

    weak = sub.add_parser("mark-weak", help="写入一个薄弱点")
    weak.add_argument("topic")
    weak.add_argument("--detail", default="")
    weak.add_argument("--session", default="demo")
    weak.set_defaults(func=_cmd_weak)

    plan = sub.add_parser("plan", help="生成复习计划")
    plan.add_argument("--session", default="demo")
    plan.add_argument("--course")
    plan.set_defaults(func=_cmd_plan)

    history = sub.add_parser("history", help="查看会话提问记录")
    history.add_argument("--session", default="demo")
    history.add_argument("--limit", type=int, default=20)
    history.set_defaults(func=_cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        service = build_service(Settings.load())
    except Exception as exc:  # noqa: BLE001
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 1
    try:
        return int(args.func(service, args))
    except Exception as exc:  # noqa: BLE001 - CLI 需要给出简洁错误
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
