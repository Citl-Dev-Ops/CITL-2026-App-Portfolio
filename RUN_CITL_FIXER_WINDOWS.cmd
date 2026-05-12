@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "EXE_ONEDIR=%ROOT%dist\CITL Fixer\CITL Fixer.exe"
set "EXE_ONEFILE=%ROOT%dist\CITL Fixer.exe"
set "SCRIPT=%ROOT%citl_fixer.py"

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
if not defined PY (
    where py.exe >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
    where python.exe >nul 2>&1
    if not errorlevel 1 set "PY=python.exe"
)
if not defined PY (
    echo [FAIL] Python 3 not found. Install Python 3.9+ or run INSTALL_CITL_APPS_PORTABLE.cmd
    pause
    exit /b 1
)

if not exist "%SCRIPT%" (
    echo [FAIL] Fixer script not found: %SCRIPT%
    pause
    exit /b 1
)

%PY% "%SCRIPT%" %*
exit /b %ERRORLEVEL%
