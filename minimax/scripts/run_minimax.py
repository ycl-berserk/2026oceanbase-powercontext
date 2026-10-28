#!/usr/bin/env python3
"""调用 MiniMax 生成一次代码修改，并保存可核对的请求与回复。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sdd_context.config import Settings  # noqa: E402
from sdd_context.context import build_context  # noqa: E402
from sdd_context.minimax import MiniMaxClient, build_prompt, extract_diff  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="用 MiniMax 生成一次代码修改")
    parser.add_argument("--task", required=True)
    parser.add_argument("--task-id", default="sdd-r4-r6")
    parser.add_argument("--no-state", action="store_true")
    parser.add_argument("--out", default=None, help="记录 JSON 路径")
    args = parser.parse_args()

    settings = Settings.load()
    context = build_context(settings, args.task, args.task_id, state=None)
    prompt = build_prompt(args.task, json.dumps(context, ensure_ascii=False, indent=2))

    client = MiniMaxClient.from_env()
    try:
        reply = client.chat(prompt)
    finally:
        client.close()

    diff = extract_diff(reply.content)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else ROOT / "docs" / "evidence" / f"minimax-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": reply.model,
        "api_style": client.api_style,
        "task": args.task,
        "task_id": args.task_id,
        "context": context,
        "prompt": prompt,
        "reply": {"content": reply.content, "usage": reply.usage},
        "diff": diff,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"记录：{out}")

    if diff:
        patch = out.with_suffix(".patch")
        patch.write_text(diff, encoding="utf-8")
        print(f"补丁：{patch}")
        print(diff)
    else:
        print("模型未返回 ```diff 代码块，请检查 reply.content")
    return 0


if __name__ == "__main__":
    sys.exit(main())
