@echo off
title UTS Test Automation
color 0A
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

echo.
echo  ====================================================================
echo   UTS TEST AUTOMATION  —  TWO RUNS (same RUN.bat)
echo.
echo   RUN 1  SCAN MODULES
echo            config\app-input.json me  "module": ""
echo            RUN.bat chalao
echo            -^> Login + scan all modules
echo            -^> Output: generated\modules.json
echo            -^> STOP  (test cases nahi banenge)
echo.
echo   RUN 2  CREATE TEST CASES (selected module)
echo            app-input.json me module daalo:
echo              "module": "Admin"
echo              "module": "Admin#PIM"   (multiple)
echo            SAME RUN.bat dubara chalao
echo            -^> Create TCs for that module only + ALM + Xpedite
echo            -^> Automation NAHI chalega (default)
echo.
echo   RUN 3  RUN AUTOMATION (optional — sirf jab user bole)
echo            app-input.json me  "run_automation": true  karo
echo            SAME RUN.bat dubara chalao
echo            -^> TCs + automation run + report
echo  ====================================================================
echo.

pip show selenium >nul 2>&1
if errorlevel 1 (
  echo [SETUP] Installing dependencies...
  pip install -r "%~dp0requirements.txt" -q
  echo.
)

python "%~dp0run_automation_only.py" %*
set EXIT_CODE=%ERRORLEVEL%

echo.
pause
exit /b %EXIT_CODE%
