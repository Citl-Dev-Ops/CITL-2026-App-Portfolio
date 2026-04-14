@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL Work and Preparedness Launcher\CITL Work and Preparedness Launcher.exe"

if exist "%EXE%" (
  "%EXE%" %*
  set "EC=%ERRORLEVEL%"
  if %EC% equ 0 exit /b 0
  echo [WARN] EXE launch failed with exit code %EC%. Falling back to Python launcher...
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\run_work_preparedness_launcher.ps1" %*
set "EC=%ERRORLEVEL%"
if %EC% neq 0 pause
exit /b %EC%
