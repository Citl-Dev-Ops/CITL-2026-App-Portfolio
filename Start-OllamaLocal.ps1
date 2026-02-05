param(
  [string]$OllamaHost = "http://127.0.0.1:11434"
)
function Test-Ollama {
  try { Invoke-RestMethod "$OllamaHost/api/tags" -TimeoutSec 2 | Out-Null; return $true }
  catch { return $false }
}
Write-Host ""
Write-Host "Checking Ollama at $OllamaHost ..." -ForegroundColor Cyan
if (Test-Ollama) {
  Write-Host "Ollama: OK" -ForegroundColor Green
  exit 0
}
Write-Warning "Ollama not reachable. Attempting to start..."
# Try service first (some installs use it)
$svc = Get-Service -Name "Ollama" -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -ne "Running") {
  Start-Service "Ollama" | Out-Null
  Start-Sleep -Seconds 2
}
# Try CLI if available
$oll = Get-Command "ollama" -ErrorAction SilentlyContinue
if ($oll) {
  Start-Process -FilePath $oll.Source -ArgumentList "serve" -WindowStyle Minimized
  Start-Sleep -Seconds 2
} else {
  # Try common install locations
  $candidates = @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "$env:ProgramFiles\Ollama\ollama.exe"
  ) | Where-Object { Test-Path $_ }
  if ($candidates.Count -gt 0) {
    Start-Process -FilePath $candidates[0] -ArgumentList "serve" -WindowStyle Minimized
    Start-Sleep -Seconds 2
  }
}
if (Test-Ollama) {
  Write-Host "Ollama: STARTED and reachable." -ForegroundColor Green
  exit 0
}
Write-Warning "Ollama still not reachable."
Write-Host "Quick checks:" -ForegroundColor Yellow
Write-Host "  netstat -ano | findstr :11434"
Write-Host "  Get-Process ollama -ErrorAction SilentlyContinue"
exit 1
