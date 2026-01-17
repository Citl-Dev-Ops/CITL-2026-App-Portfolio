param(
  [string]$Url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)

$ErrorActionPreference = "Stop"

# TLS safety for older PowerShell
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$bin  = Join-Path $repo "factbook-assistant\bin"
New-Item -ItemType Directory -Force $bin | Out-Null

$zipPath = Join-Path $env:TEMP "ffmpeg-essentials.zip"
$tmp     = Join-Path $env:TEMP "ffmpeg-essentials"

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue

Write-Host "[CITL] Downloading FFmpeg..." -ForegroundColor Cyan

$iw = @{ Uri = $Url; OutFile = $zipPath }
if ($PSVersionTable.PSVersion.Major -lt 6) { $iw.UseBasicParsing = $true }
Invoke-WebRequest @iw

Write-Host "[CITL] Extracting..." -ForegroundColor Cyan
Expand-Archive -Path $zipPath -DestinationPath $tmp -Force

# Prefer the ffmpeg.exe inside a \bin\ folder
$ff = Get-ChildItem -Path $tmp -Recurse -Filter "ffmpeg.exe" |
      Where-Object { $_.FullName -match "\\bin\\ffmpeg\.exe$" } |
      Select-Object -First 1

if (-not $ff) {
  $ff = Get-ChildItem -Path $tmp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
}

if (-not $ff) { throw "ffmpeg.exe not found inside extracted archive." }

Copy-Item $ff.FullName (Join-Path $bin "ffmpeg.exe") -Force

Write-Host "[CITL] Installed ffmpeg.exe to: $bin" -ForegroundColor Green
Write-Host "[CITL] Verifying..." -ForegroundColor Cyan
& (Join-Path $bin "ffmpeg.exe") -version | Select-Object -First 2
