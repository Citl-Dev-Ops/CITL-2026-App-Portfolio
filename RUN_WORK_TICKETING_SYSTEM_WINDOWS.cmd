@echo off
setlocal enableextensions
set "ROOT=%~dp0"
set "RUNNER=%ROOT%scripts\windows\run_work_ticketing_system.ps1"

if not exist "%RUNNER%" (
  echo [FAIL] Missing launcher script:
  echo   %RUNNER%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%RUNNER%" %*
exit /b %ERRORLEVEL%
