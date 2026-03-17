@echo off
setlocal

set "HERE=%~dp0"
set "EXTRA="

REM Pass --desktop flag through to PowerShell if requested
if /i "%1"=="--desktop" set "EXTRA=-Desktop"

echo.
echo  CITL Unified Update
echo  Updates Python packages, Ollama, FFmpeg, and shortcuts.
echo  Pass --desktop to also create Desktop shortcuts.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\update.ps1" %EXTRA%

if %ERRORLEVEL% neq 0 (
  echo.
  echo  Update encountered an error (exit code %ERRORLEVEL%).
  pause
)
