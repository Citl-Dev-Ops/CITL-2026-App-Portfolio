#Requires -Version 5.1
<#
  Sync curated professional font families for CITL Document Composer
  from external font libraries into the repo-local pack.
#>

param(
    [string]$SourceRoot = "M:\00 FONTS FONTS FONTS\QSL CARD FONTS\VINTAGE HEADER AND SUBHEADER\Apothecary Font Collection",
    [string]$DestinationRoot = "",
    [int]$MaxFontsPerFamily = 48
)

$ErrorActionPreference = "Stop"

function Write-Step { param($m) Write-Host "[....] $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $DestinationRoot = Join-Path $repo "factbook-assistant\fonts\doc_composer\apothecary"
}

if (!(Test-Path $SourceRoot)) {
    throw "SourceRoot not found: $SourceRoot"
}

New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null

$familyRegex = @(
    "Helvetica",
    "Avenir",
    "DIN",
    "Frutiger",
    "Trade Gothic",
    "Univers",
    "Proxima Nova",
    "Futura",
    "Century Gothic",
    "Arial",
    "Gilroy",
    "Nexa",
    "Sofia Pro",
    "TT Norms",
    "Neue Haas Grotesk",
    "FF Mark",
    "Campton",
    "Galano",
    "Panton",
    "Brandon Grotesque"
) -join "|"

Write-Step "Scanning source family folders..."
$familyDirs = Get-ChildItem $SourceRoot -Directory | Where-Object { $_.Name -match $familyRegex }
if (-not $familyDirs) {
    throw "No matching family directories found under: $SourceRoot"
}

$totalCopied = 0
$totalSkipped = 0
$summary = @()

foreach ($dir in $familyDirs) {
    $cleanName = ($dir.Name -replace "^\d+\.\-\s*", "")
    $cleanName = ($cleanName -replace "[^A-Za-z0-9 _-]", "")
    $cleanName = ($cleanName -replace "\s+", " ").Trim()
    if ([string]::IsNullOrWhiteSpace($cleanName)) {
        $cleanName = $dir.Name
    }
    $destFamily = Join-Path $DestinationRoot $cleanName
    New-Item -ItemType Directory -Force -Path $destFamily | Out-Null

    $files = Get-ChildItem $dir.FullName -Recurse -File -Include *.ttf,*.otf,*.ttc |
        Sort-Object Name |
        Select-Object -First $MaxFontsPerFamily

    $copied = 0
    $skipped = 0
    foreach ($src in $files) {
        $dst = Join-Path $destFamily $src.Name
        if (Test-Path $dst) {
            $s = Get-Item $dst
            if ($s.Length -eq $src.Length) {
                $skipped++
                continue
            }
        }
        Copy-Item -LiteralPath $src.FullName -Destination $dst -Force
        $copied++
    }

    $totalCopied += $copied
    $totalSkipped += $skipped
    $summary += [pscustomobject]@{
        FamilyDir = $dir.Name
        Destination = $cleanName
        Files = $files.Count
        Copied = $copied
        Skipped = $skipped
    }
    Write-OK "$($dir.Name): files=$($files.Count) copied=$copied skipped=$skipped"
}

$manifest = Join-Path $DestinationRoot "_font_sync_manifest.json"
$summary | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $manifest

Write-Host ""
Write-OK "Font sync complete."
Write-OK "Copied : $totalCopied"
Write-OK "Skipped: $totalSkipped"
Write-OK "Output : $DestinationRoot"
Write-OK "Manifest: $manifest"
