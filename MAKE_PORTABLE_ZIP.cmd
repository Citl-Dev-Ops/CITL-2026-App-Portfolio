@echo off
setlocal
set "HERE=%~dp0"
powershell.exe -ExecutionPolicy Bypass -File "%HERE%scripts\windows\make_portable_zip.ps1" %*
if %ERRORLEVEL% neq 0 pause
