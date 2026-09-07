@echo off
title UTS AI Automation
color 0B
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

echo.
echo  ====================================================================
echo   UTS AI  —  URL se samajho, phir automation banao
echo.
echo   Concepts covered:
echo     Link / Object / Enter / SendKeys / Verification
echo     Data-driven / BDD (Given-When-Then)
echo.
echo   Config:
echo     config\app-input.json  — url, username, password, module
echo     config\ai.json         — provider offline|openai|ollama|...
echo     .env                   — UTS_AI_API_KEY (optional live LLM)
echo.
echo   Offline AI planner works without any API key.
echo  ====================================================================
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" "%~dp0run_ai.py" %*
set EXIT_CODE=%ERRORLEVEL%

echo.
pause
exit /b %EXIT_CODE%
