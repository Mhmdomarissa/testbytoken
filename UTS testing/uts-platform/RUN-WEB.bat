@echo off
setlocal EnableExtensions
title UTS Automation Platform

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
  echo Python 3.10+ was not found.
  echo Install Python and select "Add Python to PATH".
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy ".env.example" ".env" >nul
    echo Created .env from .env.example
  ) else if exist "env.template" (
    copy "env.template" ".env" >nul
    echo Created .env from env.template
  ) else (
    echo Creating default .env file...
    (
      echo DATABASE_URL=mysql+pymysql://uts_user:uts_password@127.0.0.1:3306/uts_platform
      echo UTS_SECRET_KEY=replace-with-a-long-random-secret
      echo UTS_ADMIN_USERNAME=admin
      echo UTS_ADMIN_PASSWORD=admin123
      echo UTS_HOST=0.0.0.0
      echo UTS_PORT=5050
      echo UTS_OPEN_BROWSER=true
      echo UTS_BROWSER_URL=http://127.0.0.1:5050
      echo UTS_NETWORK_IPS=192.168.0.107,192.168.1.24
      echo UTS_PUBLIC_URL=http://192.168.1.24:5050
    ) > ".env"
  )
)

if not exist "web-data" mkdir "web-data"

if not exist ".venv\Scripts\python.exe" (
  echo First-time setup: creating the Python environment...
  %PY% -m venv ".venv"
  if errorlevel 1 (
    echo ERROR: Could not create the Python environment.
    pause
    exit /b 1
  )
)

set "APP_PY=%ROOT%.venv\Scripts\python.exe"
"%APP_PY%" -c "import flask, flask_sqlalchemy, selenium, dotenv, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo First-time setup: installing required packages...
  "%APP_PY%" -m pip install -r "%ROOT%requirements.txt"
  if errorlevel 1 (
    echo ERROR: Package installation failed. Check the internet connection.
    pause
    exit /b 1
  )
)

rem Use the automatic local database even with an older .env file.
set "DATABASE_URL=sqlite:///web-data/uts_platform.db"
set "UTS_BROWSER_URL=http://127.0.0.1:5050"
set "UTS_HOST=0.0.0.0"
set "UTS_NETWORK_IPS=192.168.0.107,192.168.1.24"

echo ============================================
echo  UTS Automation Platform
echo ============================================
echo Local URL   : http://127.0.0.1:5050
echo Ethernet URL: http://192.168.0.107:5050
echo Wi-Fi URL   : http://192.168.1.24:5050
echo Press Ctrl+C to stop.
echo.

"%APP_PY%" "%ROOT%run_web.py"
set "ERR=%ERRORLEVEL%"

if %ERR% NEQ 0 (
  echo.
  echo Web platform stopped with error %ERR%.
  pause
)
exit /b %ERR%
