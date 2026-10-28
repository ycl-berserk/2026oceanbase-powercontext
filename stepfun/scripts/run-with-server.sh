#!/usr/bin/env bash
# 通用：同步代码 → 装依赖 → 启动 server（含 seekdb）→ 执行给定命令
#   bash scripts/run-with-server.sh node scripts/test-api.mjs
set -euo pipefail
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 || true

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="${STEPFUN_RUN_DIR:-$HOME/stepfun-run}"
PORT="${PORT:-8787}"

mkdir -p "$RUN"
rsync -a --delete \
  --exclude node_modules --exclude data --exclude dist --exclude .git \
  "$SRC"/ "$RUN"/
cd "$RUN"

if [ ! -d node_modules/seekdb ]; then
  echo "== 安装依赖（仅 server workspace）=="
  npm install --workspace @stepfun/server --no-audit --no-fund
fi

if [ -f data/seekdb/seekdb.pid ]; then
  kill "$(cat data/seekdb/seekdb.pid)" 2>/dev/null || true
fi
pkill -f "seekdb --port 2881" 2>/dev/null || true

echo "== 启动 server =="
PORT="$PORT" node server/src/index.js >server.log 2>&1 &
SRV=$!
cleanup() {
  kill "$SRV" 2>/dev/null || true
  [ -f data/seekdb/seekdb.pid ] && kill "$(cat data/seekdb/seekdb.pid)" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 150); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  if ! kill -0 "$SRV" 2>/dev/null; then
    echo "== server 启动失败 =="; tail -40 server.log; exit 1
  fi
  sleep 1
done
head -4 server.log

export API_BASE="http://127.0.0.1:$PORT"
"$@"
