# run_citl_desktop_tts.ps1
# CITL Desktop: Text-to-Speech demo launcher (Windows)

param(
    [string]$PythonExe = "python"
)

Write-Host "=== CITL Desktop LLM – TTS Demo ===" -ForegroundColor Cyan

# Go to repo root (this script's folder)
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

# ---------- 1. Check Python ----------
Write-Host "`n[STEP] Checking Python..." -ForegroundColor Yellow
try {
    $pyVersion = & $PythonExe --version 2>$null
} catch {
    Write-Host "[ERROR] Python not found on PATH. Install Python 3.11 and retry." -ForegroundColor Red
    exit 1
}
Write-Host "Using $pyVersion"

# ---------- 2. Ensure virtual environment ----------
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "`n[STEP] Creating virtual environment at $VenvDir..." -ForegroundColor Yellow
    & $PythonExe -m venv $VenvDir
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[ERROR] Failed to create venv." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[INFO] Reusing existing venv at $VenvDir"
}

# ---------- 3. Install Python dependencies ----------
$ReqFile = Join-Path $RepoRoot "requirements.txt"
if (-not (Test-Path $ReqFile)) {
    Write-Host "[ERROR] requirements.txt not found at $ReqFile" -ForegroundColor Red
    Write-Host "Create it from the project docs, then re-run this script."
    exit 1
}

Write-Host "`n[STEP] Installing/Updating Python dependencies..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $ReqFile

# ---------- 4. Run the TTS demo ----------
$TtsScript = Join-Path $RepoRoot "factbook-assistant\citl_tts.py"
if (-not (Test-Path $TtsScript)) {
    Write-Host "[ERROR] TTS script not found at $TtsScript" -ForegroundColor Red
    exit 1
}

Write-Host "`n[STEP] Starting TTS demo (citl_tts.py)..." -ForegroundColor Green
Write-Host "You may be asked to select a microphone or output device inside the Python app." -ForegroundColor DarkGray

& $VenvPython $TtsScript