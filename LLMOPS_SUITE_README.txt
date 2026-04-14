CITL LLMOps Presentation Suite - Location and Launch Guide
==========================================================

Primary GUI source:
  factbook-assistant/citl_llmops_suite.py

Windows launchers:
  RUN_LLMOPS_WINDOWS.cmd
  scripts/windows/run_llmops.ps1

Ubuntu launcher:
  RUN_LLMOPS.sh

Build a Windows EXE:
  BUILD_LLMOPS_EXE_WINDOWS.cmd
  (or) powershell -ExecutionPolicy Bypass -File scripts/windows/build_llmops_exe.ps1

Built EXE output folder:
  dist/CITL LLMOps Presentation Suite/

Notes:
- RUN_LLMOPS_WINDOWS.cmd now prefers the built EXE when present.
- If no EXE is present, it falls back to the PowerShell/Python launcher automatically.
