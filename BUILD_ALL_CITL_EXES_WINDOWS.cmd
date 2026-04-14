@echo off
setlocal
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\build_all_citl_exes.ps1" %*
set "EC=%ERRORLEVEL%"
if %EC% neq 0 pause
exit /b %EC%
