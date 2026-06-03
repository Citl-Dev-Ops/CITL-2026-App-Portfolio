@echo off
REM ================================================================
REM  CITL PRESENTATION SUITE LAUNCHER
REM  Checks dist\ (built EXE), then old deployment folders,
REM  then falls back to direct Python launch — never hard-fails.
REM  If script is missing: runs REPAIR_CITL_APPS.cmd automatically.
REM ================================================================
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "SCRIPT=%ROOT%\factbook-assistant\citl_llmops_suite.py"
set "PPATH=%ROOT%\factbook-assistant;%ROOT%"

REM -- Try EXE from dist\ (primary — built by BUILD_ALL_CITL_EXES_WINDOWS.cmd)
set "EXE=%ROOT%\dist\CITL LLMOps Presentation Suite\CITL LLMOps Presentation Suite.exe"
if exist "%EXE%" ( start "" "%EXE%" & exit /b 0 )

REM -- Try legacy deployment folders
for %%F in (
    "%ROOT%\2-CITL-PRESENTATION-SUITE\CITL LLMOps Presentation Suite\CITL LLMOps Presentation Suite.exe"
    "%ROOT%\2-CITL-PRESENTATION-SUITE\CITL LLMOps Presentation Suite.exe"
    "%ROOT%\CITL LLMOps Presentation Suite\CITL LLMOps Presentation Suite.exe"
) do ( if exist %%F ( start "" %%F & exit /b 0 ) )

REM -- Find Python
set "PY="
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not defined PY if exist "%ROOT%\Python\python.exe" set "PY=%ROOT%\Python\python.exe"
if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe >nul 2>&1 && set "PY=py.exe" )
if not defined PY (
    for %%D in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    ) do ( if exist %%D if not defined PY set "PY=%%~D" )
)

if not defined PY (
    echo [ERROR] Python not found. Running REPAIR_CITL_APPS.cmd to fix...
    start "" "%ROOT%\REPAIR_CITL_APPS.cmd"
    exit /b 1
)

REM -- Script missing? run repair, then try again
if not exist "%SCRIPT%" (
    echo [ERROR] Script not found: %SCRIPT%
    echo [AUTO]  Running REPAIR_CITL_APPS.cmd...
    call "%ROOT%\REPAIR_CITL_APPS.cmd"
    if exist "%SCRIPT%" goto :launch
    echo [ERROR] Repair could not restore the script. Check the CITL repo.
    pause
    exit /b 1
)

:launch
set "PYTHONPATH=%PPATH%;%PYTHONPATH%"
"%PY%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%
