@echo off
setlocal
call "%~dp0RUN_FACTBOOK_WINDOWS.cmd" %*
exit /b %ERRORLEVEL%
