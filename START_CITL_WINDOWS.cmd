@echo off
:: ============================================================
:: CITL USB Quick Launch -- Windows  (auto-wizard edition)
:: Double-click from USB to install, update, or run CITL Sync Hub.
:: No admin required.  Runs on Windows 10/11.
:: ============================================================
setlocal EnableDelayedExpansion

set "USB=%~dp0"
set "SYNC_HUB_EXE=%USB%1-CITL-SYNC\CITL Sync Hub\CITL Sync Hub.exe"
set "APP_SYNC_EXE=%USB%1-CITL-SYNC\CITL App Sync\CITL App Sync.exe"
set "INSTALLER_PS1=%USB%scripts\windows\install_citl_apps_portable.ps1"

echo.
echo  =====================================================
echo   CITL App Suite ^| USB Quick Launch
echo  =====================================================
echo.

:: ---- Write USB instance ID if not present --------------------------------
:: This makes the USB identifiable in Sync Diagnostics
if not exist "%USB%citl_instance.json" (
    for /f "delims=" %%G in ('powershell -NoProfile -Command ^
      "[System.IO.File]::WriteAllText(\"%USB%citl_instance.json\", ^
      ('{\"instance_id\":\"CITL-' + (New-Guid).ToString().Replace('-','').Substring(0,8).ToUpper() + ^
      '\",\"type\":\"USB\",\"created\":\"' + (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') + ^
      '\",\"path\":\"' + '%USB%'.Replace('\','\\') + '\"}'))"') do (
        echo  [OK] Instance ID written to USB
    )
)

:: ---- Detect Python for venv bootstrap -----------------------------------
set "PY="
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do (
    if exist %%P (
        set "PY=%%~P"
        goto :py_found
    )
)
for /f "delims=" %%G in ('where python 2^>nul') do (
    echo %%G | findstr /i "WindowsApps" >nul || (set "PY=%%G" & goto :py_found)
)
:py_found

:: ---- Prefer Sync Hub exe (runs the full diagnostic wizard) ----------------
if exist "%SYNC_HUB_EXE%" goto :check_local_hub

:: ---- Sync Hub not on USB; try App Sync ------------------------------------
if exist "%APP_SYNC_EXE%" goto :check_local_sync
goto :installer_check

:: ---- Check for local Sync Hub install ------------------------------------
:check_local_hub
set "LOCAL_HUB="
for %%D in (
    "%USERPROFILE%\Desktop\CITL Apps\CITL Sync Hub"
    "%USERPROFILE%\Documents\CITL Apps\CITL Sync Hub"
    "%USERPROFILE%\Downloads\CITL Apps\CITL Sync Hub"
    "%LOCALAPPDATA%\CITL Apps\CITL Sync Hub"
) do (
    if exist "%%~D\CITL Sync Hub.exe" (
        set "LOCAL_HUB=%%~D\CITL Sync Hub.exe"
        goto :hub_found
    )
)

:: Not installed locally - run installer first
:installer_check
echo  No local CITL installation found. Running portable installer...
echo.
if exist "%INSTALLER_PS1%" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass ^
        -File "%INSTALLER_PS1%" -Apps sync -Silent
    echo.
    echo  Installer complete. Launching...
) else (
    echo  [WARN] Installer PS1 not found at: %INSTALLER_PS1%
    echo         Launching directly from USB...
)
goto :launch_hub_from_usb

:hub_found
echo  Local Sync Hub: %LOCAL_HUB%
echo.

:: ---- Check if USB has a newer build ------------------------------------
powershell -NoProfile -Command ^
  "$local = (Get-Item '%LOCAL_HUB%').LastWriteTime; ^
   $usb = Get-Item '%SYNC_HUB_EXE%' -EA SilentlyContinue; ^
   if ($usb -and $usb.LastWriteTime -gt $local) { exit 1 } else { exit 0 }" 2>nul
if %ERRORLEVEL%==1 (
    echo  [UPDATE] USB has a newer Sync Hub. Updating...
    powershell.exe -NoProfile -ExecutionPolicy Bypass ^
        -File "%INSTALLER_PS1%" -Apps sync -Silent -UpdateOnly 2>nul
    echo  Update applied.
    echo.
)

:: ---- Launch local Sync Hub -------------------------------------------
echo  Launching CITL Sync Hub from local install...
start "" "%LOCAL_HUB%"
goto :done

:launch_hub_from_usb
if exist "%SYNC_HUB_EXE%" (
    echo  Running CITL Sync Hub from USB...
    start "" "%SYNC_HUB_EXE%"
    goto :done
)

:check_local_sync
:: Fallback to App Sync if Sync Hub unavailable
set "LOCAL_SYNC="
for %%D in (
    "%USERPROFILE%\Desktop\CITL Apps\CITL App Sync"
    "%USERPROFILE%\Documents\CITL Apps\CITL App Sync"
    "%USERPROFILE%\Desktop\CITL App Sync"
) do (
    if exist "%%~D\CITL App Sync.exe" (
        set "LOCAL_SYNC=%%~D\CITL App Sync.exe"
        goto :run_sync
    )
)
:: Run App Sync from USB
if exist "%APP_SYNC_EXE%" (
    echo  Running CITL App Sync from USB...
    start "" "%APP_SYNC_EXE%"
    goto :done
)

echo  [ERROR] No CITL executable found on USB or locally.
echo  Plug in the correct CITL USB or run BUILD_ALL_CITL_EXES_WINDOWS.cmd first.
pause
goto :done

:run_sync
echo  Launching CITL App Sync...
start "" "%LOCAL_SYNC%"

:done
echo.
echo  CITL launched. This window will close in 5 seconds.
timeout /t 5 /nobreak >nul
endlocal
