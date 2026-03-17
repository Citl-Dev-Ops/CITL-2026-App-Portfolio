param(
  [switch]$Desktop   # also create Desktop shortcuts (Start Menu always created)
)
$ErrorActionPreference = "Stop"

# repo root = two levels up from scripts/windows
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path
$py   = Join-Path $Repo ".venv\Scripts\python.exe"

Write-Host "== CITL Update (Windows) ==" -ForegroundColor Cyan
Write-Host "Repo: $Repo"
Write-Host ""

# ── 1. Python packages ─────────────────────────────────────────────────────────
Write-Host "[1/4] Upgrading Python packages..." -ForegroundColor Yellow
if (!(Test-Path -LiteralPath $py)) {
  Write-Warning "  venv not found at .venv — run INSTALL_WINDOWS.cmd first, then re-run UPDATE-CITL.cmd."
} else {
  & $py -m pip install -U pip | Out-Null
  $req = Join-Path $Repo "requirements-windows.txt"
  if (Test-Path -LiteralPath $req) {
    Write-Host "  Installing: requirements-windows.txt" -ForegroundColor White
    & $py -m pip install -U -r $req
    Write-Host "  OK: requirements-windows.txt" -ForegroundColor Green
  } else {
    # Fallback: install sub-files individually
    foreach ($f in @("requirements-base.txt","requirements-transcribe.txt","requirements-translate.txt")) {
      $p = Join-Path $Repo $f
      if (Test-Path -LiteralPath $p) {
        Write-Host "  Installing: $f" -ForegroundColor White
        & $py -m pip install -U -r $p
      }
    }
  }
}

# ── 2. Ollama ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[2/4] Checking Ollama..." -ForegroundColor Yellow
$ollamaExe = @(
  "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
  "$env:ProgramFiles\Ollama\ollama.exe",
  "$env:ProgramFiles(x86)\Ollama\ollama.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($ollamaExe) {
  $ver = (& $ollamaExe --version 2>&1) -join " " | Select-String '\d+\.\d+\.\d+' |
         ForEach-Object { $_.Matches[0].Value }
  Write-Host "  Installed: $ver  ($ollamaExe)" -ForegroundColor Green
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "  Upgrading via winget (silent)..."
    winget upgrade --id Ollama.Ollama --silent --accept-package-agreements `
                   --accept-source-agreements 2>&1 | Out-Null
    Write-Host "  Ollama upgrade step complete." -ForegroundColor Green
  } else {
    Write-Host "  winget not available — download manually from https://ollama.com/download/windows" -ForegroundColor Yellow
  }
} else {
  Write-Warning "  Ollama not found. Install from: https://ollama.com/download/windows"
}

# ── 3. FFmpeg ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[3/4] Checking FFmpeg..." -ForegroundColor Yellow
$ffCmd   = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffLocal = Join-Path $Repo "common\bin\ffmpeg.exe"

if ($ffCmd -and $ffCmd.Source) {
  Write-Host "  FFmpeg (system): $($ffCmd.Source)" -ForegroundColor Green
} elseif (Test-Path -LiteralPath $ffLocal) {
  Write-Host "  FFmpeg (local): $ffLocal" -ForegroundColor Green
  # Add to PATH for this session
  $env:Path = (Split-Path $ffLocal -Parent) + ";" + $env:Path
} else {
  Write-Warning "  FFmpeg not found. Place ffmpeg.exe in common\bin\ or install system-wide."
}

# ── 4. Shortcuts ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[4/4] Creating/updating shortcuts..." -ForegroundColor Yellow
$wsh = New-Object -ComObject WScript.Shell

$startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\CITL"
New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null

# Desktop folder (only used if -Desktop flag passed)
$desktopDir = [Environment]::GetFolderPath("Desktop")

# Icon: use a bundled .ico if present, otherwise omit
$defaultIcon = Join-Path $Repo "factbook-assistant\bin\citl.ico"
if (!(Test-Path -LiteralPath $defaultIcon)) { $defaultIcon = "" }

$shortcuts = @(
  [pscustomobject]@{
    Name   = "CITL Factbook"
    Target = Join-Path $Repo "RUN_FACTBOOK_WINDOWS.cmd"
    Desc   = "CITL Study & Library Q&A, Transcription, Translation, TTS"
    Icon   = $defaultIcon
  },
  [pscustomobject]@{
    Name   = "CITL App Sync"
    Target = Join-Path $Repo "RUN_APP_SYNC_WINDOWS.cmd"
    Desc   = "CITL cross-platform sync and update utility"
    Icon   = $defaultIcon
  },
  [pscustomobject]@{
    Name   = "CITL (Launch)"
    Target = Join-Path $Repo "CITL-Run.cmd"
    Desc   = "Launch CITL"
    Icon   = $defaultIcon
  }
)

function New-Shortcut {
  param($wsh, [string]$LnkPath, [string]$Target, [string]$WorkDir, [string]$Desc, [string]$Icon)
  $lnk = $wsh.CreateShortcut($LnkPath)
  $lnk.TargetPath      = $Target
  $lnk.WorkingDirectory = $WorkDir
  $lnk.Description     = $Desc
  if ($Icon -and (Test-Path -LiteralPath $Icon)) { $lnk.IconLocation = $Icon }
  $lnk.Save()
}

foreach ($sc in $shortcuts) {
  if (!(Test-Path -LiteralPath $sc.Target)) {
    Write-Host "  SKIP (target missing): $($sc.Name)" -ForegroundColor DarkYellow
    continue
  }
  $smLnk = Join-Path $startMenuDir "$($sc.Name).lnk"
  New-Shortcut $wsh $smLnk $sc.Target $Repo $sc.Desc $sc.Icon
  Write-Host "  Start Menu: $($sc.Name)" -ForegroundColor Green

  if ($Desktop) {
    $dLnk = Join-Path $desktopDir "$($sc.Name).lnk"
    New-Shortcut $wsh $dLnk $sc.Target $Repo $sc.Desc $sc.Icon
    Write-Host "  Desktop   : $($sc.Name)" -ForegroundColor Green
  }
}

Write-Host ""
Write-Host "Update complete." -ForegroundColor Cyan
Write-Host "Start Menu folder: $startMenuDir"
if ($Desktop) { Write-Host "Desktop shortcuts also created." }
