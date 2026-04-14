@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL Sync Hub\CITL Sync Hub.exe"
if exist "%EXE%" (
    start "" "%EXE%"
) else (
    set "PY=%HERE%.venv\Scripts\python.exe"
    if not exist "%PY%" set "PY=python"
    "%PY%" "%HERE%factbook-assistant\citl_sync_hub.py"
    if %ERRORLEVEL% neq 0 pause
)
