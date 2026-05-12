#Requires -Version 5.1
<#
  CITL USB App Sync  --  professional offline sync wrapper
  =========================================================
  Syncs the CITL source repo + compiled app bundles to a detected
  USB drive or explicit target path. Works without admin, without
  internet access (offline-first), and without a pre-existing venv.

  Auto-detects:
    - CITL source repo (env var, relative path, well-known PC paths)
    - CITL USB target (removable drives with CITL markers)
    - Python 3 installation (venv, system, winget fallback)

  What gets synced (in order):
    1. App key-files for all registered CITL apps (source code, scripts,
       launchers, requirements) -- always
    2. Portable installer scripts                 -- always
    3. Built .exe bundles in numbered USB folders -- always when USB detected
       (1-CITL-SYNC, 2-CITL-PRESENTATION-SUITE, 3-CITL-WORKSTATION-APPS,
        4-CITL-FIELD-APPS, 6-CITL-WORK-TICKETING)
    4. Optional: data/ indexes               -- with -IncludeData
    5. Optional: models/ and ollama/         -- with -IncludeModels
    6. Optional: full repo mirror            -- with -FullRepo

  Usage:
    .\sync_usb_apps.ps1
    .\sync_usb_apps.ps1 -TargetRepo "E:\CITL"
    .\sync_usb_apps.ps1 -IncludeData
    .\sync_usb_apps.ps1 -IncludeModels
    .\sync_usb_apps.ps1 -FullRepo
    .\sync_usb_apps.ps1 -DuplicateUsb          # copy USB -> second USB
    .\sync_usb_apps.ps1 -SkipExeBundles        # skip numbered folder copy
    .\sync_usb_apps.ps1 -PushToPhone           # push to Android via ADB

  Environment:
    CITL_REPO  -- override source repo detection (set to your repo root)
#>
param(
    [string]  $SourceRepo         = "auto",
    [string]  $TargetRepo         = "",
    [switch]  $IncludeData,
    [switch]  $IncludeModels,
    [switch]  $SkipExeBundles,      # skip copying numbered USB app folders
    [switch]  $DuplicateUsb,
    [string]  $DuplicateFrom       = "",
    [string]  $DuplicateTo         = "",
    [string]  $OllamaModelSource   = "",
    [string]  $OllamaModelTarget   = "",
    [switch]  $SkipAppKeySync,
    [switch]  $FullRepo,
    [switch]  $PushToPhone,
    [string]  $PhoneSerial         = "auto",
    [switch]  $Silent              # suppress final pause
)

$ErrorActionPreference = "Continue"

function Write-Step { param($m) Write-Host "[....] $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }
function Write-Info { param($m) Write-Host "       $m" -ForegroundColor Gray }

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  CITL App Sync  --  Offline Professional Sync" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 1. LOCATE SOURCE CITL REPO
# ============================================================
$SyncMarker = "factbook-assistant\citl_app_sync.py"

function Find-CitlRepo {
    $candidates = [System.Collections.Generic.List[string]]::new()

    # Script lives at <repo>\scripts\windows\ so two levels up is repo root
    if ($PSScriptRoot) {
        $candidates.Add((Join-Path $PSScriptRoot "..\.."))
    }

    # Explicit env override
    $envRepo = [System.Environment]::GetEnvironmentVariable("CITL_REPO")
    if (-not [string]::IsNullOrWhiteSpace($envRepo)) { $candidates.Add($envRepo) }

    # User-profile standard locations
    foreach ($sub in @("CITL", "Documents\CITL", "Desktop\CITL")) {
        $candidates.Add((Join-Path $env:USERPROFILE $sub))
    }

    # Every drive root (catches USB repos too)
    foreach ($d in [System.IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady }) {
        $root = $d.RootDirectory.FullName.TrimEnd('\')
        $candidates.Add("$root\CITL")
        $candidates.Add("$root\CITL LLM PRESENTATION UTILITY")
    }

    # Henosis dev tree (fallback; other machines won't have this path)
    $candidates.Add("C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS\CITL")

    foreach ($raw in $candidates) {
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        try {
            $resolved = Resolve-Path $raw -ErrorAction SilentlyContinue
            if ($null -eq $resolved) { continue }
            if (Test-Path (Join-Path $resolved.Path $SyncMarker) -ErrorAction SilentlyContinue) {
                return $resolved.Path
            }
        } catch { }
    }
    return $null
}

if ($SourceRepo -eq "auto" -or [string]::IsNullOrWhiteSpace($SourceRepo)) {
    Write-Step "Auto-detecting CITL source repo..."
    $SourceRepo = Find-CitlRepo
    if ($null -eq $SourceRepo) {
        Write-Fail "Cannot locate CITL repo."
        Write-Host ""
        Write-Host "  Set CITL_REPO env variable or pass -SourceRepo <path>." -ForegroundColor Yellow
        Write-Host "  Example: set CITL_REPO=C:\Users\You\CITL" -ForegroundColor DarkGray
        Write-Host ""
        if (-not $Silent) { Read-Host "Press Enter to exit" }
        exit 1
    }
    Write-OK "Found repo : $SourceRepo"
} else {
    Write-OK "Source     : $SourceRepo"
}

$SyncScript = Join-Path $SourceRepo "factbook-assistant\citl_app_sync.py"
if (!(Test-Path -LiteralPath $SyncScript)) {
    Write-Fail "Sync script not found: $SyncScript"
    if (-not $Silent) { Read-Host "Press Enter to exit" }
    exit 1
}

# ============================================================
# 2. LOCATE OR BOOTSTRAP PYTHON
# ============================================================
Write-Step "Locating Python 3..."

$VenvPy = Join-Path $SourceRepo ".venv\Scripts\python.exe"

$knownPyPaths = @(
    $VenvPy,
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "C:\Python313\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe"
)

$pythonExe = $null
foreach ($p in $knownPyPaths) {
    if (-not [string]::IsNullOrWhiteSpace($p) -and
        $p -notlike "*WindowsApps*" -and
        (Test-Path $p -ErrorAction SilentlyContinue)) {
        $pythonExe = $p; break
    }
}

if (-not $pythonExe) {
    foreach ($name in @("python", "python3", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
            $v = & $cmd.Source --version 2>&1
            if ($v -match "Python 3\.(9|1[0-9])") { $pythonExe = $cmd.Source; break }
        }
    }
}

if (-not $pythonExe -and !(Test-Path $VenvPy -ErrorAction SilentlyContinue)) {
    Write-Warn "Python 3 not found. Attempting install via winget..."
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if ($wg) {
        & winget install Python.Python.3.11 --silent --accept-source-agreements `
                         --accept-package-agreements 2>&1 | Out-Null
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH","User")
        foreach ($p in $knownPyPaths) {
            if (-not [string]::IsNullOrWhiteSpace($p) -and
                $p -notlike "*WindowsApps*" -and
                (Test-Path $p -ErrorAction SilentlyContinue)) { $pythonExe = $p; break }
        }
    }
}

if (-not $pythonExe -and !(Test-Path $VenvPy -ErrorAction SilentlyContinue)) {
    Write-Fail "Python 3.9+ not found and could not be installed automatically."
    Write-Host "  Download: https://www.python.org/downloads/" -ForegroundColor Yellow
    if (-not $Silent) { Read-Host "Press Enter to exit" }
    exit 1
}

if (!(Test-Path $VenvPy -ErrorAction SilentlyContinue)) {
    Write-Step "Creating venv at $SourceRepo\.venv ..."
    & $pythonExe -m venv "$SourceRepo\.venv"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "venv creation failed (exit $LASTEXITCODE)."
        if (-not $Silent) { Read-Host "Press Enter to exit" }
        exit 1
    }
    Write-Step "Installing sync dependencies..."
    & $VenvPy -m pip install --upgrade pip --quiet 2>&1 | Out-Null
    $req = Join-Path $SourceRepo "requirements-windows.txt"
    if (!(Test-Path $req)) { $req = Join-Path $SourceRepo "requirements.txt" }
    if (Test-Path $req) {
        & $VenvPy -m pip install -r $req --quiet
    } else {
        & $VenvPy -m pip install requests psutil --quiet
    }
    Write-OK "venv ready."
}
Write-OK "Python     : $VenvPy"

# ============================================================
# 3. BUILD PYTHON SYNC ARGUMENT LIST
# ============================================================
$argList = @($SyncScript, "--source", $SourceRepo)

if ($DuplicateUsb) {
    $argList += "--duplicate-usb"
} else {
    $argList += "--sync-best-usb"
}

if ($IncludeData)         { $argList += "--include-data" }
if ($IncludeModels)       { $argList += "--include-models" }
if ($TargetRepo)          { $argList += @("--target-path", $TargetRepo) }
if ($DuplicateFrom)       { $argList += @("--duplicate-from", $DuplicateFrom) }
if ($DuplicateTo)         { $argList += @("--duplicate-to", $DuplicateTo) }
if ($OllamaModelSource)   { $argList += @("--ollama-model-source", $OllamaModelSource) }
if ($OllamaModelTarget)   { $argList += @("--ollama-model-target", $OllamaModelTarget) }
if ($SkipAppKeySync)      { $argList += "--no-app-key-sync" }
if ($FullRepo)            { $argList += "--full-repo-sync" }
if ($PushToPhone) {
    $argList += "--push-target-to-phone"
    if ($PhoneSerial -and $PhoneSerial -ne "auto") {
        $argList += @("--phone-serial", $PhoneSerial)
    }
}

Write-Host ""
Write-Step "Running CITL App Sync (source code + scripts)..."
Write-Host ""
& $VenvPy @argList
$syncExit = $LASTEXITCODE

# ============================================================
# 4. RESOLVE USB TARGET PATH (for bundle + installer sync)
# ============================================================
# We resolve the USB path regardless of SkipExeBundles so we
# can also update the installer script on the USB.

$usbTarget = $null

# Priority: explicit -TargetRepo flag
if ($TargetRepo -and (Test-Path $TargetRepo -ErrorAction SilentlyContinue)) {
    $usbTarget = $TargetRepo
    Write-Info "USB target (explicit): $usbTarget"
} else {
    # Use --detect-json to ask the Python sync which target it found
    Write-Step "Detecting USB target..."
    $detectArgs = @($SyncScript, "--source", $SourceRepo, "--detect-json")
    $rawJson = $null
    try {
        $rawJson = & $VenvPy @detectArgs 2>$null | Out-String
    } catch {
        Write-Warn "detect-json invocation failed: $_"
    }

    if (-not [string]::IsNullOrWhiteSpace($rawJson)) {
        try {
            $parsed = $rawJson | ConvertFrom-Json -ErrorAction Stop
            if ($parsed -and $parsed.targets -and $parsed.targets.Count -gt 0) {
                $best = $parsed.targets |
                        Sort-Object { if ($_.score) { $_.score } else { 0 } } -Descending |
                        Select-Object -First 1
                if ($best -and $best.path -and
                    (Test-Path $best.path -ErrorAction SilentlyContinue)) {
                    $usbTarget = $best.path
                    Write-OK "USB target (auto)  : $usbTarget  (score=$($best.score))"
                } else {
                    Write-Warn "detect-json returned a target but path does not exist."
                }
            } else {
                Write-Warn "detect-json found no targets."
            }
        } catch {
            Write-Warn "detect-json output could not be parsed as JSON: $_"
            Write-Info "Raw output: $($rawJson.Substring(0, [Math]::Min(300, $rawJson.Length)))"
        }
    } else {
        Write-Warn "detect-json produced no output. No USB target resolved."
    }
}

# ============================================================
# 5. SYNC BUILT EXE BUNDLES TO USB NUMBERED FOLDERS
# ============================================================
# App bundles live in dist\ (and project-specific build folders)
# and get distributed via numbered folders on the USB for easy user access.
# This runs by default whenever we can resolve a USB target.

if ($syncExit -le 1 -and (-not $SkipExeBundles) -and $usbTarget) {
    Write-Host ""
    Write-Step "Syncing built EXE bundles to USB numbered folders..."

    $DistDir = Join-Path $SourceRepo "dist"
    if (!(Test-Path $DistDir -ErrorAction SilentlyContinue)) {
        Write-Warn "No dist/ folder found. Run BUILD_ALL_CITL_EXES_WINDOWS.cmd first."
    } else {
        # Map: dist folder name -> USB numbered folder.
        # Optional SourceRel allows bundles that are built outside root dist\.
        $bundles = @(
            @{ Dist = "CITL App Sync";                 Usb = "1-CITL-SYNC";                   Exe = "CITL App Sync.exe" },
            @{ Dist = "CITL LLMOps Presentation Suite";Usb = "2-CITL-PRESENTATION-SUITE";      Exe = "CITL LLMOps Presentation Suite.exe" },
            @{ Dist = "CITL Workstation Apps";          Usb = "3-CITL-WORKSTATION-APPS";        Exe = "CITL Workstation Apps.exe" },
            @{ Dist = "CITL Field Apps";                Usb = "4-CITL-FIELD-APPS";              Exe = "CITL Field Apps.exe" },
            @{ Dist = "CITL Ticketing Automation GUI";  Usb = "6-CITL-WORK-TICKETING";          Exe = "CITL Ticketing Automation GUI.exe"; SourceRel = "powerflow_builder\dist\CITL Ticketing Automation GUI" }
        )

        foreach ($b in $bundles) {
            $src = if ($b.ContainsKey("SourceRel")) {
                Join-Path $SourceRepo $b.SourceRel
            } else {
                Join-Path $DistDir $b.Dist
            }
            $dst = Join-Path $usbTarget $b.Usb

            if (!(Test-Path (Join-Path $src $b.Exe) -ErrorAction SilentlyContinue)) {
                Write-Warn "$($b.Dist): exe not built yet - skipping. (Run BUILD_ALL_CITL_EXES_WINDOWS.cmd -Apps $($b.Dist -replace 'CITL ',''))"
                continue
            }

            # Ensure USB folder exists
            if (!(Test-Path $dst -ErrorAction SilentlyContinue)) {
                New-Item -ItemType Directory -Path $dst -Force | Out-Null
            }

            Write-Step "  $($b.Dist) -> $($b.Usb)"
            # /MIR = mirror; /XO = skip older; /R:2 /W:1 = fast-fail on locks
            # /NFL /NDL /NJH /NJS = suppress clutter; /MT:4 = 4 threads
            $roboArgs = @($src, $dst, "/MIR", "/XO", "/R:2", "/W:1",
                          "/NFL", "/NDL", "/NJH", "/NJS", "/MT:4")
            & robocopy @roboArgs | Out-Null
            $roboExit = $LASTEXITCODE
            if ($roboExit -le 7) {
                Write-OK "  $($b.Usb) updated."
            } else {
                Write-Warn "  robocopy exited $roboExit for $($b.Dist) (may be partial)."
            }
        }
    }
} elseif ($SkipExeBundles) {
    Write-Info "EXE bundle sync skipped (-SkipExeBundles)."
} elseif (-not $usbTarget) {
    Write-Warn "No USB target resolved - EXE bundle sync skipped."
}

# ============================================================
# 6. SYNC INSTALLER SCRIPTS TO USB ROOT
# ============================================================
if ($usbTarget -and $syncExit -le 1) {
    Write-Host ""
    Write-Step "Syncing portable installer to USB root..."

    $installerFiles = @(
        @{ Src = (Join-Path $SourceRepo "INSTALL_CITL_APPS_PORTABLE.cmd");          Dst = (Join-Path $usbTarget "INSTALL_CITL_APPS_PORTABLE.cmd") },
        @{ Src = (Join-Path $SourceRepo "SYNC_EXES_TO_USB_WINDOWS.cmd");            Dst = (Join-Path $usbTarget "SYNC_EXES_TO_USB_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "RUN_APP_SYNC_WINDOWS.cmd");                 Dst = (Join-Path $usbTarget "RUN_APP_SYNC_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "Run-CITL-App-Sync.ps1");                    Dst = (Join-Path $usbTarget "Run-CITL-App-Sync.ps1") },
        @{ Src = (Join-Path $SourceRepo "RUN_WORK_TICKETING_SYSTEM_WINDOWS.cmd");    Dst = (Join-Path $usbTarget "RUN_WORK_TICKETING_SYSTEM_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "RUN_WORK_TICKETING_SYSTEM_WINDOWS_EXE.cmd");Dst = (Join-Path $usbTarget "RUN_WORK_TICKETING_SYSTEM_WINDOWS_EXE.cmd") },
        @{ Src = (Join-Path $SourceRepo "REPAIR_CITL_APPS.cmd");                     Dst = (Join-Path $usbTarget "REPAIR_CITL_APPS.cmd") },
        @{ Src = (Join-Path $SourceRepo "RUN_CITL_FIXER_WINDOWS.cmd");               Dst = (Join-Path $usbTarget "RUN_CITL_FIXER_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "RUN_CITL_FIXER_UBUNTU.sh");                 Dst = (Join-Path $usbTarget "RUN_CITL_FIXER_UBUNTU.sh") },
        @{ Src = (Join-Path $SourceRepo "PATCH_CITL_48H_AUTO_WINDOWS.cmd");          Dst = (Join-Path $usbTarget "PATCH_CITL_48H_AUTO_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "PATCH_CITL_48H_MANUAL_WINDOWS.cmd");        Dst = (Join-Path $usbTarget "PATCH_CITL_48H_MANUAL_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "REGISTER_PATCH_CADENCE_TASK_WINDOWS.cmd");  Dst = (Join-Path $usbTarget "REGISTER_PATCH_CADENCE_TASK_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "UNREGISTER_PATCH_CADENCE_TASK_WINDOWS.cmd");Dst = (Join-Path $usbTarget "UNREGISTER_PATCH_CADENCE_TASK_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "RUN_CITL_USB_REPAIR_CLONER_WINDOWS.cmd");  Dst = (Join-Path $usbTarget "RUN_CITL_USB_REPAIR_CLONER_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "BUILD_CITL_USB_REPAIR_CLONER_WINDOWS.cmd");Dst = (Join-Path $usbTarget "BUILD_CITL_USB_REPAIR_CLONER_WINDOWS.cmd") },
        @{ Src = (Join-Path $SourceRepo "scripts\windows\install_citl_apps_portable.ps1"); Dst = (Join-Path $usbTarget "scripts\windows\install_citl_apps_portable.ps1") },
        @{ Src = (Join-Path $SourceRepo "scripts\windows\sync_usb_apps.ps1");       Dst = (Join-Path $usbTarget "scripts\windows\sync_usb_apps.ps1") },
        @{ Src = (Join-Path $SourceRepo "scripts\windows\run_work_ticketing_system.ps1"); Dst = (Join-Path $usbTarget "scripts\windows\run_work_ticketing_system.ps1") },
        @{ Src = (Join-Path $SourceRepo "scripts\windows\citl_usb_repair_clone.py");Dst = (Join-Path $usbTarget "scripts\windows\citl_usb_repair_clone.py") }
    )

    foreach ($f in $installerFiles) {
        if (!(Test-Path $f.Src -ErrorAction SilentlyContinue)) {
            Write-Warn "  Source not found: $($f.Src)"
            continue
        }
        try {
            $srcNorm = [System.IO.Path]::GetFullPath([string]$f.Src).TrimEnd('\').ToLowerInvariant()
            $dstNorm = [System.IO.Path]::GetFullPath([string]$f.Dst).TrimEnd('\').ToLowerInvariant()
            if ($srcNorm -eq $dstNorm) {
                Write-Info "  same path, skipped: $(Split-Path $f.Dst -Leaf)"
                continue
            }
        } catch {}
        $dstDir = Split-Path $f.Dst
        if (!(Test-Path $dstDir -ErrorAction SilentlyContinue)) {
            New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
        }
        try {
            Copy-Item -Path $f.Src -Destination $f.Dst -Force
            Write-OK "  $(Split-Path $f.Dst -Leaf)"
        } catch {
            Write-Warn "  Could not copy $(Split-Path $f.Dst -Leaf): $_"
        }
    }

    # Sync cloner executable bundle if built.
    Write-Step "Syncing CITL USB Repair Cloner executable..."
    $clonerExe = Join-Path $SourceRepo "dist\CITL USB Repair Cloner.exe"
    if (Test-Path $clonerExe -ErrorAction SilentlyContinue) {
        $clonerDstDir = Join-Path $usbTarget "1-CITL-SYNC\CITL USB Repair Cloner"
        if (!(Test-Path $clonerDstDir -ErrorAction SilentlyContinue)) {
            New-Item -ItemType Directory -Path $clonerDstDir -Force | Out-Null
        }
        try {
            Copy-Item -Path $clonerExe -Destination (Join-Path $clonerDstDir "CITL USB Repair Cloner.exe") -Force
            Write-OK "  CITL USB Repair Cloner.exe"
        } catch {
            Write-Warn "  Could not copy cloner exe: $_"
        }
    } else {
        Write-Warn "  Cloner exe not built yet: $clonerExe"
    }
}

# ============================================================
# 7. SUMMARY
# ============================================================
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Sync Summary" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

if ($syncExit -eq 0) {
    Write-OK "App key-files sync    : complete"
} elseif ($syncExit -eq 1) {
    Write-Warn "App key-files sync    : completed with warnings (exit 1)"
} else {
    Write-Fail "App key-files sync    : FAILED (exit $syncExit)"
}

if ($usbTarget) {
    Write-OK "USB target            : $usbTarget"
    if (-not $SkipExeBundles) {
        Write-OK "EXE bundles sync      : complete (numbered folders)"
    }
    Write-OK "Installer sync        : complete"
} else {
    Write-Warn "USB target            : none detected (source-only sync)"
}

Write-Host ""
Write-Info "Next steps:"
Write-Info "  - To build missing EXEs : BUILD_ALL_CITL_EXES_WINDOWS.cmd"
Write-Info "  - To build USB cloner   : BUILD_CITL_USB_REPAIR_CLONER_WINDOWS.cmd"
Write-Info "  - To install on desktop : INSTALL_CITL_APPS_PORTABLE.cmd  (or from USB)"
Write-Info "  - To duplicate to USB   : .\sync_usb_apps.ps1 -DuplicateUsb"
Write-Host ""

if (-not $Silent) { Read-Host "Press Enter to close" }
if ($syncExit -gt 1) { exit $syncExit }
exit 0
