@echo off
setlocal enableextensions
set "ROOT=%~dp0"
set "SCRIPT=%ROOT%factbook-assistant\citl_app_sync.py"
set "PY="

if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not defined PY if exist "%ROOT%python.exe" set "PY=%ROOT%python.exe"
if not defined PY if exist "%ROOT%Python\python.exe" set "PY=%ROOT%Python\python.exe"

if not defined PY (
  where python.exe >nul 2>&1
  if %ERRORLEVEL% equ 0 set "PY=python.exe"
)

if not defined PY (
  echo Python not found. Install Python 3 or add python.exe to PATH.
  pause
  exit /b 1
)

if not exist "%SCRIPT%" (
  echo Could not find citl_app_sync.py at %SCRIPT%
  pause
  exit /b 1
)

"%PY%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%
