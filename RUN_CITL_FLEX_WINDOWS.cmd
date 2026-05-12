@echo off
REM CITL FLEX Troubleshooter v1.1 - Windows launcher (dist-first, legacy-safe)
setlocal
set "ROOT=%~dp0"
set "EXE_ONEDIR=%ROOT%dist\CITL FLEX Troubleshooter\CITL FLEX Troubleshooter.exe"
set "EXE_ONEFILE=%ROOT%dist\CITL-FLEX-Troubleshooter.exe"
set "EXE_BUILD=%ROOT%build\CITL FLEX Troubleshooter\CITL FLEX Troubleshooter.exe"
set "SCRIPT=%ROOT%citl_flex_troubleshooter\flex_assistant_gui.py"

REM Preferred launch path (current PyInstaller --windowed onedir output)
if exist "%EXE_ONEDIR%" (
    start "" "%EXE_ONEDIR%" %*
    exit /b 0
)

REM Legacy onefile output support
if exist "%EXE_ONEFILE%" (
    start "" "%EXE_ONEFILE%" %*
    exit /b 0
)

REM Last-resort legacy build artifact
if exist "%EXE_BUILD%" (
    echo [WARN] Dist EXE not found; using legacy build artifact.
    start "" "%EXE_BUILD%" %*
    exit /b 0
)

REM Python fallback
set "PY="
if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe >nul 2>&1 && set "PY=py -3" )
if not defined PY (
    echo ERROR: Python not found. Install Python 3.9+ or run INSTALL_CITL_APPS_PORTABLE.cmd
    pause
    exit /b 1
)

if not exist "%SCRIPT%" (
    echo ERROR: FLEX launcher script not found: %SCRIPT%
    pause
    exit /b 1
)

%PY% "%SCRIPT%" %*
exit /b %ERRORLEVEL%
