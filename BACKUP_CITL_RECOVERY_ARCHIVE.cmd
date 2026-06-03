@echo off
REM ================================================================
REM  CITL RECOVERY ARCHIVE CREATOR
REM  Run this any time the repo is healthy.
REM  Creates C:\CITL_RECOVERY\ — a compressed snapshot of every
REM  script needed to rebuild all CITL apps from scratch.
REM  Even if .venv, dist\, or entire folders are wiped, this
REM  archive lets you restore and relaunch within minutes.
REM ================================================================
title CITL — Creating Recovery Archive
color 0E
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "BACKUP=C:\CITL_RECOVERY"
set "STAMP=%DATE:~10,4%%DATE:~4,2%%DATE:~7,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
set "STAMP=%STAMP: =0%"
set "ARCHIVE=%BACKUP%\citl_scripts_%STAMP%.zip"

echo.
echo  ============================================================
echo   CITL RECOVERY ARCHIVE  —  Creating snapshot now
echo   Source : %ROOT%
echo   Dest   : %BACKUP%
echo  ============================================================
echo.

if not exist "%BACKUP%" mkdir "%BACKUP%"

REM ── Find Python ─────────────────────────────────────────────────────────────
set "PY="
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not defined PY ( where python.exe >nul 2>&1 && set "PY=python.exe" )
if not defined PY ( where py.exe >nul 2>&1 && set "PY=py.exe" )

REM ── Copy critical scripts flat (no .venv, no embeddings, no build) ──────────
echo  [1/4] Copying critical scripts to staging area...
set "STAGE=%BACKUP%\_stage"
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"
mkdir "%STAGE%\factbook-assistant"
mkdir "%STAGE%\scripts\windows"
mkdir "%STAGE%\citl_flex_troubleshooter"

REM Root-level launchers and fixer
for %%F in (
    "citl_fixer.py"
    "citl_bootstrap.py"
    "citl_repair_all.py"
    "REPAIR_CITL_APPS.cmd"
    "DIAGNOSE_CITL_APPS.cmd"
    "BACKUP_CITL_RECOVERY_ARCHIVE.cmd"
    "RESTORE_CITL_FROM_ARCHIVE.cmd"
    "BUILD_ALL_CITL_EXES_WINDOWS.cmd"
    "INSTALL_CITL_APPS_PORTABLE.cmd"
    "CITL Presentation Suite.cmd"
    "CITL Workstation Apps.cmd"
    "CITL Field Apps.cmd"
    "RUN_FACTBOOK_WINDOWS.cmd"
    "RUN_LLMOPS_WINDOWS.cmd"
    "RUN_APP_SYNC_WINDOWS.cmd"
    "RUN_WORKSTATION_APPS_WINDOWS.cmd"
    "RUN_FIELD_APPS_WINDOWS.cmd"
    "RUN_STAFF_TOOLKIT_WINDOWS.cmd"
    "RUN_DOC_COMPOSER_WINDOWS.cmd"
    "RUN_CITL_FIXER_WINDOWS.cmd"
    "requirements.txt"
    "requirements-windows.txt"
    "requirements-base.txt"
) do (
    if exist "%ROOT%\%%~F" (
        copy /y "%ROOT%\%%~F" "%STAGE%\" >nul
        echo    + %%~F
    )
)

REM factbook-assistant — all .py scripts (no data files, no embeddings)
echo  [2/4] Copying factbook-assistant scripts...
for %%F in ("%ROOT%\factbook-assistant\*.py") do (
    copy /y "%%F" "%STAGE%\factbook-assistant\" >nul
)
echo    Copied all .py files from factbook-assistant

REM build script
copy /y "%ROOT%\scripts\windows\build_all_citl_exes.ps1" "%STAGE%\scripts\windows\" >nul 2>&1
if exist "%ROOT%\scripts\windows\run.ps1" copy /y "%ROOT%\scripts\windows\run.ps1" "%STAGE%\scripts\windows\" >nul 2>&1

REM FLEX troubleshooter entry
if exist "%ROOT%\citl_flex_troubleshooter\flex_assistant_gui.py" (
    copy /y "%ROOT%\citl_flex_troubleshooter\flex_assistant_gui.py" "%STAGE%\citl_flex_troubleshooter\" >nul
)

REM ── Compress staging area to zip ────────────────────────────────────────────
echo  [3/4] Compressing to archive...
powershell -NoProfile -Command ^
    "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%ARCHIVE%' -Force"
if !ERRORLEVEL! equ 0 (
    for %%S in ("%ARCHIVE%") do set "SZ=%%~zS"
    set /a "SZMB=!SZ! / 1048576"
    echo  [OK] Archive created: %ARCHIVE%  (!SZMB! MB^)
) else (
    echo  [ERROR] Compression failed. Stage folder left at: %STAGE%
    pause
    exit /b 1
)

REM ── Clean staging area ──────────────────────────────────────────────────────
rmdir /s /q "%STAGE%"

REM ── Keep only last 3 archives ───────────────────────────────────────────────
echo  [4/4] Pruning old archives (keeping 3 newest)...
powershell -NoProfile -Command ^
    "Get-ChildItem '%BACKUP%\citl_scripts_*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3 | Remove-Item -Force"

REM ── Write a README into BACKUP dir ──────────────────────────────────────────
(
echo CITL Recovery Archives
echo ======================
echo These ZIP files contain all scripts needed to rebuild CITL apps.
echo.
echo To restore after catastrophic failure:
echo   1. Run RESTORE_CITL_FROM_ARCHIVE.cmd  ^(in this folder^)
echo      OR manually: Expand-Archive -Path citl_scripts_*.zip -DestinationPath C:\CITL_RESTORE\
echo   2. In the restored folder: double-click REPAIR_CITL_APPS.cmd
echo   3. Then: BUILD_ALL_CITL_EXES_WINDOWS.cmd  to rebuild EXEs
echo.
echo What is NOT in the archive ^(must be re-generated^):
echo   - .venv ^(rebuilt by REPAIR_CITL_APPS.cmd^)
echo   - dist\  ^(rebuilt by BUILD_ALL_CITL_EXES_WINDOWS.cmd^)
echo   - factbook_embeddings.json  ^(large — re-index after restore^)
echo   - factbook_chunks.json      ^(large — re-index after restore^)
) > "%BACKUP%\README.txt"

echo.
echo  ============================================================
echo   RECOVERY ARCHIVE CREATED SUCCESSFULLY
echo   Location : %BACKUP%
echo   File     : %ARCHIVE%
echo.
echo   Run RESTORE_CITL_FROM_ARCHIVE.cmd to use this archive.
echo  ============================================================
echo.
if /i not "%~1"=="/silent" pause
endlocal
