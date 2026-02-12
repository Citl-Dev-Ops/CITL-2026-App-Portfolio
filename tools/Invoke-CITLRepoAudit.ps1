param(
  [switch]$Fix,
  [switch]$Smoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Stamp { (Get-Date).ToString("yyyyMMdd_HHmmss") }
function Say($msg){ Write-Host $msg }
function TryCmd([string]$label, [scriptblock]$sb){
  try {
    $out = & $sb
    return @{ ok=$true; label=$label; out=($out | Out-String).Trim() }
  } catch {
    return @{ ok=$false; label=$label; out=$_.Exception.Message }
  }
}

$RepoRoot = (Resolve-Path ".").Path
$ResultsRoot = Join-Path $RepoRoot "results"
$RunDir = Join-Path $ResultsRoot ("audit_" + (Stamp))
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

$Report = [ordered]@{
  repo_root = $RepoRoot
  timestamp = (Get-Date).ToString("o")
  machine = [ordered]@{
    computer = $env:COMPUTERNAME
    user = $env:USERNAME
    os = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Caption -ErrorAction SilentlyContinue)
    ps_version = $PSVersionTable.PSVersion.ToString()
  }
  checks = @()
  notes = @()
}

function AddCheck($obj){ $Report.checks += $obj }

# --- Git sanity ---
AddCheck (TryCmd "git: present" { git --version })
AddCheck (TryCmd "git: repo root" { git rev-parse --show-toplevel })
AddCheck (TryCmd "git: branch" { git rev-parse --abbrev-ref HEAD })
AddCheck (TryCmd "git: commit" { git rev-parse HEAD })
AddCheck (TryCmd "git: status" { git status --porcelain })

# --- Locate Python (prefer venv) ---
$VenvPyWin = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$VenvPyNix = Join-Path $RepoRoot ".venv/bin/python"
$Py = $null

if (Test-Path $VenvPyWin) { $Py = $VenvPyWin }
elseif (Test-Path $VenvPyNix) { $Py = $VenvPyNix }
else {
  $pyCmd = (Get-Command python -ErrorAction SilentlyContinue)
  if ($pyCmd) { $Py = $pyCmd.Source }
}

if (-not $Py) {
  AddCheck @{ ok=$false; label="python: found"; out="Python not found and .venv missing." }
} else {
  AddCheck @{ ok=$true; label="python: found"; out=$Py }
  AddCheck (TryCmd "python: version" { & $Py -V })
  AddCheck (TryCmd "pip: version" { & $Py -m pip -V })
  AddCheck (TryCmd "pip: check (dependency health)" { & $Py -m pip check })
}

# --- Optional FIX: ensure results/, ensure venv exists, install requirements ---
if ($Fix) {
  AddCheck @{ ok=$true; label="fix: requested"; out="Attempting safe fixes (no reboots, no driver changes)." }

  if (-not (Test-Path $ResultsRoot)) { New-Item -ItemType Directory -Force -Path $ResultsRoot | Out-Null }

  if (-not (Test-Path $VenvPyWin) -and -not (Test-Path $VenvPyNix)) {
    $pyCmd = (Get-Command python -ErrorAction SilentlyContinue)
    if ($pyCmd) {
      AddCheck (TryCmd "fix: create .venv" { python -m venv (Join-Path $RepoRoot ".venv") })
      # recompute $Py
      if (Test-Path $VenvPyWin) { $Py = $VenvPyWin }
      elseif (Test-Path $VenvPyNix) { $Py = $VenvPyNix }
    }
  }

  if ($Py -and (Test-Path (Join-Path $RepoRoot "requirements.txt"))) {
    AddCheck (TryCmd "fix: pip upgrade" { & $Py -m pip install -U pip })
    AddCheck (TryCmd "fix: install requirements.txt" { & $Py -m pip install -r (Join-Path $RepoRoot "requirements.txt") })
    AddCheck (TryCmd "fix: pip check (after install)" { & $Py -m pip check })
  }
}

# --- Tooling checks ---
AddCheck (TryCmd "ffmpeg: present" { ffmpeg -version })
AddCheck (TryCmd "nvidia-smi: present" { nvidia-smi })
AddCheck (TryCmd "nvidia-smi: query basic" { nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv,noheader })
AddCheck (TryCmd "ollama: present" { ollama version })

# --- Ollama API (Smoke) ---
if ($Smoke) {
  AddCheck @{ ok=$true; label="smoke: requested"; out="Running non-destructive smoke tests." }
  AddCheck (TryCmd "ollama api: /api/version" { Invoke-RestMethod -TimeoutSec 3 "http://localhost:11434/api/version" | ConvertTo-Json -Compress })
  AddCheck (TryCmd "ollama api: /api/tags" { Invoke-RestMethod -TimeoutSec 5 "http://localhost:11434/api/tags" | ConvertTo-Json -Compress })
}

# --- Repo launcher inventory + syntax checks ---
$Launchers = @(
  "Run-CITL.ps1",
  "run_citl_desktop_factbook.ps1",
  "run_citl_desktop_transcribe.ps1",
  "run_citl_factbook_gui.ps1",
  "factbook_assistant_gui.py",
  "factbook_assistant_gui.py"
)

foreach ($p in $Launchers) {
  $full = Join-Path $RepoRoot $p
  if (Test-Path $full) {
    AddCheck @{ ok=$true; label="exists: $p"; out=$full }
  } else {
    AddCheck @{ ok=$false; label="exists: $p"; out="Missing: $full" }
  }
}

# Compile every python file we can find (catches syntax errors without launching GUI)
if ($Py) {
  $pyfiles = Get-ChildItem $RepoRoot -Recurse -File -Filter *.py |
             Where-Object { $_.FullName -notmatch "\\\.venv\\" -and $_.FullName -notmatch "\\results\\" } |
             Select-Object -ExpandProperty FullName

  foreach ($f in $pyfiles) {
    $rel = $f.Replace($RepoRoot, ".")
    AddCheck (TryCmd "py_compile: $rel" { & $Py -m py_compile $f })
  }

  # PyQt6 import (GUI prereq)
  AddCheck (TryCmd "python: import PyQt6" { & $Py -c "import PyQt6; print('PyQt6 OK')" })
}

# --- Write outputs ---
$JsonPath = Join-Path $RunDir "audit.json"
$TxtPath  = Join-Path $RunDir "audit.txt"

($Report | ConvertTo-Json -Depth 8) | Set-Content -Encoding UTF8 $JsonPath

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("CITL Repo Audit")
$lines.Add("Repo: $RepoRoot")
$lines.Add("Time: $($Report.timestamp)")
$lines.Add("")
foreach ($c in $Report.checks) {
  $status = if ($c.ok) { "PASS" } else { "FAIL" }
  $lines.Add(("{0} - {1}" -f $status, $c.label))
  if ($c.out) { $lines.Add("  " + ($c.out -replace "`r?`n","`n  ")) }
}
$lines | Set-Content -Encoding UTF8 $TxtPath

Say ""
Say "Audit complete:"
Say "  $TxtPath"
Say "  $JsonPath"

# Exit non-zero if any FAIL
if ($Report.checks | Where-Object { -not $_.ok }) { exit 2 }
exit 0
