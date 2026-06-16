$ErrorActionPreference = "Stop"
$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# Activate venv
& (Join-Path $ROOT "venv\Scripts\Activate.ps1") | Out-Null

Write-Host "Starting API on :8000 ..."
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "cd `"$ROOT`"; & `"$ROOT\venv\Scripts\python.exe`" -m uvicorn api.app:app --reload --port 8000"
) | Out-Null

Write-Host "Starting UI on :5173 ..."
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "cd `"$ROOT\advisor-ui`"; npm run dev -- --port 5173"
) | Out-Null

Start-Sleep -Seconds 2
Write-Host "Opening UI FIRST: http://localhost:5173"
Start-Process "http://localhost:5173" | Out-Null

Write-Host ""
Write-Host "API health:    http://127.0.0.1:8000/health"
Write-Host "Ollama health: http://127.0.0.1:8000/ollama/health"
