@echo off
REM ================================================================
REM  CITL FIELD APPS LAUNCHER
REM  dist\ EXE → legacy folders → Python script → auto-repair
REM ================================================================
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "SCRIPT=%ROOT%\factbook-assistant\citl_field_apps.py"
set "PPATH=%ROOT%\factbook-assistant;%ROOT%"

set "EXE=%ROOT%\dist\CITL Field Apps\CITL Field Apps.exe"
if exist "%EXE%" ( start "" "%EXE%" & exit /b 0 )

for %%F in (
    "%ROOT%\4-CITL-FIELD-APPS\CITL Field Apps\CITL Field Apps.exe"
    "%ROOT%\4-CITL-FIELD-APPS\CITL Field Apps.exe"
    "%ROOT%\CITL Field Apps\CITL Field Apps.exe"
) do ( if exist %%F ( start "" %%F & exit /b 0 ) )

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
if not defined PY ( start "" "%ROOT%\REPAIR_CITL_APPS.cmd" & exit /b 1 )

if not exist "%SCRIPT%" (
    echo [AUTO] Script missing — running REPAIR_CITL_APPS.cmd...
    call "%ROOT%\REPAIR_CITL_APPS.cmd"
    if not exist "%SCRIPT%" ( echo [ERROR] Repair failed. & pause & exit /b 1 )
)

set "PYTHONPATH=%PPATH%;%PYTHONPATH%"
"%PY%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%
