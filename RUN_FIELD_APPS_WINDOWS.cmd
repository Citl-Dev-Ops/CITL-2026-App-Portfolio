@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL Field Apps\CITL Field Apps.exe"
if exist "%EXE%" (
    start "" "%EXE%"
) else (
    echo CITL Field Apps executable not found.
    echo Build it first: BUILD_ALL_CITL_EXES_WINDOWS.cmd -Apps fieldapps
    echo Or run from source:
    set "PY=%HERE%.venv\Scripts\python.exe"
    if not exist "%PY%" set "PY=python"
    "%PY%" "%HERE%factbook-assistant\citl_field_apps.py"
    pause
)
