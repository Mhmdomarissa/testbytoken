#!/usr/bin/env bash
# One-time UTS setup for macOS / Linux.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

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

echo "Creating the Python environment..."
"$PY" -m venv ".venv"

echo "Installing UTS automation and web dependencies..."
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -r requirements.txt

if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo "Created .env from .env.example"
fi

echo
echo "Setup complete. Google Chrome is required for automation."
echo "Start the platform with:  ./run-web.sh"
echo "Then open:                http://127.0.0.1:5050"
