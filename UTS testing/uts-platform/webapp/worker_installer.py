"""Shared one-click worker installer generators (.bat for Windows, .sh for macOS)."""

from __future__ import annotations


def _safe_username(username: str) -> str:
    return (username or "user").replace('"', "").replace("'", "").strip() or "user"


def _safe_server(server_url: str) -> str:
    return (server_url or "").rstrip("/").replace('"', "")


def build_oneclick_bat(*, server_url: str, username: str) -> tuple[str, str]:
    """Return (filename, bat_content) for portable Python one-click install."""
    safe_user = _safe_username(username).replace("%", "%%")
    safe_server = _safe_server(server_url).replace("%", "%%")

    content = f"""@echo off
setlocal EnableExtensions
title UTS Connect This PC
color 0B

set "SERVER={safe_server}"
set "WUSER={safe_user}"
set "INSTALL=%LOCALAPPDATA%\\UTS-Worker"
set "ZIP=%TEMP%\\UTS-Worker-Package.zip"
set "PYZIP=%TEMP%\\portable-python-win64.zip"
set "PY=%INSTALL%\\runtime\\python.exe"

echo.
echo  ============================================================
echo   UTS CONNECT THIS PC  (simple worker setup)
echo   Server : %SERVER%
echo   User   : %WUSER%
echo   Folder : %INSTALL%
echo  ============================================================
echo.

echo [0/7] Stopping any old UTS worker (required before reinstall)...
taskkill /F /FI "WINDOWTITLE eq UTS Worker Agent*" 2>nul
taskkill /F /FI "WINDOWTITLE eq UTS-Worker-Auto*" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" ^| Where-Object {{ $_.CommandLine -match 'UTS-Worker|worker\\\\agent.py' }} ^| ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
timeout /t 2 /nobreak >nul

echo [1/7] Downloading worker package...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try {{ Invoke-WebRequest -Uri '%SERVER%/download/worker-package.zip' -OutFile '%ZIP%' -UseBasicParsing; exit 0 }} catch {{ Write-Host $_.Exception.Message; exit 1 }}"
if errorlevel 1 (
  echo Download failed. Check network / server URL.
  pause
  exit /b 1
)

echo [2/7] Downloading portable Python 3.12...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try {{ Invoke-WebRequest -Uri '%SERVER%/download/portable-python-win64.zip' -OutFile '%PYZIP%' -UseBasicParsing; exit 0 }} catch {{ Write-Host $_.Exception.Message; exit 1 }}"
if errorlevel 1 (
  echo Portable Python download failed.
  pause
  exit /b 1
)

echo [3/7] Removing old install folder...
if exist "%INSTALL%" (
  rmdir /s /q "%INSTALL%" 2>nul
  if exist "%INSTALL%" (
    echo.
    echo ERROR: Could not delete %INSTALL%
    echo Close any UTS-Worker / black python windows, then run this .bat again.
    echo Or delete the folder manually and retry.
    pause
    exit /b 1
  )
)
mkdir "%INSTALL%" 2>nul

echo [4/7] Unpacking worker + portable Python...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -Path '%ZIP%' -DestinationPath '%TEMP%\\UTS-Worker-Unpack' -Force; Copy-Item -Path '%TEMP%\\UTS-Worker-Unpack\\UTS-Worker\\*' -Destination '%INSTALL%' -Recurse -Force; Expand-Archive -Path '%PYZIP%' -DestinationPath '%INSTALL%' -Force"
if not exist "%INSTALL%\\worker\\agent.py" (
  echo ERROR: Unpack failed — worker\\agent.py missing.
  pause
  exit /b 1
)
if not exist "%PY%" (
  echo ERROR: Portable Python missing at %PY%
  pause
  exit /b 1
)

echo [5/7] Installing packages with portable Python 3.12...
cd /d "%INSTALL%"
"%PY%" -m pip install --upgrade pip --no-warn-script-location
"%PY%" -m pip install -r requirements.txt --no-warn-script-location --no-cache-dir
if errorlevel 1 (
  echo pip install blocked — stopping worker again and retrying...
  taskkill /F /FI "WINDOWTITLE eq UTS Worker Agent*" 2>nul
  taskkill /F /FI "WINDOWTITLE eq UTS-Worker-Auto*" 2>nul
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" ^| Where-Object {{ $_.CommandLine -match 'UTS-Worker|worker\\\\agent.py' }} ^| ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
  timeout /t 2 /nobreak >nul
  if exist "%INSTALL%\\runtime\\Lib\\site-packages" rmdir /s /q "%INSTALL%\\runtime\\Lib\\site-packages" 2>nul
  mkdir "%INSTALL%\\runtime\\Lib\\site-packages" 2>nul
  "%PY%" -m pip install -r requirements.txt --no-warn-script-location --no-cache-dir --ignore-installed
  if errorlevel 1 (
    echo.
    echo pip install failed (Access denied usually means worker still running).
    echo 1. Close all UTS-Worker windows
    echo 2. Open Task Manager - end any python.exe from UTS-Worker
    echo 3. Delete: %INSTALL%
    echo 4. Run this .bat again
    pause
    exit /b 1
  )
)

echo.
set /p WPASS=Enter UTS password for %WUSER%: 
if "%WPASS%"=="" set "WPASS=admin"

(
  echo UTS_SERVER_URL=%SERVER%
  echo UTS_WORKER_USERNAME=%WUSER%
  echo UTS_WORKER_PASSWORD=%WPASS%
  echo UTS_WORKER_BROWSER=chrome
) > "%INSTALL%\\worker.env"

if not exist "%INSTALL%\\web-data" mkdir "%INSTALL%\\web-data"

echo [6/7] Startup folder — skipped (no automatic install).
echo         To auto-start later, run INSTALL-AUTO-WORKER.bat manually.

echo [7/7] Starting worker for this session only...
start "UTS-Worker-Auto" /MIN "%INSTALL%\\RUN-WORKER-AUTO.bat"

echo.
echo  DONE. Refresh UTS — header should show Worker · ThisPC
echo  Nothing was added to Windows Startup automatically.
echo.
pause
endlocal
"""
    return f"UTS-Connect-{safe_user}.bat", content


def build_oneclick_sh(*, server_url: str, username: str) -> tuple[str, str]:
    """Return (filename, sh_content) for macOS one-click worker install."""
    safe_user = _safe_username(username)
    safe_server = _safe_server(server_url)

    content = f"""#!/usr/bin/env bash
# UTS Connect This Mac — one-click worker setup
set -euo pipefail

SERVER="{safe_server}"
WUSER="{safe_user}"
INSTALL="${{HOME}}/UTS-Worker"
ZIP="${{TMPDIR:-/tmp}}/UTS-Worker-Package.zip"
UNPACK="${{TMPDIR:-/tmp}}/UTS-Worker-Unpack"

echo
echo "============================================================"
echo " UTS CONNECT THIS MAC"
echo " Server : $SERVER"
echo " User   : $WUSER"
echo " Folder : $INSTALL"
echo "============================================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install from https://www.python.org/downloads/ and retry."
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required (usually pre-installed on macOS)."
  exit 1
fi

echo "[1/5] Downloading worker package..."
curl -fsSL "$SERVER/download/worker-package.zip" -o "$ZIP"

echo "[2/5] Installing to $INSTALL ..."
rm -rf "$INSTALL" "$UNPACK"
mkdir -p "$UNPACK"
unzip -q -o "$ZIP" -d "$UNPACK"
mkdir -p "$INSTALL"
cp -R "$UNPACK/UTS-Worker/." "$INSTALL/"
cd "$INSTALL"

if [ ! -f worker/agent.py ]; then
  echo "ERROR: worker/agent.py missing after unpack."
  exit 1
fi

echo "[3/5] Creating Python environment (first time may take a few minutes)..."
chmod +x setup.sh run-worker.sh 2>/dev/null || true
./setup.sh

echo
read -rsp "Enter UTS password for $WUSER: " WPASS
echo
if [ -z "$WPASS" ]; then WPASS="admin"; fi

cat > worker.env <<EOF
UTS_SERVER_URL=$SERVER
UTS_WORKER_USERNAME=$WUSER
UTS_WORKER_PASSWORD=$WPASS
UTS_WORKER_BROWSER=chrome
EOF

mkdir -p web-data

echo "[4/5] Starting worker in background..."
if pgrep -f "$INSTALL/worker/agent.py" >/dev/null 2>&1; then
  pkill -f "$INSTALL/worker/agent.py" || true
  sleep 1
fi
nohup "$INSTALL/.venv/bin/python" -u "$INSTALL/worker/agent.py" \\
  --server "$SERVER" \\
  --username "$WUSER" \\
  --password "$WPASS" \\
  --browser chrome >> "$INSTALL/web-data/worker-auto.log" 2>&1 &

echo "[5/5] Done."
echo
echo " Worker is running. Refresh UTS in your browser."
echo " Header should show: Worker · $(hostname -s 2>/dev/null || hostname)"
echo " Log: $INSTALL/web-data/worker-auto.log"
echo
echo " To start again later: cd ~/UTS-Worker && ./run-worker.sh"
echo
"""
    return f"UTS-Connect-{safe_user}.sh", content


def worker_installer_for_platform(
    *, server_url: str, username: str, platform: str = ""
) -> tuple[str, str]:
    """Pick Windows .bat or macOS .sh installer."""
    key = (platform or "").strip().lower()
    if key in {"mac", "macos", "darwin", "osx"}:
        return build_oneclick_sh(server_url=server_url, username=username)
    return build_oneclick_bat(server_url=server_url, username=username)


def is_mac_user_agent(user_agent: str) -> bool:
    ua = user_agent or ""
    return "Macintosh" in ua or "Mac OS X" in ua
