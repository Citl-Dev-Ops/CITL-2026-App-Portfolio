param()
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$venv = Join-Path $root ".venv-1\Scripts\Activate.ps1"
if (Test-Path $venv) { . $venv }
python ".\factbook-assistant\factbook_assistant_gui_ffmpeg_graceful_v2.py"
