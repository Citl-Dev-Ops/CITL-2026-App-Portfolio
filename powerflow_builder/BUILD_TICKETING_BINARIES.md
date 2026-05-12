# Ticketing Binary Build Guide

## Windows (built here)

Build command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\powerflow_builder\build_ticketing_automation_exe.ps1 -Clean
```

Expected executable:

- `powerflow_builder/dist/CITL Ticketing Automation GUI/CITL Ticketing Automation GUI.exe`

Quick run command:

```cmd
RUN_WORK_TICKETING_SYSTEM_WINDOWS_EXE.cmd
```

## Ubuntu/Linux

Build on an Ubuntu host:

```bash
bash powerflow_builder/build_ticketing_automation_bin.sh
```

Expected binary:

- `powerflow_builder/dist/citl_ticketing_automation_gui/citl_ticketing_automation_gui`

Run on Ubuntu:

```bash
bash RUN_WORK_TICKETING_SYSTEM_UBUNTU.sh
```

## Notes

- The app does not persist Office 365 credentials.
- Access tokens used for preflight checks are in-memory only during runtime.
