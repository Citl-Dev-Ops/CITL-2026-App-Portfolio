param(
  [string]$OllamaHost = "http://127.0.0.1:11434",
  [switch]$Portable
)
$ErrorActionPreference = "Stop"
# IMPORTANT: use PSScriptRoot so this works when run as a .ps1 file
$Repo = $PSScriptRoot
if (-not $Repo) { $Repo = (Get-Location).Path }
Set-Location $Repo
Write-Host ""
Write-Host "CITL Factbook GUI - Preflight" -ForegroundColor Cyan
Write-Host "Repo: $Repo"
Write-Host ""
# --- Python / venv ---
$py = Join-Path $Repo ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $py)) {
  throw "Python venv not found: $py`nFix: python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt"
}
# --- FFmpeg ---
$ff = $null
$ffCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffCmd) { $ff = $ffCmd.Source }
if (-not $ff) {
  $localFF = Join-Path $Repo "common\bin\ffmpeg.exe"
  if (Test-Path -LiteralPath $localFF) {
    $env:PATH = (Split-Path $localFF -Parent) + ";" + $env:PATH
    $ff = $localFF
  }
}
if ($ff) {
  Write-Host "FFmpeg: OK ($ff)" -ForegroundColor Green
  & ffmpeg -version 2>$null | Select-Object -First 1
} else {
  Write-Warning "FFmpeg: NOT FOUND. Put ffmpeg.exe in .\common\bin OR install FFmpeg and ensure it's on PATH."
}
# --- Audio device check ---
try {
  $audio = Get-CimInstance Win32_SoundDevice -ErrorAction Stop
  if ($audio) { Write-Host ("Audio Devices: OK (" + $audio.Count + " found)") -ForegroundColor Green }
  else { Write-Warning "Audio Devices: none found via Win32_SoundDevice." }
} catch {
  Write-Warning "Audio Devices: unable to query Win32_SoundDevice."
}
# --- Ollama check + auto-start attempt ---
$env:CITL_OLLAMA_HOST = $OllamaHost
$ollOk = $false
try { Invoke-RestMethod "$OllamaHost/api/tags" -TimeoutSec 2 | Out-Null; $ollOk = $true } catch { $ollOk = $false }
if (-not $ollOk -and (Test-Path .\Start-OllamaLocal.ps1)) {
  & .\Start-OllamaLocal.ps1 -OllamaHost $OllamaHost | Out-Null
  try { Invoke-RestMethod "$OllamaHost/api/tags" -TimeoutSec 2 | Out-Null; $ollOk = $true } catch { $ollOk = $false }
}
if ($ollOk) { Write-Host "Ollama API: OK ($OllamaHost)" -ForegroundColor Green }
else { Write-Warning "Ollama API: NOT REACHABLE at $OllamaHost (GUI will still open, but chat will fail until Ollama is running)." }
# --- Portable mode ---
if ($Portable) { $env:CITL_PORTABLE = "1" }
Write-Host ""
Write-Host "Launching GUI..." -ForegroundColor Cyan
# Prefer the newer GUI inside factbook-assistant if present
if (Test-Path ".\factbook-assistant\factbook_assistant_gui.py") {
  & $py ".\factbook-assistant\factbook_assistant_gui.py"
} else {
  & $py ".\factbook_assistant_gui.py"
}
