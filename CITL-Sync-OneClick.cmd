@echo off
setlocal enabledelayedexpansion
set "HERE=%~dp0"

echo.
echo ============================================================
echo   CITL One-Click Sync v2.0
echo ============================================================
echo.

REM Check if we're running from USB or local repo
if exist "%HERE%factbook-assistant\citl_app_sync.py" (
    set "REPO_ROOT=%HERE%"
    echo Running from repository root
) else (
    REM Try to find repo in standard locations
    for %%d in (C D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
        if exist "%%d:\CITL\factbook-assistant\citl_app_sync.py" (
            set "REPO_ROOT=%%d:\CITL"
            echo Found repository on drive %%d:
            goto :found_repo
        )
    )
    echo ERROR: Cannot find CITL repository
    echo Please run from repository root or insert USB drive
    pause
    exit /b 1
)

:found_repo
REM Launch the enhanced sync manager
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%scripts\windows\citl_sync_manager.ps1" %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo Sync completed with warnings/errors ^(code %ERRORLEVEL%^)
    echo Check logs at %%APPDATA%%\CITL\logs\
) else (
    echo.
    echo Sync completed successfully!
)

echo.
echo Press any key to close...
pause >nul