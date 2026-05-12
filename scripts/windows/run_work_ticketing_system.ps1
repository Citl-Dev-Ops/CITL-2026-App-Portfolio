#Requires -Version 5.1
param(
    [switch]$Debug,
    [switch]$NoAutoUpdate
)

$ErrorActionPreference = "Stop"

function Write-Info { param([string]$m) Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-WarnX { param([string]$m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Fail { param([string]$m) Write-Host "[FAIL] $m" -ForegroundColor Red }
function Write-OK { param([string]$m) Write-Host "[ OK ] $m" -ForegroundColor Green }

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Repo

$patchRunner = Join-Path $Repo "PATCH_CITL_48H_AUTO_WINDOWS.cmd"
if ((-not $NoAutoUpdate) -and (Test-Path -LiteralPath $patchRunner)) {
    Write-Info "Running patch cadence preflight..."
    try {
        & cmd.exe /c $patchRunner | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-WarnX "Patch runner returned exit $LASTEXITCODE. Continuing launcher."
        }
    } catch {
        Write-WarnX "Patch runner invocation failed: $_"
    }
}

$exe = Join-Path $Repo "powerflow_builder\dist\CITL Ticketing Automation GUI\CITL Ticketing Automation GUI.exe"
if (Test-Path -LiteralPath $exe) {
    Write-Info "Launching packaged EXE..."
    Start-Process -FilePath $exe -WorkingDirectory $Repo | Out-Null
    Write-OK "Ticketing EXE launch issued."
    exit 0
}

$script = Join-Path $Repo "powerflow_builder\citl_work_ticketing_gui.py"
if (!(Test-Path -LiteralPath $script)) {
    Write-Fail "GUI script not found: $script"
    exit 1
}

$py = Join-Path $Repo ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $py)) {
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        $py = "py"
    } else {
        $sysPy = Get-Command python -ErrorAction SilentlyContinue
        if ($sysPy) {
            $py = "python"
        } else {
            Write-Fail "Python 3 not found."
            exit 1
        }
    }
}

$logDir = Join-Path $Repo "logs"
if (!(Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$stdOut = Join-Path $logDir "ticketing_launch_${stamp}.out.log"
$stdErr = Join-Path $logDir "ticketing_launch_${stamp}.err.log"

$argList = @($script)
if ($Debug -and $py -eq "py") {
    $argList = @("-3", $script)
}

if ($Debug -and $py -eq "python") {
    & python $script
    exit $LASTEXITCODE
}
if ($Debug -and (Test-Path -LiteralPath $py)) {
    & $py $script
    exit $LASTEXITCODE
}

Write-Info "Launching Python GUI with startup diagnostics log..."
if (Test-Path -LiteralPath $py) {
    $proc = Start-Process -FilePath $py -ArgumentList $script -WorkingDirectory $Repo -PassThru -RedirectStandardOutput $stdOut -RedirectStandardError $stdErr
} elseif ($py -eq "py") {
    $proc = Start-Process -FilePath "py" -ArgumentList @("-3", $script) -WorkingDirectory $Repo -PassThru -RedirectStandardOutput $stdOut -RedirectStandardError $stdErr
} else {
    $proc = Start-Process -FilePath "python" -ArgumentList $script -WorkingDirectory $Repo -PassThru -RedirectStandardOutput $stdOut -RedirectStandardError $stdErr
}

Start-Sleep -Seconds 3
if ($proc.HasExited) {
    Write-Fail "Ticketing GUI exited early (code $($proc.ExitCode))."
    Write-Host "Logs:"
    Write-Host "  $stdOut"
    Write-Host "  $stdErr"
    try {
        $tail = Get-Content -LiteralPath $stdErr -Tail 25 -ErrorAction SilentlyContinue
        if ($tail) {
            Write-Host ""
            Write-Host "stderr tail:" -ForegroundColor Yellow
            $tail | ForEach-Object { Write-Host "  $_" }
        }
    } catch {}
    exit 1
}

Write-OK "Ticketing GUI started."
exit 0
