param(
  [switch]$Portable,
  [switch]$NoOllama,
  [string]$OllamaHost = "http://localhost:11434"
)
$ErrorActionPreference = "Stop"
# repo root = two levels up from scripts/windows
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path
# setup (creates venv + installs deps if internet)
& (Join-Path $Repo "scripts\windows\setup.ps1") -Portable:$Portable
if (-not $NoOllama) {
  # Start Ollama if needed (non-fatal if it can't)
  try {
    & (Join-Path $Repo "Start-OllamaLocal.ps1") -OllamaHost $OllamaHost | Out-Null
  } catch {
    Write-Warning "Ollama start/check skipped: $($_.Exception.Message)"
  }
}
$py = Join-Path $Repo ".venv\Scripts\python.exe"
# Prefer canonical GUI in factbook-assistant folder
$gui = Join-Path $Repo "factbook-assistant\factbook_assistant_gui.py"
if (!(Test-Path -LiteralPath $gui)) {
  $gui = Join-Path $Repo "factbook_assistant_gui.py"
}
if (!(Test-Path -LiteralPath $gui)) {
  throw "GUI not found. Expected factbook-assistant\factbook_assistant_gui.py or factbook_assistant_gui.py"
}
if ($Portable) { $env:CITL_PORTABLE = "1" }
Write-Host "Launching GUI: $gui" -ForegroundColor Cyan
& $py $gui
