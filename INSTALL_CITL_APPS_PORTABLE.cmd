@echo off
:: CITL Portable App Installer - no admin required
:: Installs or updates all CITL app bundles to your Desktop
:: and creates desktop shortcuts. Double-click to run.
setlocal

set "HERE=%~dp0"

:: Locate PowerShell
where powershell.exe >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo PowerShell not found. Cannot install.
    pause
    exit /b 1
)

:: The PS1 lives under scripts\windows\ relative to the repo root.
:: If this .cmd is at the repo root, that path is direct.
:: If this .cmd is on the USB root, the PS1 is in the same USB location.
set "PS1=%HERE%scripts\windows\install_citl_apps_portable.ps1"
if not exist "%PS1%" (
    :: Fallback: check if PS1 is in a sibling scripts folder on USB
    set "PS1=%HERE%CITL-UTILITIES-EASY-RUN-v2\scripts\windows\install_citl_apps_portable.ps1"
)
if not exist "%PS1%" (
    echo install_citl_apps_portable.ps1 not found.
    echo Expected: %HERE%scripts\windows\install_citl_apps_portable.ps1
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "EC=%ERRORLEVEL%"
if %EC% neq 0 (
    echo.
    echo One or more apps failed to install. See output above.
    pause
)
exit /b %EC%
