#!/usr/bin/env bash
# Install auto-start worker on macOS/Linux (user login via crontab @reboot or LaunchAgent note)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ ! -f worker.env ]; then
  cp worker.env.example worker.env
  echo "Created worker.env — edit it, then re-run this script."
  ${EDITOR:-nano} worker.env || true
fi

# shellcheck disable=SC1091
set -a
# shellcheck source=/dev/null
source <(grep -v '^#' worker.env | sed '/^\s*$/d')
set +a

mkdir -p web-data
AUTO="$ROOT/run-worker-auto.sh"
cat > "$AUTO" <<EOF
#!/usr/bin/env bash
cd "$ROOT"
set -a
source <(grep -v '^#' "$ROOT/worker.env" | sed '/^\s*$/d')
set +a
PY="$ROOT/.venv/bin/python"
[ -x "\$PY" ] || PY=python3
exec "\$PY" -u "$ROOT/worker/agent.py" \\
  --server "\${UTS_SERVER_URL}" \\
  --username "\${UTS_WORKER_USERNAME}" \\
  --password "\${UTS_WORKER_PASSWORD}" \\
  --browser "\${UTS_WORKER_BROWSER:-chrome}" \\
  >> "$ROOT/web-data/worker-auto.log" 2>&1
EOF
chmod +x "$AUTO" run-worker.sh 2>/dev/null || true

# Add @reboot cron entry if missing
CRON_LINE="@reboot $AUTO"
(crontab -l 2>/dev/null | grep -Fv "$AUTO"; echo "$CRON_LINE") | crontab -
echo "Installed auto worker at reboot via crontab."
echo "Starting now..."
nohup "$AUTO" >/dev/null 2>&1 &
echo "Done. Log: web-data/worker-auto.log"
