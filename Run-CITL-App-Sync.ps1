$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

$NoAutoUpdate = $false
$CloneUsb = $false
$CloneTarget = ""
$CloneSource = "auto"
$ForwardArgs = New-Object System.Collections.Generic.List[string]
for ($i = 0; $i -lt $args.Count; $i++) {
  $a = [string]$args[$i]
  if ($a -eq "--no-auto-update") {
    $NoAutoUpdate = $true
    continue
  }
  if ($a -eq "--clone-usb") {
    $CloneUsb = $true
    continue
  }
  if ($a -eq "--clone-usb-target") {
    $CloneUsb = $true
    if (($i + 1) -lt $args.Count) {
      $CloneTarget = [string]$args[$i + 1]
      $i++
    }
    continue
  }
  if ($a -eq "--clone-usb-source") {
    if (($i + 1) -lt $args.Count) {
      $CloneSource = [string]$args[$i + 1]
      $i++
    }
    continue
  }
  $ForwardArgs.Add($a)
}

$patchRunner = ".\PATCH_CITL_48H_AUTO_WINDOWS.cmd"
if ((-not $NoAutoUpdate) -and (Test-Path -LiteralPath $patchRunner)) {
  Write-Host "[AUTO-PATCH] Running cadence patch runner before Sync..."
  try {
    & cmd.exe /c $patchRunner | Out-Host
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "[AUTO-PATCH] runner exit=$LASTEXITCODE (continuing launch)."
    }
  } catch {
    Write-Warning "[AUTO-PATCH] runner invocation failed: $_"
  }
}

if ($CloneUsb) {
  $cloner = ".\scripts\windows\citl_usb_repair_clone.py"
  if (!(Test-Path -LiteralPath $cloner)) {
    throw "Missing USB cloner utility: $cloner"
  }
  $targetArg = if ([string]::IsNullOrWhiteSpace($CloneTarget)) { "auto" } else { $CloneTarget }
  $cloneArgs = @($cloner, "--action", "clone", "--source", $CloneSource, "--target", $targetArg)
  Write-Host "[CLONE] Cloning latest CITL repo snapshot -> $targetArg"
  if (Test-Path ".\.venv\Scripts\python.exe") {
    & ".\.venv\Scripts\python.exe" @cloneArgs
    exit $LASTEXITCODE
  }
  $pyLauncherClone = Get-Command py -ErrorAction SilentlyContinue
  if ($pyLauncherClone) {
    & py -3 @cloneArgs
    exit $LASTEXITCODE
  }
  $sysPythonClone = Get-Command python -ErrorAction SilentlyContinue
  if ($sysPythonClone) {
    & python @cloneArgs
    exit $LASTEXITCODE
  }
  throw "Python 3 is not available. Install Python or create .venv first."
}

$script = ".\factbook-assistant\citl_app_sync.py"
if (!(Test-Path -LiteralPath $script)) {
  throw "Missing sync utility: $script"
}

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
  . ".\.venv\Scripts\Activate.ps1"
}

$argList = @($script, "--source", ".") + $ForwardArgs

if (Test-Path ".\.venv\Scripts\python.exe") {
  & ".\.venv\Scripts\python.exe" @argList
  exit $LASTEXITCODE
}

$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
  & py -3 @argList
  exit $LASTEXITCODE
}

$sysPython = Get-Command python -ErrorAction SilentlyContinue
if ($sysPython) {
  & python @argList
  exit $LASTEXITCODE
}

throw "Python 3 is not available. Install Python or create .venv first."
