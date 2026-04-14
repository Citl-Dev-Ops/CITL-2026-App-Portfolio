@echo off
setlocal enableextensions enabledelayedexpansion

REM ============================================================
REM   CITL USB Clone Launcher (Windows)
REM   Copies this USB repository to another USB drive.
REM   Run this from the USB root — double-click or right-click
REM   "Run as administrator" if the format option is needed.
REM ============================================================

set "ROOT=%~dp0"
set "GUI_SCRIPT=%ROOT%factbook-assistant\citl_usb_clone_gui.py"
set "SYNC_SCRIPT=%ROOT%factbook-assistant\citl_app_sync.py"

REM ── Locate Python ─────────────────────────────────────────────────────────
set "PY="
if exist "%ROOT%.venv\Scripts\python.exe"  set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY if exist "%ROOT%Python\python.exe" set "PY=%ROOT%Python\python.exe"
if not defined PY (
    where python.exe >nul 2>&1
    if %ERRORLEVEL% equ 0 set "PY=python.exe"
)
if not defined PY (
    where py.exe >nul 2>&1
    if %ERRORLEVEL% equ 0 set "PY=py.exe"
)

if not defined PY (
    echo.
    echo [ERROR] Python 3 not found.
    echo Install Python 3.9+ from https://www.python.org/ and retry.
    echo.
    pause
    exit /b 1
)

REM ── Launch the Clone GUI (preferred) ──────────────────────────────────────
if exist "%GUI_SCRIPT%" (
    echo [info] Launching CITL USB Clone GUI...
    "%PY%" "%GUI_SCRIPT%" --source "%ROOT%"
    exit /b %ERRORLEVEL%
)

REM ── Fallback: command-line duplicate via citl_app_sync.py ─────────────────
if exist "%SYNC_SCRIPT%" (
    echo [info] GUI not found - running command-line clone...
    "%PY%" "%SYNC_SCRIPT%" --duplicate-usb --source "%ROOT%"
    if !ERRORLEVEL! equ 0 (
        echo.
        echo ============================================================
        echo   SUCCESS! USB clone complete.
        echo ============================================================
    ) else (
        echo.
        echo ============================================================
        echo   ERROR: Clone failed (exit code !ERRORLEVEL!^)
        echo ============================================================
    )
    echo.
    pause
    exit /b !ERRORLEVEL!
)

echo.
echo [ERROR] Neither citl_usb_clone_gui.py nor citl_app_sync.py found.
echo Expected under: %ROOT%factbook-assistant\
echo.
pause
exit /b 1
