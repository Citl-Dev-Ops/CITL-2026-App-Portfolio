New-Item -ItemType Directory -Force -Path scripts,results,models | Out-Null

@'
param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "== CITL Bootstrap (Windows) ==" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"

function Require-Cmd($name, $hint) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Write-Host "MISSING: $name" -ForegroundColor Yellow
    Write-Host $hint
    exit 1
  }
}

# Python required
Require-Cmd python "Install Python 3.12+ and re-run this script."

# venv
if (-not (Test-Path ".venv")) {
  Write-Host "Creating venv..."
  python -m venv .venv
}

$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
& $Py -m pip install -U pip setuptools wheel

if (Test-Path "requirements.txt") {
  & $Py -m pip install -r requirements.txt
} else {
  Write-Host "WARNING: requirements.txt not found at repo root. Skipping pip install." -ForegroundColor Yellow
}

# ffmpeg (required for transcription / audio pipelines)
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Host "WARNING: ffmpeg not found. Install FFmpeg (recommended) and re-run." -ForegroundColor Yellow
}

# Ollama check (Windows installer is official path)
if (Get-Command ollama -ErrorAction SilentlyContinue) {
  Write-Host "Ollama: OK"
} else {
  Write-Host "Ollama: MISSING" -ForegroundColor Yellow
  Write-Host "Install Ollama for Windows from the official download page, then re-run." 
  Write-Host "https://ollama.com/download/windows"
}

Write-Host "Bootstrap complete."
Write-Host "Next: .\scripts\run_windows.ps1"
'@ | Set-Content -Encoding UTF8 scripts\bootstrap_windows.ps1
