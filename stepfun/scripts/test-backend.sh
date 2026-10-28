#!/usr/bin/env bash
# 后端端到端测试
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$HERE/run-with-server.sh" node "$HERE/test-api.mjs"
