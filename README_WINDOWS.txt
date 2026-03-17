WINDOWS SETUP AND RUN
=====================

This repository now supports the same FACTBOOK v2.0 content set on Windows and Ubuntu.

Recommended Windows workflow
----------------------------
1) Open this repo on the Windows machine.
2) Run:

   INSTALL_WINDOWS.cmd

3) After setup finishes, run:

   RUN_FACTBOOK_WINDOWS.cmd

4) When you need to patch or update another CITL copy, run:

   RUN_APP_SYNC_WINDOWS.cmd

What to expect
--------------
- The Windows setup script creates .venv, installs Windows dependencies when internet is available,
  checks for FFmpeg, and verifies Ollama.
- The Windows run script launches the same Factbook assistant content set used by the Ubuntu build.
- The sync utility is intended to keep Windows and Ubuntu repo copies aligned around the same files.

USB / portable Windows workflow
-------------------------------
- Setup portable cache and dependencies: USB-INSTALL-CITL.cmd
- Run the portable app: USB-RUN-CITL.cmd

Important note
--------------
- FACTBOOK v2.0 is the March 11, 2026 cross-platform baseline.
- The goal is one repo shape and one sync story across both operating systems.
