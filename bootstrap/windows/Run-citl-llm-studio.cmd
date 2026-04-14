@echo off
setlocal
set "HERE=%~dp0\..\.."
set "TARGET=%HERE%\CITL-LLM-Studio-Kit\app\llm_studio_gui.py"
if not exist "%TARGET%" (
  echo CITL LLM Studio: entry not found: %TARGET%
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
