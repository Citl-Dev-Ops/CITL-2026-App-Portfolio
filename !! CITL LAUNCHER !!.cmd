@echo off
REM ================================================================
REM  !! CITL LAUNCHER !!
REM  Primary entry point for this CITL USB drive.
REM  Sorts to the top of Windows Explorer on any drive letter.
REM  Launches the CITL App Launcher GUI (EXE first, Python fallback).
REM ================================================================
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL USB Launcher\CITL USB Launcher.exe"
set "SCRIPT=%HERE%citl_usb_launcher.py"

if exist "%EXE%" (
    start "" "%EXE%"
    exit /b 0
)

REM Python fallback
call "%HERE%_citl_env.cmd"
if not defined CITL_PY (
    powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python not found. Install Python 3.9+ from python.org, then re-run this launcher.','CITL Launcher','OK','Warning')"
    exit /b 1
)

if not exist "%SCRIPT%" (
    echo [ERROR] citl_usb_launcher.py not found at %SCRIPT%
    pause
    exit /b 1
)

start "" %CITL_PY% "%SCRIPT%"
exit /b 0
