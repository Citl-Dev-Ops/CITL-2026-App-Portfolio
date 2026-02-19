param([switch]$Portable)

$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot
Set-Location $Repo

Write-Host "CITL Transcription - Preflight" -ForegroundColor Cyan

if ($Portable) { $env:CITL_PORTABLE = "1" }

# Python
$py = Join-Path $Repo ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $py)) {
  Write-Warning "Python venv not found at $py"
  Write-Host "Fix:" -ForegroundColor Yellow
  Write-Host "  python -m venv .venv" -ForegroundColor Yellow
  Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
  Write-Host "  pip install -r requirements.txt" -ForegroundColor Yellow
  exit 1
}

# FFmpeg
$ff = Join-Path $Repo "common\bin\ffmpeg.exe"
if (!(Test-Path -LiteralPath $ff)) {
  $alt = Join-Path $Repo "factbook-assistant\bin\ffmpeg.exe"
  if (Test-Path -LiteralPath $alt) {
    New-Item -ItemType Directory -Force (Split-Path $ff -Parent) | Out-Null
    Copy-Item -Force $alt $ff
  }
}
if (Test-Path -LiteralPath $ff) {
  $env:PATH = (Split-Path $ff -Parent) + ";" + $env:PATH
  Write-Host "FFmpeg: OK ($ff)" -ForegroundColor Green
} else {
  Write-Warning "FFmpeg NOT FOUND. Expected $ff (or factbook-assistant\bin\ffmpeg.exe)."
}

# Audio devices (Windows check)
try {
  $audio = Get-CimInstance Win32_SoundDevice -ErrorAction Stop
  if ($audio) { Write-Host ("Audio Devices: OK (" + $audio.Count + " found)") -ForegroundColor Green }
  else { Write-Warning "Audio Devices: none found via Win32_SoundDevice." }
} catch {
  Write-Warning "Audio Devices: unable to query Win32_SoundDevice."
}

Write-Host ""
Write-Host "[STEP] Starting transcription demo..." -ForegroundColor Green

# Find a transcription entrypoint
$targets = @()
$targets += Get-ChildItem -Path (Join-Path $Repo "tools") -Filter "*transcrib*.py" -File -ErrorAction SilentlyContinue
$targets += Get-ChildItem -Path (Join-Path $Repo "factbook-assistant") -Filter "*transcrib*.py" -File -ErrorAction SilentlyContinue
$target = $targets | Select-Object -First 1

if (-not $target) {
  Write-Warning "No transcription Python entrypoint found (searched tools\ and factbook-assistant\ for *transcrib*.py)."
  exit 0
}

& $py $target.FullName
