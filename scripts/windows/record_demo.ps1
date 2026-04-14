#Requires -Version 5.1
<#
  CITL Demo Recorder  --  headless FFmpeg screen-capture script
  License: FFmpeg is LGPL 2.1  (https://ffmpeg.org/legal.html)
  Captures a specific CITL app window by title -- not the full desktop.

  Usage examples:
    .\record_demo.ps1 -App factbook
    .\record_demo.ps1 -WindowTitle "CITL Desktop LLM Assistant" -Duration 120
    .\record_demo.ps1 -App llmops -Format webm -FPS 24 -OutputDir C:\demos
    .\record_demo.ps1 -App appsync -Audio -AudioDevice "Microphone (Realtek)"
    .\record_demo.ps1 -ListApps
#>
param(
    # Shortcut for well-known CITL apps (factbook | llmops | appsync | toolkit)
    [string]$App          = "",
    # Exact or partial window title (used if -App not given or app not found)
    [string]$WindowTitle  = "",
    # Seconds to record; 0 = record until Ctrl+C
    [int]   $Duration     = 0,
    # Output format: mp4 | webm | mkv | avi | mov | gif
    [string]$Format       = "mp4",
    # Frames per second
    [int]   $FPS          = 30,
    # Output directory (default: <repo>\recordings\)
    [string]$OutputDir    = "",
    # Include audio via DirectShow
    [switch]$Audio,
    # DirectShow audio device name (auto-detected if omitted)
    [string]$AudioDevice  = "",
    # CRF quality value (lower = better; 18=high 23=medium 28=low)
    [int]   $Quality      = 21,
    # Path to ffmpeg.exe (auto-detected if omitted)
    [string]$FFmpegPath   = "",
    # List known CITL apps and exit
    [switch]$ListApps
)
$ErrorActionPreference = "Continue"

function Write-Step { param($m) Write-Host "[....] $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

# Known CITL app window titles
$CITL_APPS = @{
    "factbook" = "CITL Desktop LLM Assistant"
    "llmops"   = "CITL LLMOps Presentation Suite"
    "appsync"  = "CITL App Sync Utility"
    "toolkit"  = "CITL"
}

if ($ListApps) {
    Write-Host ""
    Write-Host "Known CITL app shortcuts for -App:" -ForegroundColor Cyan
    foreach ($k in $CITL_APPS.Keys) {
        Write-Host ("  {0,-12} -> window title contains: {1}" -f $k, $CITL_APPS[$k])
    }
    Write-Host ""
    exit 0
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  CITL Demo Recorder  --  FFmpeg / LGPL 2.1" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ---- Resolve repo root -------------------------------------------------------
$ScriptDir = $PSScriptRoot
$Repo = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

# ---- Resolve FFmpeg ---------------------------------------------------------
Write-Step "Locating FFmpeg..."
if ([string]::IsNullOrWhiteSpace($FFmpegPath)) {
    $FFmpegPath = (Get-Command ffmpeg -ErrorAction SilentlyContinue)?.Source
    if (-not $FFmpegPath) {
        # Check repo bin/
        foreach ($p in @(
            (Join-Path $Repo "bin\ffmpeg.exe"),
            (Join-Path $Repo "bin\windows\ffmpeg.exe"),
            "C:\ffmpeg\bin\ffmpeg.exe"
        )) {
            if (Test-Path $p -ErrorAction SilentlyContinue) { $FFmpegPath = $p; break }
        }
    }
}
if (-not $FFmpegPath -or !(Test-Path $FFmpegPath -ErrorAction SilentlyContinue)) {
    Write-Fail "FFmpeg not found."
    Write-Host "  Install: winget install Gyan.FFmpeg" -ForegroundColor Yellow
    Write-Host "  Or pass: -FFmpegPath C:\path\to\ffmpeg.exe" -ForegroundColor Yellow
    exit 1
}
Write-OK "FFmpeg : $FFmpegPath"

# ---- Resolve window title ---------------------------------------------------
$TargetTitle = $WindowTitle
if (-not [string]::IsNullOrWhiteSpace($App)) {
    $known = $CITL_APPS[$App.ToLower()]
    if ($known) { $TargetTitle = $known }
    else {
        Write-Warn "Unknown app '$App'. Use -ListApps to see options."
        if ([string]::IsNullOrWhiteSpace($TargetTitle)) { exit 1 }
    }
}
if ([string]::IsNullOrWhiteSpace($TargetTitle)) {
    Write-Fail "Specify -App <name> or -WindowTitle <title>."
    exit 1
}
Write-OK "Target : '$TargetTitle'"

# ---- Resolve output ---------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $Repo "recordings"
}
if (!(Test-Path $OutputDir)) { New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null }

$ext = switch ($Format.ToLower()) {
    "mp4"  { ".mp4" }  "webm" { ".webm" }  "mkv"  { ".mkv" }
    "avi"  { ".avi" }  "mov"  { ".mov"  }  "gif"  { ".gif" }
    default { ".mp4" }
}
$safe   = ($TargetTitle -replace "[^\w\s-]","").Trim() -replace "\s+","_"
$safe   = $safe.Substring(0, [Math]::Min($safe.Length, 40))
$ts     = (Get-Date).ToString("yyyyMMdd_HHmmss")
$OutFile = Join-Path $OutputDir "CITL_demo_${safe}_${ts}${ext}"
Write-OK "Output : $OutFile"
Write-OK "Format : $Format  |  FPS: $FPS  |  Quality: CRF $Quality"
Write-Host ""

# ---- Build FFmpeg args -------------------------------------------------------
$ffArgs = @("-hide_banner")

# Audio input first (DirectShow)
if ($Audio) {
    if ([string]::IsNullOrWhiteSpace($AudioDevice)) {
        # Auto-detect first audio device
        $devOut = & $FFmpegPath -hide_banner -list_devices true -f dshow -i dummy 2>&1
        $devMatch = $devOut | Select-String '"([^"]+)"' | Select-Object -First 1
        if ($devMatch) {
            $AudioDevice = $devMatch.Matches[0].Groups[1].Value
            Write-OK "Audio  : $AudioDevice (auto-detected)"
        } else {
            Write-Warn "No audio device found. Recording without audio."
            $Audio = $false
        }
    } else {
        Write-OK "Audio  : $AudioDevice"
    }
    if ($Audio) {
        $ffArgs += @("-f", "dshow", "-i", "audio=$AudioDevice")
    }
}

# Video input (gdigrab by window title)
$ffArgs += @("-f", "gdigrab", "-framerate", "$FPS", "-i", "title=$TargetTitle")

# Duration limit
if ($Duration -gt 0) {
    $ffArgs += @("-t", "$Duration")
}

# Video codec
$vcodec = switch ($Format.ToLower()) {
    "avi" { "huffyuv" }  "gif" { "gif" }  default { "libx264" }
}
$ffArgs += @("-vcodec", $vcodec)

if ($Format.ToLower() -eq "gif") {
    $ffArgs += @("-vf", "fps=10,scale=960:-1:flags=lanczos")
} elseif ($vcodec -eq "libx264") {
    $ffArgs += @("-preset", "medium", "-crf", "$Quality", "-pix_fmt", "yuv420p")
}

if ($Format.ToLower() -eq "webm") {
    $ffArgs[($ffArgs.IndexOf("libx264"))] = "libvpx-vp9"
    $ffArgs += @("-b:v", "0", "-deadline", "realtime")
}

# Audio codec
if ($Audio) {
    $acodec = switch ($Format.ToLower()) {
        "webm" { "libopus" }  "avi" { "pcm_s16le" }  "gif" { $null }  default { "aac" }
    }
    if ($acodec) { $ffArgs += @("-acodec", $acodec, "-b:a", "192k") }
    else         { $ffArgs += "-an" }
} else {
    $ffArgs += "-an"
}

$ffArgs += @("-y", $OutFile)

# ---- Launch FFmpeg -----------------------------------------------------------
Write-Host "Recording... (press Ctrl+C to stop)" -ForegroundColor Red
if ($Duration -gt 0) {
    Write-Host "Auto-stops after $Duration seconds." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "CMD: $FFmpegPath $ffArgs" -ForegroundColor DarkGray
Write-Host ""

& $FFmpegPath @ffArgs
$ec = $LASTEXITCODE

Write-Host ""
if ($ec -eq 0 -and (Test-Path $OutFile)) {
    $mb = [math]::Round((Get-Item $OutFile).Length / 1MB, 2)
    Write-OK "Saved: $OutFile  ($mb MB)"
} else {
    Write-Fail "Recording ended with exit code $ec."
}
exit $ec
