@echo off
setlocal
set "SCRIPT=%~dp0apply_bootstrap_M-20260430T004242Z-a4e6a39923.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%
