@echo off
setlocal enableextensions
set "TASKNAME=CITL_48H_PATCH_CADENCE"

schtasks /Delete /F /TN "%TASKNAME%" >nul 2>&1
if %ERRORLEVEL% neq 0 (
  echo [WARN] Task not found or could not be removed: %TASKNAME%
  exit /b 0
)

echo [OK] Removed scheduled task: %TASKNAME%
exit /b 0

