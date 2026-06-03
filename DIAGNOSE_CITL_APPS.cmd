@echo off
REM ================================================================
REM  CITL FULL DIAGNOSTIC  —  Windows
REM  Runs the CITL Fixer GUI: all checks, fix buttons, full log.
REM  Works even when factbook-assistant scripts are missing.
REM ================================================================
title CITL Full Diagnostic
color 0B
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

echo.
echo  ============================================================
echo   CITL FULL DIAGNOSTIC
echo   %ROOT%
echo  ============================================================
echo.

REM ── Find Python ─────────────────────────────────────────────────────────────
set "PY="
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not defined PY if exist "%ROOT%\Python\python.exe" set "PY=%ROOT%\Python\python.exe"
if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe >nul 2>&1 && set "PY=py.exe" )
if not defined PY (
    for %%D in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    ) do ( if exist %%D if not defined PY set "PY=%%~D" )
)

if not defined PY (
    echo  [ERROR] Python not found.
    echo          Run REPAIR_CITL_APPS.cmd first — it will install Python.
    pause
    exit /b 1
)
echo  [OK] Python: !PY!
echo.

set "PYTHONPATH=%ROOT%\factbook-assistant;%ROOT%;!PYTHONPATH!"

REM ── Launch full CITL Fixer GUI (primary) ────────────────────────────────────
if exist "%ROOT%\citl_fixer.py" (
    echo  Launching CITL Fixer (Diagnose + Fix All + Bootstrap tabs)...
    !PY! "%ROOT%\citl_fixer.py"
    goto :done
)

REM ── Fallback: factbook diagnostic ───────────────────────────────────────────
if exist "%ROOT%\factbook-assistant\citl_factbook_diagnostic.py" (
    echo  Launching Factbook Diagnostic...
    !PY! "%ROOT%\factbook-assistant\citl_factbook_diagnostic.py"
    goto :done
)

REM ── Fallback: repair all ─────────────────────────────────────────────────────
if exist "%ROOT%\factbook-assistant\citl_repair_all.py" (
    echo  Launching Repair All...
    !PY! "%ROOT%\factbook-assistant\citl_repair_all.py"
    goto :done
)

echo  [ERROR] No diagnostic scripts found. Run REPAIR_CITL_APPS.cmd to restore them.
pause
exit /b 1

:done
endlocal
