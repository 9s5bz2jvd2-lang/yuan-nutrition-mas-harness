#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
PORT="${LINGTAI_SIMPLE_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/"
echo "Yuan Nutrition MAS Harness is starting..."
echo "Open: ${URL}"
( sleep 1; open "$URL" ) >/dev/null 2>&1 &
LINGTAI_SIMPLE_PORT="$PORT" python3 server.py
