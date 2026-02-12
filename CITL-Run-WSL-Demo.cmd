@echo off
setlocal enabledelayedexpansion

echo ==============================================
echo CITL Ubuntu Launcher Demo (via WSL)
echo ==============================================

where wsl.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: WSL not found.
  echo Install WSL + Ubuntu, then re-run this.
  pause
  exit /b 1
)

REM Convert this folder (repo root) to a WSL path
for /f "usebackq delims=" %%P in (`wsl.exe wslpath -a "%~dp0"`) do set "WSLROOT=%%P"

echo Repo (Windows): %~dp0
echo Repo (WSL)    : %WSLROOT%
echo.

REM Run the Ubuntu script in demo mode (console-only)
wsl.exe -- bash -lc "cd '%WSLROOT%' && chmod +x scripts/run_ubuntu.sh && ./scripts/run_ubuntu.sh --demo"

echo.
echo Done.
pause
