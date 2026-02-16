param(
  [switch]$Portable
)
$ErrorActionPreference = "Stop"
function Test-Internet {
  try {
    # fast + reliable enough for "online"
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
    # only unpack if ffmpeg isn't already present
    $ffLocal = Join-Path $Repo "common\bin\ffmpeg.exe"
    if (!(Test-Path -LiteralPath $ffLocal)) {
      Write-Host "Unpacking common-binaries.zip (attempting to restore ffmpeg/tools)..." -ForegroundColor Yellow
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
# pip install when internet is available
$online = Test-Internet
Write-Host ("Internet: " + ($(if($online){"OK"}else{"OFFLINE"}))) -ForegroundColor White
Write-Host "Installing Python deps..." -ForegroundColor White
& $py -m pip install -U pip | Out-Null
if ($online) {
  & $py -m pip install -r (Join-Path $Repo "requirements-windows.txt")
} else {
  Write-Warning "Offline: skipping pip install. (Use internet once, then rerun.)"
}
$ff = Ensure-FFmpeg -Repo $Repo
if ($ff) {
  Write-Host "FFmpeg: OK ($ff)" -ForegroundColor Green
} else {
  Write-Warning "FFmpeg not found. Put ffmpeg.exe in common\bin\ or ensure common-binaries.zip contains it, then rerun."
}
# Try to locate Ollama exe even if not starting it here
$ollamaExe = @(
  "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
  "$env:ProgramFiles\Ollama\ollama.exe",
  "$env:ProgramFiles(x86)\Ollama\ollama.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($ollamaExe) {
  Write-Host "Ollama exe: OK ($ollamaExe)" -ForegroundColor Green
} else {
  Write-Warning "Ollama exe not found (OK if you aren't using LLM answers yet)."
}
Write-Host "Setup complete." -ForegroundColor Green
