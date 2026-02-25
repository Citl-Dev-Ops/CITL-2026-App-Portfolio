param(
  [switch]$Portable
)
$ErrorActionPreference = "Stop"

function Test-Internet {
  try {
    $r = Invoke-WebRequest "https://pypi.org" -UseBasicParsing -TimeoutSec 4
    return $true
  } catch { return $false }
}

function Ensure-Venv {
  param([string]$Repo)
  $py = Join-Path $Repo ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $py) { return $py }
  Write-Host "Creating venv (.venv)..." -ForegroundColor Yellow
  $sysPy = $null
  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if ($cmd) { $sysPy = "py -3" } else { $sysPy = "python" }
  cmd /c "$sysPy -m venv .venv" | Out-Null
  if (!(Test-Path -LiteralPath $py)) { throw "Failed to create venv: $py" }
  return $py
}

function Ensure-CommonBinaries {
  param([string]$Repo)
  $zip = Join-Path $Repo "common-binaries.zip"
  if (Test-Path -LiteralPath $zip) {
    $ffLocal = Join-Path $Repo "common\bin\ffmpeg.exe"
    if (!(Test-Path -LiteralPath $ffLocal)) {
      Write-Host "Unpacking common-binaries.zip..." -ForegroundColor Yellow
      Expand-Archive -Force -Path $zip -DestinationPath $Repo
    }
  }
}

function Ensure-FFmpeg {
  param([string]$Repo)
  $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source) { return $cmd.Source }
  $localFF = Join-Path $Repo "common\bin\ffmpeg.exe"
  if (Test-Path -LiteralPath $localFF) {
    $env:Path = (Split-Path $localFF -Parent) + ";" + $env:Path
    return $localFF
  }
  return $null
}

# repo root = two levels up from scripts/windows
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path
Write-Host "== CITL Setup (Windows) ==" -ForegroundColor Cyan
Write-Host "Repo: $Repo"

if ($Portable) { $env:CITL_PORTABLE = "1" }

Ensure-CommonBinaries -Repo $Repo
$py = Ensure-Venv -Repo $Repo

$online = Test-Internet
Write-Host ("Internet: " + ($(if($online){"OK"}else{"OFFLINE"}))) -ForegroundColor White
Write-Host "Upgrading pip..." -ForegroundColor White
& $py -m pip install -U pip | Out-Null

if ($online) {
  $req = Join-Path $Repo "requirements-windows.txt"
  if (Test-Path -LiteralPath $req) {
    Write-Host "Installing requirements-windows.txt..." -ForegroundColor White
    & $py -m pip install -r $req
  } else {
    # Fallback: install sub-files individually
    foreach ($f in @("requirements-base.txt","requirements-transcribe.txt","requirements-translate.txt")) {
      $p = Join-Path $Repo $f
      if (Test-Path -LiteralPath $p) { & $py -m pip install -r $p }
    }
  }
} else {
  Write-Warning "Offline: skipping pip install. Connect to internet and rerun."
}

$ff = Ensure-FFmpeg -Repo $Repo
if ($ff) {
  Write-Host "FFmpeg: OK ($ff)" -ForegroundColor Green
} else {
  Write-Warning "FFmpeg not found. Place ffmpeg.exe in common\bin\ or ensure common-binaries.zip exists, then rerun."
}

$ollamaExe = @(
  "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
  "$env:ProgramFiles\Ollama\ollama.exe",
  "$env:ProgramFiles(x86)\Ollama\ollama.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($ollamaExe) {
  Write-Host "Ollama: OK ($ollamaExe)" -ForegroundColor Green
} else {
  Write-Warning "Ollama not found. Install from https://ollama.com/download/windows then rerun."
}

Write-Host "Setup complete." -ForegroundColor Green
