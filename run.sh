#!/bin/sh
set -eu
cd "$(dirname "$0")"
PORT="${LINGTAI_SIMPLE_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/"
echo "LingTai Simple starting..."
echo "Open: ${URL}"
if command -v open >/dev/null 2>&1; then
  ( sleep 1; open "$URL" ) >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
  ( sleep 1; xdg-open "$URL" ) >/dev/null 2>&1 &
fi
LINGTAI_SIMPLE_PORT="$PORT" python3 server.py
