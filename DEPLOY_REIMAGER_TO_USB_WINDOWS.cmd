@echo off
REM ============================================================================
REM  CITL REIMAGER — Deploy to USB Drive(s)  (Windows)
REM  Renton Technical College — CITL
REM
REM  Double-click OR call from REPAIR_CITL_APPS.cmd to push the CITL Reimager
REM  toolkit onto any connected ExFAT USB drives.
REM
REM  What this deploys:
REM    • citl_reimager.sh     — Ubuntu drive imager (3 profiles: lean/standard/full)
REM    • fleet_sync_usb.sh    — Fleet update: one source → all targets
REM    • fix_usb_grub.sh      — Repairs the GRUB shell boot failure (Ubuntu UEFI)
REM    • boot_payload_guard.sh — Prevents false boot-ready status
REM    • preflight_check.sh   — Pre-flight dependency checker for live boot
REM    • deploy_reimager_to_usb.sh — Self-update tool
REM    • grub.cfg             — Label-based GRUB config (survives UUID changes)
REM
REM  After deployment, boot the target USB on a Ubuntu mainframe and run:
REM    sudo bash /citl_reimager/citl_reimager.sh
REM ============================================================================
title CITL Reimager — Deploy to USB
color 0A
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "REIMAGER_SRC=%ROOT%\CITL-Cannakit\reimager"

echo.
echo  ============================================================
echo   CITL REIMAGER  —  USB Deploy Tool
echo   Source: %REIMAGER_SRC%
echo  ============================================================
echo.

REM ── Verify source exists ─────────────────────────────────────────────────────
if not exist "%REIMAGER_SRC%\citl_reimager.sh" (
    echo  [ERROR] Reimager scripts not found at:
    echo          %REIMAGER_SRC%
    echo.
    echo  Ensure CITL-Cannakit\reimager\ exists in the repo root.
    echo  Run: git pull  to restore missing files.
    echo.
    pause
    exit /b 1
)
if not exist "%REIMAGER_SRC%\boot_payload_guard.sh" (
    echo  [ERROR] Boot payload guard missing at:
    echo          %REIMAGER_SRC%\boot_payload_guard.sh
    echo.
    echo  This file is required so USBs are not falsely marked boot-ready.
    echo  Restore CITL-Cannakit\reimager before deploying.
    echo.
    pause
    exit /b 1
)
echo  [OK] Source scripts verified: %REIMAGER_SRC%
echo.

REM ── Detect ExFAT drives via PowerShell ───────────────────────────────────────
echo  [SCAN] Detecting connected ExFAT USB drives...
echo.

set "DRIVE_LIST_FILE=%TEMP%\citl_exfat_drives.txt"
if exist "%DRIVE_LIST_FILE%" del "%DRIVE_LIST_FILE%"

powershell -NoProfile -Command ^
    "Get-Volume | Where-Object { $_.FileSystemType -eq 'ExFAT' -and $_.DriveLetter } | ForEach-Object { $gb = [math]::Round($_.Size/1GB,1); \"$($_.DriveLetter):  [$($_.FileSystemLabel)]  $gb GB\" } | Out-File -Encoding ASCII '%DRIVE_LIST_FILE%'"

REM Count found drives
set /a "DRIVE_COUNT=0"
if exist "%DRIVE_LIST_FILE%" (
    for /f %%L in ('type "%DRIVE_LIST_FILE%" ^| find /c /v ""') do set /a "DRIVE_COUNT=%%L"
)

if %DRIVE_COUNT% equ 0 (
    echo  [WARN] No ExFAT drives detected.
    echo.
    echo  To make a USB drive compatible:
    echo    1. Insert USB drive
    echo    2. Open Disk Management (diskmgmt.msc)
    echo    3. Format the USB partition as ExFAT
    echo    4. Re-run this tool
    echo.
    pause
    exit /b 0
)

echo  Found %DRIVE_COUNT% ExFAT drive(s):
echo.
set /a "IDX=0"
for /f "tokens=*" %%L in ('type "%DRIVE_LIST_FILE%"') do (
    set /a "IDX+=1"
    set "DRIVE_!IDX!=%%L"
    echo    !IDX!) %%L
)
echo.
echo  (Enter drive numbers to deploy to, comma-separated, e.g. 1,3)
echo  (Press ENTER to deploy to ALL detected drives)
echo.
set /p "SELECTION=  Selection [ENTER=all]: "
echo.

REM ── Deploy ───────────────────────────────────────────────────────────────────
set /a "OK_COUNT=0"
set /a "FAIL_COUNT=0"

if "%SELECTION%"=="" (
    REM Deploy to all
    for /l %%I in (1,1,%DRIVE_COUNT%) do (
        call :deploy_to_drive "%%I"
    )
) else (
    REM Deploy to selected
    REM Replace commas with spaces and iterate
    set "SEL_CLEAN=%SELECTION:,= %"
    for %%N in (!SEL_CLEAN!) do (
        call :deploy_to_drive "%%N"
    )
)

echo.
echo  ============================================================
echo   DEPLOY SUMMARY
echo   OK:   %OK_COUNT% drive(s)
echo   FAIL: %FAIL_COUNT% drive(s)
echo  ============================================================
echo.

if %FAIL_COUNT% gtr 0 (
    echo  [WARN] Some drives failed. Check errors above.
    echo         Ensure the drives are not write-protected.
    echo.
)

if %OK_COUNT% gtr 0 (
    echo  [NEXT STEPS]
    echo   On each updated USB, boot a Ubuntu machine from the CITLBOOT partition,
    echo   then open a terminal and run:
    echo.
    echo     sudo bash /media/citl/citl_reimager/citl_reimager.sh
    echo.
    echo   Or for fleet sync:
    echo     sudo bash /media/citl/citl_reimager/fleet_sync_usb.sh --all
    echo.
)

if exist "%DRIVE_LIST_FILE%" del "%DRIVE_LIST_FILE%"
pause
exit /b 0


REM ── Subroutine: deploy to drive number N ──────────────────────────────────────
:deploy_to_drive
set /a "DNUM=%~1" 2>nul
if !DNUM! lss 1 goto :eof
if !DNUM! gtr %DRIVE_COUNT% (
    echo  [SKIP] No drive #%~1
    goto :eof
)

set "DRIVE_ENTRY=!DRIVE_%DNUM%!"
REM Extract drive letter (first char)
for /f "tokens=1" %%D in ("!DRIVE_ENTRY!") do set "DLETTER=%%D"
REM DLETTER is like "E:"
set "DEST=!DLETTER!\citl_reimager"

echo  [DEPLOY] #%~1: !DRIVE_ENTRY!
echo           Destination: !DEST!

REM Check drive is writable
echo test > "!DLETTER!\citl_write_test.tmp" 2>nul
if errorlevel 1 (
    echo  [FAIL]  Drive !DLETTER! is read-only or inaccessible.
    set /a "FAIL_COUNT+=1"
    goto :eof
)
del "!DLETTER!\citl_write_test.tmp" 2>nul

REM Create destination folder
if not exist "!DEST!" mkdir "!DEST!" 2>nul

REM Robocopy: /E=subdirs, /R:2=retry twice, /W:1=wait 1s, /NFL/NDL=no file/dir list
robocopy "%REIMAGER_SRC%" "!DEST!" /E /R:2 /W:1 /NFL /NDL /NJH /NJS >nul 2>&1
set "RC=!ERRORLEVEL!"

REM Robocopy exit codes: 0=nothing copied, 1=ok copies, 2=extra files, 3=ok+extra
REM Codes >=8 mean actual errors
if !RC! geq 8 (
    echo  [FAIL]  Robocopy error code: !RC!
    set /a "FAIL_COUNT+=1"
    goto :eof
)

REM Write manifest
(
    echo CITL Reimager Fleet Sync
    echo Deployed:  %DATE% %TIME%
    echo Source:    %REIMAGER_SRC%
    echo Target:    !DEST!
    echo Machine:   %COMPUTERNAME%
    echo.
    echo Scripts included:
    echo   citl_reimager.sh        -- Ubuntu drive imager (lean/standard/full)
    echo   fleet_sync_usb.sh       -- Fleet USB sync
    echo   fix_usb_grub.sh         -- GRUB repair for boot failures
    echo   boot_payload_guard.sh   -- Payload and boot-readiness guard
    echo   preflight_check.sh      -- Boot preflight dependency checker
    echo   deploy_reimager_to_usb.sh -- Self-deploy/update tool
    echo   grub.cfg                -- Label-based GRUB config
) > "!DEST!\MANIFEST.txt" 2>nul

set "PAYLOAD_STATUS=MISSING:no-citlboot-or-offline-payload"
set "CITLBOOT_DRIVE="
set "HAS_KERNEL="
set "HAS_INITRD="
for /f "usebackq delims=" %%B in (`powershell -NoProfile -Command "$v=Get-Volume ^| Where-Object { $_.FileSystemLabel -eq 'CITLBOOT' -and $_.DriveLetter } ^| Select-Object -First 1; if($v){ Write-Output ($v.DriveLetter + ':') }"`) do (
    if not defined CITLBOOT_DRIVE set "CITLBOOT_DRIVE=%%B"
)
if defined CITLBOOT_DRIVE (
    if exist "!CITLBOOT_DRIVE!\casper\vmlinuz" set "HAS_KERNEL=1"
    if exist "!CITLBOOT_DRIVE!\casper\vmlinuz.efi" set "HAS_KERNEL=1"
    if exist "!CITLBOOT_DRIVE!\casper\initrd" set "HAS_INITRD=1"
    if exist "!CITLBOOT_DRIVE!\casper\initrd.lz" set "HAS_INITRD=1"
    if exist "!CITLBOOT_DRIVE!\casper\filesystem.squashfs" (
        if defined HAS_KERNEL if defined HAS_INITRD set "PAYLOAD_STATUS=OK:casper:!CITLBOOT_DRIVE!\casper"
    )
)
if "!PAYLOAD_STATUS:~0,3!" neq "OK:" (
    if exist "!DLETTER!\ubuntu-base\filesystem.squashfs" set "PAYLOAD_STATUS=OK:offline:!DLETTER!\ubuntu-base\filesystem.squashfs"
)
if "!PAYLOAD_STATUS:~0,3!" neq "OK:" (
    for %%I in ("!DLETTER!\ubuntu-24*.iso" "!DLETTER!\CITL_Images\ubuntu-24*.iso" "!DLETTER!\*ubuntu*desktop*.iso") do (
        if exist "%%~fI" if "!PAYLOAD_STATUS:~0,3!" neq "OK:" set "PAYLOAD_STATUS=OK:offline:%%~fI"
    )
)
(
    echo CITL boot payload status
    echo.
    echo Checked: %DATE% %TIME%
    echo Status : !PAYLOAD_STATUS!
    echo Target : !DEST!
    echo.
    echo Boot-ready requires CITLBOOT\casper\vmlinuz, CITLBOOT\casper\initrd,
    echo and CITLBOOT\casper\filesystem.squashfs. Offline ISO/squashfs payloads
    echo can support repair or reimage work, but do not replace casper boot files.
) > "!DEST!\CITL_BOOT_PAYLOAD_STATUS.txt" 2>nul

if "!PAYLOAD_STATUS:~0,7!"=="MISSING" (
    echo  [WARN]  Boot payload missing on/near !DLETTER!. Tools copied, but this USB is not boot-ready.
    echo          See !DEST!\CITL_BOOT_PAYLOAD_STATUS.txt
)
echo  [OK]    Deployed to !DLETTER! — %REIMAGER_SRC% files copied.
set /a "OK_COUNT+=1"
goto :eof
