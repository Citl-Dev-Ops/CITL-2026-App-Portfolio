@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "EXE1=%ROOT%\dist\CITL USB Repair Cloner.exe"
set "EXE2=%ROOT%\dist\CITL USB Repair Cloner\CITL USB Repair Cloner.exe"
set "EXE3=%ROOT%\1-CITL-SYNC\CITL USB Repair Cloner\CITL USB Repair Cloner.exe"
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "SCRIPT=%ROOT%\scripts\windows\citl_usb_repair_clone.py"

if exist "%EXE1%" (
  "%EXE1%" %*
  exit /b %ERRORLEVEL%
)

if exist "%EXE2%" (
  "%EXE2%" %*
  exit /b %ERRORLEVEL%
)

if exist "%EXE3%" (
  "%EXE3%" %*
  exit /b %ERRORLEVEL%
)

if exist "%PY%" if exist "%SCRIPT%" (
  "%PY%" "%SCRIPT%" %*
  exit /b %ERRORLEVEL%
)

echo [FAIL] CITL USB Repair Cloner executable not found.
echo.
echo Build it first:
echo   BUILD_CITL_USB_REPAIR_CLONER_WINDOWS.cmd
echo.
pause
exit /b 1
