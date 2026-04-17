@echo off
REM ═══════════════════════════════════════════════════════════════
REM  CITL Factbook Pipeline Diagnostic — Windows USB Launcher
REM  Runs the 18-stage live pipeline test.
REM  Every failure shows exact error + exact fix command + Fix button.
REM ═══════════════════════════════════════════════════════════════
setlocal
set "ROOT=%~dp0"
set "DIAG=%ROOT%factbook-assistant\citl_factbook_diagnostic.py"

REM Add factbook-assistant to path
set "PYTHONPATH=%ROOT%factbook-assistant;%PYTHONPATH%"

REM Find Python
set "PY="
if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe    >nul 2>&1 && set "PY=py -3" )
if not defined PY (
    powershell -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python not found. Install Python 3.9+ from python.org', 'CITL Diagnostic Error', 'OK', 'Error')"
    exit /b 1
)

if not exist "%DIAG%" (
    echo ERROR: Diagnostic script not found: %DIAG%
    pause
    exit /b 1
)

%PY% "%DIAG%" %*
endlocal
