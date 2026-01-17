param()

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$ff = Join-Path $root "factbook-assistant\bin\ffmpeg.exe"
if (-not (Test-Path $ff)) {
  Write-Host "[ERROR] Missing ffmpeg.exe at:" -ForegroundColor Red
  Write-Host "  $ff"
  Write-Host "`nFix: Put ffmpeg.exe in factbook-assistant\bin\ffmpeg.exe" -ForegroundColor Yellow
  exit 1
}

Write-Host "`n[CITL] Listing DirectShow audio devices (FFmpeg)..." -ForegroundColor Cyan

$out = & $ff -hide_banner -f dshow -list_devices true -i dummy 2>&1
$lines = $out | Out-String | Select-String -Pattern "DirectShow audio devices|DirectShow video devices|`"" -AllMatches

# Extract audio device names appearing between the "audio devices" marker and before "video devices"
$audio = @()
$inAudio = $false
foreach ($l in ($out | Out-String).Split("`n")) {
  if ($l -match "DirectShow audio devices") { $inAudio = $true; continue }
  if ($l -match "DirectShow video devices") { $inAudio = $false; break }
  if ($inAudio -and $l -match '"([^"]+)"') {
    $name = $Matches[1].Trim()
    if ($name -and -not ($audio -contains $name)) { $audio += $name }
  }
}

if (-not $audio -or $audio.Count -eq 0) {
  Write-Host "`n[ERROR] No DirectShow audio devices found." -ForegroundColor Red
  Write-Host "Windows likely blocked mic access or driver did not enumerate." -ForegroundColor Yellow
  Write-Host "`nTry:" -ForegroundColor Yellow
  Write-Host "  1) Settings -> Privacy & security -> Microphone -> enable desktop apps"
  Write-Host "  2) Settings -> System -> Sound -> Input -> select the Yeti"
  Write-Host "  3) Replug the Yeti (different USB port)"
  exit 2
}

Write-Host "`n[CITL] Audio devices found:" -ForegroundColor Green
$audio | ForEach-Object { Write-Host "  - $_" }

# Pick best match for Yeti
$pick = $audio | Where-Object { $_ -match "(?i)yeti" } | Select-Object -First 1
if (-not $pick) { $pick = $audio | Where-Object { $_ -match "(?i)blue" } | Select-Object -First 1 }
if (-not $pick) { $pick = $audio | Select-Object -First 1 }

Write-Host "`n[CITL] Selected device:" -ForegroundColor Cyan
Write-Host "  $pick"

# Write config to %APPDATA%\CITL\config.json (same place the GUI uses)
$dataDir = Join-Path $env:APPDATA "CITL"
New-Item -ItemType Directory -Force $dataDir | Out-Null
$cfgPath = Join-Path $dataDir "config.json"

$cfg = @{}
if (Test-Path $cfgPath) {
  try { $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json -AsHashtable } catch { $cfg = @{} }
}

$cfg["dshow_audio_device"] = $pick

$cfg | ConvertTo-Json -Depth 6 | Set-Content -Path $cfgPath -Encoding UTF8

Write-Host "`n[CITL] Wrote config:" -ForegroundColor Green
Write-Host "  $cfgPath"
Write-Host "  dshow_audio_device = $pick"

Write-Host "`n[CITL] Launching GUI..." -ForegroundColor Green
& (Join-Path $root "run_citl_factbook_gui_ffmpeg.ps1")
