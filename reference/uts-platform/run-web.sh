#!/usr/bin/env bash
# UTS Automation Platform launcher for macOS / Linux.
# Each user runs this on their own machine, so the automation browser
# (Chrome/Edge/Firefox) opens locally on that same machine.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Find Python 3.10+
PY=""
if command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
fi
if [ -z "$PY" ]; then
  echo "Python 3.10+ was not found. Install it from https://www.python.org/downloads/ and retry."
  exit 1
fi

# First-time .env
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp ".env.example" ".env"
    echo "Created .env from .env.example"
  elif [ -f "env.template" ]; then
    cp "env.template" ".env"
    echo "Created .env from env.template"
  fi
fi

mkdir -p "web-data"

# First-time virtual environment
if [ ! -x ".venv/bin/python" ]; then
  echo "First-time setup: creating the Python environment..."
  "$PY" -m venv ".venv"
fi

APP_PY="$ROOT/.venv/bin/python"

# Install dependencies if anything is missing
if ! "$APP_PY" -c "import flask, flask_sqlalchemy, selenium, dotenv, openpyxl" >/dev/null 2>&1; then
  echo "First-time setup: installing required packages..."
  "$APP_PY" -m pip install --upgrade pip >/dev/null
  "$APP_PY" -m pip install -r "$ROOT/requirements.txt"
fi

# Local zero-setup database and browser URL (per-user machine)
export DATABASE_URL="${DATABASE_URL:-sqlite:///web-data/uts_platform.db}"
export UTS_HOST="${UTS_HOST:-127.0.0.1}"
export UTS_BROWSER_URL="${UTS_BROWSER_URL:-http://127.0.0.1:5050}"
export UTS_OPEN_BROWSER="${UTS_OPEN_BROWSER:-true}"

echo "============================================"
echo " UTS Automation Platform (this machine)"
echo "============================================"
echo "Local URL : http://127.0.0.1:5050"
echo "The testing browser will open on THIS machine."
echo "Press Ctrl+C to stop."
echo

exec "$APP_PY" "$ROOT/run_web.py"
