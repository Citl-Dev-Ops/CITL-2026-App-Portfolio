@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL Workstation Apps\CITL Workstation Apps.exe"
if exist "%EXE%" (
    start "" "%EXE%"
) else (
    echo CITL Workstation Apps executable not found.
    echo Build it first: BUILD_ALL_CITL_EXES_WINDOWS.cmd -Apps workstationapps
    echo Or run from source:
    set "PY=%HERE%.venv\Scripts\python.exe"
    if not exist "%PY%" set "PY=python"
    "%PY%" "%HERE%factbook-assistant\citl_workstation_apps.py"
    pause
)
