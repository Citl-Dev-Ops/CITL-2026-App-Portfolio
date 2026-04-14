@echo off
setlocal enableextensions

set "ROOT=%~dp0"
set "EXE=%ROOT%1-CITL-SYNC\CITL Sync Hub\CITL Sync Hub.exe"
set "SCRIPT=%ROOT%factbook-assistant\citl_sync_hub.py"

REM ── Try pre-built EXE first ───────────────────────────────────────────────
if exist "%EXE%" (
    start "" "%EXE%"
    exit /b 0
)

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
    echo [ERROR] Python not found and no pre-built EXE available.
    echo Install Python 3.9+ from https://www.python.org/ then retry.
    echo.
    pause
    exit /b 1
)

if not exist "%SCRIPT%" (
    echo.
    echo [ERROR] Could not find: %SCRIPT%
    echo.
    pause
    exit /b 1
)

REM ── Launch via Python ─────────────────────────────────────────────────────
"%PY%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%
