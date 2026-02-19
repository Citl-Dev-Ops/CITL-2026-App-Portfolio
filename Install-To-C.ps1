param(
  [string]$DestRoot = "C:\CITL",
  [string]$SourceRoot = ""
)

$ErrorActionPreference = "Stop"

function Say($m){ Write-Host $m -ForegroundColor Cyan }
function Ok($m){ Write-Host $m -ForegroundColor Green }
function Warn($m){ Write-Warning $m }

function Find-InstallerRoot {
  # If SourceRoot passed and valid, use it
  if ($SourceRoot -and (Test-Path -LiteralPath $SourceRoot)) { return $SourceRoot }

  # If script is running from USB folder, $PSScriptRoot is correct
  if (Test-Path -LiteralPath (Join-Path $PSScriptRoot "AI-TRAINING-HUB-main") -or
      (Get-ChildItem -Path $PSScriptRoot -Filter "*AI-TRAINING-HUB-main*.zip" -File -ErrorAction SilentlyContinue)) {
    return $PSScriptRoot
  }

  # Otherwise search removable drives for AI-TRAINING-HUB-INSTALLER
  $usb = Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DriveType -eq 2 } | Select-Object -ExpandProperty DeviceID
  foreach ($d in $usb) {
    $cand = Join-Path ($d + "\") "AI-TRAINING-HUB-INSTALLER"
    if (Test-Path -LiteralPath $cand) { return $cand }
  }

  throw "Could not find installer root. Run this script from the USB folder AI-TRAINING-HUB-INSTALLER."
}

function Ensure-CopiedOrExtracted {
  param(
    [string]$Root,
    [string]$FolderNameOrPattern,
    [string]$ZipPattern,
    [string]$DestPath
  )

  New-Item -ItemType Directory -Force $DestPath | Out-Null

  $srcFolder = Join-Path $Root $FolderNameOrPattern
  if (Test-Path -LiteralPath $srcFolder) {
    Say "Copying folder -> $DestPath"
    robocopy $srcFolder $DestPath /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    Ok "OK: Copied $FolderNameOrPattern"
    return
  }

  $zip = Get-ChildItem -Path $Root -File -Filter $ZipPattern -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1

  if (-not $zip) { throw "Missing '$FolderNameOrPattern' AND missing zip '$ZipPattern' in $Root" }

  Say "Extracting $($zip.Name) -> $DestPath"
  Expand-Archive -Force -LiteralPath $zip.FullName -DestinationPath $DestPath
  Ok "OK: Extracted $($zip.Name)"
}

$src = Find-InstallerRoot
Say "Installer root: $src"

New-Item -ItemType Directory -Force $DestRoot | Out-Null

$destHub  = Join-Path $DestRoot "AI-TRAINING-HUB"
$destCITL = Join-Path $DestRoot "CITL-Desktop-LLM-EZ-Install-Kits"

# 1) Hub
Ensure-CopiedOrExtracted -Root $src `
  -FolderNameOrPattern "AI-TRAINING-HUB-main" `
  -ZipPattern "AI-TRAINING-HUB-main*.zip" `
  -DestPath $destHub

# 2) CITL Kit (folder name varies; zip name varies)
# If folder exists, copy it; else extract most recent matching zip
$citlFolderCandidate = Get-ChildItem -Path $src -Directory -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like "CITL*Desktop*LLM*Install*Kits*" } |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1

if ($citlFolderCandidate) {
  Ensure-CopiedOrExtracted -Root $src `
    -FolderNameOrPattern $citlFolderCandidate.Name `
    -ZipPattern "CITL*Desktop*LLM*Install*Kits*.zip" `
    -DestPath $destCITL
} else {
  Ensure-CopiedOrExtracted -Root $src `
    -FolderNameOrPattern "CITL - Desktop LLM EZ Install Kits" `
    -ZipPattern "CITL*Desktop*LLM*Install*Kits*.zip" `
    -DestPath $destCITL
}

# Ensure ffmpeg is in common\bin
$ff1 = Join-Path $destCITL "common\bin\ffmpeg.exe"
$ff2 = Join-Path $destCITL "factbook-assistant\bin\ffmpeg.exe"
if (!(Test-Path -LiteralPath $ff1) -and (Test-Path -LiteralPath $ff2)) {
  New-Item -ItemType Directory -Force (Split-Path $ff1 -Parent) | Out-Null
  Copy-Item -Force $ff2 $ff1
  Ok "OK: Copied ffmpeg into common\bin"
}

# Create launcher
$launcher = Join-Path $DestRoot "Launch-FactbookGUI.ps1"
@"
param([switch]`$Portable)

`$ErrorActionPreference = 'Stop'
`$Repo = `"$destCITL`"
Set-Location `$Repo

if (`$Portable) { `$env:CITL_PORTABLE = '1' }

`$ff = Join-Path `$Repo 'common\bin\ffmpeg.exe'
if (Test-Path -LiteralPath `$ff) { `$env:PATH = (Split-Path `$ff -Parent) + ';' + `$env:PATH }

# Start Ollama if needed
try { Invoke-RestMethod 'http://localhost:11434/api/tags' -TimeoutSec 2 | Out-Null } catch {
  `$oll = Get-Command ollama -ErrorAction SilentlyContinue
  if (`$oll) { Start-Process -WindowStyle Hidden -FilePath `$oll.Source -ArgumentList 'serve'; Start-Sleep 2 }
}

`$py = Join-Path `$Repo '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath `$py)) { throw "Missing venv python: `$py" }

& `$py '.\factbook_assistant_gui.py'
"@ | Set-Content -Encoding UTF8 -LiteralPath $launcher

Ok "DONE."
Ok "Launcher: $launcher"
