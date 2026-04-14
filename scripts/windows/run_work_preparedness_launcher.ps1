#Requires -Version 5.1
param()
$ErrorActionPreference = "Stop"

function Write-Step { param($m) Write-Host "[....] $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Fail { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Script = Join-Path $Repo "factbook-assistant\citl_staff_toolkit.py"
$VenvPy = Join-Path $Repo ".venv\Scripts\python.exe"

if (Test-Path $VenvPy) {
    & $VenvPy -V *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Existing .venv is invalid, recreating..."
        try { Remove-Item -Recurse -Force (Join-Path $Repo ".venv") } catch { }
    }
}

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  CITL Work and Preparedness Launcher" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-OK "Repo   : $Repo"
Write-OK "Script : $Script"

if (-not (Test-Path $Script)) {
    Write-Fail "Script not found: $Script"
    exit 1
}

if (-not (Test-Path $VenvPy)) {
    Write-Step "Creating .venv and installing requirements..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv (Join-Path $Repo ".venv")
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv (Join-Path $Repo ".venv")
    } else {
        Write-Fail "Python not found."
        exit 1
    }
    if (-not (Test-Path $VenvPy)) {
        Write-Fail "Could not create virtual environment."
        exit 1
    }
    $req = Join-Path $Repo "requirements-windows.txt"
    if (-not (Test-Path $req)) { $req = Join-Path $Repo "requirements.txt" }
    if (Test-Path $req) {
        & $VenvPy -m pip install --upgrade pip
        & $VenvPy -m pip install -r $req
    }
}

$env:CITL_REPO = $Repo
Write-OK "Launching..."
& $VenvPy $Script
exit $LASTEXITCODE
