# =====================  CITL ALL-IN-ONE (NON-ADMIN) =====================
# What it does:
# 1) Fetches both CITL repos as ZIP (no Git), unpacks to %USERPROFILE%\CITL
# 2) Ensures Ollama is installed for the current user only (silent)
# 3) Creates a per-user models folder (no registry; no system changes)
# 4) Starts/uses Ollama API on 127.0.0.1:11434
# 5) Runs a full environment smoke test (offline-safe); optional online test is available
# ========================================================================

$ErrorActionPreference = 'Stop'
$PSStyle.OutputRendering = 'PlainText'  # avoid weird ANSI on some consoles

function Write-Info($m){ Write-Host "[*] $m" -ForegroundColor Cyan }
function Write-Ok  ($m){ Write-Host "[+] $m" -ForegroundColor Green }
function Write-Warn($m){ Write-Host "[!] $m" -ForegroundColor Yellow }
function Write-Err ($m){ Write-Host "[x] $m" -ForegroundColor Red }

# ------------------------------------------------------------------------
# 0) Parameters you can tweak (keep defaults if unsure)
# ------------------------------------------------------------------------
$RunOnlineSmokeTest = $false  # set $true if internet allowed and you want to auto-pull a tiny model for a talk-back test
$CITLRoot = Join-Path $env:USERPROFILE 'CITL'
$ModelsRoot = Join-Path $CITLRoot 'Models'   # per-user model cache; no registry
$OllamaSetupUrl = 'https://ollama.com/download/OllamaSetup.exe'

# Desktop kit (pinned commit first, then main as fallback)
$DeskZipPinned = 'https://github.com/Citl-Dev-Ops/CITL---Desktop-LLM-EZ-Install-Kits/archive/762656f1c591670b47846d30ae2d1d233831db15.zip'
$DeskZipMain   = 'https://github.com/Citl-Dev-Ops/CITL---Desktop-LLM-EZ-Install-Kits/archive/refs/heads/main.zip'

# CannaKit kit (main)
$CanZipMain    = 'https://github.com/Citl-Dev-Ops/CITL-Cannakit-Demo-EZInstaller-v2/archive/refs/heads/main.zip'

# ------------------------------------------------------------------------
# 1) Pre-flight: TLS, folders, basic cmdlets
# ------------------------------------------------------------------------
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
New-Item -ItemType Directory -Force -Path $CITLRoot | Out-Null
Set-Location $CITLRoot

# Sanity check: Expand-Archive & Invoke-WebRequest exist (PowerShell 5+)
if (-not (Get-Command Expand-Archive -ErrorAction SilentlyContinue)) { throw "Expand-Archive not available. Need Windows PowerShell 5.1 or PowerShell 7+." }
if (-not (Get-Command Invoke-WebRequest -ErrorAction SilentlyContinue)) { throw "Invoke-WebRequest not available. Enable or use PowerShell 7+." }

Write-Info "Working in: $CITLRoot"

# ------------------------------------------------------------------------
# 2) Download & unpack both repos (no Git; no admin)
# ------------------------------------------------------------------------
$DeskZip = Join-Path $CITLRoot 'CITL-Desktop.zip'
$CanZip  = Join-Path $CITLRoot 'CITL-Cannakit.zip'

Write-Info "Downloading Desktop kit ZIP (pinned commit → fallback to main if needed)..."
$deskOK = $false
try {
  Invoke-WebRequest -Uri $DeskZipPinned -OutFile $DeskZip -UseBasicParsing
  $deskOK = $true
} catch {
  Write-Warn "Pinned commit unavailable, trying main branch..."
  try {
    Invoke-WebRequest -Uri $DeskZipMain -OutFile $DeskZip -UseBasicParsing
    $deskOK = $true
  } catch {
    Write-Err "Failed to download Desktop kit from both URLs."
  }
}
if (-not $deskOK) { throw "Cannot continue without Desktop kit ZIP." }

Write-Info "Downloading CannaKit kit ZIP (main)..."
Invoke-WebRequest -Uri $CanZipMain -OutFile $CanZip -UseBasicParsing

# Unpack & normalize names
$DeskDir = Join-Path $CITLRoot 'CITL-Desktop'
$CanDir  = Join-Path $CITLRoot 'CITL-Cannakit'
if (Test-Path $DeskDir) { Remove-Item $DeskDir -Recurse -Force }
if (Test-Path $CanDir)  { Remove-Item $CanDir  -Recurse -Force }

Expand-Archive -Path $DeskZip -DestinationPath $CITLRoot -Force
Expand-Archive -Path $CanZip  -DestinationPath $CITLRoot -Force

$deskSrc = Get-ChildItem -Directory "$CITLRoot\CITL---Desktop-LLM-EZ-Install-Kits-*" | Select-Object -First 1
$canSrc  = Get-ChildItem -Directory "$CITLRoot\CITL-Cannakit-Demo-EZInstaller-v2-*"   | Select-Object -First 1
if (-not $deskSrc) { throw "Desktop kit folder not found after unzip." }
if (-not $canSrc)  { throw "CannaKit folder not found after unzip." }

Move-Item $deskSrc.FullName $DeskDir
Move-Item $canSrc.FullName  $CanDir
Remove-Item $DeskZip,$CanZip -Force

Write-Ok  "Repos ready:"
Write-Host "  $DeskDir"
Write-Host "  $CanDir"

# ------------------------------------------------------------------------
# 3) Ensure Ollama exists (per-user install; no registry edits from us)
# ------------------------------------------------------------------------
$haveOllama = $false
try { $ver = & ollama --version 2>$null; if ($LASTEXITCODE -eq 0 -and $ver) { $haveOllama = $true } } catch {}

if ($haveOllama) {
  Write-Ok "Ollama already present: $ver"
} else {
  Write-Warn "Ollama not found. Installing for current user (silent)..."
  $Tmp = Join-Path $env:TEMP 'OllamaSetup.exe'
  Invoke-WebRequest -Uri $OllamaSetupUrl -OutFile $Tmp -UseBasicParsing
  # Silent switch is '/S'. This installs to user space on current builds.
  Start-Process -FilePath $Tmp -ArgumentList '/S' -Wait
  try { $ver = & ollama --version 2>$null } catch {}
  if ($LASTEXITCODE -ne 0 -or -not $ver) { throw "Ollama install failed or was blocked by policy." }
  Write-Ok "Ollama installed: $ver"
}

# ------------------------------------------------------------------------
# 4) Per-user models folder + start API (no registry; safe on domain)
# ------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $ModelsRoot | Out-Null
Write-Info "Models folder: $ModelsRoot"

# If API not reachable, start one in background with our per-process env
$apiOK = $false
try {
  $j = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3
  if ($j.version) { $apiOK = $true; Write-Ok "Ollama API is up: $($j.version)" }
} catch {}

if (-not $apiOK) {
  Write-Info "Starting Ollama API in background..."
  $env:OLLAMA_MODELS = $ModelsRoot
  $null = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoLogo","-NoProfile","-WindowStyle","Hidden","-Command","`$env:OLLAMA_MODELS='$ModelsRoot'; ollama serve"
  Start-Sleep -Seconds 3
  try {
    $j = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 5
    if ($j.version) { $apiOK = $true; Write-Ok "Ollama API started: $($j.version)" }
  } catch {
    Write-Warn "API still not reachable; a prior instance may be bound to 11434. Proceeding anyway."
  }
}

# Make sure all subsequent ollama CLI calls use our per-user models dir
$env:OLLAMA_MODELS = $ModelsRoot

# ------------------------------------------------------------------------
# 5) Environment smoke tests (offline-safe); optional online test
# ------------------------------------------------------------------------
Write-Info "Running environment checks..."

# Test A: CLI works
try {
  & ollama list | Out-Null
  Write-Ok "CLI responsive (ollama list)."
} catch {
  Write-Err "CLI not responsive. Check corporate AV or policy."
}

# Test B: API health
try {
  $v = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 5
  Write-Ok "API health OK: $($v.version)"
} catch {
  Write-Warn "API health check failed; continuing (some GUIs start their own server)."
}

# Test C (offline-safe): verify models folder is writable
$probe = Join-Path $ModelsRoot "._probe_$(Get-Random).tmp"
"probe" | Set-Content -Path $probe -Encoding ASCII
if (Test-Path $probe) { Remove-Item $probe -Force; Write-Ok "Models folder writable." } else { Write-Err "Models folder not writable." }

# Optional Test D (online): pull tiny test model & run a ping
if ($RunOnlineSmokeTest) {
  Write-Info "Online smoke test enabled: pulling tiny model (tinyllama:chat)."
  try {
    & ollama pull tinyllama:chat
    $ping = @{ model='tinyllama:chat'; prompt='Say hello in one short sentence.'; stream=$false } | ConvertTo-Json -Compress
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -ContentType 'application/json' -Body $ping -TimeoutSec 60
    if ($resp.response) { Write-Ok "Model responded: $($resp.response.Trim())" } else { Write-Warn "No response payload." }
  } catch {
    Write-Warn "Online smoke test failed (network or proxy). Skip this on offline boxes."
  }
} else {
  Write-Info "Online smoke test skipped (set `$RunOnlineSmokeTest = `$true to enable)."
}

# ------------------------------------------------------------------------
# 6) Final pointers for colleagues (what to run next)
# ------------------------------------------------------------------------
Write-Host ""
Write-Ok "Environment is ready (no admin, no registry writes). Next steps:"
Write-Host "  • Desktop kit: $DeskDir" -ForegroundColor Gray
Write-Host "  • CannaKit kit: $CanDir" -ForegroundColor Gray
Write-Host "  • Models dir (per-user): $ModelsRoot" -ForegroundColor Gray
Write-Host ""
Write-Host "Use each repo’s README / installer scripts. If ExecutionPolicy blocks them, run:" -ForegroundColor Yellow
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "If you already have prepackaged model ZIPs (GGUF + Modelfiles), place them where the repo README expects," -ForegroundColor Yellow
Write-Host "then run the included installer to 'ollama create' tags into this per-user models directory." -ForegroundColor Yellow
Write-Host ""
Write-Ok "Done."
# ========================================================================