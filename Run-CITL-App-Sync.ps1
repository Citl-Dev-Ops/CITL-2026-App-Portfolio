$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

$script = ".\factbook-assistant\citl_app_sync.py"
if (!(Test-Path -LiteralPath $script)) {
  throw "Missing sync utility: $script"
}

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
  . ".\.venv\Scripts\Activate.ps1"
}

$argList = @($script, "--source", ".") + $args

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
