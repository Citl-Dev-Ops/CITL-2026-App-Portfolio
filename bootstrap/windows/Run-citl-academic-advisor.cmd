@echo off
setlocal
set "HERE=%~dp0\..\.."
set "TARGET=%HERE%\api\app.py"
if not exist "%TARGET%" (
  echo CITL Academic Advisor: entry not found: %TARGET%
  pause
  exit /b 1
)
if exist "%HERE%\.venv\Scripts\python.exe" (
  "%HERE%\.venv\Scripts\python.exe" "%TARGET%" %*
) else (
  where py >nul 2>&1
  if %ERRORLEVEL%==0 (
    py -3 "%TARGET%" %*
  ) else (
    python "%TARGET%" %*
  )
)
exit /b %ERRORLEVEL%
