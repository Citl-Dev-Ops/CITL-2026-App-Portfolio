@echo off
setlocal
set "SCRIPT=%~dp0apply_bootstrap_M-20260430T004440Z-df034b6967.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%
