@echo off
setlocal enableextensions
set "ROOT=%~dp0"
set "TARGET="

if exist "%ROOT%Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%"
if not defined TARGET if exist "%ROOT%CITL_FACTBOOK_UBUNTU\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL_FACTBOOK_UBUNTU\"
if not defined TARGET if exist "%ROOT%CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL\"
if not defined TARGET if exist "%ROOT%PORTABLE_APPS\CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%PORTABLE_APPS\CITL\"

if not defined TARGET (
  for /d %%D in ("%ROOT%*") do (
    if exist "%%~fD\Run-CITL-App-Sync.ps1" (
      set "TARGET=%%~fD\"
      goto :found
    )
  )
)

:found
if not defined TARGET (
  echo Could not find Run-CITL-App-Sync.ps1 under %ROOT%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%Run-CITL-App-Sync.ps1" --source "%TARGET%" --duplicate-usb --duplicate-from "%TARGET%" %*
exit /b %ERRORLEVEL%
