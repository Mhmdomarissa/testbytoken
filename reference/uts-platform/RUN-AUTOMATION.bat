@echo off
title UTS Automation-Only — Xpedite Format
color 0A
cd /d "%~dp0"

echo.
echo  ====================================================================
echo   UTS AUTOMATION-ONLY RUNNER  (Xpedite Format)
echo   1. Edit config\app-input.json  (url, username, password)
echo   2. NO manual test cases — automation only
echo   3. Exports: TC_*.xml, BPW_*.xml, BC_*.xml, TestData.xlsx
echo   4. TestData.xlsx RowNum starts from 2
echo   5. On fail: no halt — logout, fresh login, retry, continue
echo  ====================================================================
echo.

pip show selenium >nul 2>&1
if errorlevel 1 (
  echo [SETUP] Installing dependencies...
  pip install -r "%~dp0requirements.txt" -q
  echo.
)

python "%~dp0run_automation_only.py"
set EXIT_CODE=%ERRORLEVEL%

echo.
pause
exit /b %EXIT_CODE%
