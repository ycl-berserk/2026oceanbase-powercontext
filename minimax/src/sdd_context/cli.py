"""sddctx 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .context import build_context, render_markdown
from .ingest import ingest
from .state import PowerContextState, StateUnavailable


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sddctx", description="SDD 工程上下文模块")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = sub.add_parser("ingest", help="导入规格、代码与测试")
    ingest_cmd.add_argument("--project", default=None, help="业务工程目录")

    plan_cmd = sub.add_parser("plan", help="按任务生成上下文")
    plan_cmd.add_argument("--task", required=True, help="任务描述")
    plan_cmd.add_argument("--task-id", default="active", help="任务标识")
    plan_cmd.add_argument("--project", default=None)
    plan_cmd.add_argument("--json", action="store_true", help="输出 JSON")
    plan_cmd.add_argument("--no-state", action="store_true", help="不读取 PowerContext")

    start_cmd = sub.add_parser("start", help="登记任务与待办")
    start_cmd.add_argument("--task-id", required=True)
    start_cmd.add_argument("--items", required=True, help="待办规格，逗号分隔")
    start_cmd.add_argument("--project", default=None)

    done_cmd = sub.add_parser("done", help="记录完成与验证结果")
    done_cmd.add_argument("--task-id", required=True)
    done_cmd.add_argument("--summary", required=True)
    done_cmd.add_argument("--log", default=None, help="测试日志路径")
    done_cmd.add_argument("--project", default=None)

    status_cmd = sub.add_parser("status", help="读取任务状态")
    status_cmd.add_argument("--task-id", required=True)
    status_cmd.add_argument("--json", action="store_true")
    status_cmd.add_argument("--project", default=None)

    reset_cmd = sub.add_parser("reset", help="清空索引")
    reset_cmd.add_argument("--project", default=None)
    return parser


def _tail(path: str | Path, lines: int = 5) -> str:
    text = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(text[-lines:])


def _state(settings: Settings) -> PowerContextState:
    return PowerContextState(settings.powercontext_url, settings.powercontext_timeout)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings.load(getattr(args, "project", None))

    if args.command == "ingest":
        result = ingest(settings)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "reset":
        from .db import Store

        with Store(settings.db_path) as store:
            store.clear()
        print(f"已清空 {settings.db_path}")
        return 0

    if args.command == "plan":
        state = None if args.no_state else _state(settings)
        try:
            context = build_context(settings, args.task, args.task_id, state=state)
        finally:
            if state is not None:
                state.close()
        if args.json:
            print(json.dumps(context, ensure_ascii=False, indent=2))
        else:
            print(render_markdown(context), end="")
        return 0

    if args.command == "start":
        state = _state(settings)
        try:
            scope_id = state.ensure_scope(args.task_id)
            items = [item.strip() for item in args.items.split(",") if item.strip()]
            state.remember(
                scope_id,
                f"待办：{', '.join(items)}",
                kind="todo",
                reason="任务开始",
            )
        except StateUnavailable as exc:
            print(f"PowerContext 不可用：{exc}", file=sys.stderr)
            return 2
        finally:
            state.close()
        print(json.dumps({"task_id": args.task_id, "scope_id": scope_id, "todo": items}, ensure_ascii=False))
        return 0

    if args.command == "done":
        state = _state(settings)
        try:
            scope_id = state.ensure_scope(args.task_id)
            state.remember(scope_id, args.summary, kind="done", reason="任务完成")
            if args.log:
                state.remember(
                    scope_id,
                    f"验证结果：{args.summary}\n{_tail(args.log)}",
                    kind="verified",
                    reason="测试日志",
                )
        except StateUnavailable as exc:
            print(f"PowerContext 不可用：{exc}", file=sys.stderr)
            return 2
        finally:
            state.close()
        print(json.dumps({"task_id": args.task_id, "scope_id": scope_id, "saved": True}, ensure_ascii=False))
        return 0

    if args.command == "status":
        state = _state(settings)
        try:
            payload = state.status(args.task_id)
        except StateUnavailable as exc:
            print(f"PowerContext 不可用：{exc}", file=sys.stderr)
            return 2
        finally:
            state.close()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"scope: {payload['scope_id']}")
            for label in ("todo", "done", "verified"):
                print(f"{label}: {'；'.join(payload[label]) if payload[label] else '（空）'}")
        return 0

    return 1
