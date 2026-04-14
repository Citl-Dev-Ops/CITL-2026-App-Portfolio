@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL Document Composer\CITL Document Composer.exe"

if exist "%EXE%" (
  "%EXE%" %*
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\run_doc_composer.ps1" %*
set "EC=%ERRORLEVEL%"
if %EC% neq 0 pause
exit /b %EC%
