#Requires -Version 5.1
<#
  CITL Portable Suite ZIP Builder
  =================================
  Packages all built CITL exe bundles + the portable installer script
  into a single ZIP archive that can be unzipped anywhere on Windows
  and run without admin rights.

  ZIP structure:
    CITL-Portable-Suite\
      INSTALL_HERE.cmd                <- double-click to install + create shortcuts
      install_citl_apps_portable.ps1  <- the installer (no admin needed)
      1-CITL-SYNC\
        CITL App Sync\                <- exe bundle
        CITL Sync Hub\                <- exe bundle
      2-CITL-PRESENTATION-SUITE\
        CITL LLMOps Presentation Suite\
      3-CITL-WORKSTATION-APPS\
        CITL Workstation Apps\
      4-CITL-FIELD-APPS\
        CITL Field Apps\

  Usage:
    .\make_portable_zip.ps1
    .\make_portable_zip.ps1 -OutDir "C:\Temp"
    .\make_portable_zip.ps1 -Apps sync,workstation
    .\make_portable_zip.ps1 -CopyToUsb     # also write zip to F:\ if detected
#>
param(
    [string] $Apps      = "all",    # "all" | comma list: sync,presentation,workstation,field
    [string] $OutDir    = "",       # output folder; defaults to repo root
    [switch] $CopyToUsb,            # copy finished zip to USB root after building
    [switch] $Silent                # suppress Read-Host pause at end
)

$ErrorActionPreference = "Continue"

function Write-Step { param($m) Write-Host "[....] $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }
function Write-Info { param($m) Write-Host "       $m" -ForegroundColor Gray }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  CITL Portable Suite ZIP Builder" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---- Resolve repo root -------------------------------------------------------
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else {
    Split-Path -Parent $MyInvocation.MyCommand.Path
}
$RepoRoot = $ScriptDir
for ($i = 0; $i -lt 4; $i++) {
    if (Test-Path (Join-Path $RepoRoot "factbook-assistant")) { break }
    $RepoRoot = Split-Path -Parent $RepoRoot
}
$DistDir     = Join-Path $RepoRoot "dist"
$InstallerPs = Join-Path $RepoRoot "scripts\windows\install_citl_apps_portable.ps1"
Write-Info "Repo root  : $RepoRoot"
Write-Info "Dist dir   : $DistDir"

# ---- App bundle definitions --------------------------------------------------
$AllBundles = @(
    [ordered]@{ Key="sync";         UsbFolder="1-CITL-SYNC";               DistFolders=@("CITL App Sync","CITL Sync Hub") },
    [ordered]@{ Key="presentation"; UsbFolder="2-CITL-PRESENTATION-SUITE"; DistFolders=@("CITL LLMOps Presentation Suite") },
    [ordered]@{ Key="workstation";  UsbFolder="3-CITL-WORKSTATION-APPS";   DistFolders=@("CITL Workstation Apps") },
    [ordered]@{ Key="field";        UsbFolder="4-CITL-FIELD-APPS";         DistFolders=@("CITL Field Apps") }
)

$RequestedKeys = if ($Apps -eq "all") {
    $AllBundles | ForEach-Object { $_.Key }
} else {
    $Apps -split "," | ForEach-Object { $_.Trim().ToLowerInvariant() }
}
$Selected = $AllBundles | Where-Object { $RequestedKeys -contains $_.Key }
if (-not $Selected) {
    Write-Fail "No matching apps for: $Apps"
    exit 1
}

# ---- Temp staging area -------------------------------------------------------
$TmpRoot  = Join-Path $env:TEMP "CITL-Portable-Suite-Stage"
$ZipInner = Join-Path $TmpRoot "CITL-Portable-Suite"

if (Test-Path $TmpRoot) { Remove-Item -Recurse -Force $TmpRoot }
New-Item -ItemType Directory -Path $ZipInner -Force | Out-Null
Write-Info "Staging at : $ZipInner"

# ---- Copy installer scripts into root of zip ---------------------------------
# The portable installer script goes right at the top level for easy access
if (Test-Path $InstallerPs) {
    Copy-Item $InstallerPs (Join-Path $ZipInner "install_citl_apps_portable.ps1")
    Write-OK "Copied installer PS1"
} else {
    Write-Warn "Installer PS1 not found: $InstallerPs"
}

# Write INSTALL_HERE.cmd that targets the embedded PS1
$installCmd = @"
@echo off
setlocal
set "HERE=%~dp0"
powershell.exe -ExecutionPolicy Bypass -File "%HERE%install_citl_apps_portable.ps1"
if %ERRORLEVEL% neq 0 pause
"@
$installCmd | Set-Content (Join-Path $ZipInner "INSTALL_HERE.cmd") -Encoding ASCII

Write-OK "Created INSTALL_HERE.cmd"

# ---- Copy each selected app bundle ------------------------------------------
$included = 0
$missing  = 0

foreach ($bundle in $Selected) {
    $usbDir = Join-Path $ZipInner $bundle.UsbFolder
    New-Item -ItemType Directory -Path $usbDir -Force | Out-Null

    foreach ($distFolder in $bundle.DistFolders) {
        $src = Join-Path $DistDir $distFolder
        $dst = Join-Path $usbDir $distFolder
        if (Test-Path $src) {
            Write-Step "Copying $distFolder ..."
            robocopy $src $dst /E /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
            $rc = $LASTEXITCODE
            if ($rc -le 7) {
                $sz = [math]::Round(
                    (Get-ChildItem $dst -Recurse -ErrorAction SilentlyContinue |
                     Measure-Object Length -Sum).Sum / 1MB, 1)
                Write-OK "$distFolder  ($sz MB)"
                $included++
            } else {
                Write-Fail "Robocopy failed (exit $rc) for $distFolder"
                $missing++
            }
        } else {
            Write-Warn "Not found in dist\: $distFolder  (build it first)"
            $missing++
        }
    }
}

if ($included -eq 0) {
    Write-Fail "No app bundles found. Run BUILD_ALL_CITL_EXES_WINDOWS.cmd first."
    Remove-Item -Recurse -Force $TmpRoot -ErrorAction SilentlyContinue
    exit 1
}

# ---- Compress to ZIP ---------------------------------------------------------
$Stamp  = Get-Date -Format "yyyy-MM-dd"
$ZipName = "CITL-Portable-Suite_$Stamp.zip"

if ($OutDir -and $OutDir -ne "") {
    $ZipPath = Join-Path $OutDir $ZipName
} else {
    $ZipPath = Join-Path $RepoRoot $ZipName
}

Write-Step "Compressing -> $ZipPath ..."
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

try {
    Compress-Archive -Path $ZipInner -DestinationPath $ZipPath -CompressionLevel Optimal
    $zipMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
    Write-OK "ZIP created : $ZipPath  ($zipMB MB)"
} catch {
    Write-Fail "Compress-Archive failed: $_"
    Remove-Item -Recurse -Force $TmpRoot -ErrorAction SilentlyContinue
    exit 1
}

# ---- Optionally copy to USB root --------------------------------------------
if ($CopyToUsb) {
    $drives = [System.IO.DriveInfo]::GetDrives() |
        Where-Object { $_.DriveType -in "Removable","Network" -and $_.IsReady }
    $usbRoots = $drives | Where-Object {
        (Test-Path "$($_.RootDirectory.FullName.TrimEnd('\'))\1-CITL-SYNC") -or
        (Test-Path "$($_.RootDirectory.FullName.TrimEnd('\'))\2-CITL-PRESENTATION-SUITE")
    } | ForEach-Object { $_.RootDirectory.FullName.TrimEnd('\') }

    if ($usbRoots) {
        foreach ($usb in $usbRoots) {
            $dst = Join-Path $usb $ZipName
            Copy-Item $ZipPath $dst -Force
            Write-OK "Copied to USB: $dst"
        }
    } else {
        Write-Warn "No CITL USB detected. ZIP stays at: $ZipPath"
    }
}

# ---- Clean up staging -------------------------------------------------------
Remove-Item -Recurse -Force $TmpRoot -ErrorAction SilentlyContinue

# ---- Summary ----------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-OK "Bundles included : $included"
if ($missing -gt 0) { Write-Warn "Bundles missing  : $missing  (build them first)" }
Write-OK "ZIP location     : $ZipPath"
Write-Host ""
Write-Info "To install from ZIP:"
Write-Info "  1. Unzip CITL-Portable-Suite_*.zip anywhere (Desktop, USB, etc.)"
Write-Info "  2. Double-click CITL-Portable-Suite\INSTALL_HERE.cmd"
Write-Info "  3. Apps install to Desktop\CITL Apps  (no admin needed)"
Write-Host ""
if (-not $Silent) { Read-Host "Press Enter to close" }
