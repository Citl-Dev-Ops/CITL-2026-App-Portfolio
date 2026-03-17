$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runner = Join-Path $PSScriptRoot "scripts\windows\run.ps1"
if (!(Test-Path -LiteralPath $runner)) {
  throw "Missing Windows runner: $runner"
}
& $runner @args
