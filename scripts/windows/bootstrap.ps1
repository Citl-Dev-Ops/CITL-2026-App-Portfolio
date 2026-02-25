param(
  [string]$OllamaHost = "http://localhost:11434",
  [string]$Model = "llama3.1:8b",
  [switch]$PullModel,
  [switch]$Portable
)
$ErrorActionPreference = "Stop"
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path
Set-Location $Repo

function Test-Internet {
  try { Invoke-WebRequest -Uri "https://pypi.org" -UseBasicParsing -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}

function Find-OllamaExe {
  $candidates = @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "$env:ProgramFiles\Ollama\ollama.exe",
    "$env:ProgramFiles(x86)\Ollama\ollama.exe"
  )
  foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
  return $null
}

function Ensure-Venv {
  if (!(Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating venv..." -ForegroundColor Cyan
    python -m venv .venv
  }
  & .\.venv\Scripts\python.exe -m pip install -U pip | Out-Null
}

function Ensure-PythonDeps {
  if (Test-Internet) {
    Write-Host "Internet: OK. Installing deps..." -ForegroundColor Green
    $req = ".\requirements-windows.txt"
    if (Test-Path $req) {
      & .\.venv\Scripts\python.exe -m pip install -r $req
    } else {
      # Fallback to base requirements.txt
      & .\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
    }
  } else {
    Write-Warning "Internet not detected. Skipping pip install."
  }
}

function Ensure-FFmpeg {
  $ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if ($ff) { Write-Host "FFmpeg: OK ($($ff.Source))" -ForegroundColor Green; return }

  $localFF = Join-Path $Repo "common\bin\ffmpeg.exe"
  if (Test-Path $localFF) {
    $env:PATH = (Split-Path $localFF -Parent) + ";" + $env:PATH
    Write-Host "FFmpeg: OK ($localFF)" -ForegroundColor Green
    return
  }

  if (-not (Test-Internet)) {
    Write-Warning "FFmpeg not found and no internet. Place ffmpeg.exe in common\bin\ and rerun."
    return
  }

  Write-Host "FFmpeg missing. Downloading to common\bin\ ..." -ForegroundColor Cyan
  New-Item -ItemType Directory -Force (Join-Path $Repo "common\bin") | Out-Null
  $zip = Join-Path $Repo "common\bin\ffmpeg.zip"
  $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
  Invoke-WebRequest $url -OutFile $zip -UseBasicParsing
  $tmp = Join-Path $Repo "common\bin\_ffmpeg_tmp"
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $exe = Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
  if (-not $exe) { throw "FFmpeg download succeeded but ffmpeg.exe not found in archive." }
  Copy-Item $exe.FullName $localFF -Force
  Remove-Item $zip -Force
  Remove-Item $tmp -Recurse -Force
  $env:PATH = (Split-Path $localFF -Parent) + ";" + $env:PATH
  Write-Host "FFmpeg: OK ($localFF)" -ForegroundColor Green
}

function Start-Ollama {
  $ollama = Find-OllamaExe
  if (-not $ollama) {
    Write-Warning "Ollama not found. Install: winget install Ollama.Ollama"
    return $null
  }
  $dir = Split-Path $ollama -Parent
  if ($env:Path -notlike "*$dir*") { $env:Path = "$dir;$env:Path" }

  $listening = $false
  try {
    $tcp = Test-NetConnection "localhost" -Port 11434 -WarningAction SilentlyContinue
    $listening = [bool]$tcp.TcpTestSucceeded
  } catch {}

  if (-not $listening) {
    Write-Host "Starting Ollama (serve)..." -ForegroundColor Cyan
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep 2
  }

  try {
    Invoke-RestMethod "$OllamaHost/api/tags" -TimeoutSec 3 | Out-Null
    Write-Host "Ollama API: OK ($OllamaHost)" -ForegroundColor Green
  } catch {
    Write-Warning "Ollama API not reachable at $OllamaHost"
  }

  if ($PullModel) { & $ollama pull $Model }
  return $ollama
}

if ($Portable) { $env:CITL_PORTABLE = "1" }

Write-Host "== CITL Bootstrap (Windows) ==" -ForegroundColor White
Write-Host "Repo: $Repo" -ForegroundColor DarkGray

Ensure-Venv
Ensure-PythonDeps
Ensure-FFmpeg
Start-Ollama | Out-Null

# Launch GUI
$gui1 = Join-Path $Repo "factbook-assistant\factbook_assistant_gui.py"
$gui2 = Join-Path $Repo "factbook_assistant_gui.py"
if (Test-Path $gui1) {
  Write-Host "Launching GUI: $gui1" -ForegroundColor Green
  & .\.venv\Scripts\python.exe $gui1
} elseif (Test-Path $gui2) {
  Write-Host "Launching GUI: $gui2" -ForegroundColor Green
  & .\.venv\Scripts\python.exe $gui2
} else {
  throw "No GUI found. Expected: factbook-assistant\factbook_assistant_gui.py"
}
