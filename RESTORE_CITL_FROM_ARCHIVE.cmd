@echo off
REM ================================================================
REM  CITL RECOVERY RESTORE
REM  Companion to BACKUP_CITL_RECOVERY_ARCHIVE.cmd
REM
REM  Finds the newest ZIP in C:\CITL_RECOVERY\, extracts it back
REM  into the CITL repo root, then auto-runs REPAIR_CITL_APPS.cmd
REM  to rebuild .venv and all dependencies.
REM
REM  Run this after a catastrophic loss of the repo folder,
REM  a corrupt .venv, or missing launcher scripts.
REM ================================================================
title CITL — Restore from Recovery Archive
color 0C
setlocal enabledelayedexpansion

set "BACKUP=C:\CITL_RECOVERY"
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

echo.
echo  ============================================================
echo   CITL RECOVERY RESTORE
echo   Archive source : %BACKUP%
echo   Restore target : %ROOT%
echo  ============================================================
echo.

REM ── Verify archive folder exists ────────────────────────────────────────────
if not exist "%BACKUP%" (
    echo  [ERROR] Recovery folder not found: %BACKUP%
    echo          Run BACKUP_CITL_RECOVERY_ARCHIVE.cmd first to create a snapshot.
    pause
    exit /b 1
)

REM ── Find the newest archive via PowerShell ───────────────────────────────────
echo  [1/5] Locating newest recovery archive...
set "ARCHIVE="
for /f "usebackq delims=" %%A in (
    `powershell -NoProfile -Command "Get-ChildItem '%BACKUP%\citl_scripts_*.zip' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName"`
) do set "ARCHIVE=%%A"

if not defined ARCHIVE (
    echo  [ERROR] No citl_scripts_*.zip found in %BACKUP%
    echo          Run BACKUP_CITL_RECOVERY_ARCHIVE.cmd from a healthy machine first.
    pause
    exit /b 1
)

echo  [OK] Found archive: %ARCHIVE%
echo.

REM ── Confirm before overwriting ───────────────────────────────────────────────
echo  WARNING: This will overwrite existing scripts in:
echo    %ROOT%
echo.
echo  .venv and dist\ are NOT touched (they must be rebuilt by REPAIR_CITL_APPS.cmd).
echo.
set /p "CONFIRM=  Type YES to continue, anything else to cancel: "
if /i not "%CONFIRM%"=="YES" (
    echo  Restore cancelled.
    pause
    exit /b 0
)
echo.

REM ── Extract archive into repo root ───────────────────────────────────────────
echo  [2/5] Extracting archive to %ROOT%...
powershell -NoProfile -Command ^
    "Expand-Archive -Path '%ARCHIVE%' -DestinationPath '%ROOT%' -Force"
if !ERRORLEVEL! neq 0 (
    echo  [ERROR] Extraction failed. Archive may be corrupt.
    echo          Try a different archive from: %BACKUP%
    pause
    exit /b 1
)
echo  [OK] Scripts restored.
echo.

REM ── Verify key files restored ────────────────────────────────────────────────
echo  [3/5] Verifying restored files...
set "MISSING=0"
for %%F in (
    "citl_fixer.py"
    "citl_repair_all.py"
    "REPAIR_CITL_APPS.cmd"
    "DIAGNOSE_CITL_APPS.cmd"
    "requirements.txt"
) do (
    if exist "%ROOT%\%%~F" (
        echo    [OK] %%~F
    ) else (
        echo    [MISSING] %%~F
        set /a MISSING+=1
    )
)
if !MISSING! gtr 0 (
    echo.
    echo  [WARN] !MISSING! file(s) missing after restore.
    echo         Archive may have been created with an incomplete repo.
    echo         Continuing anyway — REPAIR will attempt to recover these.
)
echo.

REM ── Run REPAIR to rebuild venv + deps ───────────────────────────────────────
echo  [4/5] Running REPAIR_CITL_APPS.cmd to rebuild .venv and dependencies...
echo        (This may take several minutes on first run.)
echo.
if exist "%ROOT%\REPAIR_CITL_APPS.cmd" (
    call "%ROOT%\REPAIR_CITL_APPS.cmd"
) else (
    echo  [WARN] REPAIR_CITL_APPS.cmd not found. Attempting pip install directly...
    set "PY="
    if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
    if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
    if not defined PY ( where py.exe >nul 2>&1 && set "PY=py.exe" )
    if defined PY (
        "%PY%" -m pip install --upgrade pip >nul 2>&1
        if exist "%ROOT%\requirements.txt" "%PY%" -m pip install -r "%ROOT%\requirements.txt"
    ) else (
        echo  [ERROR] Python not found. Install Python 3.10+ then re-run this script.
    )
)

REM ── Prompt to rebuild EXEs ───────────────────────────────────────────────────
echo.
echo  ============================================================
echo   [5/5] RESTORE COMPLETE
echo.
echo   Scripts are back. Your .venv has been rebuilt.
echo.
echo   NEXT STEP — Rebuild the EXE launchers:
echo     Double-click: BUILD_ALL_CITL_EXES_WINDOWS.cmd
echo     OR run in PowerShell:
echo       .\scripts\windows\build_all_citl_exes.ps1
echo.
echo   This recreates:
echo     dist\CITL LLMOps Presentation Suite\
echo     dist\CITL Workstation Apps\
echo     dist\CITL Field Apps\
echo     dist\CITL App Sync\
echo     dist\CITL FLEX Troubleshooter\
echo.
echo   Archive used: %ARCHIVE%
echo  ============================================================
echo.

set /p "BUILDNOW=  Build EXEs now? (YES/no): "
if /i "%BUILDNOW%"=="YES" (
    if exist "%ROOT%\BUILD_ALL_CITL_EXES_WINDOWS.cmd" (
        echo  Launching build...
        start "" "%ROOT%\BUILD_ALL_CITL_EXES_WINDOWS.cmd"
    ) else (
        echo  [WARN] BUILD_ALL_CITL_EXES_WINDOWS.cmd not found.
        echo         Run scripts\windows\build_all_citl_exes.ps1 manually.
    )
)

echo.
pause
endlocal
