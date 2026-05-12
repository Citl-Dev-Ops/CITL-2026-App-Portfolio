param(
  [switch]$AlsoUsb
)
$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Repo = Split-Path -Parent $Repo
$SyncPy = Join-Path $Repo 'factbook-assistant\citl_app_sync.py'
$Pkg = Join-Path $Repo 'bootstrap\patches\citl_bootstrap_M_20260430T004242Z_a4e6a399.zip'
if (!(Test-Path -LiteralPath $SyncPy)) { throw "citl_app_sync.py not found: $SyncPy" }
if (!(Test-Path -LiteralPath $Pkg)) { throw "bootstrap package not found: $Pkg" }
$args = @('--bootstrap-install-package', $Pkg, '--bootstrap-install-target', 'local')
if ($AlsoUsb) { $args += '--bootstrap-install-usb-if-found' }
if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 $SyncPy @args
} else {
  & python $SyncPy @args
}
exit $LASTEXITCODE
