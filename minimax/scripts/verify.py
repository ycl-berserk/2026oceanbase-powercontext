#!/usr/bin/env python3
"""12 项可复现验收，对应 MiniMax 赛题六项必做要求。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sdd_context.config import Settings  # noqa: E402
from sdd_context.context import build_context  # noqa: E402
from sdd_context.ingest import ingest  # noqa: E402
from sdd_context.state import PowerContextState, StateUnavailable  # noqa: E402

PY = sys.executable
PC_URL = os.environ.get("SDD_POWERCONTEXT_URL", "http://127.0.0.1:8102")
TASK = (
    "为 list_tickets 增加 priority 过滤，非法 priority 与越界 limit 抛出 InvalidFilter，"
    "结果按优先级和创建时间稳定排序"
)


def run(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 240
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, env=env, capture_output=True, text=True, timeout=timeout
    )


class Checks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: str) -> bool:
        self.rows.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(row["ok"] for row in self.rows)


def _source_ok(row: dict[str, Any]) -> tuple[bool, str]:
    path = ROOT / "workspace" / str(row["path"])
    if not path.is_file():
        return False, f"文件不存在：{row['path']}"
    total = len(path.read_text(encoding="utf-8").splitlines())
    start, end = int(row["start_line"]), int(row["end_line"])
    if not (1 <= start <= end <= total):
        return False, f"行号越界：{row['path']}:{start}-{end}（共 {total} 行）"
    return True, f"{row['path']}:{start}-{end}"


def _start_powercontext() -> tuple[subprocess.Popen[bytes] | None, PowerContextState]:
    state = PowerContextState(PC_URL)
    try:
        state.health()
        return None, state
    except StateUnavailable:
        state.close()

    db = ROOT / "data" / "powercontext" / "verify.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["POWERCONTEXT_SERVER_DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    exe = Path(PY).with_name("powercontext")
    command = [str(exe) if exe.exists() else "powercontext", "server", "run", "--host", "127.0.0.1", "--port", "8102"]
    process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    state = PowerContextState(PC_URL)
    for _ in range(45):
        try:
            state.health()
            return process, state
        except StateUnavailable:
            time.sleep(1)
    process.terminate()
    raise StateUnavailable("PowerContext 启动超时，请检查 powercontext[builtin,cli] 是否安装")


def main() -> int:
    checks = Checks()
    settings = Settings.load()
    workspace = ROOT / "workspace"
    target_tests = [
        "test_filters_by_priority",
        "test_rejects_unknown_priority",
        "test_rejects_limit_out_of_range",
        "test_orders_by_priority_then_recency",
        "test_combines_status_and_priority",
    ]

    # 1. 可运行所需文件齐全
    required = [
        workspace / "specs" / "tickets.md",
        workspace / "src" / "ticket_service" / "service.py",
        workspace / "tests" / "test_priority_filter.py",
        ROOT / "evals" / "task.md",
        ROOT / "README.md",
        ROOT / "TECHNICAL.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    checks.check("files", not missing, "缺少：" + ", ".join(missing) if missing else "必需文件齐全")

    # 2. 导入计数
    result = ingest(settings)
    counts = result["counts"]
    ok = counts.get("spec", 0) >= 6 and counts.get("code", 0) >= 3 and counts.get("test", 0) >= 10
    checks.check("ingest", ok, f"seekdb 导入 {counts}，合计 {result['total']} 条")

    # 3. 三类检索非空
    context = build_context(settings, TASK, "verify", state=None)
    ok = all(context[key] for key in ("specs", "code", "tests"))
    checks.check(
        "retrieval",
        ok,
        f"specs={len(context['specs'])} code={len(context['code'])} tests={len(context['tests'])}",
    )

    # 4. 规格条目与来源
    spec_ids = {row["symbol"] for row in context["specs"]}
    bad: list[str] = []
    for row in context["specs"]:
        valid, detail = _source_ok(row)
        if not valid:
            bad.append(detail)
    checks.check(
        "specs",
        {"R4", "R5", "R6"}.issubset(spec_ids) and not bad,
        f"命中 {sorted(spec_ids)}；无效来源 {bad}",
    )

    # 5. 代码符号
    code_rows = [row for row in context["code"] if row["symbol"] == "list_tickets"]
    code_ok = False
    code_detail = "未命中 list_tickets"
    if code_rows:
        row = code_rows[0]
        valid, detail = _source_ok(row)
        if valid:
            lines = (ROOT / "workspace" / row["path"]).read_text(encoding="utf-8").splitlines()
            region = "\n".join(lines[int(row["start_line"]) - 1 : int(row["end_line"])])
            code_ok = "def list_tickets" in region
            code_detail = f"{detail} 覆盖 def list_tickets={code_ok}"
        else:
            code_detail = detail
    checks.check("code", code_ok, code_detail)

    # 6. 目标测试
    test_names = {row["symbol"] for row in context["tests"]}
    missing_tests = [name for name in target_tests if name not in test_names]
    checks.check("tests", not missing_tests, f"命中 {len(test_names)} 个测试；缺少 {missing_tests}")

    # 7. 规格更新后重新导入
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "workspace"
        shutil.copytree(workspace, project, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        shutil.copy(ROOT / "evals" / "spec-v2" / "tickets.md", project / "specs" / "tickets.md")
        env = os.environ.copy()
        env["SDD_PROJECT"] = str(project)
        env["SDD_DB_PATH"] = str(Path(tmp) / "sdd-v2.db")
        ing = run([PY, "-m", "sdd_context", "ingest"], cwd=ROOT, env=env)
        plan = run(
            [PY, "-m", "sdd_context", "plan", "--task", TASK, "--task-id", "spec-v2", "--no-state", "--json"],
            cwd=ROOT,
            env=env,
        )
        new_marker = "P3 表示“观察中”"
        old_marker = "取值为 `P0`、`P1`、`P2`。为"
        ok = (
            ing.returncode == 0
            and plan.returncode == 0
            and new_marker in plan.stdout
            and old_marker not in plan.stdout
        )
        detail = (
            f"新规格文本出现={new_marker in plan.stdout}；旧文本消失={old_marker not in plan.stdout}"
            if ok
            else f"ingest={ing.returncode} plan={plan.returncode} {ing.stderr[-200:]}"
        )
        checks.check("spec-update", ok, detail)

    # 8-10. PowerContext
    process: subprocess.Popen[bytes] | None = None
    state: PowerContextState | None = None
    try:
        process, state = _start_powercontext()
        health = state.health()
        checks.check("pc-health", health["alive"] and health["ready"], json.dumps(health, ensure_ascii=False))

        task_id = f"verify-{datetime.now():%Y%m%d-%H%M%S}"
        scope = state.ensure_scope(task_id)
        state.remember(scope, "待办：R4,R5,R6", kind="todo", reason="verify")
        entries = state.list_entries(scope)
        checks.check(
            "pc-write",
            len(entries) >= 1,
            f"scope={scope} 写入 {len(entries)} 条记录（空状态开始）",
        )

        status_run = run(
            [PY, "-m", "sdd_context", "status", "--task-id", task_id, "--json"], cwd=ROOT
        )
        payload: dict[str, Any] = {}
        if status_run.returncode == 0:
            payload = json.loads(status_run.stdout)
        reused = (
            status_run.returncode == 0
            and payload.get("scope_id") == scope
            and any("R4" in item for item in payload.get("todo", []))
        )
        checks.check(
            "pc-restart",
            reused,
            f"新进程读回 scope={payload.get('scope_id')} todo={payload.get('todo')}"
            if status_run.returncode == 0
            else status_run.stderr[-200:],
        )
    except StateUnavailable as exc:
        checks.check("pc-health", False, str(exc))
        checks.check("pc-write", False, "前置：PowerContext 不可用")
        checks.check("pc-restart", False, "前置：PowerContext 不可用")
    finally:
        if state is not None:
            state.close()
        if process is not None:
            process.terminate()

    # 11. 改前红、改后绿
    red_file = ROOT / "docs" / "evidence" / "red-commit.txt"
    if not red_file.is_file():
        checks.check("red-green", False, "缺少 docs/evidence/red-commit.txt")
    else:
        red_commit = red_file.read_text(encoding="utf-8").strip()
        tmp = tempfile.mkdtemp(prefix="sdd-red-")
        red_worktree = Path(tmp) / "red"
        try:
            add = run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(red_worktree), red_commit])
            red_ws = red_worktree / "minimax" / "workspace"
            red_env = os.environ.copy()
            red_env["PYTHONPATH"] = str(red_ws / "src")
            red_run = run(
                [PY, "-m", "pytest", "-q", str(red_ws / "tests" / "test_priority_filter.py")],
                cwd=red_ws,
                env=red_env,
            )
            green_env = os.environ.copy()
            green_env["PYTHONPATH"] = str(workspace / "src")
            green_run = run([PY, "-m", "pytest", "-q", "tests"], cwd=workspace, env=green_env)
            ok = add.returncode == 0 and red_run.returncode != 0 and green_run.returncode == 0
            detail = (
                f"red({red_commit[:8]}) exit={red_run.returncode}，当前测试 exit={green_run.returncode}"
                if ok
                else f"add={add.returncode} red={red_run.returncode} green={green_run.returncode}"
            )
            checks.check("red-green", ok, detail)
        finally:
            run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(red_worktree)])
            shutil.rmtree(tmp, ignore_errors=True)

    # 12. 无密钥入库
    tracked = run(["git", "-C", str(ROOT), "ls-files", "minimax"]).stdout.splitlines()
    patterns = (
        re.compile(r"sk-[A-Za-z0-9]{16,}"),
        re.compile(r"MINIMAX_API_KEY\s*=\s*[^\s\"']"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    )
    hits: list[str] = []
    for rel in tracked:
        path = ROOT / rel
        if not path.is_file() or path.suffix not in {".md", ".py", ".sh", ".toml", ".json", ".txt", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in patterns):
            hits.append(rel)
    checks.check("secrets", not hits, "发现疑似凭据：" + ", ".join(hits) if hits else "跟踪文件未发现凭据")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(ROOT),
        "ok": checks.ok,
        "checks": checks.rows,
    }
    out = ROOT / "docs" / "verification" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{sum(row['ok'] for row in checks.rows)}/{len(checks.rows)} 通过，报告：{out}")
    return 0 if checks.ok else 1


if __name__ == "__main__":
    sys.exit(main())
