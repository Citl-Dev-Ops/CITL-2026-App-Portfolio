# === CITL repos: download as ZIPs from GitHub and unpack to %USERPROFILE%\CITL ===
$ErrorActionPreference = 'Stop'
$Root = Join-Path $env:USERPROFILE 'CITL'
New-Item -ItemType Directory -Force -Path $Root | Out-Null
Set-Location $Root

# Enable TLS
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

# Desktop kit (try pinned commit first, then main)
$DeskZip1 = 'https://github.com/Citl-Dev-Ops/CITL---Desktop-LLM-EZ-Install-Kits/archive/762656f1c591670b47846d30ae2d1d233831db15.zip'
$DeskZip2 = 'https://github.com/Citl-Dev-Ops/CITL---Desktop-LLM-EZ-Install-Kits/archive/refs/heads/main.zip'
$DeskOut  = Join-Path $Root 'CITL-Desktop.zip'
try { Invoke-WebRequest -Uri $DeskZip1 -OutFile $DeskOut -UseBasicParsing }
catch { Invoke-WebRequest -Uri $DeskZip2 -OutFile $DeskOut -UseBasicParsing }

# CannaKit kit (main)
$CanZip  = 'https://github.com/Citl-Dev-Ops/CITL-Cannakit-Demo-EZInstaller-v2/archive/refs/heads/main.zip'
$CanOut  = Join-Path $Root 'CITL-Cannakit.zip'
Invoke-WebRequest -Uri $CanZip -OutFile $CanOut -UseBasicParsing

# Unpack
$DeskDir = Join-Path $Root 'CITL-Desktop'
$CanDir  = Join-Path $Root 'CITL-Cannakit'
if (Test-Path $DeskDir) { Remove-Item $DeskDir -Recurse -Force }
if (Test-Path $CanDir)  { Remove-Item $CanDir  -Recurse -Force }

Expand-Archive -Path $DeskOut -DestinationPath $Root -Force
Expand-Archive -Path $CanOut  -DestinationPath $Root -Force

# Normalize folder names
$deskSrc = Get-ChildItem -Directory "$Root\CITL---Desktop-LLM-EZ-Install-Kits-*" | Select-Object -First 1
$canSrc  = Get-ChildItem -Directory "$Root\CITL-Cannakit-Demo-EZInstaller-v2-*"   | Select-Object -First 1
if (-not $deskSrc) { throw "Desktop kit folder not found after unzip." }
if (-not $canSrc)  { throw "CannaKit folder not found after unzip." }

Move-Item $deskSrc.FullName $DeskDir
Move-Item $canSrc.FullName  $CanDir

# Clean up zips
Remove-Item $DeskOut,$CanOut -Force

Write-Host "`n[OK] Repos ready:" -ForegroundColor Green
Write-Host "  $DeskDir"
Write-Host "  $CanDir"