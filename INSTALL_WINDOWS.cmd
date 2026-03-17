@echo off
setlocal
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\setup.ps1" %*
exit /b %ERRORLEVEL%
