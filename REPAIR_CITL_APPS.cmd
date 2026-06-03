@echo off
REM ================================================================
REM  CITL UNIVERSAL REPAIR TOOL  —  Windows
REM  Double-click this from ANYWHERE to fix EVERYTHING:
REM    - Python missing       -> installs via winget
REM    - pip packages missing -> auto-installs them
REM    - Ollama not running   -> starts it
REM    - D: drive corrupted   -> repairs from C: source
REM    - Missing scripts      -> restores from repo
REM    - Launches full CITL Fixer GUI with Fix-All button
REM
REM  This script has NO external dependencies.
REM  It is self-contained and runs even when everything is broken.
REM ================================================================
title CITL Universal Repair Tool — Full Self-Heal
color 0A
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

echo.
echo  ============================================================
echo   CITL UNIVERSAL REPAIR TOOL  —  Full Self-Heal
echo   %ROOT%
echo  ============================================================
echo.

REM ── STEP 1: Find Python ─────────────────────────────────────────────────────
echo  [1/6] Locating Python...
set "PY="

REM Check local .venv first (fastest, most reliable)
if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PY=%ROOT%\.venv\Scripts\python.exe"
    echo        Found: .venv\Scripts\python.exe
    goto :found_python
)
if exist "%ROOT%\Python\python.exe" (
    set "PY=%ROOT%\Python\python.exe"
    echo        Found: Python\python.exe
    goto :found_python
)

REM Check system PATH
for %%C in (python.exe python3.exe py.exe) do (
    where %%C >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        if not defined PY (
            set "PY=%%C"
            echo        Found on PATH: %%C
        )
    )
)
if defined PY goto :found_python

REM Check common install locations
for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
    "C:\Program Files\Python311\python.exe"
    "C:\Program Files\Python312\python.exe"
) do (
    if exist %%D if not defined PY (
        set "PY=%%~D"
        echo        Found: %%~D
    )
)
if defined PY goto :found_python

REM Last resort: install Python via winget
echo  [INSTALL] Python not found. Installing Python 3.11 via winget...
winget install Python.Python.3.11 --silent --accept-source-agreements >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [WARN] winget failed. Trying Python.Python.3.12...
    winget install Python.Python.3.12 --silent --accept-source-agreements >nul 2>&1
)
REM Refresh PATH from registry
for /f "tokens=*" %%i in ('powershell -NoProfile -Command ^
    "[System.Environment]::GetEnvironmentVariable(\"PATH\",\"Machine\") + \";\" + [System.Environment]::GetEnvironmentVariable(\"PATH\",\"User\")"') do set "PATH=%%i"
where python.exe >nul 2>&1 && set "PY=python.exe"
where py.exe    >nul 2>&1 && if not defined PY set "PY=py.exe"
if not defined PY (
    echo.
    echo  [ERROR] Could not install Python automatically.
    echo          Download manually: https://www.python.org/downloads/
    echo          Install, then re-run this file.
    echo.
    pause
    exit /b 1
)
echo  [OK] Python installed: !PY!

:found_python
echo  [OK] Python: !PY!
echo.

REM ── STEP 2: Install minimum GUI dependencies ────────────────────────────────
echo  [2/6] Checking minimum dependencies (requests, tkinter)...
!PY! -c "import tkinter, requests, json, pathlib" >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo  [INSTALL] Installing missing packages...
    !PY! -m pip install --quiet --upgrade pip 2>nul
    !PY! -m pip install --quiet requests 2>nul
    echo  [OK] Base packages ready.
) else (
    echo  [OK] Core packages present.
)
echo.

REM ── STEP 3: Check Ollama ────────────────────────────────────────────────────
echo  [3/6] Checking Ollama service...
powershell -NoProfile -Command ^
    "try { $r=(Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -ErrorAction Stop); Write-Host '  [OK] Ollama running on port 11434' } catch { Write-Host '  [WARN] Ollama not responding on port 11434 — attempting start...' }"

REM Try to start Ollama silently if not running
for %%O in (
    "%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    "%LOCALAPPDATA%\Ollama\ollama.exe"
    "ollama.exe"
) do (
    if exist "%%~O" (
        powershell -NoProfile -Command ^
            "try { $r=(Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 1 -ErrorAction Stop) } catch { Start-Process '%%~O' -ArgumentList 'serve' -WindowStyle Hidden }"
        echo  [INFO] Ollama start attempted: %%~O
        goto :ollama_done
    )
)
where ollama.exe >nul 2>&1
if !ERRORLEVEL! equ 0 (
    powershell -NoProfile -Command ^
        "try { $r=(Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 1 -ErrorAction Stop) } catch { Start-Process 'ollama' -ArgumentList 'serve' -WindowStyle Hidden }"
    echo  [INFO] Ollama start attempted from PATH.
)
:ollama_done
echo.

REM ── STEP 4: Repair corrupted D: drive files from C: source ──────────────────
echo  [4/6] Checking for corrupted remote copies...
set "CSRC=%ROOT%\factbook-assistant"
for %%D in (D E F G H) do (
    if exist "%%D:\00 CITL APPS 2026" (
        set "DDEST=%%D:\00 CITL APPS 2026\CITL-UTILITIES-EASY-RUN-v2"
        if exist "!DDEST!\factbook-assistant" (
            echo  [CHECK] Found remote copy: !DDEST!
            REM Test if the key file is readable
            powershell -NoProfile -Command ^
                "try { [System.IO.File]::ReadAllBytes('!DDEST!\factbook-assistant\factbook_assistant_gui.py') | Out-Null; Write-Host '  [OK] Remote copy readable' } catch { Write-Host '  [REPAIR] Corrupted remote file detected — copying from C: source...'; Copy-Item -Path '%CSRC%\*' -Destination '!DDEST!\factbook-assistant\' -Recurse -Force -ErrorAction SilentlyContinue; Write-Host '  [DONE] Remote copy repaired.' }"
        )
    )
)
echo.

REM ── STEP 5: Ensure citl_fixer.py is present ─────────────────────────────────
echo  [5/6] Verifying repair scripts...
if not exist "%ROOT%\citl_fixer.py" (
    echo  [WARN] citl_fixer.py missing from root.
    if exist "%ROOT%\factbook-assistant\citl_fixer.py" (
        copy "%ROOT%\factbook-assistant\citl_fixer.py" "%ROOT%\citl_fixer.py" >nul
        echo  [OK] Restored citl_fixer.py from factbook-assistant.
    ) else if exist "%ROOT%\citl_bootstrap.py" (
        echo  [FALLBACK] Will use citl_bootstrap.py
    ) else (
        echo  [ERROR] No repair scripts found. Re-sync from your CITL repository.
        pause
        exit /b 1
    )
) else (
    echo  [OK] citl_fixer.py present.
)
echo.

REM ── AUTO-BACKUP: Snapshot healthy scripts before launching ─────────────────
echo  [AUTO] Scripts verified — snapshotting recovery archive...
if exist "%ROOT%\BACKUP_CITL_RECOVERY_ARCHIVE.cmd" (
    call "%ROOT%\BACKUP_CITL_RECOVERY_ARCHIVE.cmd" /silent
    echo  [OK] Recovery archive updated in C:\CITL_RECOVERY
) else (
    echo  [SKIP] Backup script not found — skipping snapshot.
)
echo.

REM ── STEP 5b: USB Reimager Deploy (optional, non-blocking) ──────────────────
echo  [5b/6] Checking for ExFAT USB drives to update with CITL Reimager...
set "REIMAGER_SRC=%ROOT%\CITL-Cannakit\reimager"
if not exist "%REIMAGER_SRC%\citl_reimager.sh" (
    echo  [SKIP] CITL-Cannakit\reimager not found — skipping USB deploy step.
    goto :skip_usb_deploy
)

REM Count ExFAT drives silently
set "USB_COUNT=0"
for /f %%C in ('powershell -NoProfile -Command "( Get-Volume | Where-Object { $_.FileSystemType -eq ''ExFAT'' -and $_.DriveLetter } ).Count" 2^>nul') do set "USB_COUNT=%%C"

if "%USB_COUNT%"=="0" (
    echo  [INFO] No ExFAT USB drives connected — skipping deploy.
    goto :skip_usb_deploy
)

echo.
echo  [FOUND] %USB_COUNT% ExFAT USB drive(s) detected.
powershell -NoProfile -Command ^
    "Get-Volume | Where-Object { $_.FileSystemType -eq 'ExFAT' -and $_.DriveLetter } | ForEach-Object { '    ' + $_.DriveLetter + ':  [' + $_.FileSystemLabel + ']  ' + [math]::Round($_.Size/1GB,1) + ' GB' }"
echo.
set /p "DO_USB_DEPLOY=  Deploy CITL Reimager to these USB drives? [Y/n]: "
if /i "!DO_USB_DEPLOY!"=="n" goto :skip_usb_deploy

call "%ROOT%\DEPLOY_REIMAGER_TO_USB_WINDOWS.cmd"

:skip_usb_deploy
echo.

REM ── STEP 6: Launch CITL Fixer GUI ───────────────────────────────────────────
echo  [6/6] Launching CITL Fixer GUI...
echo.

set "PYTHONPATH=%ROOT%\factbook-assistant;%ROOT%;!PYTHONPATH!"

if exist "%ROOT%\citl_fixer.py" (
    echo  Starting CITL Fixer (full diagnostic + fix-all)...
    !PY! "%ROOT%\citl_fixer.py"
    goto :done
)

if exist "%ROOT%\factbook-assistant\citl_repair_all.py" (
    echo  Starting CITL Repair All GUI...
    !PY! "%ROOT%\factbook-assistant\citl_repair_all.py"
    goto :done
)

if exist "%ROOT%\citl_bootstrap.py" (
    echo  Starting CITL Bootstrap...
    !PY! "%ROOT%\citl_bootstrap.py" --gui
    goto :done
)

REM ── Emergency inline repair (no scripts needed) ─────────────────────────────
echo.
echo  ============================================================
echo   EMERGENCY INLINE REPAIR
echo  ============================================================
echo.
echo  Installing core packages...
!PY! -m pip install --quiet requests pillow tkinter-tooltip 2>nul
echo.
echo  [DONE] Packages attempted. Check errors above.
echo.
echo  Remaining steps to restore CITL apps:
echo    1. Open a terminal in:  %ROOT%
echo    2. Run:  git pull
echo    3. Run:  pip install -r requirements.txt
echo    4. Re-run this file.
echo.

:done
echo.
echo  ============================================================
echo   CITL Repair Tool finished. Press any key to close.
echo  ============================================================
pause >nul
endlocal
