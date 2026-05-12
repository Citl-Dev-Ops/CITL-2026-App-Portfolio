@echo off
REM =======================================================
REM  CITL FLEX Troubleshooter - USB/Windows Launcher
REM  Prefers packaged EXE in dist; falls back to bootstrap.
REM =======================================================
setlocal
set "ROOT=%~dp0"
set "EXE_ONEDIR=%ROOT%dist\CITL FLEX Troubleshooter\CITL FLEX Troubleshooter.exe"
set "EXE_ONEFILE=%ROOT%dist\CITL-FLEX-Troubleshooter.exe"
set "BOOTSTRAP=%ROOT%citl_bootstrap.py"

if exist "%EXE_ONEDIR%" (
    start "" "%EXE_ONEDIR%" %*
    exit /b 0
)

if exist "%EXE_ONEFILE%" (
    start "" "%EXE_ONEFILE%" %*
    exit /b 0
)

set "PY="
if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe >nul 2>&1 && set "PY=py -3" )
if not defined PY (
    powershell -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python 3.9+ is required but was not found.`n`nInstall Python from https://www.python.org/downloads/', 'CITL Bootstrap Error', 'OK', 'Error')"
    exit /b 1
)

if not exist "%BOOTSTRAP%" (
    echo ERROR: Bootstrap not found: %BOOTSTRAP%
    pause
    exit /b 1
)

%PY% "%BOOTSTRAP%" --app flex %*
endlocal
