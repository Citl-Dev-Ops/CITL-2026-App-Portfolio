@echo off
setlocal
set "ROOT=%~dp0"
set "EXE=%ROOT%powerflow_builder\dist\CITL Ticketing Automation GUI\CITL Ticketing Automation GUI.exe"
if not exist "%EXE%" (
  echo EXE not found: %EXE%
  echo Build first with:
  echo   powershell -ExecutionPolicy Bypass -File ".\powerflow_builder\build_ticketing_automation_exe.ps1"
  pause
  exit /b 1
)
"%EXE%" %*
exit /b %ERRORLEVEL%
