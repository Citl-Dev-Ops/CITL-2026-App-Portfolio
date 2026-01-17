$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$py = Join-Path $here ".venv\Scripts\python.exe"
if (!(Test-Path $py)) { $py = "python" }

$script = Join-Path $here "factbook_assistant_gui.py"
if (!(Test-Path $script)) {
  Write-Host "ERROR: factbook_assistant_gui.py not found next to launcher." -ForegroundColor Red
  Write-Host "Folder: $here"
  pause
  exit 1
}

& $py $script