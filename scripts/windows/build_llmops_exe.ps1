param(
  [switch]$Clean,
  [switch]$SkipDeps
)
$ErrorActionPreference = "Stop"

$Repo = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
$Entry = Join-Path $Repo "factbook-assistant\citl_llmops_suite.py"
$DistDir = Join-Path $Repo "dist"
$WorkDir = Join-Path $Repo "build"
$ExeName = "CITL LLMOps Presentation Suite"
$OutputDir = Join-Path $DistDir $ExeName

Write-Host "== CITL LLMOps EXE Builder ==" -ForegroundColor Cyan
Write-Host "Repo   : $Repo"
Write-Host "Entry  : $Entry"

if (!(Test-Path -LiteralPath $Entry)) {
  throw "Entry script not found: $Entry"
}

if (!(Test-Path -LiteralPath $Py)) {
  Write-Host "Creating venv (.venv)..." -ForegroundColor Yellow
  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if ($cmd) { py -3 -m venv "$Repo\.venv" } else { python -m venv "$Repo\.venv" }
}

if (!(Test-Path -LiteralPath $Py)) {
  throw "Unable to create or locate venv Python: $Py"
}

if (!$SkipDeps) {
  Write-Host "Installing dependencies..." -ForegroundColor White
  & $Py -m pip install -U pip | Out-Null

  $req = Join-Path $Repo "requirements-windows.txt"
  if (Test-Path -LiteralPath $req) {
    & $Py -m pip install -r $req
  } else {
    & $Py -m pip install requests psutil
  }

  & $Py -m pip install -U pyinstaller
}

if ($Clean) {
  Write-Host "Cleaning old build artifacts..." -ForegroundColor Yellow
  if (Test-Path $WorkDir) { Remove-Item -Recurse -Force $WorkDir }
  if (Test-Path $OutputDir) { Remove-Item -Recurse -Force $OutputDir }
}

Write-Host "Building EXE with PyInstaller..." -ForegroundColor Cyan
Set-Location $Repo

& $Py -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name "$ExeName" `
  --distpath "$DistDir" `
  --workpath "$WorkDir" `
  "$Entry"

if (Test-Path $OutputDir) {
  $sizeMb = (Get-ChildItem $OutputDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
  Write-Host ""
  Write-Host "Build complete." -ForegroundColor Green
  Write-Host "Output : $OutputDir"
  Write-Host "Size   : $([math]::Round($sizeMb,1)) MB"
  Write-Host ""
  Write-Host "Run it with:" -ForegroundColor DarkGray
  Write-Host "  RUN_LLMOPS_WINDOWS.cmd"
} else {
  throw "Build finished but output folder was not found: $OutputDir"
}
