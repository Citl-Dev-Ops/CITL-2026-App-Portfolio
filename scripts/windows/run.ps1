param(
  [switch]$Portable,
  [switch]$NoOllama,
  [string]$OllamaHost = "http://localhost:11434"
)
$ErrorActionPreference = "Stop"

# repo root = two levels up from scripts/windows
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path

# Run setup (creates venv, installs deps if internet available)
& (Join-Path $Repo "scripts\windows\setup.ps1") -Portable:$Portable

if (-not $NoOllama) {
  $ollamaStarter = Join-Path $Repo "Start-OllamaLocal.ps1"
  if (Test-Path -LiteralPath $ollamaStarter) {
    try {
      & $ollamaStarter -OllamaHost $OllamaHost | Out-Null
    } catch {
      Write-Warning "Ollama start/check skipped: $($_.Exception.Message)"
    }
  }
}

$py = Join-Path $Repo ".venv\Scripts\python.exe"

$gui = Join-Path $Repo "factbook-assistant\factbook_assistant_gui.py"
if (!(Test-Path -LiteralPath $gui)) {
  $gui = Join-Path $Repo "factbook_assistant_gui.py"
}
if (!(Test-Path -LiteralPath $gui)) {
  throw "GUI not found. Expected factbook-assistant\factbook_assistant_gui.py"
}

if ($Portable) { $env:CITL_PORTABLE = "1" }
Write-Host "Launching GUI: $gui" -ForegroundColor Cyan
& $py $gui
