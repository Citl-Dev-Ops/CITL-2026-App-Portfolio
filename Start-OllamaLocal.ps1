param(
  [string]$OllamaHost = "http://localhost:11434",
  [int]$TimeoutSec = 12
)
function Test-OllamaUp {
  param([string]$Host)
  try {
    Invoke-RestMethod "$Host/api/tags" -TimeoutSec 2 | Out-Null
    return $true
  } catch { return $false }
}
function Find-OllamaExe {
  $candidates = @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "$env:ProgramFiles\Ollama\ollama.exe",
    "$env:ProgramFiles(x86)\Ollama\ollama.exe"
  )
  foreach ($p in $candidates) { if (Test-Path -LiteralPath $p) { return $p } }
  # last-resort: search LOCALAPPDATA\Programs (can take a moment)
  $root = Join-Path $env:LOCALAPPDATA "Programs"
  if (Test-Path $root) {
    $hit = Get-ChildItem $root -Recurse -Filter ollama.exe -ErrorAction SilentlyContinue |
           Select-Object -First 1 -ExpandProperty FullName
    if ($hit) { return $hit }
  }
  return $null
}
if (Test-OllamaUp -Host $OllamaHost) {
  Write-Host "Ollama API: OK ($OllamaHost)" -ForegroundColor Green
  exit 0
}
$ollamaExe = Find-OllamaExe
if (-not $ollamaExe) {
  Write-Warning "Ollama not found. Install Ollama, then re-run. Expected: $env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
  exit 1
}
# add to PATH for current session
$dir = Split-Path $ollamaExe -Parent
if ($env:Path -notlike "*$dir*") { $env:Path = "$dir;$env:Path" }
Write-Host "Ollama exe: OK ($ollamaExe)" -ForegroundColor Green
# start serve (hidden)
try {
  Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden | Out-Null
} catch {
  Write-Warning "Failed to start Ollama: $($_.Exception.Message)"
}
# wait for API
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
  if (Test-OllamaUp -Host $OllamaHost) {
    Write-Host "Ollama API: OK ($OllamaHost)" -ForegroundColor Green
    exit 0
  }
  Start-Sleep -Milliseconds 400
}
Write-Warning "Ollama API still not reachable at $OllamaHost. Try launching Ollama desktop app manually, then re-run."
exit 2
