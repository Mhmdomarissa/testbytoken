@echo off
setlocal EnableExtensions
title Allow UTS Network Access

net session >nul 2>&1
if errorlevel 1 (
  echo Requesting Administrator permission...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo Adding Windows Firewall rule for UTS TCP port 5050...
netsh advfirewall firewall delete rule name="UTS Automation Platform 5050" >nul 2>&1
netsh advfirewall firewall add rule ^
  name="UTS Automation Platform 5050" ^
  dir=in action=allow protocol=TCP localport=5050 profile=private

if errorlevel 1 (
  echo.
  echo Failed to add the firewall rule.
  pause
  exit /b 1
)

echo.
echo Network access enabled:
echo   http://192.168.1.94:5050
echo.
echo Keep the Windows network profile set to Private.
pause
endlocal
