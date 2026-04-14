@echo off
setlocal
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\sync_usb_apps.ps1" %*
if %ERRORLEVEL% neq 0 pause
exit /b %ERRORLEVEL%
