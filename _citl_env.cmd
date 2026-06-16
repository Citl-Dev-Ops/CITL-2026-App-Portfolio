@echo off
REM ================================================================
REM  _citl_env.cmd -- CITL Universal Environment Resolver
REM  Call this from any launcher BEFORE setlocal.
REM  Sets: CITL_PY  CITL_FA  CITL_SW  CITL_FLEX
REM
REM  Search order for each variable:
REM    1. Drive root (local dev machine)
REM    2. CITL_FACTBOOK_UBUNTU V1\  (USB primary payload)
REM    3. PORTABLE_APPS\CITL\       (USB portable install)
REM ================================================================

set "_CE_ROOT=%~dp0"

REM ── Python ──────────────────────────────────────────────────────
set "CITL_PY="
if exist "%_CE_ROOT%.venv\Scripts\python.exe" set "CITL_PY=%_CE_ROOT%.venv\Scripts\python.exe"
if not defined CITL_PY if exist "%_CE_ROOT%Python\python.exe" set "CITL_PY=%_CE_ROOT%Python\python.exe"
if not defined CITL_PY ( where py.exe >nul 2>&1 && set "CITL_PY=py -3" )
if not defined CITL_PY ( where python.exe >nul 2>&1 && set "CITL_PY=python.exe" )
if not defined CITL_PY for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do ( if not defined CITL_PY if exist %%D set "CITL_PY=%%~D" )

REM ── factbook-assistant ──────────────────────────────────────────
set "CITL_FA="
for %%D in (
    "%_CE_ROOT%factbook-assistant"
    "%_CE_ROOT%CITL_FACTBOOK_UBUNTU V1\factbook-assistant"
    "%_CE_ROOT%PORTABLE_APPS\CITL\factbook-assistant"
) do (
    if not defined CITL_FA if exist "%%~D\factbook_assistant_gui.py" set "CITL_FA=%%~D"
)

REM ── scripts\windows (PS1 launchers) ────────────────────────────
set "CITL_SW="
for %%D in (
    "%_CE_ROOT%scripts\windows"
    "%_CE_ROOT%CITL_FACTBOOK_UBUNTU V1\scripts\windows"
    "%_CE_ROOT%PORTABLE_APPS\CITL\scripts\windows"
) do (
    if not defined CITL_SW if exist "%%~D\run_llmops.ps1" set "CITL_SW=%%~D"
)

REM ── citl_flex_troubleshooter ────────────────────────────────────
set "CITL_FLEX="
for %%D in (
    "%_CE_ROOT%citl_flex_troubleshooter"
    "%_CE_ROOT%CITL_FACTBOOK_UBUNTU V1\factbook-assistant\citl_flex_troubleshooter"
    "%_CE_ROOT%factbook-assistant\citl_flex_troubleshooter"
    "%_CE_ROOT%PORTABLE_APPS\CITL\citl_flex_troubleshooter"
) do (
    if not defined CITL_FLEX if exist "%%~D\flex_assistant_gui.py" set "CITL_FLEX=%%~D"
)

set "_CE_ROOT="
