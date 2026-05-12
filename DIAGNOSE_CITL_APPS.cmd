@echo off
REM ================================================================
REM  CITL FACTBOOK DIAGNOSTIC  (Windows)
REM  Double-click to run the 18-stage live pipeline test.
REM  Every failure shows exact error + exact fix command.
REM  Fix buttons run the repair directly from this window.
REM ================================================================
title CITL Factbook Diagnostic
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "DIAG=%ROOT%factbook-assistant\citl_factbook_diagnostic.py"
set "PYTHONPATH=%ROOT%factbook-assistant;%PYTHONPATH%"

set "PY="
if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY ( where python.exe >/dev/null 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe >/dev/null 2>&1 && set "PY=py -3" )

if not defined PY (
    powershell -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python 3.9+ not found.`n`nInstall from https://python.org', 'CITL Diagnostic', 'OK', 'Error')"
    exit /b 1
)

if not exist "%DIAG%" (
    echo ERROR: %DIAG% not found.
    echo Run REPAIR_CITL_APPS.cmd first to install repair scripts.
    pause
    exit /b 1
)

echo Running CITL Factbook Diagnostic (GUI mode)...
!PY! "%DIAG%"
endlocal
