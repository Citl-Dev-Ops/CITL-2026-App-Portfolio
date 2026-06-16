@echo off
call "%~dp0_citl_env.cmd"
setlocal
set "HERE=%~dp0"
title CITL Factbook Diagnostic
if not defined CITL_FA  ( echo [ERROR] factbook-assistant not found on this drive. & pause & exit /b 1 )
if not defined CITL_PY  ( echo [ERROR] Python not found. Run INSTALL_CITL_APPS_PORTABLE.cmd & pause & exit /b 1 )
set "PYTHONPATH=%CITL_FA%;%PYTHONPATH%"
%CITL_PY% "%CITL_FA%\citl_factbook_diagnostic.py" %*
set EC=%ERRORLEVEL%
if %EC% neq 0 pause
exit /b %EC%
