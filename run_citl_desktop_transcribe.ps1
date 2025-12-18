# run_citl_desktop_transcribe.ps1
param(
    [string]$PythonExe = "python"
)

Write-Host "=== CITL Desktop LLM – Lecture Transcription Demo ===" -ForegroundColor Cyan

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

# Python
try { $pyVersion = & $PythonExe --version 2>$null }
catch {
    Write-Host "[ERROR] Python not found on PATH. Install Python 3.11+ and retry." -ForegroundColor Red
    exit 1
}
Write-Host "Using $pyVersion"

# venv
$VenvDir    = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[STEP] Creating virtual environment at $VenvDir..." -ForegroundColor Yellow
    & $PythonExe -m venv $VenvDir
}
# deps
$ReqFile = Join-Path $RepoRoot "requirements.txt"
if (-not (Test-Path $ReqFile)) {
    Write-Host "[ERROR] requirements.txt not found." -ForegroundColor Red
    exit 1
}
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $ReqFile

# run transcriber
$Script = Join-Path $RepoRoot "factbook-assistant\citl_transcribe_lecture.py"
if (-not (Test-Path $Script)) {
    Write-Host "[ERROR] citl_transcribe_lecture.py not found at $Script" -ForegroundColor Red
    exit 1
}

Write-Host "`n[STEP] Starting transcription demo..." -ForegroundColor Green
& $VenvPython $Script