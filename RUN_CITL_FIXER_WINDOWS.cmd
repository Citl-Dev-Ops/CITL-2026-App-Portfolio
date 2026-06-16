@echo off
call "%~dp0_citl_env.cmd"
setlocal
set "HERE=%~dp0"
set "EXE_ONEDIR=%HERE%dist\CITL Fixer\CITL Fixer.exe"
set "EXE_ONEFILE=%HERE%dist\CITL Fixer.exe"
if exist "%EXE_ONEDIR%" ( start "" "%EXE_ONEDIR%" %* & exit /b 0 )
if exist "%EXE_ONEFILE%" ( start "" "%EXE_ONEFILE%" %* & exit /b 0 )
if not defined CITL_PY ( echo [ERROR] Python not found. Run INSTALL_CITL_APPS_PORTABLE.cmd & pause & exit /b 1 )
set "SCRIPT=%HERE%citl_fixer.py"
if not exist "%SCRIPT%" if defined CITL_FA set "SCRIPT=%CITL_FA%\..\citl_fixer.py"
if not exist "%SCRIPT%" ( echo [ERROR] citl_fixer.py not found. & pause & exit /b 1 )
%CITL_PY% "%SCRIPT%" %*
set EC=%ERRORLEVEL%
if %EC% neq 0 pause
exit /b %EC%
