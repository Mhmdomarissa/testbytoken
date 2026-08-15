@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python 3.10+ was not found.
  pause
  exit /b 1
)

echo Installing UTS automation and web dependencies...
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example
)

echo.
echo Setup complete. Chrome and MySQL 8 are required.
echo.
echo CLI: double-click RUN.bat
echo Web: configure .env, run database\setup-mysql.sql, then RUN-WEB.bat
pause
endlocal
