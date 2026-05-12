@echo off
setlocal enableextensions
set "ROOT=%~dp0"
set "RUNNER=%ROOT%PATCH_CITL_48H_AUTO_WINDOWS.cmd"
set "TASKNAME=CITL_48H_PATCH_CADENCE"

if not exist "%RUNNER%" (
  echo [ERROR] Missing runner: %RUNNER%
  exit /b 1
)

echo [TASK] Creating/updating %TASKNAME%...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$taskName='%TASKNAME%';" ^
  "$runner='%RUNNER%';" ^
  "$action=New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c \"\"' + $runner + '\"\"');" ^
  "$trigger=New-ScheduledTaskTrigger -Daily -At 06:00AM -DaysInterval 2;" ^
  "Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Force | Out-Null" >nul 2>&1
if %ERRORLEVEL% neq 0 (
  echo [WARN] PowerShell registration failed, trying schtasks fallback...
  set "TASKCMD=%ComSpec% /c \"\"%RUNNER%\"\""
  schtasks /Create /F /TN "%TASKNAME%" /SC DAILY /MO 2 /ST 06:00 /TR "%TASKCMD%" >nul 2>&1
  if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to create scheduled task. Try running as Administrator.
    exit /b 1
  )
)

echo [OK] Scheduled task installed: %TASKNAME%
echo [OK] Runs every 48 hours at 06:00 local time.
exit /b 0
