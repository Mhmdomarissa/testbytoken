@echo off
setlocal EnableExtensions
title UTS - Reset Admin Login
cd /d "%~dp0"

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python not found.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating environment...
  %PY% -m venv ".venv"
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

if not exist ".env" copy ".env.example" ".env" >nul

echo Resetting admin login to values from .env ...
".venv\Scripts\python.exe" -c "from dotenv import load_dotenv; load_dotenv(); from webapp import create_app; from webapp.models import User, db; app=create_app(); ctx=app.app_context(); ctx.push(); u=User.query.filter(db.func.lower(User.username)=='admin').first(); print('OK admin ready' if u else 'ERROR admin missing'); print('Login: admin / ' + (__import__('os').getenv('UTS_ADMIN_PASSWORD') or 'admin'))"

echo.
echo Done. Start with RUN-WEB.bat then open http://127.0.0.1:5050/login
echo Username: admin
echo Password: admin
pause
endlocal
