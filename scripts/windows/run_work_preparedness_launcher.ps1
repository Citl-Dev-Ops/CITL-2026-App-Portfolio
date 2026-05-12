#Requires -Version 5.1
param()
$ErrorActionPreference = "Continue"

function Write-Step { param($m) Write-Host "[....] $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Fail { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

$Repo   = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Script = Join-Path $Repo "factbook-assistant\citl_staff_toolkit.py"

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

# Find Python - check venv first (USB or local), then system Python.
# Never delete the venv; a USB venv may report non-zero on -V but still run scripts fine.
$PY = $null

foreach ($candidate in @(
    (Join-Path $Repo ".venv\Scripts\pythonw.exe"),
    (Join-Path $Repo ".venv\Scripts\python.exe"),
    "C:\Users\$env:USERNAME\CITL\.venv\Scripts\pythonw.exe",
    "C:\Users\$env:USERNAME\CITL\.venv\Scripts\python.exe"
)) {
    if (Test-Path $candidate) { $PY = $candidate; break }
}

if (-not $PY) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $resolved = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($resolved -and (Test-Path $resolved)) { $PY = $resolved }
    }
}

if (-not $PY) {
    foreach ($cmd in @("python", "python3")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) { $PY = $found.Source; break }
    }
}

if (-not $PY) {
    Write-Fail "Python not found. Install Python 3.9+ from https://python.org"
    Write-Host "Or ensure a .venv exists at: $Repo\.venv" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-OK "Python : $PY"
$env:CITL_REPO = $Repo
$env:PYTHONPATH = "$Repo\factbook-assistant;$Repo;$env:PYTHONPATH"
Write-OK "Launching..."
& $PY $Script
exit $LASTEXITCODE
