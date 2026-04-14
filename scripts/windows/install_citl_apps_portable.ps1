#Requires -Version 5.1
<#
  CITL Portable App Installer
  ============================
  Installs or updates the four CITL USB app bundles to a user-writable
  location - no admin, no registry, no system folders.

  Install locations searched (in priority order):
    1. Already installed somewhere - update in place
    2. %USERPROFILE%\Desktop\CITL Apps\
    3. %USERPROFILE%\Documents\CITL Apps\
    4. %USERPROFILE%\Downloads\CITL Apps\

  Creates Desktop shortcuts (.lnk) pointing to the local copy.

  Usage (from USB or project root):
    .\install_citl_apps_portable.ps1
    .\install_citl_apps_portable.ps1 -Destination "$env:USERPROFILE\Documents\CITL Apps"
    .\install_citl_apps_portable.ps1 -Apps sync,presentation
    .\install_citl_apps_portable.ps1 -UpdateOnly       # skip copy if not installed
    .\install_citl_apps_portable.ps1 -NoShortcuts      # copy only, no .lnk
    .\install_citl_apps_portable.ps1 -Uninstall        # remove all local copies + shortcuts

  Source resolution (first match wins):
    - USB numbered folders  (1-CITL-SYNC, etc.)
    - Sibling dist\ folder relative to this script repo
#>
param(
    [string]  $Apps        = "all",   # "all" | comma-list: sync,presentation,workstation,field
    [string]  $Destination = "",      # override install root; default = Desktop\CITL Apps
    [switch]  $UpdateOnly,            # only update already-installed apps; skip fresh installs
    [switch]  $NoShortcuts,           # skip .lnk creation/update
    [switch]  $Uninstall,             # remove installed copies and shortcuts
    [switch]  $Silent                 # suppress pause at end
)

$ErrorActionPreference = "Continue"

# ---- Console helpers --------------------------------------------------------
function Write-Step { param($m) Write-Host "[....] $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }
function Write-Info { param($m) Write-Host "       $m" -ForegroundColor Gray }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  CITL Portable App Installer" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---- Resolve repo root ------------------------------------------------------
# This script lives at <repo>\scripts\windows\ but may also run from USB.
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else {
    Split-Path -Parent $MyInvocation.MyCommand.Path
}
# Walk up to find repo root (contains factbook-assistant\ or dist\)
$RepoRoot = $ScriptDir
for ($i = 0; $i -lt 4; $i++) {
    if ((Test-Path (Join-Path $RepoRoot "factbook-assistant")) -or
        (Test-Path (Join-Path $RepoRoot "dist"))) { break }
    $RepoRoot = Split-Path -Parent $RepoRoot
}
$DistDir = Join-Path $RepoRoot "dist"
Write-Info "Script dir : $ScriptDir"
Write-Info "Repo root  : $RepoRoot"
Write-Info "Dist dir   : $DistDir"

# ---- App definitions --------------------------------------------------------
$AppDefs = @(
    [ordered]@{
        Key          = "sync"
        DisplayName  = "CITL App Sync"
        ExeName      = "CITL App Sync.exe"
        UsbFolder    = "1-CITL-SYNC"
        DistFolder   = "CITL App Sync"
        ShortcutName = "CITL App Sync"
    },
    [ordered]@{
        Key          = "presentation"
        DisplayName  = "CITL Presentation Suite"
        ExeName      = "CITL LLMOps Presentation Suite.exe"
        UsbFolder    = "2-CITL-PRESENTATION-SUITE"
        DistFolder   = "CITL LLMOps Presentation Suite"
        ShortcutName = "CITL Presentation Suite"
    },
    [ordered]@{
        Key          = "workstation"
        DisplayName  = "CITL Workstation Apps"
        ExeName      = "CITL Workstation Apps.exe"
        UsbFolder    = "3-CITL-WORKSTATION-APPS"
        DistFolder   = "CITL Workstation Apps"
        ShortcutName = "CITL Workstation Apps"
    },
    [ordered]@{
        Key          = "field"
        DisplayName  = "CITL Field Apps"
        ExeName      = "CITL Field Apps.exe"
        UsbFolder    = "4-CITL-FIELD-APPS"
        DistFolder   = "CITL Field Apps"
        ShortcutName = "CITL Field Apps"
    }
)

# ---- Filter requested apps --------------------------------------------------
$RequestedKeys = if ($Apps -eq "all") {
    $AppDefs | ForEach-Object { $_.Key }
} else {
    $Apps -split "," | ForEach-Object { $_.Trim().ToLowerInvariant() }
}
$SelectedApps = $AppDefs | Where-Object { $RequestedKeys -contains $_.Key }
if (-not $SelectedApps) {
    Write-Fail "No matching apps found for: $Apps"
    Write-Info "Valid keys: sync, presentation, workstation, field"
    exit 1
}

# ---- Detect USB drives ------------------------------------------------------
function Find-UsbRoot {
    $drives = [System.IO.DriveInfo]::GetDrives() |
        Where-Object { $_.DriveType -in "Removable","Network" -and $_.IsReady }
    foreach ($d in $drives) {
        $root = $d.RootDirectory.FullName.TrimEnd('\')
        if ((Test-Path "$root\1-CITL-SYNC") -or
            (Test-Path "$root\2-CITL-PRESENTATION-SUITE")) {
            return $root
        }
    }
    return $null
}

$UsbRoot = Find-UsbRoot
if ($UsbRoot) {
    Write-OK "USB detected : $UsbRoot"
} else {
    Write-Warn "No CITL USB detected. Will use local dist\ only."
}

# ---- Resolve source for each app --------------------------------------------
function Resolve-Source {
    param([hashtable]$App)
    # 1. USB numbered folder
    if ($UsbRoot) {
        $usbSrc = Join-Path $UsbRoot $App.UsbFolder
        if (Test-Path (Join-Path $usbSrc $App.ExeName)) { return $usbSrc }
    }
    # 2. dist\ folder
    $distSrc = Join-Path $DistDir $App.DistFolder
    if (Test-Path (Join-Path $distSrc $App.ExeName)) { return $distSrc }
    return $null
}

# ---- Find an already-installed copy -----------------------------------------
$SearchRoots = @(
    "$env:USERPROFILE\Desktop\CITL Apps",
    "$env:USERPROFILE\Documents\CITL Apps",
    "$env:USERPROFILE\Downloads\CITL Apps",
    "$env:LOCALAPPDATA\CITL Apps"
)

function Find-Installed {
    param([hashtable]$App)
    foreach ($root in $SearchRoots) {
        $candidate = Join-Path $root $App.DisplayName
        if (Test-Path (Join-Path $candidate $App.ExeName)) { return $candidate }
    }
    return $null
}

# ---- Shortcut helper --------------------------------------------------------
function New-Shortcut {
    param([string]$LinkPath, [string]$TargetPath, [string]$Description = "")
    try {
        $wsh = New-Object -ComObject WScript.Shell
        $lnk = $wsh.CreateShortcut($LinkPath)
        $lnk.TargetPath       = $TargetPath
        $lnk.WorkingDirectory = Split-Path $TargetPath
        $lnk.Description      = $Description
        $lnk.Save()
        return $true
    } catch {
        return $false
    }
}

# ---- Uninstall mode ---------------------------------------------------------
if ($Uninstall) {
    Write-Host ""
    Write-Step "Uninstall mode - removing local copies and shortcuts..."
    foreach ($app in $SelectedApps) {
        $installed = Find-Installed -App $app
        if ($installed) {
            Write-Step "Removing $($app.DisplayName) from $installed"
            try {
                Remove-Item -Recurse -Force $installed
                Write-OK "Removed: $installed"
            } catch {
                Write-Warn "Could not remove ${installed} : $_"
            }
        } else {
            Write-Info "$($app.DisplayName) not found locally - skipped."
        }
        # Remove shortcut
        $lnk = Join-Path "$env:USERPROFILE\Desktop" "$($app.ShortcutName).lnk"
        if (Test-Path $lnk) {
            Remove-Item $lnk -Force
            Write-OK "Shortcut removed: $lnk"
        }
    }
    Write-Host ""
    Write-OK "Uninstall complete."
    if (-not $Silent) { Read-Host "Press Enter to close" }
    exit 0
}

# ---- Determine install root -------------------------------------------------
if ($Destination -and $Destination -ne "") {
    $InstallRoot = $Destination
} else {
    $existingRoot = $SearchRoots | Where-Object { Test-Path $_ } | Select-Object -First 1
    $InstallRoot = if ($existingRoot) { $existingRoot } else {
        "$env:USERPROFILE\Desktop\CITL Apps"
    }
}
Write-Info "Install root : $InstallRoot"

# ---- Main install / update loop ---------------------------------------------
$results = @{}

foreach ($app in $SelectedApps) {
    Write-Host ""
    Write-Host "---- $($app.DisplayName) ----" -ForegroundColor Magenta

    # Find source
    $src = Resolve-Source -App $app
    if (-not $src) {
        Write-Warn "Source not found for $($app.DisplayName)."
        Write-Info "Build it first: BUILD_ALL_CITL_EXES_WINDOWS.cmd -Apps $($app.Key)"
        $results[$app.DisplayName] = "SOURCE_MISSING"
        continue
    }
    Write-Info "Source : $src"

    # Find destination - check if already installed somewhere
    $installedPath = Find-Installed -App $app
    if ($installedPath) {
        $dest = $installedPath
        Write-OK "Already installed at: $dest - will UPDATE"
    } elseif ($UpdateOnly) {
        Write-Info "$($app.DisplayName) not installed locally. Skipping (UpdateOnly mode)."
        $results[$app.DisplayName] = "SKIPPED_NOT_INSTALLED"
        continue
    } else {
        $dest = Join-Path $InstallRoot $app.DisplayName
        Write-Step "Fresh install -> $dest"
    }

    # Ensure destination folder exists
    if (-not (Test-Path $dest)) {
        try {
            New-Item -ItemType Directory -Path $dest -Force | Out-Null
        } catch {
            Write-Fail "Cannot create destination: $dest  ($_)"
            $results[$app.DisplayName] = "FAILED"
            continue
        }
    }

    # Robocopy: mirror source to destination
    # /MIR = mirror (add new, update changed, remove deleted)
    # /XO  = exclude older (only copy newer/new files)
    # /NFL /NDL /NJH /NJS = suppress verbose output
    # /R:2 /W:1 = retry 2 times, wait 1s
    Write-Step "Syncing files..."
    $roboArgs = @($src, $dest, "/MIR", "/XO", "/R:2", "/W:1",
                  "/NFL", "/NDL", "/NJH", "/NJS")
    & robocopy @roboArgs | Out-Null
    $roboExit = $LASTEXITCODE
    # Robocopy exit codes 0-7 are success (8+ are errors)
    if ($roboExit -le 7) {
        $exePath = Join-Path $dest $app.ExeName
        if (Test-Path $exePath) {
            $sizeBytes = (Get-ChildItem $dest -Recurse -ErrorAction SilentlyContinue |
                         Measure-Object -Property Length -Sum).Sum
            $sizeMbStr = [math]::Round($sizeBytes / 1048576, 1).ToString() + " MB"
            Write-OK "$($app.DisplayName) installed ($sizeMbStr) -> $dest"
            $results[$app.DisplayName] = "OK"

            # Create / update desktop shortcut
            if (-not $NoShortcuts) {
                $lnkPath = Join-Path "$env:USERPROFILE\Desktop" "$($app.ShortcutName).lnk"
                $desc = "CITL - $($app.DisplayName)"
                $ok = New-Shortcut -LinkPath $lnkPath -TargetPath $exePath -Description $desc
                if ($ok) { Write-OK "Shortcut: $lnkPath" }
                else     { Write-Warn "Shortcut creation failed (non-critical)." }
            }
        } else {
            Write-Fail "Robocopy succeeded but exe missing: $exePath"
            $results[$app.DisplayName] = "FAILED"
        }
    } else {
        Write-Fail "Robocopy exited with code $roboExit for $($app.DisplayName)"
        $results[$app.DisplayName] = "FAILED"
    }
}

# ---- Summary ----------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Installation Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
$failed = 0
foreach ($k in $results.Keys) {
    switch ($results[$k]) {
        "OK"                    { Write-OK   "$k" }
        "SKIPPED_NOT_INSTALLED" { Write-Info "$k  (skipped - not previously installed)" }
        "SOURCE_MISSING"        { Write-Warn "$k  (source not found - build first)"; $failed++ }
        "FAILED"                { Write-Fail "$k  FAILED"; $failed++ }
    }
}

Write-Host ""
if ($failed -eq 0) {
    Write-OK "All apps ready. Desktop shortcuts created."
    Write-Host ""
    Write-Info "Install location : $InstallRoot"
    Write-Info "To update later  : run this script again from USB or repo"
    Write-Info "To uninstall     : run with -Uninstall flag"
} elseif ($failed -gt 0 -and $results.Values -contains 'OK') {
    Write-Warn "$failed app(s) had issues, but at least one app installed successfully."
    Write-Host ""
    Write-Info "Install location : $InstallRoot"
    Write-Info "To update later  : run this script again from USB or repo"
    Write-Info "To uninstall     : run with -Uninstall flag"
} else {
    Write-Warn "$failed app(s) failed and no app was installed successfully. See above."
}

Write-Host ""
if (-not $Silent) { Read-Host "Press Enter to close" }
if ($failed -gt 0 -and -not ($results.Values -contains 'OK')) { exit 1 }
