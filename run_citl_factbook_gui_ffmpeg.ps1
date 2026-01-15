param()

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Activate venv (adjust if your venv folder differs)
$venv = Join-Path $root ".venv-1\Scripts\Activate.ps1"
if (Test-Path $venv) { . $venv } else { Write-Host "WARNING: venv not found at $venv" -ForegroundColor Yellow }

# Optional: set ffmpeg path override if you want
# $env:CITL_FFMPEG_PATH="C:\path\to\ffmpeg.exe"

python ".\factbook-assistant\factbook_assistant_gui_ffmpeg.py"
