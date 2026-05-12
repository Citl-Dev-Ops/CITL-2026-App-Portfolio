@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "SCRIPT=%ROOT%\scripts\windows\citl_usb_repair_clone.py"
set "SPEC=%ROOT%\CITL USB Repair Cloner.spec"

if not exist "%SCRIPT%" (
  echo [FAIL] Missing script: %SCRIPT%
  pause
  exit /b 1
)

if not exist "%SPEC%" (
  echo [FAIL] Missing spec: %SPEC%
  pause
  exit /b 1
)

set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  for /f "delims=" %%G in ('where python 2^>nul') do (
    set "PY=%%G"
    goto :py_found
  )
)
:py_found

if not exist "%PY%" (
  echo [FAIL] Python not found. Install Python 3.10+ or create .venv first.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Building: CITL USB Repair Cloner.exe
echo ============================================================
echo Python: %PY%
echo Script: %SCRIPT%
echo.

pushd "%ROOT%"
"%PY%" -m PyInstaller --noconfirm --clean "%SPEC%"
set "BUILD_RC=%ERRORLEVEL%"
popd
if not "%BUILD_RC%"=="0" (
  echo [FAIL] PyInstaller build failed.
  pause
  exit /b %BUILD_RC%
)

set "EXE=%ROOT%\dist\CITL USB Repair Cloner.exe"
if not exist "%EXE%" (
  echo [FAIL] Expected output missing: %EXE%
  pause
  exit /b 1
)

set "ALT=%ROOT%\dist\CITL USB Repair Cloner\CITL USB Repair Cloner.exe"
if not exist "%ROOT%\dist\CITL USB Repair Cloner" mkdir "%ROOT%\dist\CITL USB Repair Cloner" >nul 2>&1
copy /Y "%EXE%" "%ALT%" >nul

echo [ OK ] Build complete:
echo       %EXE%
echo [ OK ] Bundle copy:
echo       %ALT%
echo.
pause
exit /b 0
