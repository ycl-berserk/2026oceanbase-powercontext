#!/usr/bin/env bash
# 在 Linux/WSL 下准备 seekdb 运行环境并执行任意命令。
#   bash scripts/linux-env.sh node scripts/probe-seekdb.mjs
set -euo pipefail
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 || true

WORK_DIR="${PROBE_WORK_DIR:-$HOME/seekdb-probe}"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# libaio.so.1 兼容软链（Ubuntu 24.04 只有 libaio.so.1t64）
if ! ldconfig -p | grep -q "libaio.so.1 "; then
  mkdir -p "$WORK_DIR/extra-libs"
  SRC=$(ls /lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1t64 2>/dev/null | head -1 || true)
  [ -n "$SRC" ] && ln -sf "$SRC" "$WORK_DIR/extra-libs/libaio.so.1"
  export LD_LIBRARY_PATH="$WORK_DIR/extra-libs:${LD_LIBRARY_PATH:-}"
fi

# libseekdb 的静态 TLS 问题（server 模式下 seekdb 是独立进程，不能污染）
if [[ " $* " != *" --server "* && -z "${SKIP_PRELOAD:-}" ]]; then
  LIB=$(find "$HOME/.seekdb/bindings" -name libseekdb.so 2>/dev/null | head -1 || true)
  [ -n "$LIB" ] && export LD_PRELOAD="$LIB"
fi

export PROBE_WORK_DIR="$WORK_DIR"
exec "$@"
