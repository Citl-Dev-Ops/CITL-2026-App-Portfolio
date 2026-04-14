@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL AV IT Operations\CITL AV IT Operations.exe"

if exist "%EXE%" (
  "%EXE%" %*
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\run_av_it_ops.ps1" %*
set "EC=%ERRORLEVEL%"
if %EC% neq 0 pause
exit /b %EC%
