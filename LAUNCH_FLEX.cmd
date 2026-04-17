@echo off
REM ═══════════════════════════════════════════════════════
REM  CITL FLEX Troubleshooter — USB/Windows Launcher
REM  Runs bootstrap first; shows GUI dialog if any issues
REM ═══════════════════════════════════════════════════════
setlocal
set "ROOT=%~dp0"
set "BOOTSTRAP=%ROOT%citl_bootstrap.py"
set "EXE=%ROOT%dist\CITL-FLEX-Troubleshooter.exe"

REM Try pre-built EXE first
if exist "%EXE%" (
    start "" "%EXE%"
    exit /b 0
)

REM Find Python
set "PY="
if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe    >nul 2>&1 && set "PY=py -3" )
if not defined PY (
    powershell -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python 3.9+ is required but was not found.^n^nInstall Python from https://www.python.org/downloads/', 'CITL Bootstrap Error', 'OK', 'Error')"
    exit /b 1
)

%PY% "%BOOTSTRAP%" --app flex
endlocal
