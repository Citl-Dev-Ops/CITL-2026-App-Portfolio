@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL Technical Writing and Tutorial Creator\CITL Technical Writing and Tutorial Creator.exe"

if exist "%EXE%" (
  "%EXE%" %*
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\run_technical_writer_creator.ps1" %*
set "EC=%ERRORLEVEL%"
if %EC% neq 0 pause
exit /b %EC%
