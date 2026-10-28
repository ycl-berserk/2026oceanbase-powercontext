#!/usr/bin/env bash
# 现场复现「改前红、改后绿」。红态提交记录在 docs/evidence/red-commit.txt。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
RED_COMMIT_FILE="$ROOT/docs/evidence/red-commit.txt"
RED_TESTS="minimax/workspace/tests/test_priority_filter.py"

if [ ! -f "$RED_COMMIT_FILE" ]; then
  echo "缺少 $RED_COMMIT_FILE" >&2
  exit 1
fi
RED="$(tr -d '[:space:]' < "$RED_COMMIT_FILE")"

TMP="$(mktemp -d)"
cleanup() {
  git -C "$ROOT" worktree remove --force "$TMP/red" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

git -C "$ROOT" worktree add --detach "$TMP/red" "$RED" >/dev/null

echo "== 红态（$RED）：目标测试应当失败 =="
set +e
PYTHONPATH="$TMP/red/minimax/workspace/src" "$PY" -m pytest -q "$TMP/red/$RED_TESTS"
RED_STATUS=$?
set -e
echo "red exit=$RED_STATUS"

echo
echo "== 当前版本：目标测试与回归测试应当全部通过 =="
PYTHONPATH="$ROOT/workspace/src" "$PY" -m pytest -q "$ROOT/workspace/tests"
GREEN_STATUS=$?

if [ "$RED_STATUS" -eq 0 ]; then
  echo "目标测试在红态没有失败，R4–R6 的失败证据不成立" >&2
  exit 1
fi
if [ "$GREEN_STATUS" -ne 0 ]; then
  echo "当前版本测试未通过" >&2
  exit 1
fi
echo "红 → 绿 复现通过"
