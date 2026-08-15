#!/usr/bin/env bash
# UTS Worker Agent for macOS / Linux — opens the automation browser on THIS machine.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

SERVER="${UTS_SERVER_URL:-}"
if [ -z "$SERVER" ]; then
  read -r -p "Central UTS server URL [http://127.0.0.1:5050]: " SERVER
  SERVER="${SERVER:-http://127.0.0.1:5050}"
fi

echo
echo "===================================================================="
echo " UTS WORKER AGENT — browser opens on THIS machine"
echo " Server: $SERVER"
echo " Keep this terminal open. Ctrl+C to stop."
echo "===================================================================="
echo

exec "$PY" "$ROOT/worker/agent.py" --server "$SERVER" "$@"
