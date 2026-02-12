Write-Host "=== CITL Desktop debug: env + paths ===" -ForegroundColor Cyan

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "Script root: $root"

$factbookPath = Join-Path $root "factbook-assistant"
Write-Host "Expecting factbook-assistant at: $factbookPath"
Write-Host "Exists? " -NoNewline
if (Test-Path $factbookPath) {
    Write-Host "YES" -ForegroundColor Green
} else {
    Write-Host "NO" -ForegroundColor Red
}

if (Test-Path "$factbookPath\citl_tts.py") {
    Write-Host "Found citl_tts.py" -ForegroundColor Green
} else {
    Write-Host "Missing citl_tts.py in factbook-assistant" -ForegroundColor Yellow
}

if (Test-Path "$factbookPath\citl_transcribe_lecture.py") {
    Write-Host "Found citl_transcribe_lecture.py" -ForegroundColor Green
} else {
    Write-Host "Missing citl_transcribe_lecture.py in factbook-assistant" -ForegroundColor Yellow
}

if (Test-Path "$factbookPath\.venv\Scripts\python.exe") {
    Write-Host "Found venv python at .venv\Scripts\python.exe" -ForegroundColor Green
} else {
    Write-Host "No .venv\Scripts\python.exe yet (will need to create venv)" -ForegroundColor Yellow
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    $pyVersion = python --version 2>$null
    Write-Host "System 'python' command is available: $pyVersion" -ForegroundColor Green
} else {
    Write-Host "System 'python' command NOT found in PATH." -ForegroundColor Yellow
}

Write-Host "`nDone. Press Enter to close." -ForegroundColor Cyan
Read-Host | Out-Null
