@echo off
:: Copies CITL executables from dist\ into numbered drive folders.
:: Usage:
::   SYNC_EXES_TO_USB_WINDOWS.cmd            (auto-detect target, prefers K:)
::   SYNC_EXES_TO_USB_WINDOWS.cmd K:

setlocal EnableExtensions
set "HERE=%~dp0"
set "DIST=%HERE%dist"
set "TICKET_DIST=%HERE%powerflow_builder\dist"
set "USB=%~1"

if not defined USB call :detect_target
if not defined USB (
    echo [FAIL] Could not detect a CITL target drive.
    echo        Plug in a drive with ^"1-CITL-SYNC^" or pass one explicitly:
    echo        SYNC_EXES_TO_USB_WINDOWS.cmd K:
    echo.
    pause
    exit /b 1
)

if "%USB:~-1%"=="\" set "USB=%USB:~0,-1%"

echo.
echo ============================================================
echo   CITL EXE Sync
echo ============================================================
echo Target drive: %USB%
echo.

call :sync_bundle "%DIST%\CITL App Sync" "CITL App Sync.exe" "1-CITL-SYNC" "CITL App Sync"
call :sync_bundle "%DIST%\CITL LLMOps Presentation Suite" "CITL LLMOps Presentation Suite.exe" "2-CITL-PRESENTATION-SUITE" "CITL LLMOps Presentation Suite"
call :sync_bundle "%DIST%\CITL Workstation Apps" "CITL Workstation Apps.exe" "3-CITL-WORKSTATION-APPS" "CITL Workstation Apps"
call :sync_bundle "%DIST%\CITL Field Apps" "CITL Field Apps.exe" "4-CITL-FIELD-APPS" "CITL Field Apps"
call :sync_bundle "%TICKET_DIST%\CITL Ticketing Automation GUI" "CITL Ticketing Automation GUI.exe" "6-CITL-WORK-TICKETING" "CITL Ticketing Automation GUI"
call :sync_single_exe "%DIST%\CITL USB Repair Cloner.exe" "1-CITL-SYNC\CITL USB Repair Cloner\CITL USB Repair Cloner.exe" "CITL USB Repair Cloner"

echo.
echo ============================================================
echo   Sync complete. Folder targets:
echo     %USB%\1-CITL-SYNC\
echo     %USB%\2-CITL-PRESENTATION-SUITE\
echo     %USB%\3-CITL-WORKSTATION-APPS\
echo     %USB%\4-CITL-FIELD-APPS\
echo     %USB%\6-CITL-WORK-TICKETING\
echo ============================================================
echo.
pause
exit /b 0

:sync_bundle
set "SRC=%~1"
set "EXE=%~2"
set "DST_FOLDER=%~3"
set "LABEL=%~4"

if exist "%SRC%\%EXE%" (
    echo [....] Syncing %LABEL%...
    robocopy "%SRC%" "%USB%\%DST_FOLDER%" /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS >nul
    if %ERRORLEVEL% LEQ 7 (
        echo [ OK ] %LABEL% synced.
    ) else (
        echo [WARN] %LABEL% robocopy returned %ERRORLEVEL%.
    )
) else (
    echo [WARN] %LABEL% not built yet. Missing: %SRC%\%EXE%
)
exit /b 0

:sync_single_exe
set "SRC_EXE=%~1"
set "DST_EXE=%~2"
set "LABEL=%~3"

if exist "%SRC_EXE%" (
    echo [....] Syncing %LABEL%...
    for %%P in ("%USB%\%DST_EXE%") do if not exist "%%~dpP" mkdir "%%~dpP" >nul 2>&1
    copy /Y "%SRC_EXE%" "%USB%\%DST_EXE%" >nul
    if errorlevel 1 (
        echo [WARN] %LABEL% copy failed.
    ) else (
        echo [ OK ] %LABEL% synced.
    )
) else (
    echo [WARN] %LABEL% not built yet. Missing: %SRC_EXE%
)
exit /b 0

:detect_target
if exist "K:\1-CITL-SYNC" (
    set "USB=K:"
    goto :eof
)

for %%D in (D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
    if exist "%%D:\1-CITL-SYNC" (
        set "USB=%%D:"
        goto :eof
    )
)

if exist "K:\" (
    set "USB=K:"
    goto :eof
)

if exist "F:\" (
    set "USB=F:"
    goto :eof
)
exit /b 0
