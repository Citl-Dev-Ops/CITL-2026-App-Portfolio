@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL AV IT Operations\CITL AV IT Operations.exe"

if exist "%EXE%" (
  "%EXE%" %*
  exit /b %ERRORLEVEL%
)

REM Locate PowerShell launcher -- check local, then USB deployment paths
set "PS1="
if exist "%HERE%scripts\windows\run_av_it_ops.ps1" (
    set "PS1=%HERE%scripts\windows\run_av_it_ops.ps1"
)
if not defined PS1 if exist "%HERE%CITL_FACTBOOK_UBUNTU V1\scripts\windows\run_av_it_ops.ps1" (
    set "PS1=%HERE%CITL_FACTBOOK_UBUNTU V1\scripts\windows\run_av_it_ops.ps1"
)
if not defined PS1 if exist "%HERE%CITL_FACTBOOK_UBUNTU V1\factbook-assistant\scripts\windows\run_av_it_ops.ps1" (
    set "PS1=%HERE%CITL_FACTBOOK_UBUNTU V1\factbook-assistant\scripts\windows\run_av_it_ops.ps1"
)

if defined PS1 (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
    set "EC=%ERRORLEVEL%"
    if %EC% neq 0 pause
    exit /b %EC%
)

REM PS1 not found -- run Python script directly
set "PY_SCRIPT="
if exist "%HERE%factbook-assistant\citl_av_it_ops.py" (
    set "PY_SCRIPT=%HERE%factbook-assistant\citl_av_it_ops.py"
)
if not defined PY_SCRIPT if exist "%HERE%CITL_FACTBOOK_UBUNTU V1\factbook-assistant\citl_av_it_ops.py" (
    set "PY_SCRIPT=%HERE%CITL_FACTBOOK_UBUNTU V1\factbook-assistant\citl_av_it_ops.py"
)

if not defined PY_SCRIPT (
    echo [ERROR] citl_av_it_ops.py not found in any expected location.
    pause
    exit /b 1
)

where py >nul 2>&1 && ( py -3 "%PY_SCRIPT%" %* & exit /b %ERRORLEVEL% )
where python >nul 2>&1 && ( python "%PY_SCRIPT%" %* & exit /b %ERRORLEVEL% )
echo [ERROR] Python not found. Install Python 3 and re-run.
pause
exit /b 1
