#!/usr/bin/env bash
# Linux / WSL 上跑 seekdb 探针的辅助脚本。
# 用途：确认嵌入式 API 可用（建集合 / 写入 / refresh_index / 混合检索），并规避 libseekdb 的静态 TLS 问题。
set -euo pipefail

# 非登录 shell 下 nvm/node 可能不在 PATH
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 || true

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${PROBE_WORK_DIR:-$HOME/seekdb-probe}"

mkdir -p "$WORK_DIR"
cd "$WORK_DIR"
[ -f package.json ] || npm init -y >/dev/null
if [ ! -d node_modules/seekdb ]; then
  npm i seekdb@1.4.0 @seekdb/js-bindings@1.4.0 @oceanbase/seekdb-node@1.4.0 mysql2 \
    --legacy-peer-deps --no-audit --no-fund
fi

cp "$REPO_DIR/scripts/probe-seekdb.mjs" ./probe.mjs
rm -rf "$WORK_DIR/probe-data"

# seekdb 依赖 libaio.so.1；Ubuntu 24.04 走 t64 命名（只有 libaio.so.1t64），
# 这里不用 sudo：在用户目录建一个兼容软链，再通过 LD_LIBRARY_PATH 暴露。
if ! ldconfig -p | grep -q "libaio.so.1 "; then
  mkdir -p "$WORK_DIR/extra-libs"
  if [ ! -e "$WORK_DIR/extra-libs/libaio.so.1" ]; then
    SRC=$(ls /lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1t64 2>/dev/null | head -1 || true)
    if [ -n "$SRC" ]; then
      ln -sf "$SRC" "$WORK_DIR/extra-libs/libaio.so.1"
    else
      (cd "$WORK_DIR" && apt-get download libaio1t64 >/dev/null 2>&1 || apt-get download libaio1 >/dev/null 2>&1)
      DEB=$(ls -1 "$WORK_DIR"/libaio*_amd64.deb 2>/dev/null | head -1 || true)
      if [ -n "$DEB" ]; then
        dpkg-deb -x "$DEB" "$WORK_DIR/extra-libs/pkg"
        ln -sf "$(find "$WORK_DIR/extra-libs/pkg" -name 'libaio.so.1*' | head -1)" "$WORK_DIR/extra-libs/libaio.so.1"
      else
        echo "警告：未能准备 libaio，若下面报 libaio.so.1 缺失请手动安装 libaio1t64" >&2
      fi
    fi
  fi
  export LD_LIBRARY_PATH="$WORK_DIR/extra-libs:${LD_LIBRARY_PATH:-}"
fi

# libseekdb.so 自带大量 TLS 变量，dlopen 时会报 "cannot allocate memory in static TLS block"，
# 预先加载即可绕过（glibc 2.39 起常见）。
# libseekdb.so 自带大量 TLS 变量，dlopen 时会报 "cannot allocate memory in static TLS block"，
# 预先加载即可绕过。remote 模式下没有独立子进程，但预加载也无害；这里只对 embedded 生效。
if [[ " $* " != *" --remote "* ]]; then
  LIB=$(find "$HOME/.seekdb/bindings" -name libseekdb.so 2>/dev/null | head -1 || true)
  if [ -n "$LIB" ]; then
    echo "LD_PRELOAD=$LIB"
    export LD_PRELOAD="$LIB"
  fi
fi

export PROBE_DATA_DIR="$WORK_DIR/probe-data"
timeout 300 node probe.mjs "$@"
