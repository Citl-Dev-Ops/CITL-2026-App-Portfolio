$ErrorActionPreference="Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
& "$RepoRoot\.venv\Scripts\python.exe" -m apps.launcher
