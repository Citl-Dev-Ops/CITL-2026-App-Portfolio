CITL Sync Utility Launchers
===========================

Ubuntu launcher: RUN_APP_SYNC_UBUNTU.sh
Windows launcher: RUN_APP_SYNC_WINDOWS.cmd

Self-duplicate launchers (USB -> next USB):
  Ubuntu: COPY_THIS_USB_TO_NEXT_UBUNTU.sh
  Windows: COPY_THIS_USB_TO_NEXT_WINDOWS.cmd

These launchers search this USB drive for the CITL repo and then open the
cross-platform sync utility.

Default sync behavior is time-considerate: full repo delta copy while excluding
large model/data/media folders unless explicitly requested.

Headless options:
  --sync-best-usb                 Auto-pick best USB target and sync PC -> USB
  --duplicate-usb                 Duplicate one USB copy to another
  --duplicate-from <path>         Source USB path for duplicate mode
  --duplicate-to <path>           Destination USB path for duplicate mode
  --include-models                Include repo models/ollama folders
  --ollama-model-source <path>    Optional external Ollama model source directory
  --ollama-model-target <path>    Optional external Ollama model target directory
