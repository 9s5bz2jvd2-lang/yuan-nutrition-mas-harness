#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
PORT="${LINGTAI_SIMPLE_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/"
echo "圆酱专属轻量版灵台启动中..."
echo "打开：${URL}"
( sleep 1; open "$URL" ) >/dev/null 2>&1 &
LINGTAI_SIMPLE_PORT="$PORT" python3 server.py
