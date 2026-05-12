param(
    [string]$RepoPath
)

function Write-OK { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

# Resolve repo root if not provided
if (-not $RepoPath) {
    $RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$pdfName = 'MAIN - The FLEX Team One Note - FULL.pdf'
$destDir = Join-Path $RepoPath 'citl_flex_troubleshooter\data'
$backupDir = Join-Path $RepoPath 'citl_flex_troubleshooter\backups'

$candidate1 = Join-Path -Path $RepoPath -ChildPath $pdfName
$candidate2 = Join-Path -Path 'C:\Users\Doc_M\CITL' -ChildPath $pdfName
$candidates = @($candidate1, $candidate2)

$src = $null
foreach ($c in $candidates) {
    if (Test-Path $c) { $src = $c; break }
}

if (-not $src) {
    $msg = "PDF not found in known locations. Searched: $($candidates -join '; ' )"
    Write-Fail $msg
    $notify = Join-Path $PSScriptRoot 'notify.ps1'
    if (Test-Path $notify) { & powershell -NoProfile -ExecutionPolicy Bypass -File $notify -Type Error -Title 'FLEX PDF Missing' -Message $msg }
    exit 1
}

if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir -Force | Out-Null }

$dest = Join-Path $destDir $pdfName
Copy-Item -Path $src -Destination $dest -Force
if ($?) {
    $m = "Copied PDF to $dest"
    Write-OK $m
    $notify = Join-Path $PSScriptRoot 'notify.ps1'
    if (Test-Path $notify) { & powershell -NoProfile -ExecutionPolicy Bypass -File $notify -Type Success -Title 'FLEX PDF Copied' -Message $m }
} else {
    $m = "Failed to copy PDF to $dest"
    Write-Fail $m; 
    $notify = Join-Path $PSScriptRoot 'notify.ps1'
    if (Test-Path $notify) { & powershell -NoProfile -ExecutionPolicy Bypass -File $notify -Type Error -Title 'FLEX PDF Copy Failed' -Message $m }
    exit 1
}

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$backupName = "$($pdfName).$ts"
$backupPath = Join-Path $backupDir $backupName
Copy-Item -Path $src -Destination $backupPath -Force
if ($?) { Write-OK "Backup written to $backupPath" } else { Write-Warn "Backup failed: $backupPath" }

if ($?) {
    $m2 = "Backup written to $backupPath"
    Write-OK $m2
    if (Test-Path (Join-Path $PSScriptRoot 'notify.ps1')) { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'notify.ps1') -Type Info -Title 'FLEX PDF Backup' -Message $m2 }
} else {
    $m2 = "Backup failed: $backupPath"
    Write-Warn $m2
    if (Test-Path (Join-Path $PSScriptRoot 'notify.ps1')) { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'notify.ps1') -Type Warn -Title 'FLEX PDF Backup Warning' -Message $m2 }
}

exit 0
