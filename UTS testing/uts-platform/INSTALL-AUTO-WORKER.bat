@echo off
setlocal EnableExtensions
title UTS Install Auto Worker
cd /d "%~dp0"

echo ============================================================
echo  Install automatic UTS Worker (Windows Startup folder)
echo  After install, worker starts every time you log into Windows.
echo  Browser on THIS PC opens when you Scan/Run on the server.
echo ============================================================
echo.

if not exist "worker.env" (
  if exist "worker.env.example" (
    copy "worker.env.example" "worker.env" >nul
    echo Created worker.env from worker.env.example
  ) else (
    (
      echo UTS_SERVER_URL=http://144.91.113.113:5050
      echo UTS_WORKER_USERNAME=admin
      echo UTS_WORKER_PASSWORD=admin
      echo UTS_WORKER_BROWSER=chrome
    ) > "worker.env"
    echo Created worker.env
  )
)

echo.
echo Edit worker.env if needed, then press any key to install...
notepad "worker.env"
pause

if not exist "web-data" mkdir "web-data"

set "TASK=UTS_Worker_AutoStart"
set "TR=%~dp0RUN-WORKER-AUTO.bat"

REM Always install Startup-folder shortcut (works without Admin)
echo Installing Startup-folder auto-start...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$startup=[Environment]::GetFolderPath('Startup'); $lnk=Join-Path $startup 'UTS-Worker-Auto.lnk'; $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($lnk); $s.TargetPath='%~dp0RUN-WORKER-AUTO.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Description='UTS Worker Agent (auto-start)'; $s.Save(); Write-Host ('Startup shortcut: ' + $lnk)"

REM Optional: also create logon scheduled task when permitted
schtasks /Delete /TN "%TASK%" /F >nul 2>&1
schtasks /Create /TN "%TASK%" /SC ONLOGON /TR "\"%TR%\"" /F >nul 2>&1
if errorlevel 1 (
  echo Scheduled task skipped (needs Admin). Startup folder is enough.
) else (
  echo Scheduled task also created: %TASK%
)

echo.
echo Starting worker now...
start "UTS-Worker-Auto" /MIN "%TR%"

echo.
echo DONE.
echo  - Worker starts automatically at every Windows login
echo  - Startup shortcut: %%APPDATA%%\Microsoft\Windows\Start Menu\Programs\Startup\UTS-Worker-Auto.lnk
echo  - Config: worker.env
echo  - Log: web-data\worker-auto.log
echo.
echo To remove auto-start later: run UNINSTALL-AUTO-WORKER.bat
pause
endlocal
