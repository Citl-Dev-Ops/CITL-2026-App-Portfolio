@echo off
setlocal enableextensions
set "ROOT=%~dp0"
set "SYNC=%ROOT%citl_app_sync.py"
set "PY="
set "TRY1=%ROOT%.venv\Scripts\python.exe"
set "TRY2=%ROOT%\Python\python.exe"
set "TRY3=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
set "TRY4=%USERPROFILE%\CITL\.venv\Scripts\python.exe"

if exist "%TRY1%" (
  "%TRY1%" -V >nul 2>&1
  if not errorlevel 1 set "PY=%TRY1%"
)
if not defined PY if exist "%TRY2%" (
  "%TRY2%" -V >nul 2>&1
  if not errorlevel 1 set "PY=%TRY2%"
)
if not defined PY if exist "%TRY3%" (
  "%TRY3%" -V >nul 2>&1
  if not errorlevel 1 set "PY=%TRY3%"
)
if not defined PY if exist "%TRY4%" (
  "%TRY4%" -V >nul 2>&1
  if not errorlevel 1 set "PY=%TRY4%"
)
if not defined PY (
  py -3 -V >nul 2>&1
  if %ERRORLEVEL% equ 0 set "PY=py -3"
)
if not defined PY (
  where python.exe >nul 2>&1
  if %ERRORLEVEL% equ 0 set "PY=python.exe"
)

if not defined PY (
  echo [ERROR] Python not found.
  exit /b 1
)
if not exist "%SYNC%" (
  echo [ERROR] Missing sync engine: %SYNC%
  exit /b 1
)

echo [PATCH] Auto 48h cadence run (C->exFAT auto-target)...
%PY% "%SYNC%" --apply --days 2 --cadence-hours 48 --target auto
exit /b %ERRORLEVEL%
