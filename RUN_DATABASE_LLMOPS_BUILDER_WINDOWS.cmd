@echo off
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL Database LLMOps Builder\CITL Database LLMOps Builder.exe"

if exist "%EXE%" (
  "%EXE%" %*
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%scripts\windows\run_database_llmops_builder.ps1" %*
set "EC=%ERRORLEVEL%"
if %EC% neq 0 pause
exit /b %EC%
