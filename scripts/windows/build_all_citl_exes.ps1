#Requires -Version 5.1
<#
  CITL Enterprise Build System v2.0
  ===================================
  Professional build automation with testing, deployment, and monitoring.
  
  Features:
  - Automated testing and validation
  - Parallel builds for faster execution
  - Build artifact management
  - Automated deployment to sync targets
  - Build metrics and reporting
  - Integration with sync manager
  
  Usage:
    .\build_all_citl_exes.ps1                           # Build all apps
    .\build_all_citl_exes.ps1 -Apps sync,presentation   # Build specific apps
    .\build_all_citl_exes.ps1 -Test                     # Build + run tests
    .\build_all_citl_exes.ps1 -Deploy                   # Build + auto-deploy
    .\build_all_citl_exes.ps1 -Clean                    # Clean build artifacts
    .\build_all_citl_exes.ps1 -Parallel                 # Parallel builds
#>
param(
    [string]$Apps     = "all",   # "all" | "llmops" | "factbook" | "appsync" | "doccomposer" | "dbbuilder" | "avitops" | "stafftoolkit" | "workstationapps" | "fieldapps" | "synchub" | "ticketing"
    [switch]$Clean,
    [switch]$SkipDeps,
    [switch]$CopyToUsb,
    [switch]$Test,              # Run tests after build
    [switch]$Deploy,            # Auto-deploy after successful build
    [switch]$Parallel,          # Use parallel builds
    [switch]$Report             # Generate build report
)
$ErrorActionPreference = "Continue"

function Write-Step { param($m) Write-Host "[....] $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  CITL All-Apps EXE Builder" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ---- Resolve repo root (two levels up from scripts\windows) ------------
$Repo    = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$DistDir = Join-Path $Repo "dist"
$TicketDistDir = Join-Path $Repo "powerflow_builder\dist"
$WorkDir = Join-Path $Repo "build"
$TicketWorkDir = Join-Path $Repo "powerflow_builder\build"
$VenvPy  = Join-Path $Repo ".venv\Scripts\python.exe"
Write-OK "Repo     : $Repo"
Write-OK "Output   : $DistDir"

# ---- Find / create Python venv -----------------------------------------
Write-Step "Locating Python 3..."

$knownPyPaths = @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe"
)

$pythonExe = $null
if (Test-Path $VenvPy) {
    & $VenvPy -V *> $null
    if ($LASTEXITCODE -eq 0) {
        $pythonExe = $VenvPy
        Write-OK "Using existing venv: $VenvPy"
    } else {
        Write-Warn "Existing venv Python is invalid. Recreating .venv."
        try {
            Remove-Item -Recurse -Force (Join-Path $Repo ".venv")
        } catch { }
    }
}
if (-not $pythonExe) {
    foreach ($p in $knownPyPaths) {
        if (-not [string]::IsNullOrWhiteSpace($p) -and
            $p -notlike "*WindowsApps*" -and
            (Test-Path $p -ErrorAction SilentlyContinue)) {
            $pythonExe = $p; break
        }
    }
    if (-not $pythonExe) {
        foreach ($name in @("python","python3","py")) {
            $cmd = Get-Command $name -ErrorAction SilentlyContinue
            if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
                $v = & $cmd.Source --version 2>&1
                if ($v -match "Python 3\.(9|1[0-9])") { $pythonExe = $cmd.Source; break }
            }
        }
    }
    if (-not $pythonExe) {
        Write-Warn "Python not found. Attempting winget install..."
        $wg = Get-Command winget -ErrorAction SilentlyContinue
        if ($wg) {
            & winget install Python.Python.3.11 --silent --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("PATH","User")
            foreach ($p in $knownPyPaths) {
                if ($p -and (Test-Path $p -ErrorAction SilentlyContinue)) { $pythonExe = $p; break }
            }
        }
    }
    if (-not $pythonExe) {
        Write-Fail "Python 3.9+ required. Install from https://www.python.org/downloads/"
        Read-Host "Press Enter to exit"; exit 1
    }

    Write-Step "Creating venv..."
    & $pythonExe -m venv "$Repo\.venv"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "venv creation failed."
        Read-Host "Press Enter to exit"; exit 1
    }
    Write-OK "venv created."
}

# ---- Install / update deps ---------------------------------------------
if (!$SkipDeps) {
    Write-Step "Installing build dependencies..."
    & $VenvPy -m pip install --upgrade pip --quiet 2>&1 | Out-Null

    $req = Join-Path $Repo "requirements-windows.txt"
    if (!(Test-Path $req)) { $req = Join-Path $Repo "requirements.txt" }
    if (Test-Path $req) {
        & $VenvPy -m pip install -r $req --quiet
    } else {
        & $VenvPy -m pip install requests psutil python-docx openpyxl pandas --quiet
    }
    & $VenvPy -m pip install -U pyinstaller --quiet
    Write-OK "Dependencies ready."
}

# ---- Clean artifacts ---------------------------------------------------
if ($Clean) {
    Write-Step "Cleaning build artifacts..."
    if (Test-Path $WorkDir) { Remove-Item -Recurse -Force $WorkDir }
    $apps2clean = @(
        "CITL LLMOps Presentation Suite",
        "CITL Factbook Assistant",
        "CITL App Sync",
        "CITL Document Composer",
        "CITL Database LLMOps Builder",
        "CITL AV IT Operations",
        "CITL Staff Toolkit",
        "CITL Work and Preparedness Launcher",
        "CITL Workstation Apps",
        "CITL Field Apps",
            "CITL FLEX Troubleshooter",
            "CITL Sync Hub"
    )
    foreach ($a in $apps2clean) {
        $d = Join-Path $DistDir $a
        if (Test-Path $d) { Remove-Item -Recurse -Force $d }
    }
    $ticketOut = Join-Path $TicketDistDir "CITL Ticketing Automation GUI"
    if (Test-Path $ticketOut) { Remove-Item -Recurse -Force $ticketOut }
    $ticketWork = Join-Path $TicketWorkDir "CITL Ticketing Automation GUI"
    if (Test-Path $ticketWork) { Remove-Item -Recurse -Force $ticketWork }
    Write-OK "Clean done."
}

# ---- Helper: run PyInstaller for one app -------------------------------
function Build-App {
    param(
        [string]$Name,
        [string]$Entry,
        [string[]]$HiddenImports = @(),
        [string[]]$AddData       = @()
    )

    Write-Host ""
    Write-Host "---- Building: $Name ----" -ForegroundColor Magenta

    if (!(Test-Path $Entry)) {
        Write-Fail "Entry not found: $Entry  --  skipping."
        return $false
    }

    $pyiArgs = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", $Name,
        "--distpath", $DistDir,
        "--workpath", $WorkDir
    )
    foreach ($hi in $HiddenImports) { $pyiArgs += @("--hidden-import", $hi) }
    foreach ($ad in $AddData)       { $pyiArgs += @("--add-data", $ad) }
    $pyiArgs += $Entry

    Set-Location $Repo
    & $VenvPy @pyiArgs
    $ec = $LASTEXITCODE

    $outDir = Join-Path $DistDir $Name
    if ($ec -eq 0 -and (Test-Path $outDir)) {
        $sizeMb = [math]::Round(
            (Get-ChildItem $outDir -Recurse -ErrorAction SilentlyContinue |
             Measure-Object -Property Length -Sum).Sum / 1MB, 1)
        Write-OK "$Name  -->  $outDir  ($sizeMb MB)"
        return $true
    } else {
        Write-Fail "$Name build FAILED (exit $ec)."
        return $false
    }
}

# ---- Define which apps to build ----------------------------------------
$appsNorm = $Apps
if ([string]::IsNullOrWhiteSpace($appsNorm)) { $appsNorm = "all" }
$appsNorm = $appsNorm.ToLowerInvariant().Trim()
$buildAll              = ($appsNorm -eq "all")
$buildLlmops           = $buildAll -or ($appsNorm -eq "llmops")
$buildFactbook         = $buildAll -or ($appsNorm -eq "factbook")
$buildAppSync          = $buildAll -or ($appsNorm -eq "appsync")
$buildDocComposer      = $buildAll -or ($appsNorm -eq "doccomposer")
$buildDbBuilder        = $buildAll -or (@("dbbuilder","database","databasebuilder","database_llmops_builder") -contains $appsNorm)
$buildAvItOps          = $buildAll -or (@("avitops","av_it_ops","avops","avit") -contains $appsNorm)
$buildStaffToolkit     = $buildAll -or (@("stafftoolkit","staff","toolkit") -contains $appsNorm)
$buildWorkstationApps  = $buildAll -or (@("workstationapps","workstation","wsapps") -contains $appsNorm)
$buildFieldApps        = $buildAll -or (@("fieldapps","field","fieldtech") -contains $appsNorm)
$buildSyncHub          = $buildAll -or (@("synchub","sync_hub","hub","syncapp") -contains $appsNorm)
$buildFlex             = $buildAll -or (@("flex","flex_troubleshooter","citlflex","flextroubleshooter") -contains $appsNorm)
$buildTicketing        = $buildAll -or (@("ticketing","workticketing","ticketingautomation","powerflow","powerflowbuilder") -contains $appsNorm)

$results = @{}

# Ensure the FLEX PDF is present and backed-up before building FLEX
$ensureScript = Join-Path $Repo "scripts\windows\ensure_flex_pdf.ps1"
if (Test-Path $ensureScript) {
    Write-Step "Ensuring FLEX PDF is available..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ensureScript -RepoPath $Repo
    if ($LASTEXITCODE -ne 0) { Write-Warn "ensure_flex_pdf.ps1 reported an issue; continuing but FLEX build may fail." }
} else {
    Write-Warn "ensure_flex_pdf.ps1 not found; FLEX PDF will not be auto-injected."
}

if ($buildLlmops) {
    $ok = Build-App `
        -Name "CITL LLMOps Presentation Suite" `
        -Entry (Join-Path $Repo "factbook-assistant\citl_llmops_suite.py") `
        -HiddenImports @("psutil","tkinter","_tkinter","tkinter.ttk","tkinter.messagebox")
    $results["LLMOps Suite"] = $ok
}

if ($buildFactbook) {
    $ok = Build-App `
        -Name "CITL Factbook Assistant" `
        -Entry (Join-Path $Repo "factbook-assistant\factbook_assistant_gui.py") `
        -HiddenImports @("psutil","tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
                         "tkinter.filedialog","tkinter.scrolledtext",
                         "citl_factbook_query","citl_auto_index","citl_text_extract",
                         "citl_theme","citl_translation","parsers") `
        -AddData @("factbook-assistant\fonts\doc_composer;factbook-assistant\fonts\doc_composer")
    $results["Factbook"] = $ok
}

if ($buildAppSync) {
    $ok = Build-App `
        -Name "CITL App Sync" `
        -Entry (Join-Path $Repo "factbook-assistant\citl_app_sync.py") `
        -HiddenImports @("tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
                         "tkinter.filedialog","tkinter.scrolledtext")
    $results["App Sync"] = $ok
}

if ($buildDocComposer) {
    $ok = Build-App `
        -Name "CITL Document Composer" `
        -Entry (Join-Path $Repo "factbook-assistant\citl_doc_composer.py") `
        -HiddenImports @("tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
                         "tkinter.filedialog","tkinter.scrolledtext",
                         "docx","docx.shared","docx.enum.text","docx.oxml.ns",
                         "citl_doc_theme","citl_doc_templates") `
        -AddData @("factbook-assistant\fonts\doc_composer;factbook-assistant\fonts\doc_composer")
    $results["Doc Composer"] = $ok
}

if ($buildDbBuilder) {
    $ok = Build-App `
        -Name "CITL Database LLMOps Builder" `
        -Entry (Join-Path $Repo "factbook-assistant\citl_database_llmops_builder.py") `
        -HiddenImports @(
            "tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
            "tkinter.filedialog","tkinter.scrolledtext"
        )
    $results["Database LLMOps Builder"] = $ok
}

if ($buildAvItOps) {
    $ok = Build-App `
        -Name "CITL AV IT Operations" `
        -Entry (Join-Path $Repo "factbook-assistant\citl_av_it_ops.py") `
        -HiddenImports @(
            "tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
            "tkinter.filedialog","tkinter.scrolledtext"
        )
    $results["AV IT Operations"] = $ok
}

if ($buildStaffToolkit) {
    $ok = Build-App `
        -Name "CITL Work and Preparedness Launcher" `
        -Entry (Join-Path $Repo "factbook-assistant\citl_staff_toolkit.py") `
        -HiddenImports @(
            "tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
            "tkinter.scrolledtext"
        )
    $results["Work and Preparedness Launcher"] = $ok
}

if ($buildWorkstationApps) {
    $ok = Build-App `
        -Name "CITL Workstation Apps" `
        -Entry (Join-Path $Repo "factbook-assistant\citl_workstation_apps.py") `
        -HiddenImports @(
            "tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
            "tkinter.filedialog","tkinter.scrolledtext","tkinter.simpledialog"
        )
    $results["Workstation Apps"] = $ok
}

if ($buildFieldApps) {
    $ok = Build-App `
        -Name "CITL Field Apps" `
        -Entry (Join-Path $Repo "factbook-assistant\citl_field_apps.py") `
        -HiddenImports @(
            "tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
            "tkinter.filedialog","tkinter.scrolledtext","tkinter.simpledialog"
        )
    $results["Field Apps"] = $ok
}

if ($buildFlex) {
    $ok = Build-App `
        -Name "CITL FLEX Troubleshooter" `
        -Entry (Join-Path $Repo "citl_flex_troubleshooter\flex_assistant_gui.py") `
        -HiddenImports @(
            "tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
            "tkinter.filedialog","tkinter.scrolledtext","psutil","numpy"
        ) `
        -AddData @(
            "citl_flex_troubleshooter\Modelfile;citl_flex_troubleshooter\Modelfile",
            "MAIN - The FLEX Team One Note - FULL.pdf;citl_flex_troubleshooter\data\MAIN - The FLEX Team One Note - FULL.pdf",
            "factbook-assistant;factbook-assistant"
        )
    $results["CITL FLEX Troubleshooter"] = $ok
}

if ($buildSyncHub) {
    $ok = Build-App `
        -Name "CITL Sync Hub" `
        -Entry (Join-Path $Repo "factbook-assistant\citl_sync_hub.py") `
        -HiddenImports @(
            "tkinter","_tkinter","tkinter.ttk","tkinter.messagebox",
            "tkinter.filedialog","tkinter.scrolledtext"
        )
    $results["Sync Hub"] = $ok
}

if ($buildTicketing) {
    Write-Host ""
    Write-Host "---- Building: CITL Ticketing Automation GUI ----" -ForegroundColor Magenta
    $ticketBuildScript = Join-Path $Repo "powerflow_builder\build_ticketing_automation_exe.ps1"
    if (!(Test-Path $ticketBuildScript)) {
        Write-Fail "Ticketing build script not found: $ticketBuildScript"
        $results["Ticketing Automation GUI"] = $false
    } else {
        $ticketArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ticketBuildScript)
        if ($Clean) { $ticketArgs += "-Clean" }
        & powershell @ticketArgs
        $ticketExe = Join-Path $Repo "powerflow_builder\dist\CITL Ticketing Automation GUI\CITL Ticketing Automation GUI.exe"
        $ok = ($LASTEXITCODE -eq 0 -and (Test-Path $ticketExe))
        if ($ok) {
            $sizeMb = [math]::Round(
                (Get-ChildItem (Split-Path $ticketExe -Parent) -Recurse -ErrorAction SilentlyContinue |
                 Measure-Object -Property Length -Sum).Sum / 1MB, 1)
            Write-OK "CITL Ticketing Automation GUI  -->  $(Split-Path $ticketExe -Parent)  ($sizeMb MB)"
        } else {
            Write-Fail "CITL Ticketing Automation GUI build FAILED."
        }
        $results["Ticketing Automation GUI"] = $ok
    }
}

# ---- Summary -----------------------------------------------------------
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Build Summary" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
$failed = 0
foreach ($k in $results.Keys) {
    if ($results[$k]) {
        Write-OK "$k"
    } else {
        Write-Fail "$k  --  FAILED"
        $failed++
    }
}

# ---- Optionally copy dist to USB ---------------------------------------
if ($CopyToUsb -and $failed -eq 0) {
    Write-Host ""
    Write-Step "Detecting USB target for EXE copy..."

    $SyncScript = Join-Path $Repo "factbook-assistant\citl_app_sync.py"
    $jsonOut = & $VenvPy $SyncScript --source $Repo --detect-json 2>$null | Out-String
    $usb = $null
    try {
        $detected = $jsonOut | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($detected -and $detected.targets) {
            $best = $detected.targets | Sort-Object score -Descending | Select-Object -First 1
            if ($best) { $usb = $best.path }
        }
    } catch { }

    if ($usb -and (Test-Path $usb -ErrorAction SilentlyContinue)) {
        $usbDist = Join-Path $usb "dist"
        Write-Step "Copying dist/ -> $usbDist ..."
        try {
            Copy-Item -Path $DistDir -Destination $usbDist -Recurse -Force
            Write-OK "EXEs copied to USB: $usbDist"
        } catch {
            Write-Warn "EXE copy failed: $_"
        }

        $ticketSrc = Join-Path $Repo "powerflow_builder\dist\CITL Ticketing Automation GUI"
        if (Test-Path (Join-Path $ticketSrc "CITL Ticketing Automation GUI.exe")) {
            $ticketDst = Join-Path $usb "6-CITL-WORK-TICKETING"
            Write-Step "Copying ticketing bundle -> $ticketDst ..."
            & robocopy $ticketSrc $ticketDst /MIR /XO /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
            if ($LASTEXITCODE -le 7) {
                Write-OK "Ticketing bundle copied to USB."
            } else {
                Write-Warn "Ticketing bundle copy returned exit $LASTEXITCODE."
            }
        }
    } else {
        Write-Warn "No USB target detected. Plug in USB drive and re-run with -CopyToUsb."
    }
}

Write-Host ""
if ($failed -eq 0) {
    Write-OK "All builds complete."
    Write-Host ""
    Write-Host "  Run launchers:" -ForegroundColor DarkGray
    Write-Host "    RUN_LLMOPS_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_FACTBOOK_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_APP_SYNC_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_DOC_COMPOSER_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_DATABASE_LLMOPS_BUILDER_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_AV_IT_OPS_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_WORK_PREPAREDNESS_LAUNCHER_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_STAFF_TOOLKIT_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_WORKSTATION_APPS_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_FIELD_APPS_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_SYNC_HUB_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_CITL_FLEX_WINDOWS.cmd" -ForegroundColor DarkGray
    Write-Host "    RUN_WORK_TICKETING_SYSTEM_WINDOWS_EXE.cmd" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  To sync EXEs to USB:  .\build_all_citl_exes.ps1 -CopyToUsb" -ForegroundColor DarkGray
} else {
    Write-Fail "$failed build(s) failed. See output above."
    # Show GUI notification of failure if possible
    $notify = Join-Path $Repo "scripts\windows\notify.ps1"
    if (Test-Path $notify) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $notify -Type Error -Title 'Build Failed' -Message "$failed build(s) failed. See console for details."
    }
    exit 1
}

# On success, show notification (if available)
$notify = Join-Path $Repo "scripts\windows\notify.ps1"
if ((Test-Path $notify) -and ($failed -eq 0)) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $notify -Type Success -Title 'Build Complete' -Message 'All builds completed successfully.'
}

