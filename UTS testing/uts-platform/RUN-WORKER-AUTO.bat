@echo off
REM Non-interactive worker start (used by auto-start / scheduled task)
title UTS Worker Agent (Auto)
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

REM Load worker.env if present (KEY=VALUE lines)
if exist "%~dp0worker.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0worker.env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

if "%UTS_SERVER_URL%"=="" set "UTS_SERVER_URL=http://144.91.113.113:5050"
if "%UTS_WORKER_USERNAME%"=="" set "UTS_WORKER_USERNAME=admin"
if "%UTS_WORKER_PASSWORD%"=="" set "UTS_WORKER_PASSWORD=admin"
if "%UTS_WORKER_BROWSER%"=="" set "UTS_WORKER_BROWSER=chrome"

REM Prefer portable runtime (one-click), then venv, then system python
if exist "%~dp0runtime\python.exe" (
  set "PY=%~dp0runtime\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

if not exist "%~dp0web-data" mkdir "%~dp0web-data"
echo [%date% %time%] Auto worker starting for %UTS_SERVER_URL% using %PY% >> "%~dp0web-data\worker-auto.log"
"%PY%" -u "%~dp0worker\agent.py" --server "%UTS_SERVER_URL%" --username "%UTS_WORKER_USERNAME%" --password "%UTS_WORKER_PASSWORD%" --browser "%UTS_WORKER_BROWSER%" >> "%~dp0web-data\worker-auto.log" 2>&1
exit /b %ERRORLEVEL%
