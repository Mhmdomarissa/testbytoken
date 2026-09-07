@echo off
title UTS Worker Agent
color 0B
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

echo.
echo  ====================================================================
echo   UTS WORKER AGENT  —  browser opens on THIS Windows PC
echo.
echo   Tip: run INSTALL-AUTO-WORKER.bat once to start this automatically
echo        at every Windows login (no manual step).
echo  ====================================================================
echo.

if exist "%~dp0worker.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0worker.env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

if "%UTS_SERVER_URL%"=="" (
  set /p UTS_SERVER_URL=Central UTS server URL [http://144.91.113.113:5050]: 
)
if "%UTS_SERVER_URL%"=="" set UTS_SERVER_URL=http://144.91.113.113:5050

if exist "%~dp0runtime\python.exe" (
  set "PY=%~dp0runtime\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

if not "%UTS_WORKER_USERNAME%"=="" if not "%UTS_WORKER_PASSWORD%"=="" (
  "%PY%" -u "%~dp0worker\agent.py" --server "%UTS_SERVER_URL%" --username "%UTS_WORKER_USERNAME%" --password "%UTS_WORKER_PASSWORD%" --browser "%UTS_WORKER_BROWSER%" %*
) else (
  "%PY%" -u "%~dp0worker\agent.py" --server "%UTS_SERVER_URL%" %*
)
set EXIT_CODE=%ERRORLEVEL%
echo.
pause
exit /b %EXIT_CODE%
