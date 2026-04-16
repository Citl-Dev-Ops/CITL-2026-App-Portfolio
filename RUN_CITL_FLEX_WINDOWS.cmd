@echo off
REM CITL FLEX Troubleshooter v1.0 — Windows launcher
setlocal
set "ROOT=%~dp0"
set "EXE=%ROOT%dist\CITL-FLEX-Troubleshooter.exe"
set "SCRIPT=%ROOT%citl_flex_troubleshooter\flex_troubleshooter_gui.py"

REM Try built EXE first
if exist "%EXE%" ( start "" "%EXE%" %* & exit /b 0 )

REM Find Python
set "PY="
if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe >nul 2>&1 && set "PY=py -3" )
if not defined PY (
    echo ERROR: Python not found. Install Python 3.9+ or run INSTALL_CITL_APPS_PORTABLE.cmd
    pause
    exit /b 1
)

%PY% "%SCRIPT%" %*
endlocal