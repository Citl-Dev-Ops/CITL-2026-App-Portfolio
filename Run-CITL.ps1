$ErrorActionPreference="Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (Test-Path ".\.venv\Scripts\Activate.ps1") { . ".\.venv\Scripts\Activate.ps1" }
$env:CITL_OLLAMA_HOST="http://127.0.0.1:11434"
$env:CITL_LLM_MODEL="llama3.1:8b"
$oll=(Get-Command ollama -ErrorAction SilentlyContinue).Source
if ($oll) { Start-Process -WindowStyle Hidden -FilePath $oll -ArgumentList "serve" | Out-Null }
Start-Sleep -Seconds 1
python ".\factbook-assistant\factbook_assistant_gui.py"
