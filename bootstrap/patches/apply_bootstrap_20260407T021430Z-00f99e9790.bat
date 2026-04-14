@echo off
setlocal
set "SCRIPT=%~dp0apply_bootstrap_20260407T021430Z-00f99e9790.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%
