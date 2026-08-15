@echo off
setlocal EnableExtensions
title UTS Connect This PC
color 0B

set "SERVER=http://144.91.113.113:5050"
set "WUSER=JackTest"
set "INSTALL=%LOCALAPPDATA%\UTS-Worker"
set "ZIP=%TEMP%\UTS-Worker-Package.zip"
set "PYZIP=%TEMP%\portable-python-win64.zip"
set "PY=%INSTALL%\runtime\python.exe"

echo.
echo  ============================================================
echo   UTS CONNECT THIS PC  (simple worker setup)
echo   Server : %SERVER%
echo   User   : %WUSER%
echo   Folder : %INSTALL%
echo  ============================================================
echo.

echo [0/7] Stopping any old UTS worker (required before reinstall)...
taskkill /F /FI "WINDOWTITLE eq UTS Worker Agent*" 2>nul
taskkill /F /FI "WINDOWTITLE eq UTS-Worker-Auto*" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process -Filter "Name='python.exe'" ^| Where-Object { $_.CommandLine -match 'UTS-Worker|worker\\agent.py' } ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo [1/7] Downloading worker package...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Invoke-WebRequest -Uri '%SERVER%/download/worker-package.zip' -OutFile '%ZIP%' -UseBasicParsing; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
  echo Download failed. Check network / server URL.
  pause
  exit /b 1
)

echo [2/7] Downloading portable Python 3.12...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Invoke-WebRequest -Uri '%SERVER%/download/portable-python-win64.zip' -OutFile '%PYZIP%' -UseBasicParsing; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
  echo Portable Python download failed.
  pause
  exit /b 1
)

echo [3/7] Removing old install folder...
if exist "%INSTALL%" (
  rmdir /s /q "%INSTALL%" 2>nul
  if exist "%INSTALL%" (
    echo.
    echo ERROR: Could not delete %INSTALL%
    echo Close any UTS-Worker / black python windows, then run this .bat again.
    echo Or delete the folder manually and retry.
    pause
    exit /b 1
  )
)
mkdir "%INSTALL%" 2>nul

echo [4/7] Unpacking worker + portable Python...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -Path '%ZIP%' -DestinationPath '%TEMP%\UTS-Worker-Unpack' -Force; Copy-Item -Path '%TEMP%\UTS-Worker-Unpack\UTS-Worker\*' -Destination '%INSTALL%' -Recurse -Force; Expand-Archive -Path '%PYZIP%' -DestinationPath '%INSTALL%' -Force"
if not exist "%INSTALL%\worker\agent.py" (
  echo ERROR: Unpack failed — worker\agent.py missing.
  pause
  exit /b 1
)
if not exist "%PY%" (
  echo ERROR: Portable Python missing at %PY%
  pause
  exit /b 1
)

echo [5/7] Installing packages with portable Python 3.12...
cd /d "%INSTALL%"
"%PY%" -m pip install --upgrade pip --no-warn-script-location
"%PY%" -m pip install -r requirements.txt --no-warn-script-location --no-cache-dir
if errorlevel 1 (
  echo pip install blocked — stopping worker again and retrying...
  taskkill /F /FI "WINDOWTITLE eq UTS Worker Agent*" 2>nul
  taskkill /F /FI "WINDOWTITLE eq UTS-Worker-Auto*" 2>nul
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-CimInstance Win32_Process -Filter "Name='python.exe'" ^| Where-Object { $_.CommandLine -match 'UTS-Worker|worker\\agent.py' } ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
  timeout /t 2 /nobreak >nul
  if exist "%INSTALL%\runtime\Lib\site-packages" rmdir /s /q "%INSTALL%\runtime\Lib\site-packages" 2>nul
  mkdir "%INSTALL%\runtime\Lib\site-packages" 2>nul
  "%PY%" -m pip install -r requirements.txt --no-warn-script-location --no-cache-dir --ignore-installed
  if errorlevel 1 (
    echo.
    echo pip install failed (Access denied usually means worker still running).
    echo 1. Close all UTS-Worker windows
    echo 2. Open Task Manager - end any python.exe from UTS-Worker
    echo 3. Delete: %INSTALL%
    echo 4. Run this .bat again
    pause
    exit /b 1
  )
)

echo.
set /p WPASS=Enter UTS password for %WUSER%: 
if "%WPASS%"=="" set "WPASS=admin"

(
  echo UTS_SERVER_URL=%SERVER%
  echo UTS_WORKER_USERNAME=%WUSER%
  echo UTS_WORKER_PASSWORD=%WPASS%
  echo UTS_WORKER_BROWSER=chrome
) > "%INSTALL%\worker.env"

if not exist "%INSTALL%\web-data" mkdir "%INSTALL%\web-data"

echo [6/7] Startup folder — skipped (no automatic install).
echo         To auto-start later, run INSTALL-AUTO-WORKER.bat manually.

echo [7/7] Starting worker for this session only...
start "UTS-Worker-Auto" /MIN "%INSTALL%\RUN-WORKER-AUTO.bat"

echo.
echo  DONE. Refresh UTS — header should show Worker · ThisPC
echo  Nothing was added to Windows Startup automatically.
echo.
pause
endlocal
