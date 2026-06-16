@echo off
call "%~dp0_citl_env.cmd"
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%dist\CITL Work and Preparedness Launcher\CITL Work and Preparedness Launcher.exe"
if exist "%EXE%" ( start "" "%EXE%" %* & exit /b 0 )
if not defined CITL_SW ( echo [ERROR] scripts\windows not found on this drive. & pause & exit /b 1 )
powershell -NoProfile -ExecutionPolicy Bypass -File "%CITL_SW%\run_work_preparedness_launcher.ps1" %*
set EC=%ERRORLEVEL%
if %EC% neq 0 pause
exit /b %EC%
