@echo off
setlocal EnableExtensions
title UTS Uninstall Auto Worker
cd /d "%~dp0"

schtasks /Delete /TN "UTS_Worker_AutoStart" /F >nul 2>&1
echo Removed scheduled task (if present).

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=Join-Path ([Environment]::GetFolderPath('Startup')) 'UTS-Worker-Auto.lnk'; if (Test-Path $p) { Remove-Item $p -Force; Write-Host 'Removed Startup shortcut.' } else { Write-Host 'No Startup shortcut found.' }"

taskkill /FI "WINDOWTITLE eq UTS Worker Agent (Auto)*" /F >nul 2>&1
echo Done.
pause
endlocal
