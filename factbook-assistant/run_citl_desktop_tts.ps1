param([switch]$Portable)

$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot
Set-Location $Repo

Write-Host "CITL TTS - Preflight" -ForegroundColor Cyan
if ($Portable) { $env:CITL_PORTABLE = "1" }

$py = Join-Path $Repo ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $py)) {
  Write-Warning "Python venv not found at $py"
  exit 1
}

Write-Host ""
Write-Host "[STEP] Starting TTS demo..." -ForegroundColor Green

# Find a TTS entrypoint
$targets = @()
$tools = Join-Path $Repo "tools"
if (Test-Path -LiteralPath $tools) { $targets += Get-ChildItem -Path $tools -Filter "*tts*.py" -File -ErrorAction SilentlyContinue }
$target = $targets | Select-Object -First 1

if (-not $target) {
  Write-Warning "No TTS Python entrypoint found (searched tools\ for *tts*.py)."
  exit 0
}

& $py $target.FullName
