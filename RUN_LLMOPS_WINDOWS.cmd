@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL LLMOps Presentation Suite\CITL LLMOps Presentation Suite.exe"

if exist "%EXE%" (
  "%EXE%" %*
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\run_llmops.ps1" %*
set "EC=%ERRORLEVEL%"
if %EC% neq 0 pause
exit /b %EC%
