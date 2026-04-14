@echo off
:: Copies the four CITL USB executables from dist\ into the
:: clean numbered folders on the USB drive (F:\).
:: Run this after BUILD_ALL_CITL_EXES_WINDOWS.cmd completes.

setlocal
set "HERE=%~dp0"
set "DIST=%HERE%dist"
set "USB=F:"

echo.
echo ============================================================
echo   CITL EXE Sync to USB
echo ============================================================
echo.

:: ---- CITL App Sync → 1-CITL-SYNC ----
if exist "%DIST%\CITL App Sync\CITL App Sync.exe" (
    echo [....] Syncing CITL App Sync...
    robocopy "%DIST%\CITL App Sync" "%USB%\1-CITL-SYNC" /MIR /NFL /NDL /NJH /NJS
    echo [ OK ] CITL App Sync synced.
) else (
    echo [WARN] CITL App Sync not built yet. Run BUILD_ALL_CITL_EXES_WINDOWS.cmd -Apps appsync
)

:: ---- CITL Presentation Suite → 2-CITL-PRESENTATION-SUITE ----
if exist "%DIST%\CITL LLMOps Presentation Suite\CITL LLMOps Presentation Suite.exe" (
    echo [....] Syncing CITL LLMOps Presentation Suite...
    robocopy "%DIST%\CITL LLMOps Presentation Suite" "%USB%\2-CITL-PRESENTATION-SUITE" /MIR /NFL /NDL /NJH /NJS
    echo [ OK ] CITL LLMOps Presentation Suite synced.
) else (
    echo [WARN] CITL LLMOps Presentation Suite not built yet.
)

:: ---- CITL Workstation Apps → 3-CITL-WORKSTATION-APPS ----
if exist "%DIST%\CITL Workstation Apps\CITL Workstation Apps.exe" (
    echo [....] Syncing CITL Workstation Apps...
    robocopy "%DIST%\CITL Workstation Apps" "%USB%\3-CITL-WORKSTATION-APPS" /MIR /NFL /NDL /NJH /NJS
    echo [ OK ] CITL Workstation Apps synced.
) else (
    echo [WARN] CITL Workstation Apps not built yet. Run: BUILD_ALL_CITL_EXES_WINDOWS.cmd -Apps workstationapps
)

:: ---- CITL Field Apps → 4-CITL-FIELD-APPS ----
if exist "%DIST%\CITL Field Apps\CITL Field Apps.exe" (
    echo [....] Syncing CITL Field Apps...
    robocopy "%DIST%\CITL Field Apps" "%USB%\4-CITL-FIELD-APPS" /MIR /NFL /NDL /NJH /NJS
    echo [ OK ] CITL Field Apps synced.
) else (
    echo [WARN] CITL Field Apps not built yet. Run: BUILD_ALL_CITL_EXES_WINDOWS.cmd -Apps fieldapps
)

echo.
echo ============================================================
echo   Sync complete. USB structure:
echo     %USB%\1-CITL-SYNC\
echo     %USB%\2-CITL-PRESENTATION-SUITE\
echo     %USB%\3-CITL-WORKSTATION-APPS\
echo     %USB%\4-CITL-FIELD-APPS\
echo ============================================================
echo.
pause
