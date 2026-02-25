param(
  [switch]$Clean,      # wipe build/dist before building
  [switch]$SkipDeps   # skip pip install (faster rebuilds)
)
$ErrorActionPreference = "Stop"

$Repo    = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path
$FaDir   = Join-Path $Repo "factbook-assistant"
$SpecFile = Join-Path $FaDir "CITL Library Assistant.spec"
$Py      = Join-Path $Repo ".venv\Scripts\python.exe"

Write-Host "== CITL EXE Builder ==" -ForegroundColor Cyan
Write-Host "Repo   : $Repo"
Write-Host "Spec   : $SpecFile"

# ---- Venv ----
if (!(Test-Path -LiteralPath $Py)) {
  Write-Host "Creating venv..." -ForegroundColor Yellow
  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if ($cmd) { py -3 -m venv "$Repo\.venv" } else { python -m venv "$Repo\.venv" }
}

if (!$SkipDeps) {
  Write-Host "Installing Python deps..." -ForegroundColor White
  & $Py -m pip install -U pip | Out-Null

  foreach ($req in @("requirements-windows.txt","requirements-transcribe.txt","requirements-translate.txt")) {
    $p = Join-Path $Repo $req
    if (Test-Path -LiteralPath $p) {
      Write-Host "  pip install -r $req"
      & $Py -m pip install -r $p
    }
  }

  Write-Host "Installing PyInstaller..." -ForegroundColor White
  & $Py -m pip install -U pyinstaller
}

# ---- Optional clean ----
if ($Clean) {
  Write-Host "Cleaning build/dist..." -ForegroundColor Yellow
  $build = Join-Path $Repo "build"
  $dist  = Join-Path $Repo "dist"
  if (Test-Path $build) { Remove-Item -Recurse -Force $build }
  if (Test-Path $dist)  { Remove-Item -Recurse -Force $dist }
}

# ---- Build ----
if (!(Test-Path -LiteralPath $SpecFile)) {
  throw "Spec file not found: $SpecFile"
}

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
Set-Location $FaDir
& $Py -m PyInstaller `
  --distpath (Join-Path $Repo "dist") `
  --workpath (Join-Path $Repo "build") `
  $SpecFile

$out = Join-Path $Repo "dist\CITL Library Assistant"
if (Test-Path $out) {
  $size = (Get-ChildItem $out -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
  Write-Host ""
  Write-Host "Build complete!" -ForegroundColor Green
  Write-Host "Output : $out"
  Write-Host "Size   : $([math]::Round($size,1)) MB"
  Write-Host ""
  Write-Host "NOTE: The target machine also needs (or use setup.ps1 once with internet):" -ForegroundColor DarkYellow
  Write-Host "  - Ollama installed and running" -ForegroundColor DarkYellow
  Write-Host "  - faster-whisper / ctranslate2 for transcription (heavy ML, not bundled)" -ForegroundColor DarkYellow
} else {
  Write-Warning "Build finished but output folder not found: $out"
}
