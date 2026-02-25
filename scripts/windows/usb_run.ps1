param(
  [switch]$InstallOnly,
  [switch]$NoOllama,
  [string]$OllamaHost = "http://localhost:11434"
)

$ErrorActionPreference = "Stop"

$Repo = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path

function Test-Internet {
  try { Invoke-WebRequest -Uri "https://pypi.org" -UseBasicParsing -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}
function Pick-SystemPython {
  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if ($cmd) { return @("py","-3") }
  return @("python",$null)
}
function Ensure-CacheVenv {
  param([string]$CacheRoot)
  $py = Join-Path $CacheRoot ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $py) { return $py }
  New-Item -ItemType Directory -Force $CacheRoot | Out-Null
  Write-Host "Creating cached venv at: $CacheRoot\.venv" -ForegroundColor Yellow
  $sys = Pick-SystemPython
  if ($sys[1]) { & $sys[0] $sys[1] -m venv (Join-Path $CacheRoot ".venv") | Out-Null }
  else { & $sys[0] -m venv (Join-Path $CacheRoot ".venv") | Out-Null }
  if (!(Test-Path -LiteralPath $py)) { throw "Failed to create venv: $py" }
  return $py
}
function Ensure-Deps {
  param([string]$PyExe, [string]$RepoRoot)
  & $PyExe -m pip install -U pip | Out-Null
  if (-not (Test-Internet)) { Write-Warning "Offline: skipping pip install. Connect once and rerun."; return }
  $req = Join-Path $RepoRoot "requirements-windows.txt"
  if (Test-Path -LiteralPath $req) { & $PyExe -m pip install -r $req; return }
  foreach ($f in @("requirements-base.txt","requirements-transcribe.txt","requirements-translate.txt")) {
    $p = Join-Path $RepoRoot $f
    if (Test-Path -LiteralPath $p) { & $PyExe -m pip install -r $p }
  }
}
function Ensure-CommonBinaries {
  param([string]$RepoRoot)
  $zip = Join-Path $RepoRoot "common-binaries.zip"
  if (Test-Path -LiteralPath $zip) {
    $ffLocal = Join-Path $RepoRoot "common\bin\ffmpeg.exe"
    if (!(Test-Path -LiteralPath $ffLocal)) {
      Write-Host "Unpacking common-binaries.zip..." -ForegroundColor Yellow
      Expand-Archive -Force -Path $zip -DestinationPath $RepoRoot
    }
  }
}
function Ensure-FFmpeg {
  param([string]$RepoRoot)
  $ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if ($ff) { return $ff.Source }
  $localFF = Join-Path $RepoRoot "common\bin\ffmpeg.exe"
  if (Test-Path -LiteralPath $localFF) {
    $env:PATH = (Split-Path $localFF -Parent) + ";" + $env:PATH
    return $localFF
  }
  return $null
}

Write-Host "== CITL USB RUN ==" -ForegroundColor White
Write-Host "Repo: $Repo" -ForegroundColor DarkGray

# Keep CITL data ON the USB by default if repo is on removable media;
# otherwise default to repo-local data\citl
$usbData = Join-Path $Repo "data\citl"
New-Item -ItemType Directory -Force $usbData | Out-Null
$env:CITL_PORTABLE = "1"
$env:CITL_DATA_DIR = $usbData

Ensure-CommonBinaries -RepoRoot $Repo

$repoName  = Split-Path -Leaf $Repo
$cacheBase = Join-Path ($env:LOCALAPPDATA ?? $env:APPDATA) "CITL_USB_CACHE\$repoName"
$Py = Ensure-CacheVenv -CacheRoot $cacheBase

Ensure-Deps -PyExe $Py -RepoRoot $Repo

$ffmpeg = Ensure-FFmpeg -RepoRoot $Repo
if ($ffmpeg) { Write-Host "FFmpeg: OK ($ffmpeg)" -ForegroundColor Green }
else { Write-Warning "FFmpeg not found. Put ffmpeg.exe in common\bin\ or ensure common-binaries.zip contains it." }

if (-not $NoOllama) {
  $starter = Join-Path $Repo "Start-OllamaLocal.ps1"
  if (Test-Path -LiteralPath $starter) {
    try { & $starter -OllamaHost $OllamaHost | Out-Null } catch { Write-Warning "Ollama start/check skipped: $($_.Exception.Message)" }
  }
}

if ($InstallOnly) { Write-Host "InstallOnly complete." -ForegroundColor Green; exit 0 }

$gui = Join-Path $Repo "factbook-assistant\factbook_assistant_gui.py"
if (!(Test-Path -LiteralPath $gui)) { $gui = Join-Path $Repo "factbook_assistant_gui.py" }
if (!(Test-Path -LiteralPath $gui)) { throw "GUI not found. Expected factbook-assistant\factbook_assistant_gui.py" }

Write-Host "Launching GUI: $gui" -ForegroundColor Cyan
& $Py $gui
