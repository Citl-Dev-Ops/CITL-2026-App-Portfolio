#Requires -Version 5.1
param(
    [switch]$Portable,
    [switch]$ForcePython
)
$ErrorActionPreference = "Continue"

function Write-Step { param($m) Write-Host "[....] $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  CITL LLMOps Presentation Suite" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

# ---- Locate repo root (two levels up from scripts/windows) ------------------
$Repo   = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Script = Join-Path $Repo "factbook-assistant\citl_llmops_suite.py"
$Exe    = Join-Path $Repo "dist\CITL LLMOps Presentation Suite\CITL LLMOps Presentation Suite.exe"
Write-OK "Repo   : $Repo"
Write-OK "Script : $Script"

if (-not $ForcePython -and (Test-Path $Exe)) {
    Write-OK "Using EXE : $Exe"
    $env:CITL_REPO = $Repo
    $proc = Start-Process -FilePath $Exe -WorkingDirectory $Repo -PassThru
    $proc.WaitForExit()
    exit $proc.ExitCode
}

# ---- Detect non-C: drive and use portable venv cache ------------------------
$repoDrive = (Split-Path -Qualifier $Repo).ToUpper()
if ($repoDrive -ne "C:" -or $Portable) {
    $CacheBase = Join-Path $env:LOCALAPPDATA "CITL_USB_CACHE\citl_llmops_suite"
    $env:CITL_PORTABLE = "1"
} else {
    $CacheBase = $Repo
}
$VenvPy = Join-Path $CacheBase ".venv\Scripts\python.exe"

# ---- Find real Python (skip Windows Store stub) -----------------------------
Write-Step "Checking Python..."
$pythonExe = $null
$knownPaths = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Program Files\Python311\python.exe",
    "C:\Program Files\Python312\python.exe"
)
foreach ($p in $knownPaths) {
    if (Test-Path $p) { $pythonExe = $p; break }
}
if (-not $pythonExe) {
    foreach ($name in @("python","python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
            $v = & $cmd.Source --version 2>&1
            if ($v -match "3\.(9|1[0-9])") { $pythonExe = $cmd.Source; break }
        }
    }
}
if (-not $pythonExe -and -not (Test-Path $VenvPy)) {
    Write-Warn "Python not found. Trying winget..."
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if ($wg) {
        & winget install Python.Python.3.11 --silent --accept-source-agreements --accept-package-agreements
        $env:PATH = [Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH","User")
        foreach ($p in $knownPaths) { if (Test-Path $p) { $pythonExe = $p; break } }
    }
}
if ($pythonExe) { Write-OK "Python : $pythonExe" } else { Write-Warn "Python not pre-located (venv may already exist)" }

# ---- Create venv if missing -------------------------------------------------
if (-not (Test-Path $VenvPy)) {
    if (-not $pythonExe) {
        Write-Fail "Python 3.9+ not found. Install from https://www.python.org/downloads/"
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Step "Creating venv..."
    $venvDir = Join-Path $CacheBase ".venv"
    $venvParent = Split-Path $venvDir -Parent
    if (-not (Test-Path $venvParent)) { New-Item -ItemType Directory -Force -Path $venvParent | Out-Null }
    & $pythonExe -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Write-Fail "venv creation failed"; Read-Host; exit 1 }

    Write-Step "Installing dependencies..."
    $req = Join-Path $Repo "requirements-windows.txt"
    if (-not (Test-Path $req)) { $req = Join-Path $Repo "requirements.txt" }
    & $VenvPy -m pip install --upgrade pip --quiet 2>&1 | Out-Null
    if (Test-Path $req) {
        & $VenvPy -m pip install -r $req --quiet
    } else {
        & $VenvPy -m pip install requests psutil pillow --quiet
    }
    Write-OK "Dependencies installed."
}
Write-OK "venv     : $VenvPy"

# ---- Verify script exists ---------------------------------------------------
if (-not (Test-Path $Script)) {
    Write-Fail "Script not found: $Script"
    Read-Host "Press Enter to exit"
    exit 1
}

Write-OK "Launching GUI..."
try {
    $proc = Start-Process -FilePath $VenvPy -ArgumentList @("`"$Script`"") -WorkingDirectory $Repo -PassThru
} catch {
    Write-Fail "Could not start python process: $_"
    Read-Host "Press Enter to exit"
    exit 1
}

Start-Sleep -Seconds 2
$log = Join-Path $Repo "factbook-assistant\citl_llmops_crash.log"
if ($proc.HasExited) {
    $ec = $proc.ExitCode
    Write-Fail "Process exited immediately with code $ec."
    if (Test-Path $log) { Write-Host "--- Crash log ---" -ForegroundColor Yellow; Get-Content $log | Write-Host }
    Read-Host "Press Enter to exit"
    exit ([Math]::Max(1, $ec))
}

Write-OK "GUI process started (PID $($proc.Id))."
exit 0
