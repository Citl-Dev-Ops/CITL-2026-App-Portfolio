CITL Sync Utility Launchers
===========================

Ubuntu sync launcher: RUN_APP_SYNC_UBUNTU.sh
Windows sync launcher: RUN_APP_SYNC_WINDOWS.cmd
Ubuntu self-duplicate launcher: COPY_THIS_USB_TO_NEXT_UBUNTU.sh
Windows self-duplicate launcher: COPY_THIS_USB_TO_NEXT_WINDOWS.cmd
Windows one-click USB updater: SYNC_CITL_APPS_TO_USB_WINDOWS.cmd
Ubuntu one-click USB updater: SYNC_CITL_APPS_TO_USB_UBUNTU.sh

These launchers search the current drive for the CITL repo and then open the
same cross-platform sync utility.

One-click USB updater notes
---------------------------
- SYNC_CITL_APPS_TO_USB_WINDOWS.cmd auto-detects source + USB target and pushes PC -> USB.
- COPY_THIS_USB_TO_NEXT_WINDOWS.cmd duplicates the current USB repo copy to the next detected CITL USB target.
- To duplicate one USB to another backup USB (for example K: -> I:), run:
  powershell -ExecutionPolicy Bypass -File scripts\windows\sync_usb_apps.ps1 -DuplicateUsb
- Optional flags:
  --IncludeData (includes data/index folders)
  --IncludeModels (includes models/ollama folders)
  --DuplicateUsb (copy selected USB repo to another USB target)
  --DuplicateFrom <path> (source USB repo path for duplicate mode)
  --DuplicateTo <path> (destination USB repo path for duplicate mode)
  --TargetRepo <path> (explicit target repo path for sync-best mode)
  --OllamaModelSource <path> (external Ollama model source directory)
  --OllamaModelTarget <path> (external Ollama model target directory)
  --SkipAppKeySync (skip per-app key-file pass)
  --FullRepo (also run full repo copy; slower)
  --SourceRepo <path|auto> (override source repo path; defaults to this local repo for this wrapper)
  --PushToPhone (zip selected USB target and push it to Android Downloads via ADB)
  --PhoneSerial <serial> (optional explicit ADB serial; defaults to auto)
- For Academic Advisor on machines with a non-standard repo path, set:
  CITL_ACADEMIC_ADVISOR_REPO=<full repo path>
  Example: set CITL_ACADEMIC_ADVISOR_REPO=D:\Projects\2026 ACADEMIC ADVISOR

Academic Advisor USB sync notes
--------------------------------
The Academic Advisor ships two things to USB:
  1. Source code (advisor-ui/src/, api/*.py) — for rebuilding on any machine
  2. Pre-built UI (advisor-ui/dist/) — so the UI runs without Node.js on target

Before syncing, build the UI on the dev machine:
  cd "C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS\2026 ACADEMIC ADVISOR\advisor-ui"
  npm install
  npm run build

The sync will then carry the built dist/ to the USB alongside source.
On the target machine, only Python + pip + Ollama are required to run the app.
Node.js is NOT required on the target if dist/ is present.

This repo now ships as a shared Windows/Ubuntu content set.
Use the same repo contents on both operating systems.

Windows app setup and launch
----------------------------
- Local setup: INSTALL_WINDOWS.cmd
- Local run: RUN_FACTBOOK_WINDOWS.cmd
- USB setup: USB-INSTALL-CITL.cmd
- USB run: USB-RUN-CITL.cmd

Ubuntu app setup and launch
---------------------------
- Local install: INSTALL_UBUNTU.sh
- Local run after install: RUN_FACTBOOK.sh
