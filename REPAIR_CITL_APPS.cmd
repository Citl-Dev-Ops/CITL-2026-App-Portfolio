@echo off
REM ================================================================
REM  CITL UNIVERSAL REPAIR TOOL  (Windows)
REM  Double-click this to:
REM    1. Search this PC for all CITL / Factbook installs
REM    2. Run 18-stage diagnostic on each found install
REM    3. Offer one-click Fix buttons for every identified error
REM    4. Patch latest repair scripts into found installs
REM
REM  Works from USB - no install required.
REM ================================================================
title CITL Universal Repair Tool
color 1F
echo.
echo  ============================================================
echo   CITL UNIVERSAL REPAIR TOOL
echo   Searching for CITL installs and diagnosing problems...
echo  ============================================================
echo.
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "REPAIR=%ROOT%factbook-assistant\citl_repair_all.py"
set "BOOTSTRAP=%ROOT%citl_bootstrap.py"
set "PYTHONPATH=%ROOT%factbook-assistant;%PYTHONPATH%"
set "PATCH_RUNNER=%ROOT%PATCH_CITL_48H_AUTO_WINDOWS.cmd"

set "PY="
if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe >nul 2>&1 && set "PY=py -3" )

if not defined PY (
    echo.
    echo  ERROR: Python 3.9+ not found on this machine.
    echo  Install from https://python.org and re-run.
    echo.
    powershell -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python 3.9+ not found.`n`nInstall from python.org then re-run REPAIR_CITL_APPS.cmd', 'CITL Repair', 'OK', 'Error')"
    pause
    exit /b 1
)

echo  Python found: !PY!

if /I "%1"=="--clone-usb-target" (
    if "%~2"=="" (
        echo  ERROR: Missing target path. Example:
        echo    REPAIR_CITL_APPS.cmd --clone-usb-target F:\
        exit /b 1
    )
    echo  Starting USB clone flow via CITL Sync utility...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%Run-CITL-App-Sync.ps1" --clone-usb-target "%~2"
    exit /b %ERRORLEVEL%
)

if exist "%PATCH_RUNNER%" (
    echo  Running automatic patch cadence check...
    call "%PATCH_RUNNER%"
)

if exist "%REPAIR%" (
    echo  Starting CITL Repair All GUI...
    !PY! "%REPAIR%"
    goto :done
)

if exist "%BOOTSTRAP%" (
    echo  Repair All not found. Starting Bootstrap Diagnostic...
    !PY! "%BOOTSTRAP%" --gui
    goto :done
)

echo.
echo  ERROR: Repair scripts not found on this drive.
echo  This USB drive may be out of date.
echo  Sync from: https://github.com/your-org/CITL
echo.
pause
exit /b 1

:done
endlocal
