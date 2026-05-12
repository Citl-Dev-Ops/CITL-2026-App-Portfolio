#!/usr/bin/env python3
"""
CITL Sync Hub  v1.0
====================
Maroon RTC-themed self-contained sync dashboard.
Runs from USB or local install. Detects repos, installs, updates,
syncs PC<->USB, pushes to GitHub, pulls from device.
All PowerShell logic is embedded -- no external .ps1 files required.
"""
from __future__ import annotations
import json, os, subprocess, sys, threading, time, uuid, webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:
    sys.exit("tkinter required")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
if getattr(sys, "frozen", False):
    # Running as compiled exe: citl_sync_hub.exe lives inside
    # dist/CITL Sync Hub/  which is inside  1-CITL-SYNC/  on USB
    # Walk up to USB root (has START_CITL_WINDOWS.cmd or factbook-assistant/)
    _root = Path(sys.executable).parent
    for _ in range(5):
        if (_root / "factbook-assistant").exists() or (_root / "START_CITL_WINDOWS.cmd").exists():
            break
        _root = _root.parent
    USB_ROOT: Optional[Path] = _root
    REPO: Path = _root
else:
    USB_ROOT = None
    REPO = _HERE.parent

# ---------------------------------------------------------------------------
# Maroon RTC theme
# ---------------------------------------------------------------------------
C = {
    "bg":       "#1A0505",   # deep maroon-black
    "panel":    "#2A0808",   # dark maroon panel
    "panel2":   "#380A0A",   # slightly lighter panel
    "card":     "#300C0C",   # tile card
    "card_sel": "#5A1010",   # selected tile
    "text":     "#F5DDD0",   # warm off-white
    "muted":    "#C49080",   # muted text
    "faint":    "#7A4030",   # very faint text
    "accent":   "#CC3333",   # primary RTC red
    "gold":     "#E8A020",   # gold accent (WCC gold)
    "btn":      "#4A1010",   # button base
    "btn_hi":   "#6A1818",   # button hover
    "btn_acc":  "#8B1A1A",   # accent button
    "btn_ok":   "#1A4A1A",   # success green button
    "line":     "#5A1818",   # divider
    "good":     "#1A5C1A",   # success bg
    "warn":     "#5C3A00",   # warning bg
    "err":      "#5C0A0A",   # error bg
    "out_bg":   "#100303",   # output console bg
    "out_fg":   "#F0C8B0",   # output console text
    "out_ok":   "#60D060",   # OK lines in console
    "out_warn": "#F0C040",   # WARN lines
    "out_err":  "#FF6060",   # ERR lines
}
_F = "Segoe UI" if sys.platform == "win32" else "Ubuntu"
APP_NAME    = "CITL Sync Hub"
APP_VERSION = "v1.0"

# ---------------------------------------------------------------------------
# Repo detection
# ---------------------------------------------------------------------------
REPO_MARKER    = "factbook-assistant/citl_app_sync.py"
REPO_NAMES_RE  = ["CITL", "citl", "factbook", "Factbook",
                   "CITL LLM PRESENTATION UTILITY",
                   "CITL-UTILITIES-EASY-RUN"]
SCAN_ROOTS_WIN = [
    Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / sub
    for sub in ("Desktop", "Documents", "Downloads",
                "Desktop/CITL Apps", "Documents/CITL Apps",
                "Desktop/CITL", "Documents/CITL")
]
SCAN_ROOTS_NIX = [
    Path.home() / sub
    for sub in ("Desktop", "Documents", "Downloads", "CITL")
]
SCAN_ROOTS = SCAN_ROOTS_WIN if sys.platform == "win32" else SCAN_ROOTS_NIX

# Hard rule: always prioritize the canonical CITL workspace roots first.
PREFERRED_REPO_ROOTS_WIN = [
    Path("C:/CITL"),
    Path.home() / "CITL",
]
PREFERRED_REPO_ROOTS_NIX = [
    Path.home() / "CITL",
    Path("/CITL"),
]

APP_BUNDLES = [
    ("CITL App Sync",                 "1-CITL-SYNC",                "CITL App Sync.exe"),
    ("CITL Presentation Suite",       "2-CITL-PRESENTATION-SUITE",  "CITL LLMOps Presentation Suite.exe"),
    ("CITL Workstation Apps",         "3-CITL-WORKSTATION-APPS",    "CITL Workstation Apps.exe"),
    ("CITL Field Apps",               "4-CITL-FIELD-APPS",          "CITL Field Apps.exe"),
    ("CITL Ticketing Automation GUI", "6-CITL-WORK-TICKETING",      "CITL Ticketing Automation GUI.exe"),
]


def _canon_path_str(p: Path) -> str:
    try:
        q = p.resolve()
    except Exception:
        q = p
    return str(q).replace("\\", "/").rstrip("/").lower()


def _repo_priority(path: Path) -> int:
    preferred = PREFERRED_REPO_ROOTS_WIN if sys.platform == "win32" else PREFERRED_REPO_ROOTS_NIX
    target = _canon_path_str(path)
    for idx, root in enumerate(preferred):
        root_s = _canon_path_str(root)
        if target == root_s or target.startswith(root_s + "/"):
            return idx
    return len(preferred) + 10

def _find_repos() -> List[Dict]:
    """Scan user dirs for existing CITL repos. Returns list of info dicts."""
    found: List[Dict] = []
    seen: set = set()
    candidates: List[Path] = []
    preferred = PREFERRED_REPO_ROOTS_WIN if sys.platform == "win32" else PREFERRED_REPO_ROOTS_NIX
    for p in preferred:
        if p.exists():
            candidates.append(p)
    for r in SCAN_ROOTS:
        if r.exists():
            candidates.append(r)
            try:
                for sub in r.iterdir():
                    if sub.is_dir() and not sub.name.startswith("."):
                        candidates.append(sub)
            except PermissionError:
                pass
    # Also check every drive root
    if sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            p = Path(f"{letter}:/CITL")
            candidates.append(p)
            candidates.append(Path(f"{letter}:/"))

    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        marker = candidate / REPO_MARKER.replace("/", os.sep)
        if not marker.exists():
            continue
        try:
            mtime = marker.stat().st_mtime
            age_days = (time.time() - mtime) / 86400
        except Exception:
            age_days = 0.0
        # Check git status
        has_git = (candidate / ".git").exists()
        git_branch = ""
        if has_git:
            try:
                r2 = subprocess.run(
                    ["git", "-C", str(candidate), "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, timeout=5
                )
                git_branch = r2.stdout.strip()
            except Exception:
                pass
        # Count key files present
        key_files = ["factbook-assistant/citl_app_sync.py",
                     "factbook-assistant/citl_staff_toolkit.py",
                     "factbook-assistant/citl_av_it_ops.py",
                     "factbook-assistant/citl_workstation_apps.py",
                     "factbook-assistant/citl_field_apps.py"]
        present = sum(1 for f in key_files
                      if (candidate / f.replace("/", os.sep)).exists())
        found.append({
            "path":       candidate,
            "age_days":   age_days,
            "has_git":    has_git,
            "git_branch": git_branch,
            "files_ok":   present,
            "files_total": len(key_files),
            "stale":      age_days > 14,
        })
    found.sort(key=lambda r: (_repo_priority(r["path"]), r["age_days"], str(r["path"]).lower()))
    return found


def _find_usb_roots() -> List[Path]:
    """Find connected USB drives that look like CITL install drives."""
    found: List[Path] = []
    if sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:/")
            if not root.exists():
                continue
            # Has numbered CITL folders or factbook-assistant
            if ((root / "1-CITL-SYNC").exists() or
                    (root / "factbook-assistant" / "citl_app_sync.py").exists() or
                    (root / "START_CITL_WINDOWS.cmd").exists()):
                found.append(root)
    else:
        for media in [Path("/media") / os.environ.get("USER", "user"),
                      Path("/mnt"), Path("/run/media")]:
            if media.exists():
                try:
                    for dev in media.iterdir():
                        for sub in ([dev] + list(dev.iterdir())
                                    if dev.is_dir() else []):
                            if (sub / "1-CITL-SYNC").exists() or \
                               (sub / "START_CITL_UBUNTU.sh").exists():
                                found.append(sub)
                except Exception:
                    pass
    return found


# ---------------------------------------------------------------------------
# Instance identity
# ---------------------------------------------------------------------------
def _get_or_create_instance_id(root: Path) -> dict:
    """Read or generate a unique identity tag for this CITL installation root."""
    id_file = root / "citl_instance.json"
    if id_file.exists():
        try:
            with open(id_file, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("instance_id"):
                return data
        except Exception:
            pass

    short = uuid.uuid4().hex[:8].upper()

    # Detect install type
    install_type = "PC"
    try:
        if sys.platform == "win32":
            import ctypes
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(root.anchor))
            if drive_type == 2:   # DRIVE_REMOVABLE
                install_type = "USB"
            elif drive_type == 4: # DRIVE_REMOTE
                install_type = "NET"
    except Exception:
        pass
    if install_type == "PC" and (root / ".git").exists():
        install_type = "DEV"

    label = f"{install_type}-{root.anchor.rstrip('/').rstrip(chr(92))}-{short[:4]}"
    data = {
        "instance_id":  f"CITL-{short}",
        "type":          install_type,
        "label":         label,
        "created":       datetime.now().isoformat(timespec="seconds"),
        "path":          str(root),
    }
    try:
        with open(id_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return data


def _load_instance_id(root: Path) -> Optional[dict]:
    """Read instance ID from a path without creating one."""
    id_file = root / "citl_instance.json"
    if id_file.exists():
        try:
            with open(id_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Embedded PowerShell logic blocks
# ---------------------------------------------------------------------------
def _ps(script: str, log_fn: Optional[Callable] = None, timeout: int = 120) -> int:
    """Run embedded PS script (Windows) or bash script (Linux/Mac)."""
    if sys.platform == "win32":
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-NonInteractive", "-Command", script]
    else:
        # On Linux: script is a bash heredoc string
        cmd = ["bash", "-c", script]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", bufsize=1
        )
        if proc.stdout:
            for line in proc.stdout:
                if log_fn:
                    log_fn(line.rstrip())
        proc.wait(timeout=timeout)
        return proc.returncode
    except FileNotFoundError:
        if log_fn:
            log_fn(f"[ERROR] Shell not found: {cmd[0]}")
        return 1
    except subprocess.TimeoutExpired:
        proc.kill()
        if log_fn:
            log_fn("[TIMEOUT] Operation exceeded time limit")
        return 1


def _sh(cmd: List[str], log_fn: Optional[Callable] = None, timeout: int = 120,
        cwd: Optional[str] = None) -> int:
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 errors="replace", bufsize=1, cwd=cwd)
        if proc.stdout:
            for line in proc.stdout:
                if log_fn:
                    log_fn(line.rstrip())
        proc.wait(timeout=timeout)
        return proc.returncode
    except FileNotFoundError:
        if log_fn:
            log_fn(f"[ERROR] command not found: {cmd[0]}")
        return 1
    except subprocess.TimeoutExpired:
        proc.kill()
        if log_fn:
            log_fn("[TIMEOUT]")
        return 1


PS_SYSTEM_CHECK = r"""
Write-Host "=== SYSTEM CHECK ==="
Write-Host "OS: $([System.Environment]::OSVersion.VersionString)"
Write-Host "User: $env:USERNAME  Host: $env:COMPUTERNAME"
Write-Host ""
Write-Host "=== PYTHON ==="
$pyPaths = @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
)
$found = $false
foreach ($p in $pyPaths) {
    if (Test-Path $p) {
        $v = & $p --version 2>&1
        Write-Host "  [OK] $v  at $p"
        $found = $true; break
    }
}
if (!$found) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
        $v = & $cmd.Source --version 2>&1
        Write-Host "  [OK] $v  at $($cmd.Source)"
        $found = $true
    }
}
if (!$found) { Write-Host "  [WARN] Python 3 not found - will need to install" }

Write-Host ""
Write-Host "=== GIT ==="
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) { $gv = & git --version 2>&1; Write-Host "  [OK] $gv" }
else       { Write-Host "  [WARN] git not found" }

Write-Host ""
Write-Host "=== DISK SPACE ==="
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | ForEach-Object {
    $free = [math]::Round($_.Free/1GB,1)
    $used = [math]::Round($_.Used/1GB,1)
    Write-Host "  $($_.Root)  Free: ${free} GB  Used: ${used} GB"
}

Write-Host ""
Write-Host "=== VENV ==="
$venvPaths = @()
"""

PS_VENV_CHECK = r"""
$venvCandidates = @(
    "$env:USERPROFILE\Desktop\CITL\.venv\Scripts\python.exe",
    "$env:USERPROFILE\Documents\CITL\.venv\Scripts\python.exe",
    "$env:USERPROFILE\Desktop\CITL Apps\CITL App Sync\_internal\python.exe"
)
$venvFound = $false
foreach ($v in $venvCandidates) {
    if (Test-Path $v) { Write-Host "  [OK] venv at $v"; $venvFound = $true }
}
if (!$venvFound) { Write-Host "  [INFO] No venv found - will be created on first sync" }
"""

def _ps_install_from_usb(usb_root: str, dest: str) -> str:
    return fr"""
$USB   = '{usb_root}'
$DEST  = '{dest}'
$MARKER = 'factbook-assistant\citl_app_sync.py'

Write-Host "=== CITL FIRST-TIME INSTALL ==="
Write-Host "Source : $USB"
Write-Host "Dest   : $DEST"
Write-Host ""

# Create destination
New-Item -ItemType Directory -Path $DEST -Force | Out-Null

# Use robocopy to mirror source files (exclude large dirs)
$exclude = @('.git','__pycache__','.venv','models','ollama','build','dist')
$roboArgs = @($USB, $DEST, '/MIR', '/XO', '/R:2', '/W:1', '/MT:4',
              '/NFL', '/NDL', '/NJH', '/NJS')
foreach ($ex in $exclude) {{ $roboArgs += "/XD"; $roboArgs += $ex }}
Write-Host "Copying files..."
robocopy @roboArgs | Out-Null
$rc = $LASTEXITCODE
if ($rc -le 7) {{ Write-Host "[OK] Files copied (robocopy exit $rc)" }}
else           {{ Write-Host "[WARN] robocopy exit $rc - some files may have failed" }}

# Bootstrap venv
$VenvPy = "$DEST\.venv\Scripts\python.exe"
if (!(Test-Path $VenvPy)) {{
    Write-Host ""
    Write-Host "Creating Python virtual environment..."
    $py = $null
    foreach ($p in @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )) {{ if (Test-Path $p) {{ $py = $p; break }} }}
    if (!$py) {{ $py = (Get-Command python -ErrorAction SilentlyContinue)?.Source }}
    if ($py -and $py -notlike '*WindowsApps*') {{
        & $py -m venv "$DEST\.venv"
        & "$DEST\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet 2>&1 | Out-Null
        $req = "$DEST\requirements-windows.txt"
        if (!(Test-Path $req)) {{ $req = "$DEST\requirements.txt" }}
        if (Test-Path $req) {{
            Write-Host "Installing requirements..."
            & "$DEST\.venv\Scripts\python.exe" -m pip install -r $req --quiet
        }}
        Write-Host "[OK] venv ready at $VenvPy"
    }} else {{
        Write-Host "[WARN] Python not found - install from python.org then re-run"
    }}
}}

# Create desktop shortcuts
Write-Host ""
Write-Host "Creating desktop shortcuts..."
$Desktop = [Environment]::GetFolderPath('Desktop')
$wsh = New-Object -ComObject WScript.Shell
$apps = @(
    @{{Name='CITL App Sync';          Exe='dist\CITL App Sync\CITL App Sync.exe'}},
    @{{Name='CITL Presentation Suite'; Exe='dist\CITL LLMOps Presentation Suite\CITL LLMOps Presentation Suite.exe'}},
    @{{Name='CITL Workstation Apps';  Exe='dist\CITL Workstation Apps\CITL Workstation Apps.exe'}},
    @{{Name='CITL Field Apps';         Exe='dist\CITL Field Apps\CITL Field Apps.exe'}},
    @{{Name='CITL Ticketing Automation GUI'; Exe='powerflow_builder\dist\CITL Ticketing Automation GUI\CITL Ticketing Automation GUI.exe'}},
    @{{Name='CITL Sync Hub';           Exe='dist\CITL Sync Hub\CITL Sync Hub.exe'}}
)
foreach ($app in $apps) {{
    $exePath = Join-Path $DEST $app.Exe
    if (Test-Path $exePath) {{
        $lnk = $wsh.CreateShortcut("$Desktop\$($app.Name).lnk")
        $lnk.TargetPath = $exePath
        $lnk.WorkingDirectory = Split-Path $exePath
        $lnk.Save()
        Write-Host "  [OK] Shortcut: $($app.Name)"
    }} else {{
        Write-Host "  [--] $($app.Name) exe not built yet"
    }}
}}

Write-Host ""
Write-Host "[DONE] Install complete: $DEST"
"""


def _ps_sync_pc_to_usb(source: str, usb_root: str) -> str:
    return fr"""
$SRC = '{source}'
$USB = '{usb_root}'
Write-Host "=== PC TO USB SYNC ==="
Write-Host "Source : $SRC"
Write-Host "Target : $USB"
Write-Host ""

# Get file counts before sync
$beforeFiles = (Get-ChildItem $USB -Recurse -File -EA SilentlyContinue | Measure-Object).Count
$beforeSize = (Get-ChildItem $USB -Recurse -File -EA SilentlyContinue | Measure-Object -Property Length -Sum).Sum
Write-Host "USB before: $beforeFiles files, $([math]::Round($beforeSize/1MB,1)) MB"

# Sync source files (key files only - not models/dist)
$exclude = @('.git','__pycache__','.venv','models','ollama','dist','build','*.pyc','*.log','*.tmp')
$roboArgs = @($SRC, $USB, '/XO', '/R:2', '/W:1', '/MT:4')
foreach ($ex in $exclude) {{ $roboArgs += "/XD"; $roboArgs += $ex }}
Write-Host ""
Write-Host "Syncing source files..."
Write-Host "Command: robocopy $($roboArgs -join ' ')"
robocopy @roboArgs
$rc = $LASTEXITCODE
if ($rc -le 7) {{ Write-Host "[OK] Source files synced (exit $rc)" }}
else           {{ Write-Host "[WARN] robocopy exit $rc - some files may not have copied" }}

# Sync dist exe bundles to numbered folders
Write-Host ""
Write-Host "Syncing EXE bundles..."
$bundles = @(
    @{{Dist='CITL App Sync';                 Usb='1-CITL-SYNC';                  Exe='CITL App Sync.exe'}},
    @{{Dist='CITL LLMOps Presentation Suite';Usb='2-CITL-PRESENTATION-SUITE';    Exe='CITL LLMOps Presentation Suite.exe'}},
    @{{Dist='CITL Workstation Apps';          Usb='3-CITL-WORKSTATION-APPS';      Exe='CITL Workstation Apps.exe'}},
    @{{Dist='CITL Field Apps';                Usb='4-CITL-FIELD-APPS';            Exe='CITL Field Apps.exe'}},
    @{{Dist='CITL Ticketing Automation GUI';  Usb='6-CITL-WORK-TICKETING';        Exe='CITL Ticketing Automation GUI.exe'; Root='powerflow_builder\dist'}},
    @{{Dist='CITL Sync Hub';                  Usb='1-CITL-SYNC';                  Exe='CITL Sync Hub.exe'}}
)
foreach ($b in $bundles) {{
    if ($b.Root) {{
        $srcDir = "$SRC\$($b.Root)\$($b.Dist)"
    }} else {{
        $srcDir = "$SRC\dist\$($b.Dist)"
    }}
    $dstDir = "$USB\$($b.Usb)"
    $exeFile = "$srcDir\$($b.Exe)"
    if (!(Test-Path $exeFile)) {{
        Write-Host "  [--] $($b.Dist): EXE not built, skipping"
        continue
    }}
    Write-Host "  [SYNC] $($b.Dist) -> $($b.Usb)"
    if (!(Test-Path $dstDir)) {{ New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }}
    robocopy $srcDir $dstDir /MIR /XO /R:1 /W:1 /MT:4
    $bundleSize = [math]::Round((Get-ChildItem $dstDir -Recurse -EA SilentlyContinue | Measure-Object -Property Length -Sum).Sum/1MB,1)
    Write-Host "  [OK] $($b.Usb) ($bundleSize MB)"
}}

# Get final counts
$afterFiles = (Get-ChildItem $USB -Recurse -File -EA SilentlyContinue | Measure-Object).Count
$afterSize = (Get-ChildItem $USB -Recurse -File -EA SilentlyContinue | Measure-Object -Property Length -Sum).Sum
$addedFiles = $afterFiles - $beforeFiles
$addedSize = $afterSize - $beforeSize

Write-Host ""
Write-Host "[DONE] PC to USB sync complete"
Write-Host "Files added: $addedFiles"
Write-Host "Size added: $([math]::Round($addedSize/1MB,1)) MB"
Write-Host "USB total: $afterFiles files, $([math]::Round($afterSize/1MB,1)) MB"
"""


def _ps_sync_usb_to_pc(usb_root: str, dest: str) -> str:
    return fr"""
$USB  = '{usb_root}'
$DEST = '{dest}'
Write-Host "=== USB TO PC UPDATE ==="
Write-Host "Source : $USB"
Write-Host "Target : $DEST"
Write-Host ""

if (!(Test-Path $DEST)) {{
    Write-Host "[INFO] Destination not found - creating..."
    New-Item -ItemType Directory -Path $DEST -Force | Out-Null
}}

# Get file counts before sync
$beforeFiles = (Get-ChildItem $DEST -Recurse -File -EA SilentlyContinue | Measure-Object).Count
$beforeSize = (Get-ChildItem $DEST -Recurse -File -EA SilentlyContinue | Measure-Object -Property Length -Sum).Sum
Write-Host "PC before: $beforeFiles files, $([math]::Round($beforeSize/1MB,1)) MB"

$exclude = @('.git','__pycache__','.venv','models','ollama','dist','build','*.pyc','*.log','*.tmp')
$roboArgs = @($USB, $DEST, '/XO', '/R:2', '/W:1', '/MT:4')
foreach ($ex in $exclude) {{ $roboArgs += "/XD"; $roboArgs += $ex }}
Write-Host ""
Write-Host "Syncing source files..."
Write-Host "Command: robocopy $($roboArgs -join ' ')"
robocopy @roboArgs
$rc = $LASTEXITCODE
if ($rc -le 7) {{ Write-Host "[OK] Files updated (exit $rc)" }}
else           {{ Write-Host "[WARN] robocopy exit $rc - some files may not have updated" }}

# Copy exe bundles from numbered USB folders to local dist/
Write-Host ""
Write-Host "Syncing EXE bundles to local dist/..."
$bundles = @(
    @{{Usb='1-CITL-SYNC';                   Dist='CITL App Sync'}},
    @{{Usb='2-CITL-PRESENTATION-SUITE';     Dist='CITL LLMOps Presentation Suite'}},
    @{{Usb='3-CITL-WORKSTATION-APPS';       Dist='CITL Workstation Apps'}},
    @{{Usb='4-CITL-FIELD-APPS';             Dist='CITL Field Apps'}},
    @{{Usb='6-CITL-WORK-TICKETING';         Dist='CITL Ticketing Automation GUI'; Root='powerflow_builder\dist'}}
)
foreach ($b in $bundles) {{
    $usbDir  = "$USB\$($b.Usb)"
    if ($b.Root) {{
        $distDir = "$DEST\$($b.Root)\$($b.Dist)"
    }} else {{
        $distDir = "$DEST\dist\$($b.Dist)"
    }}
    if (!(Test-Path $usbDir)) {{ Write-Host "  [--] USB folder missing: $($b.Usb)"; continue }}
    Write-Host "  [SYNC] $($b.Usb) -> $($b.Dist)"
    if (!(Test-Path $distDir)) {{ New-Item -ItemType Directory -Path $distDir -Force | Out-Null }}
    robocopy $usbDir $distDir /MIR /XO /R:1 /W:1 /MT:4
    Write-Host "  [OK] $($b.Dist)"
}}

# Get final counts
$afterFiles = (Get-ChildItem $DEST -Recurse -File -EA SilentlyContinue | Measure-Object).Count
$afterSize = (Get-ChildItem $DEST -Recurse -File -EA SilentlyContinue | Measure-Object -Property Length -Sum).Sum
$addedFiles = $afterFiles - $beforeFiles
$addedSize = $afterSize - $beforeSize

Write-Host ""
Write-Host "[DONE] USB to PC update complete"
Write-Host "Files added/updated: $addedFiles"
Write-Host "Size added: $([math]::Round($addedSize/1MB,1)) MB"
Write-Host "PC total: $afterFiles files, $([math]::Round($afterSize/1MB,1)) MB"
"""


def _ps_git_push(repo_path: str, message: str, remote: str = "origin",
                  branch: str = "main") -> str:
    safe_msg = message.replace("'", "`'")
    return fr"""
Set-Location '{repo_path}'
Write-Host "=== GIT STATUS ==="
git status --short
Write-Host ""
Write-Host "=== STAGING ALL CHANGES ==="
git add -A
Write-Host ""
Write-Host "=== COMMIT ==="
git commit -m '{safe_msg}' 2>&1
$commitExit = $LASTEXITCODE
if ($commitExit -eq 0)  {{ Write-Host "[OK] Committed" }}
elseif ($commitExit -eq 1) {{ Write-Host "[INFO] Nothing to commit or commit failed - see above" }}
Write-Host ""
Write-Host "=== PUSH to {remote}/{branch} ==="
git push {remote} {branch} 2>&1
$pushExit = $LASTEXITCODE
if ($pushExit -eq 0) {{ Write-Host "[OK] Push successful" }}
else                  {{ Write-Host "[ERROR] Push failed (exit $pushExit) - check credentials and remote" }}
Write-Host ""
Write-Host "[DONE] git push complete (commit exit=$commitExit, push exit=$pushExit)"
"""


def _ps_git_pull(repo_path: str) -> str:
    return fr"""
Set-Location '{repo_path}'
Write-Host "=== GIT PULL ==="
git fetch --all 2>&1
git status
Write-Host ""
git pull 2>&1
$rc = $LASTEXITCODE
if ($rc -eq 0) {{ Write-Host "[OK] Pull successful" }}
else            {{ Write-Host "[ERROR] Pull failed (exit $rc)" }}
Write-Host ""
Write-Host "=== CURRENT LOG (last 5) ==="
git log --oneline -5 2>&1
"""


def _ps_make_shortcuts(dest: str) -> str:
    return fr"""
$DEST    = '{dest}'
$Desktop = [Environment]::GetFolderPath('Desktop')
$wsh     = New-Object -ComObject WScript.Shell
Write-Host "=== CREATING DESKTOP SHORTCUTS ==="
Write-Host "Repo   : $DEST"
Write-Host "Desktop: $Desktop"
Write-Host ""
$apps = @(
    @{{Name='CITL App Sync';           Exe='dist\CITL App Sync\CITL App Sync.exe'}},
    @{{Name='CITL Presentation Suite'; Exe='dist\CITL LLMOps Presentation Suite\CITL LLMOps Presentation Suite.exe'}},
    @{{Name='CITL Workstation Apps';   Exe='dist\CITL Workstation Apps\CITL Workstation Apps.exe'}},
    @{{Name='CITL Field Apps';          Exe='dist\CITL Field Apps\CITL Field Apps.exe'}},
    @{{Name='CITL Sync Hub';            Exe='dist\CITL Sync Hub\CITL Sync Hub.exe'}},
    @{{Name='CITL Staff Toolkit';       Exe='dist\CITL Work and Preparedness Launcher\CITL Work and Preparedness Launcher.exe'}}
)
foreach ($app in $apps) {{
    $exePath = Join-Path $DEST $app.Exe
    if (Test-Path $exePath) {{
        $lnk = $wsh.CreateShortcut("$Desktop\$($app.Name).lnk")
        $lnk.TargetPath = $exePath
        $lnk.WorkingDirectory = Split-Path $exePath
        $lnk.Description = "CITL - $($app.Name)"
        $lnk.Save()
        Write-Host "  [OK] $($app.Name)"
    }} else {{
        Write-Host "  [--] $($app.Name): exe not found at $exePath"
    }}
}}
Write-Host ""
Write-Host "[DONE] Shortcuts created."
"""


# ---------------------------------------------------------------------------
# Operation tile definitions
# ---------------------------------------------------------------------------
# Linux / bash equivalents — same operations, bash syntax
# ---------------------------------------------------------------------------
BASH_SYSTEM_CHECK = r"""
echo "=== SYSTEM CHECK ==="
echo "OS: $(uname -a)"
echo "User: $(whoami)  Host: $(hostname)"
echo ""
echo "=== PYTHON ==="
for py in python3 python; do
    if command -v $py &>/dev/null; then
        echo "  [OK] $($py --version 2>&1)  at $(which $py)"
        break
    fi
done
echo ""
echo "=== GIT ==="
if command -v git &>/dev/null; then
    echo "  [OK] $(git --version)"
else
    echo "  [WARN] git not found — install: sudo apt install git"
fi
echo ""
echo "=== DISK SPACE ==="
df -h --output=source,size,used,avail,target 2>/dev/null | grep -v tmpfs | head -8
echo ""
echo "=== VENV ==="
for venv in \
    "$HOME/Desktop/CITL/.venv/bin/python" \
    "$HOME/Documents/CITL/.venv/bin/python" \
    "$HOME/CITL/.venv/bin/python"; do
    [ -x "$venv" ] && echo "  [OK] venv at $venv" && break
done
echo ""
echo "=== RSYNC ==="
if command -v rsync &>/dev/null; then
    echo "  [OK] $(rsync --version | head -1)"
else
    echo "  [WARN] rsync not found — install: sudo apt install rsync"
fi
"""

BASH_VENV_CHECK = r"""
echo "=== VENV CHECK ==="
for venv in \
    "$HOME/Desktop/CITL/.venv/bin/python" \
    "$HOME/Documents/CITL/.venv/bin/python" \
    "$HOME/CITL/.venv/bin/python"; do
    if [ -x "$venv" ]; then
        echo "  [OK] $($venv --version 2>&1)  at $venv"
    fi
done
"""


def _bash_install_from_usb(usb_root: str, dest: str) -> str:
    ex = "--exclude=.git/ --exclude=__pycache__/ --exclude=.venv/ --exclude=models/ --exclude=ollama/ --exclude=blobs/ --exclude='*.gguf' --exclude='*.bin' --exclude=dist/ --exclude=build/ --max-size=500m"
    return f"""
USB='{usb_root}'
DEST='{dest}'
echo "=== CITL FIRST-TIME INSTALL ==="
echo "Source : $USB"
echo "Dest   : $DEST"
mkdir -p "$DEST"
echo "Copying files (rsync)..."
rsync -av {ex} "$USB/" "$DEST/" 2>&1 | tail -5
echo "[OK] Files copied"
# Bootstrap venv
VENV="$DEST/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating venv..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip --quiet
    for req in "$DEST/requirements-linux.txt" "$DEST/requirements.txt"; do
        [ -f "$req" ] && "$VENV/bin/pip" install -r "$req" --quiet && break
    done
    echo "[OK] venv ready"
fi
# Write instance ID
INST="$DEST/citl_instance.json"
if [ ! -f "$INST" ]; then
    ID="CITL-$(cat /proc/sys/kernel/random/uuid 2>/dev/null | tr -d '-' | head -c 8 | tr a-z A-Z)"
    printf '{{\\n  "instance_id": "%s",\\n  "type": "PC",\\n  "created": "%s",\\n  "path": "%s"\\n}}\\n' \
        "$ID" "$(date -Iseconds)" "$DEST" > "$INST"
    echo "[OK] Instance ID: $ID"
fi
# Create .desktop shortcuts
DESKTOP="$HOME/Desktop"
mkdir -p "$DESKTOP"
APPS=(
    "CITL App Sync|$DEST/factbook-assistant/citl_app_sync.py"
    "CITL Sync Hub|$DEST/factbook-assistant/citl_sync_hub.py"
    "CITL Staff Toolkit|$DEST/factbook-assistant/citl_staff_toolkit.py"
    "CITL LLMOps Suite|$DEST/factbook-assistant/citl_llmops_suite.py"
)
for entry in "${{APPS[@]}}"; do
    name="${{entry%%|*}}"
    script="${{entry##*|}}"
    shortcut="$DESKTOP/$name.desktop"
    if [ -f "$script" ]; then
        cat > "$shortcut" <<DESKTOP_EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$name
Exec=$VENV/bin/python $script
Terminal=false
Categories=Utility;Education;
DESKTOP_EOF
        chmod +x "$shortcut"
        echo "  [OK] Shortcut: $name"
    fi
done
echo ""
echo "[DONE] Install complete: $DEST"
"""


def _bash_sync_pc_to_usb(source: str, usb_root: str) -> str:
    ex = "--exclude=.git/ --exclude=__pycache__/ --exclude=.venv/ --exclude=models/ --exclude=ollama/ --exclude=blobs/ --exclude='*.gguf' --exclude='*.bin' --exclude=dist/ --exclude=build/ --max-size=500m"
    return f"""
SRC='{source}'
USB='{usb_root}'
echo "=== PC TO USB SYNC ==="
echo "Source : $SRC"
echo "Target : $USB"
echo ""
echo "Syncing source files..."
rsync -av --update {ex} "$SRC/" "$USB/" 2>&1 | tail -8
echo "[OK] Source files synced"
echo ""
echo "Note: EXE bundles are Windows-only — use BUILD_ALL_CITL_EXES_WINDOWS.cmd on Windows"
echo "[DONE] PC to USB sync complete."
"""


def _bash_sync_usb_to_pc(usb_root: str, dest: str) -> str:
    ex = "--exclude=.git/ --exclude=__pycache__/ --exclude=.venv/ --exclude=models/ --exclude=ollama/ --exclude=blobs/ --exclude='*.gguf' --exclude='*.bin' --exclude=dist/ --exclude=build/ --max-size=500m"
    return f"""
USB='{usb_root}'
DEST='{dest}'
echo "=== USB TO PC UPDATE ==="
echo "Source : $USB"
echo "Target : $DEST"
mkdir -p "$DEST"
echo "Syncing files..."
rsync -av --update {ex} "$USB/" "$DEST/" 2>&1 | tail -8
echo "[OK] Files updated"
echo "[DONE] USB to PC update complete."
"""


def _bash_git_push(repo_path: str, message: str,
                   remote: str = "origin", branch: str = "main") -> str:
    safe_msg = message.replace("'", "\\'")
    return f"""
cd '{repo_path}'
echo "=== GIT STATUS ==="
git status --short
echo ""
echo "=== STAGING ==="
git add -A
echo ""
echo "=== COMMIT ==="
git commit -m '{safe_msg}' 2>&1
COMMIT_EXIT=$?
echo ""
echo "=== PUSH to {remote}/{branch} ==="
git push {remote} {branch} 2>&1
PUSH_EXIT=$?
if [ $PUSH_EXIT -eq 0 ]; then echo "[OK] Push successful"; else echo "[ERROR] Push failed (exit $PUSH_EXIT)"; fi
echo ""
echo "[DONE] git push complete (commit=$COMMIT_EXIT, push=$PUSH_EXIT)"
"""


def _bash_git_pull(repo_path: str) -> str:
    return f"""
cd '{repo_path}'
echo "=== GIT PULL ==="
git fetch --all 2>&1
git status
echo ""
git pull 2>&1
RC=$?
if [ $RC -eq 0 ]; then echo "[OK] Pull successful"; else echo "[ERROR] Pull failed (exit $RC)"; fi
echo ""
echo "=== RECENT COMMITS ==="
git log --oneline -5 2>&1
"""


def _bash_make_shortcuts(dest: str) -> str:
    return f"""
DEST='{dest}'
DESKTOP="$HOME/Desktop"
VENV="$DEST/.venv/bin/python"
[ -x "$VENV" ] || VENV="python3"
echo "=== CREATING .desktop SHORTCUTS ==="
echo "Repo   : $DEST"
echo "Desktop: $DESKTOP"
mkdir -p "$DESKTOP"
APPS=(
    "CITL App Sync|$DEST/factbook-assistant/citl_app_sync.py"
    "CITL Sync Hub|$DEST/factbook-assistant/citl_sync_hub.py"
    "CITL Staff Toolkit|$DEST/factbook-assistant/citl_staff_toolkit.py"
    "CITL LLMOps Suite|$DEST/factbook-assistant/citl_llmops_suite.py"
    "CITL Doc Composer|$DEST/factbook-assistant/citl_doc_composer.py"
)
for entry in "${{APPS[@]}}"; do
    name="${{entry%%|*}}"
    script="${{entry##*|}}"
    shortcut="$DESKTOP/$name.desktop"
    if [ -f "$script" ]; then
        cat > "$shortcut" <<DESKTOP_EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$name
Comment=CITL - RTC/Whatcom Community College
Exec=$VENV $script
Terminal=false
Categories=Utility;Education;
StartupNotify=true
DESKTOP_EOF
        chmod +x "$shortcut"
        echo "  [OK] $name"
    else
        echo "  [--] $name: script not found at $script"
    fi
done
echo ""
echo "[DONE] Shortcuts created at $DESKTOP"
"""


def _bash_diagnostic_sync(src: str, dst: str, dry_run: bool = True) -> str:
    n_flag = "--dry-run" if dry_run else ""
    mode_label = "DRY-RUN" if dry_run else "LIVE SYNC"
    return f"""
SRC='{src}'
DST='{dst}'
echo "=== SYNC DIAGNOSTICS  [{mode_label}] ==="
echo "Source : $SRC"
echo "Target : $DST"
echo ""
# Instance IDs
SRC_ID=$(python3 -c "import json; d=json.load(open('$SRC/citl_instance.json')); print(d.get('instance_id','?'))" 2>/dev/null || echo "(none)")
DST_ID=$(python3 -c "import json; d=json.load(open('$DST/citl_instance.json')); print(d.get('instance_id','?'))" 2>/dev/null || echo "(none)")
echo "Source Instance : $SRC_ID"
echo "Target Instance : $DST_ID"
echo ""
echo "--- Exclusions ---"
echo "  *.gguf  *.bin  *.blob  ollama/  blobs/  .venv/  dist/  build/  max 500MB"
echo ""
echo "--- File Delta ---"
rsync -av --update {n_flag} \\
    --exclude='.git/' --exclude='__pycache__/' --exclude='.venv/' \\
    --exclude='models/' --exclude='ollama/' --exclude='blobs/' \\
    --exclude='*.gguf' --exclude='*.bin' --exclude='*.blob' \\
    --exclude='dist/' --exclude='build/' --max-size=500m \\
    "$SRC/" "$DST/" 2>&1
RC=$?
echo ""
echo "--- Result ---"
if [ $RC -eq 0 ]; then echo "[OK] rsync exit 0 - success"; else echo "[ERROR] rsync exit $RC"; fi
[ "{dry_run}" = "True" ] && echo "" && echo "[NOTE] DRY-RUN only - no files changed."
"""


def _bash_clone_usb(src_usb: str, dst_usb: str, mode: str) -> str:
    folder_map = {
        "all":          "1-CITL-SYNC 2-CITL-PRESENTATION-SUITE 3-CITL-WORKSTATION-APPS 4-CITL-FIELD-APPS 6-CITL-WORK-TICKETING",
        "sync":         "1-CITL-SYNC",
        "presentation": "2-CITL-PRESENTATION-SUITE",
        "workstation":  "3-CITL-WORKSTATION-APPS",
        "field":        "4-CITL-FIELD-APPS",
        "ticketing":    "6-CITL-WORK-TICKETING",
    }
    folders = folder_map.get(mode, folder_map["all"])
    return f"""
SRC='{src_usb}'
DST='{dst_usb}'
FOLDERS=({folders})
echo "=== USB CLONE [{mode}] ==="
echo "Source : $SRC"
echo "Target : $DST"
echo ""
[ -d "$SRC" ] || {{ echo "[ERROR] Source not found: $SRC"; exit 1; }}
[ -d "$DST" ] || {{ echo "[ERROR] Target not found: $DST"; exit 1; }}
TOTAL=0; FAILED=0
for folder in "${{FOLDERS[@]}}"; do
    SRC_DIR="$SRC/$folder"
    DST_DIR="$DST/$folder"
    [ -d "$SRC_DIR" ] || {{ echo "  [--] $folder not on source - skipping"; continue; }}
    mkdir -p "$DST_DIR"
    echo "Cloning $folder ..."
    rsync -av --update \\
        --exclude='*.gguf' --exclude='*.bin' --exclude='*.blob' \\
        --exclude='ollama/' --exclude='blobs/' --exclude='.git/' \\
        --exclude='__pycache__/' --max-size=500m \\
        "$SRC_DIR/" "$DST_DIR/" 2>&1 | tail -4
    if [ $? -eq 0 ]; then
        SZ=$(du -sh "$DST_DIR" 2>/dev/null | cut -f1)
        echo "  [OK] $folder -> $DST_DIR  ($SZ)"
        TOTAL=$((TOTAL+1))
    else
        echo "  [FAIL] $folder"
        FAILED=$((FAILED+1))
    fi
done
{'# Copy root files' if mode == 'all' else ''}
{'for f in START_CITL_UBUNTU.sh INSTALL_CITL_APPS_PORTABLE.cmd MAKE_PORTABLE_ZIP.cmd autorun.inf; do' if mode == 'all' else ':'}
{'    [ -f "$SRC/$f" ] && cp -f "$SRC/$f" "$DST/$f" && echo "  [OK] $f"' if mode == 'all' else ''}
{'done' if mode == 'all' else ''}
echo ""
echo "[DONE] USB clone complete. $TOTAL folder(s) copied, $FAILED failed."
"""


def _get_system_check_script() -> str:
    """Return the correct system check script for this OS."""
    if sys.platform == "win32":
        return PS_SYSTEM_CHECK + PS_VENV_CHECK
    return BASH_SYSTEM_CHECK + BASH_VENV_CHECK


def _op(fn_win, fn_nix, log_fn, timeout=120) -> int:
    """Dispatch to Windows PS or Linux bash operation."""
    script = fn_win() if sys.platform == "win32" else fn_nix()
    return _ps(script, log_fn, timeout)


def _ps_diagnostic_sync(src: str, dst: str, dry_run: bool = True) -> str:
    """
    Robocopy with verbose file listing and stats visible.
    dry_run=True adds /L (list only, no actual copy).
    Excludes Ollama blobs and files > 500 MB.
    """
    l_flag = "/L" if dry_run else ""
    mode_label = "DRY-RUN (no files will be copied)" if dry_run else "LIVE SYNC"
    return fr"""
$SRC  = '{src}'
$DST  = '{dst}'
Write-Host "=== SYNC DIAGNOSTICS  [{mode_label}] ==="
Write-Host "Source : $SRC"
Write-Host "Target : $DST"
Write-Host ""

# Read instance IDs if present
$srcId = "unknown"
$dstId = "unknown"
$srcInst = Join-Path $SRC "citl_instance.json"
$dstInst = Join-Path $DST "citl_instance.json"
if (Test-Path $srcInst) {{
    try {{ $d = Get-Content $srcInst | ConvertFrom-Json; $srcId = $d.instance_id }} catch {{}}
}}
if (Test-Path $dstInst) {{
    try {{ $d = Get-Content $dstInst | ConvertFrom-Json; $dstId = $d.instance_id }} catch {{}}
}}
Write-Host "Source Instance : $srcId"
Write-Host "Target Instance : $dstId"
Write-Host ""

# Exclusions
$xf  = @('*.gguf','*.bin','*.ot','*.blob','Modelfile')
$xd  = @('.git','__pycache__','.venv','ollama','blobs','models','dist','build','*.pyc')
$max = 524288000   # 500 MB

Write-Host "--- Exclusions ---"
Write-Host "  File types : $($xf -join ', ')"
Write-Host "  Directories: $($xd -join ', ')"
Write-Host "  Max size   : 500 MB"
Write-Host ""

# Build robocopy args
# /V  = verbose (show each file)  /TS = include timestamps
# Do NOT use /NFL /NDL /NJH /NJS so full stats are visible
$args = @($SRC, $DST, {l_flag} '/E', '/XO', '/V', '/TS', '/NP',
          '/R:1', '/W:0', '/MAX', $max.ToString())
foreach ($f in $xf) {{ $args += '/XF'; $args += $f }}
foreach ($d in $xd) {{ $args += '/XD'; $args += $d }}

Write-Host "--- File Scan ---"
robocopy @args
$rc = $LASTEXITCODE

Write-Host ""
Write-Host "--- Result ---"
switch ($rc) {{
    0  {{ Write-Host "[OK] No changes needed - source and target are in sync." }}
    1  {{ Write-Host "[OK] Files copied/found." }}
    2  {{ Write-Host "[OK] Extra files exist on destination (may be removed on full MIR sync)." }}
    3  {{ Write-Host "[OK] Files copied + extra files on destination." }}
    default {{
        if ($rc -le 7) {{ Write-Host "[OK] Robocopy success (exit $rc)" }}
        else {{ Write-Host "[ERROR] Robocopy exit code $rc - check above for errors." }}
    }}
}}
if ('{dry_run}' -eq 'True') {{
    Write-Host ""
    Write-Host "[NOTE] This was a DRY-RUN. No files were changed."
    Write-Host "       Run 'Full Sync (Live)' to actually transfer files."
}}
"""


def _ps_clone_usb(src_usb: str, dst_usb: str, mode: str) -> str:
    """
    mode: 'all' | 'sync' | 'workstation' | 'field' | 'presentation' | 'ticketing'
    Clones CITL USB folders from src_usb to dst_usb via robocopy.
    Excludes Ollama blobs, .gguf models, and files >500 MB.
    """
    # Map mode -> list of (src subfolder, dst subfolder) pairs
    # 'all' copies everything relevant; targeted modes copy a single numbered folder
    mode_map = {
        "all":          ["1-CITL-SYNC", "2-CITL-PRESENTATION-SUITE",
                         "3-CITL-WORKSTATION-APPS", "4-CITL-FIELD-APPS",
                         "6-CITL-WORK-TICKETING"],
        "sync":         ["1-CITL-SYNC"],
        "presentation": ["2-CITL-PRESENTATION-SUITE"],
        "workstation":  ["3-CITL-WORKSTATION-APPS"],
        "field":        ["4-CITL-FIELD-APPS"],
        "ticketing":    ["6-CITL-WORK-TICKETING"],
    }
    folders = mode_map.get(mode, mode_map["all"])
    folder_list_ps = ", ".join(f"'{f}'" for f in folders)

    # Root-level files to copy for 'all' mode (installers / launchers)
    copy_root_files = "all" in mode

    root_file_block = r"""
# Copy root-level launcher/installer scripts
$rootFiles = @(
    'INSTALL_CITL_APPS_PORTABLE.cmd',
    'START_CITL_WINDOWS.cmd',
    'MAKE_PORTABLE_ZIP.cmd',
    'autorun.inf',
    'CITL_APP_SUITE.desktop'
)
foreach ($f in $rootFiles) {
    $src = Join-Path $SRC $f
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $DST $f) -Force
        Write-Host "  [OK] $f"
    }
}
""" if copy_root_files else ""

    return fr"""
$SRC = '{src_usb}'
$DST = '{dst_usb}'
$FOLDERS = @({folder_list_ps})

Write-Host "=== USB CLONE ==="
Write-Host "Source : $SRC"
Write-Host "Target : $DST"
Write-Host "Mode   : {mode}"
Write-Host ""

# Verify source
if (!(Test-Path $SRC)) {{
    Write-Host "[ERROR] Source USB not found: $SRC"
    exit 1
}}
# Verify target writable
if (!(Test-Path $DST)) {{
    Write-Host "[ERROR] Target drive not found: $DST"
    exit 1
}}

# Robocopy flags shared by all folder copies
# /XO = only newer, /R:2 /W:1 = quick retry, /MT:4 = 4 threads
# /XF *.gguf *.bin = exclude large model files
# /MAX:524288000 = skip files >500 MB
$base = @('/MIR','/XO','/R:2','/W:1','/MT:4','/NFL','/NDL','/NJH','/NJS',
          '/XF','*.gguf','/XF','*.bin','/XF','*.ot',
          '/MAX','524288000',
          '/XD','ollama','/XD','blobs','/XD','.git','/XD','__pycache__')

$total = 0
$failed = 0
foreach ($folder in $FOLDERS) {{
    $srcDir = Join-Path $SRC $folder
    $dstDir = Join-Path $DST $folder
    if (!(Test-Path $srcDir)) {{
        Write-Host "  [--] $folder not found on source - skipping"
        continue
    }}
    if (!(Test-Path $dstDir)) {{
        New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
    }}
    Write-Host "Cloning $folder ..."
    $args = @($srcDir, $dstDir) + $base
    robocopy @args | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -le 7) {{
        $sz = [math]::Round(
            (Get-ChildItem $dstDir -Recurse -EA SilentlyContinue |
             Measure-Object -Property Length -Sum).Sum / 1MB, 1)
        Write-Host "  [OK] $folder -> $dstDir  ($sz MB)"
        $total++
    }} else {{
        Write-Host "  [FAIL] $folder exit code $rc"
        $failed++
    }}
}}
{root_file_block}
Write-Host ""
if ($failed -eq 0) {{
    Write-Host "[DONE] USB clone complete. $total folder(s) copied."
}} else {{
    Write-Host "[WARN] $failed folder(s) failed, $total succeeded."
}}
"""


def _ps_exfat_repair(drive_letter: str, mode: str, salvage_root: str) -> str:
    """
    Directed exFAT diagnostics/repair runner.
    mode: inspect | salvage | repair_scan | repair_fix | repair_deep
    """
    letter = (drive_letter or "").strip().replace("\\", "").replace("/", "")
    return fr"""
$DriveInput = '{letter}'
$Mode = '{mode}'
$SalvageRoot = '{salvage_root}'

if (-not $DriveInput) {{
    Write-Host "[ERROR] Missing drive letter."
    exit 2
}}

$Letter = $DriveInput.Trim().TrimEnd(':')
if ($Letter.Length -lt 1) {{
    Write-Host "[ERROR] Invalid drive letter input: $DriveInput"
    exit 2
}}
$Letter = $Letter.Substring(0, 1).ToUpper()
$Root = "$Letter`:\"
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'

New-Item -ItemType Directory -Path $SalvageRoot -Force | Out-Null
$DiagRoot = Join-Path $SalvageRoot ("EXFAT_DIAG_" + $Letter + "_" + $Stamp)
New-Item -ItemType Directory -Path $DiagRoot -Force | Out-Null

Write-Host "=== CITL exFAT REPAIR UTILITY ==="
Write-Host "Drive      : $Root"
Write-Host "Mode       : $Mode"
Write-Host "Diagnostics: $DiagRoot"
Write-Host ""

$vol = Get-Volume -DriveLetter $Letter -ErrorAction SilentlyContinue
if (-not $vol) {{
    Write-Host "[WARN] Drive $Root is not currently mounted."
    Write-Host "Mounted volumes right now:"
    Get-Volume -ErrorAction SilentlyContinue |
      Select-Object DriveLetter,FileSystem,HealthStatus,OperationalStatus,SizeRemaining,Size |
      Format-Table -AutoSize
    exit 3
}}

$part = Get-Partition -DriveLetter $Letter -ErrorAction SilentlyContinue | Select-Object -First 1
$disk = $null
if ($part) {{
    $disk = Get-Disk -Number $part.DiskNumber -ErrorAction SilentlyContinue
}}

$vol | Format-List * | Out-File (Join-Path $DiagRoot "volume.txt") -Encoding utf8
if ($part) {{ $part | Format-List * | Out-File (Join-Path $DiagRoot "partition.txt") -Encoding utf8 }}
if ($disk) {{ $disk | Format-List * | Out-File (Join-Path $DiagRoot "disk.txt") -Encoding utf8 }}

$fsName = if ($vol.FileSystemType) {{ $vol.FileSystemType }} elseif ($vol.FileSystem) {{ $vol.FileSystem }} else {{ "unknown" }}
$health = if ($vol.HealthStatus) {{ $vol.HealthStatus.ToString() }} else {{ "Unknown" }}
$status = if ($vol.OperationalStatus) {{ ($vol.OperationalStatus -join ',') }} else {{ "Unknown" }}

Write-Host "[INFO] Volume metadata captured."
Write-Host "       FileSystem=$fsName  Health=$health  Status=$status"
Write-Host ""

Write-Host "[STEP] Running baseline scan: chkdsk $Root /scan"
cmd /c "chkdsk $Root /scan" 2>&1 | Tee-Object -FilePath (Join-Path $DiagRoot "chkdsk_scan.txt")

if ($Mode -eq "inspect") {{
    Write-Host ""
    Write-Host "[DONE] Inspect mode complete."
    exit 0
}}

if ($Mode -eq "salvage") {{
    Write-Host ""
    Write-Host "[STEP] Salvage copy of readable data..."
    $out = Join-Path $SalvageRoot ("SALVAGE_" + $Letter + "_" + $Stamp)
    New-Item -ItemType Directory -Path $out -Force | Out-Null
    $roboLog = Join-Path $DiagRoot "robocopy_salvage.log"
    $args = @($Root, $out, '/E', '/COPY:DAT', '/DCOPY:T', '/R:0', '/W:0', '/XJ', '/FFT', '/NP', '/TEE', "/LOG:$roboLog")
    robocopy @args
    $rc = $LASTEXITCODE
    if ($rc -le 7) {{
        Write-Host "[OK] Salvage completed to: $out"
        exit 0
    }}
    Write-Host "[WARN] Salvage completed with robocopy exit code $rc (check $roboLog)"
    exit $rc
}}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {{
    Write-Host ""
    Write-Host "[ERROR] Mode $Mode requires Administrator PowerShell."
    Write-Host "Open PowerShell as Administrator and run one of:"
    Write-Host "  chkdsk $Root /f /x"
    Write-Host "  chkdsk $Root /f /r /x"
    exit 5
}}

if ($Mode -eq "repair_scan") {{
    Write-Host ""
    Write-Host "[STEP] Repair-Volume scan..."
    Repair-Volume -DriveLetter $Letter -Scan -ErrorAction Continue | Out-String | Write-Host
    cmd /c "chkdsk $Root /scan" 2>&1 | Tee-Object -FilePath (Join-Path $DiagRoot "chkdsk_scan_after.txt")
    Write-Host "[DONE] repair_scan complete."
    exit 0
}}

if ($Mode -eq "repair_fix") {{
    Write-Host ""
    Write-Host "[STEP] SpotFix + chkdsk /f /x"
    Repair-Volume -DriveLetter $Letter -SpotFix -ErrorAction Continue | Out-String | Write-Host
    cmd /c "chkdsk $Root /f /x" 2>&1 | Tee-Object -FilePath (Join-Path $DiagRoot "chkdsk_fix.txt")
    exit $LASTEXITCODE
}}

if ($Mode -eq "repair_deep") {{
    Write-Host ""
    Write-Host "[STEP] Deep repair (chkdsk /f /r /x) - this can take a long time."
    cmd /c "chkdsk $Root /f /r /x" 2>&1 | Tee-Object -FilePath (Join-Path $DiagRoot "chkdsk_deep.txt")
    exit $LASTEXITCODE
}}

Write-Host "[ERROR] Unknown mode: $Mode"
exit 2
"""


# ---------------------------------------------------------------------------
TILES = [
    {
        "id":    "scan",
        "title": "System Scan",
        "sub":   "Detect repos, Python, Git, disk space",
        "color": "#4A0A0A",
        "icon":  "SCAN",
    },
    {
        "id":    "install",
        "title": "First-Time Install",
        "sub":   "USB -> PC: copy files, create venv, shortcuts",
        "color": "#1A3A1A",
        "icon":  "INST",
    },
    {
        "id":    "usb_to_pc",
        "title": "USB -> PC Update",
        "sub":   "Pull latest from this USB to an existing local repo",
        "color": "#1A2A4A",
        "icon":  "PULL",
    },
    {
        "id":    "pc_to_usb",
        "title": "PC -> USB Sync",
        "sub":   "Push PC repo + built EXEs back to this USB",
        "color": "#3A1A00",
        "icon":  "PUSH",
    },
    {
        "id":    "git_push",
        "title": "Git Upload",
        "sub":   "Stage, commit, and push to GitHub remote",
        "color": "#1C1A3A",
        "icon":  "GIT",
    },
    {
        "id":    "git_pull",
        "title": "Git Pull",
        "sub":   "Fetch and pull latest from GitHub remote",
        "color": "#1A1A1A",
        "icon":  "GPLL",
    },
    {
        "id":    "shortcuts",
        "title": "Fix Shortcuts",
        "sub":   "Re-create all desktop .lnk shortcuts",
        "color": "#3A1A3A",
        "icon":  "LINK",
    },
    {
        "id":    "status",
        "title": "App Bundle Status",
        "sub":   "Check all USB exe bundles + local dist/",
        "color": "#2A1A00",
        "icon":  "STAT",
    },
    {
        "id":    "diagnostics",
        "title": "Sync Diagnostics",
        "sub":   "Discover all CITL instances, preview sync, verify file transfers",
        "color": "#0A2A3A",
        "icon":  "DIAG",
    },
    {
        "id":    "clone_usb",
        "title": "Clone USB Drive",
        "sub":   "Mirror CITL USB to another USB (4 modes)",
        "color": "#1A2A1A",
        "icon":  "CLON",
    },
    {
        "id":    "exfat_repair",
        "title": "exFAT Repair Utility",
        "sub":   "Inspect, salvage, and run directed exFAT repair modes",
        "color": "#2A1A1A",
        "icon":  "XFIX",
    },
    {
        "id":    "make_zip",
        "title": "Make Portable ZIP",
        "sub":   "Package all EXE bundles + installer into a ZIP",
        "color": "#1A1A3A",
        "icon":  "ZIP",
    },
]


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class SyncHub(tk.Tk):
    def __init__(self):
        super().__init__()
        self.configure(bg=C["bg"])
        self.geometry("1140x760")
        self.minsize(960, 640)

        self._repos: List[Dict] = []
        self._usbs:  List[Path] = []
        self._busy   = False
        self._selected_repo: Optional[Path] = None
        self._selected_usb:  Optional[Path] = None

        # Load or create this installation's unique instance identity
        self._instance = _get_or_create_instance_id(REPO)
        iid  = self._instance.get("instance_id", "CITL-????")
        itype = self._instance.get("type", "PC")
        self.title(f"{APP_NAME}  {APP_VERSION}  [{iid}  {itype}]")

        self._build_ui()
        self.after(200, lambda: threading.Thread(
            target=self._background_scan, daemon=True).start())

    # ------------------------------------------------------------------ Layout
    def _build_ui(self):
        # Header strip
        hdr = tk.Frame(self, bg=C["panel"])
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=C["accent"], height=4).pack(fill="x")
        hi = tk.Frame(hdr, bg=C["panel"])
        hi.pack(fill="x", padx=16, pady=10)
        tk.Label(hi, text=APP_NAME, font=(_F, 18, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(side="left")
        tk.Label(hi, text=APP_VERSION, font=(_F, 10, "bold"),
                 bg=C["panel"], fg=C["accent"]).pack(side="left", padx=8)
        iid   = self._instance.get("instance_id", "CITL-????")
        itype = self._instance.get("type", "PC")
        tk.Label(hi, text=f"[{iid}  {itype}]", font=(_F, 9, "bold"),
                 bg=C["panel"], fg=C["gold"]).pack(side="left", padx=6)
        tk.Label(hi, text="RTC CITL  |  USB Install, Sync, Git, Diagnostics",
                 font=(_F, 9), bg=C["panel"], fg=C["muted"]).pack(side="right")

        # Body: left controls + right output
        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

        # Status bar
        self._status_var = tk.StringVar(value="Scanning system...")
        tk.Label(self, textvariable=self._status_var,
                 bg=C["panel"], fg=C["muted"], font=(_F, 9),
                 anchor="w", padx=12).pack(fill="x", side="bottom")

    def _build_left(self, parent):
        left = tk.Frame(parent, bg=C["panel"], width=320)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)

        # Scroll wrapper
        canvas = tk.Canvas(left, bg=C["panel"], highlightthickness=0)
        vsb = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["panel"])
        wid = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))

        # -- Repo selector
        self._section(inner, "TARGET REPO ON THIS PC")
        self._repo_var = tk.StringVar(value="Scanning...")
        self._repo_cb = ttk.Combobox(inner, textvariable=self._repo_var,
                                      font=(_F, 9), state="readonly", width=32)
        self._repo_cb.pack(fill="x", padx=10, pady=(2, 4))
        self._repo_cb.bind("<<ComboboxSelected>>", self._on_repo_select)
        self._repo_info_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self._repo_info_var, font=(_F, 8),
                 bg=C["panel"], fg=C["muted"], anchor="w",
                 justify="left", wraplength=290).pack(fill="x", padx=12, pady=(0, 6))
        self._btn(inner, "Browse for Repo...", self._browse_repo, color=C["btn"])

        # -- USB selector
        self._section(inner, "USB / EXTERNAL TARGET")
        self._usb_var = tk.StringVar(value="Scanning...")
        self._usb_cb = ttk.Combobox(inner, textvariable=self._usb_var,
                                     font=(_F, 9), state="readonly", width=32)
        self._usb_cb.pack(fill="x", padx=10, pady=(2, 4))
        self._usb_cb.bind("<<ComboboxSelected>>", self._on_usb_select)
        self._usb_info_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self._usb_info_var, font=(_F, 8),
                 bg=C["panel"], fg=C["muted"], anchor="w",
                 justify="left", wraplength=290).pack(fill="x", padx=12, pady=(0, 6))
        self._btn(inner, "Browse for USB Path...", self._browse_usb, color=C["btn"])
        self._btn(inner, "Re-Scan Drives", lambda: threading.Thread(
            target=self._background_scan, daemon=True).start(), color=C["btn"])

        self._div(inner)

        # -- Operation tiles
        self._section(inner, "OPERATIONS")
        style = ttk.Style()
        style.configure("TNotebook", background=C["bg"], borderwidth=0)
        for tile in TILES:
            self._tile_btn(inner, tile)

        self._div(inner)

        # -- Git commit message
        self._section(inner, "GIT COMMIT MESSAGE")
        self._commit_var = tk.StringVar(
            value=f"CITL sync {datetime.now():%Y-%m-%d %H:%M}")
        tk.Entry(inner, textvariable=self._commit_var, font=(_F, 9),
                 bg=C["card"], fg=C["text"], insertbackground=C["text"],
                 relief="flat", width=36).pack(fill="x", padx=10, pady=(2, 8))

        self._div(inner)

        # -- Quick links
        self._section(inner, "QUICK OPEN")
        for label, url in [
            ("github.com",       "https://github.com"),
            ("office.com",       "https://www.office.com"),
        ]:
            self._btn(inner, label, lambda u=url: webbrowser.open(u),
                      color=C["btn"])
        tk.Frame(inner, bg=C["panel"], height=16).pack()

    def _build_right(self, parent):
        right = tk.Frame(parent, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Op title bar
        self._op_title_var = tk.StringVar(value="Select an operation")
        op_hdr = tk.Frame(right, bg=C["card_sel"])
        op_hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(op_hdr, textvariable=self._op_title_var,
                 font=(_F, 12, "bold"), bg=C["card_sel"], fg=C["text"],
                 anchor="w", padx=14, pady=8).pack(side="left")
        self._run_btn = tk.Button(op_hdr, text="RUN",
                                   font=(_F, 11, "bold"),
                                   bg=C["accent"], fg="white",
                                   relief="flat", padx=20, pady=6,
                                   cursor="hand2",
                                   command=self._run_current,
                                   state="disabled")
        self._run_btn.pack(side="right", padx=10, pady=4)
        self._clear_btn = tk.Button(op_hdr, text="Clear",
                                     font=(_F, 9), bg=C["btn"],
                                     fg=C["muted"], relief="flat",
                                     padx=10, pady=6, cursor="hand2",
                                     command=self._clear_output)
        self._clear_btn.pack(side="right", padx=(0, 4), pady=4)

        # Console output
        self._output = scrolledtext.ScrolledText(
            right, bg=C["out_bg"], fg=C["out_fg"],
            font=("Consolas", 9), insertbackground=C["text"],
            wrap="none", relief="flat")
        self._output.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._output.tag_configure("ok",   foreground=C["out_ok"])
        self._output.tag_configure("warn", foreground=C["out_warn"])
        self._output.tag_configure("err",  foreground=C["out_err"])
        self._output.tag_configure("head", foreground=C["gold"],
                                    font=("Consolas", 9, "bold"))

        self._current_tile: Optional[Dict] = None

    # ------------------------------------------------------------------ Widgets
    def _section(self, parent, text: str):
        tk.Label(parent, text=text, font=(_F, 8, "bold"),
                 bg=C["panel"], fg=C["faint"],
                 anchor="w").pack(fill="x", padx=12, pady=(14, 3))

    def _div(self, parent):
        tk.Frame(parent, bg=C["line"], height=1).pack(fill="x", padx=8, pady=6)

    def _btn(self, parent, text: str, cmd: Callable,
              color: Optional[str] = None, fg: Optional[str] = None):
        tk.Button(parent, text=f"  {text}",
                  font=(_F, 9), bg=color or C["btn_acc"],
                  fg=fg or C["text"], relief="flat", bd=0,
                  padx=10, pady=5, anchor="w", cursor="hand2",
                  command=cmd).pack(fill="x", padx=8, pady=2)

    def _tile_btn(self, parent, tile: Dict):
        card = tk.Frame(parent, bg=tile["color"],
                        highlightthickness=1,
                        highlightbackground=C["line"])
        card.pack(fill="x", padx=8, pady=3)
        card.columnconfigure(1, weight=1)
        tk.Label(card, text=tile["icon"], font=(_F, 9, "bold"),
                 bg=tile["color"], fg=C["text"],
                 width=5, anchor="center").grid(
            row=0, column=0, rowspan=2, padx=(4, 6), pady=4, sticky="ns")
        tk.Label(card, text=tile["title"], font=(_F, 10, "bold"),
                 bg=tile["color"], fg=C["text"],
                 anchor="w").grid(row=0, column=1, sticky="w", pady=(5, 1))
        tk.Label(card, text=tile["sub"], font=(_F, 8),
                 bg=tile["color"], fg=C["muted"],
                 anchor="w", wraplength=200).grid(row=1, column=1, sticky="w",
                                                    pady=(0, 4))
        tk.Button(card, text="Select", font=(_F, 8),
                  bg=C["btn"], fg=C["text"], relief="flat",
                  padx=8, pady=3, cursor="hand2",
                  command=lambda t=tile: self._select_tile(t)).grid(
            row=0, column=2, rowspan=2, padx=6)

    # ------------------------------------------------------------------ Scan
    def _background_scan(self):
        self._status("Scanning for repos and USB drives...")
        self._repos = _find_repos()
        self._usbs  = _find_usb_roots()
        # Ensure each USB root gets an instance ID (creates if absent, reads if present)
        for usb in self._usbs:
            try:
                _get_or_create_instance_id(usb)
            except Exception:
                pass

        # Default USB = this exe's drive (if running from USB)
        if USB_ROOT and USB_ROOT not in self._usbs:
            self._usbs.insert(0, USB_ROOT)

        self.after(0, self._populate_dropdowns)

    def _populate_dropdowns(self):
        # Repos
        if self._repos:
            choices = [
                f"{r['path'].name}  [{int(r['age_days'])}d old]  "
                f"{'STALE ' if r['stale'] else ''}"
                f"{'GIT' if r['has_git'] else 'no-git'}  "
                f"{r['files_ok']}/{r['files_total']} files"
                for r in self._repos
            ]
            self._repo_cb["values"] = choices
            self._repo_cb.current(0)
            self._selected_repo = self._repos[0]["path"]
            self._update_repo_info(self._repos[0])
        else:
            self._repo_cb["values"] = ["No CITL repos found on this PC"]
            self._repo_info_var.set("No repo found. Use 'First-Time Install' to install.")

        # USBs
        if self._usbs:
            self._usb_cb["values"] = [str(p) for p in self._usbs]
            self._usb_cb.current(0)
            self._selected_usb = self._usbs[0]
            self._update_usb_info(self._usbs[0])
        else:
            self._usb_cb["values"] = ["No CITL USB detected"]
            self._usb_info_var.set("Plug in USB drive and click Re-Scan Drives.")

        self._status(
            f"Found {len(self._repos)} repo(s), {len(self._usbs)} USB drive(s).")
        # Auto-run scan output, then launch wizard
        self._select_tile(next(t for t in TILES if t["id"] == "scan"))
        self._run_current()
        self.after(1800, self._auto_wizard)

    def _update_repo_info(self, repo: Dict):
        age = int(repo["age_days"])
        stale = "  [STALE]" if repo["stale"] else ""
        git = f"  Branch: {repo['git_branch']}" if repo["has_git"] else "  (no git)"
        inst = _load_instance_id(repo["path"])
        iid  = f"  ID: {inst['instance_id']}" if inst else "  ID: (none)"
        self._repo_info_var.set(
            f"{repo['path']}\n{age}d old{stale}{git}{iid}\n"
            f"Key files: {repo['files_ok']}/{repo['files_total']}")

    def _update_usb_info(self, usb: Path):
        bundles_ok = sum(
            1 for _, folder, exe in APP_BUNDLES
            if (usb / folder / exe).exists()
        )
        inst = _load_instance_id(usb)
        iid  = f"  ID: {inst['instance_id']}" if inst else "  ID: (none yet)"
        self._usb_info_var.set(
            f"{usb}\nApp bundles: {bundles_ok}/{len(APP_BUNDLES)}{iid}")

    def _on_repo_select(self, _e=None):
        idx = self._repo_cb.current()
        if 0 <= idx < len(self._repos):
            self._selected_repo = self._repos[idx]["path"]
            self._update_repo_info(self._repos[idx])

    def _on_usb_select(self, _e=None):
        idx = self._usb_cb.current()
        if 0 <= idx < len(self._usbs):
            self._selected_usb = self._usbs[idx]
            self._update_usb_info(self._usbs[idx])

    def _browse_repo(self):
        p = filedialog.askdirectory(title="Select CITL repo folder")
        if p:
            candidate = Path(p)
            self._repos.insert(0, {
                "path": candidate, "age_days": 0, "has_git": (candidate/".git").exists(),
                "git_branch": "", "files_ok": 0, "files_total": 5, "stale": False
            })
            self._populate_dropdowns()

    def _browse_usb(self):
        p = filedialog.askdirectory(title="Select USB / external drive root")
        if p:
            usb = Path(p)
            if usb not in self._usbs:
                self._usbs.insert(0, usb)
            self._populate_dropdowns()

    # ------------------------------------------------------------------ Tile select / run
    def _select_tile(self, tile: Dict):
        self._current_tile = tile
        self._op_title_var.set(f"{tile['icon']}  {tile['title']}  --  {tile['sub']}")
        self._run_btn.configure(state="normal", bg=C["accent"])

    def _run_current(self):
        if not self._current_tile or self._busy:
            return
        tile = self._current_tile
        tid  = tile["id"]

        # Validate requirements per operation
        if tid in ("install", "usb_to_pc") and not self._selected_usb:
            messagebox.showwarning(APP_NAME, "No USB drive selected.\nPlug in USB and click Re-Scan Drives.")
            return
        if tid in ("pc_to_usb", "git_push", "git_pull", "shortcuts") and not self._selected_repo:
            messagebox.showwarning(APP_NAME, "No local repo selected.\nUse 'Browse for Repo' to locate your CITL folder.")
            return

        # Git push: pick install destination for first-time install
        if tid == "install":
            dest_choices = [
                str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "CITL"),
                str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "CITL"),
            ]
            if self._repos:
                dest_choices = [str(r["path"]) for r in self._repos] + dest_choices
            dest = self._ask_choice(
                "First-Time Install",
                "Select install destination:",
                dest_choices,
                dest_choices[0]
            )
            if not dest:
                return
            u = str(self._selected_usb)
            self._launch_op(lambda lf, u=u, d=dest: _ps(
                _ps_install_from_usb(u, d) if sys.platform == "win32"
                else _bash_install_from_usb(u, d), lf), tile)
            return

        if tid == "usb_to_pc":
            dest = str(self._selected_repo) if self._selected_repo else str(
                Path.home() / "Desktop" / "CITL")
            u = str(self._selected_usb)
            self._launch_op(lambda lf, u=u, d=dest: _ps(
                _ps_sync_usb_to_pc(u, d) if sys.platform == "win32"
                else _bash_sync_usb_to_pc(u, d), lf), tile)
            return

        if tid == "pc_to_usb":
            usb = self._selected_usb
            if not usb:
                if not self._usbs:
                    messagebox.showwarning(APP_NAME, "No USB drive detected.\nPlug in USB and Re-Scan.")
                    return
                usb = self._usbs[0]
            r = str(self._selected_repo)
            u = str(usb)
            self._launch_op(lambda lf, r=r, u=u: _ps(
                _ps_sync_pc_to_usb(r, u) if sys.platform == "win32"
                else _bash_sync_pc_to_usb(r, u), lf), tile)
            return

        if tid == "git_push":
            msg = self._commit_var.get().strip() or f"CITL sync {datetime.now():%Y-%m-%d %H:%M}"
            r = str(self._selected_repo)
            self._launch_op(lambda lf, r=r, m=msg: _ps(
                _ps_git_push(r, m) if sys.platform == "win32"
                else _bash_git_push(r, m), lf), tile)
            return

        if tid == "git_pull":
            r = str(self._selected_repo)
            self._launch_op(lambda lf, r=r: _ps(
                _ps_git_pull(r) if sys.platform == "win32"
                else _bash_git_pull(r), lf), tile)
            return

        if tid == "shortcuts":
            r = str(self._selected_repo)
            self._launch_op(lambda lf, r=r: _ps(
                _ps_make_shortcuts(r) if sys.platform == "win32"
                else _bash_make_shortcuts(r), lf), tile)
            return

        if tid == "scan":
            self._launch_op(lambda lf: _ps(
                _get_system_check_script(), lf, timeout=30), tile)
            return

        if tid == "status":
            self._run_status_check()
            return

        if tid == "diagnostics":
            self._run_diagnostics()
            return

        if tid == "clone_usb":
            self._run_clone_usb()
            return

        if tid == "exfat_repair":
            self._run_exfat_repair()
            return

        if tid == "make_zip":
            self._run_make_zip()
            return

    # ------------------------------------------------------------------ Auto wizard
    def _offer_popup(self, title: str, message: str, buttons: list):
        """
        Show a non-blocking, topmost offer dialog with custom action buttons.
        buttons = list of (label, callable_or_None) tuples.
        First button gets accent color; rest get btn color.
        """
        win = tk.Toplevel(self)
        win.title(f"CITL - {title}")
        win.configure(bg=C["bg"])
        win.resizable(False, False)
        win.attributes("-topmost", True)
        # Center over main window
        self.update_idletasks()
        mx = self.winfo_x() + self.winfo_width() // 2
        my = self.winfo_y() + 90
        win.geometry(f"520x+{mx - 260}+{my}")

        tk.Frame(win, bg=C["accent"], height=3).pack(fill="x")
        tk.Label(win, text=title, font=(_F, 12, "bold"),
                 bg=C["bg"], fg=C["gold"]).pack(padx=20, pady=(14, 0), anchor="w")
        tk.Frame(win, bg=C["line"], height=1).pack(fill="x", padx=12, pady=6)
        tk.Label(win, text=message, font=(_F, 9),
                 bg=C["bg"], fg=C["text"], justify="left",
                 wraplength=476, anchor="w").pack(padx=20, pady=8, fill="x")

        btn_row = tk.Frame(win, bg=C["bg"])
        btn_row.pack(fill="x", padx=16, pady=(4, 16))
        for i, (lbl, action) in enumerate(buttons):
            color = C["accent"] if i == 0 else C["btn"]
            fgc   = "white"    if i == 0 else C["muted"]
            bold  = "bold"     if i == 0 else ""
            def _cmd(a=action, w=win):
                w.destroy()
                if a:
                    self.after(50, a)
            tk.Button(btn_row, text=lbl, font=(_F, 9, bold) if bold else (_F, 9),
                      bg=color, fg=fgc, relief="flat", padx=14, pady=6,
                      cursor="hand2", command=_cmd).pack(side="left", padx=(0, 6))

    def _auto_git_check(self, repo_path: Path):
        """Background-check git status; offer push popup if uncommitted changes."""
        if not (repo_path / ".git").exists():
            return
        def _check():
            try:
                r = subprocess.run(
                    ["git", "-C", str(repo_path), "status", "--short"],
                    capture_output=True, text=True, timeout=10
                )
                changes = r.stdout.strip()
                if changes:
                    n = len(changes.splitlines())
                    def _show():
                        self._offer_popup(
                            "Uncommitted Git Changes Detected",
                            f"{n} uncommitted change(s) in:\n{repo_path}\n\n"
                            "Push these changes to GitHub now?",
                            buttons=[
                                ("Push to GitHub", lambda: (
                                    self._select_tile(
                                        next(t for t in TILES if t["id"] == "git_push")),
                                    self.after(80, self._run_current))),
                                ("Ignore", None),
                            ]
                        )
                    self.after(0, _show)
            except Exception:
                pass
        threading.Thread(target=_check, daemon=True).start()

    def _auto_wizard(self):
        """
        Startup wizard: examine detected state and show contextual offer dialogs.
        Called 1.8 seconds after scan populates dropdowns.
        """
        has_repos = bool(self._repos)
        has_usb   = bool(self._usbs)

        # ---- Case 1: nothing found ----
        if not has_repos and not has_usb:
            self._offer_popup(
                "No CITL Installation Found",
                "No CITL repos or USB drives were detected.\n\n"
                "Options:\n"
                "  1. Connect your CITL USB drive, then click Re-Scan Drives\n"
                "  2. Use 'Browse for Repo' to locate an existing install\n"
                "  3. Use 'Browse for USB Path' to manually set the USB root",
                buttons=[
                    ("Re-Scan Drives", lambda: threading.Thread(
                        target=self._background_scan, daemon=True).start()),
                    ("Browse for Repo", self._browse_repo),
                    ("Dismiss", None),
                ]
            )
            return

        # ---- Case 2: USB found but no local install ----
        if not has_repos and has_usb:
            usb = self._usbs[0]
            usb_id = _load_instance_id(usb)
            id_label = usb_id.get("instance_id", "USB") if usb_id else "USB"
            self._offer_popup(
                "First-Time Install Available",
                f"USB detected: {usb}  ({id_label})\n\n"
                "No local CITL installation found on this PC.\n\n"
                "Install CITL apps to your Desktop now?\n"
                "(Copies files, sets up Python venv, creates shortcuts.  No admin needed.)",
                buttons=[
                    ("Install Now", lambda: (
                        self._select_tile(
                            next(t for t in TILES if t["id"] == "install")),
                        self.after(80, self._run_current))),
                    ("Browse for Existing Repo", self._browse_repo),
                    ("Not Now", None),
                ]
            )
            return

        # ---- Case 3: repo found, USB present ----
        if has_repos and has_usb:
            repo    = self._repos[0]
            usb     = self._usbs[0]
            age     = int(repo["age_days"])
            repo_id = _load_instance_id(repo["path"])
            usb_id  = _load_instance_id(usb)
            rid     = repo_id.get("instance_id", "local") if repo_id else "local"
            uid     = usb_id.get("instance_id", "USB")    if usb_id  else "USB"

            if age > 14:
                self._offer_popup(
                    "Sync Recommended — Repo Is Stale",
                    f"Local repo [{rid}]:  {repo['path']}\n"
                    f"Last updated: {age} days ago  (>14 days = stale)\n\n"
                    f"USB [{uid}]: {usb}\n\n"
                    "Pull latest files from USB to bring this PC up to date?",
                    buttons=[
                        ("Sync USB -> PC Now", lambda: (
                            self._select_tile(
                                next(t for t in TILES if t["id"] == "usb_to_pc")),
                            self.after(80, self._run_current))),
                        ("Open Sync Diagnostics", lambda: (
                            self._select_tile(
                                next(t for t in TILES if t["id"] == "diagnostics")),
                            self.after(80, self._run_current))),
                        ("Skip", None),
                    ]
                )
            else:
                # Repo is fresh — offer diagnostics + check git
                self._offer_popup(
                    "CITL Repo & USB Detected",
                    f"Local repo [{rid}]:  {repo['path']}  ({age}d old, fresh)\n"
                    f"USB [{uid}]: {usb}\n\n"
                    "Run Sync Diagnostics to compare source and target?",
                    buttons=[
                        ("Run Diagnostics", lambda: (
                            self._select_tile(
                                next(t for t in TILES if t["id"] == "diagnostics")),
                            self.after(80, self._run_current))),
                        ("PC -> USB Sync", lambda: (
                            self._select_tile(
                                next(t for t in TILES if t["id"] == "pc_to_usb")),
                            self.after(80, self._run_current))),
                        ("Dismiss", None),
                    ]
                )
                self._auto_git_check(repo["path"])
            return

        # ---- Case 4: repo found, no USB ----
        if has_repos and not has_usb:
            self._auto_git_check(self._repos[0]["path"])

    def _run_diagnostics(self):
        """Full diagnostic window: discover all CITL instances, preview sync, run live."""
        win = tk.Toplevel(self)
        win.title("Sync Diagnostics")
        win.configure(bg=C["bg"])
        win.geometry("900x720")
        win.minsize(780, 560)

        # ---- Header ----
        hdr = tk.Frame(win, bg=C["panel"])
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=C["accent"], height=3).pack(fill="x")
        hi = tk.Frame(hdr, bg=C["panel"])
        hi.pack(fill="x", padx=14, pady=8)
        tk.Label(hi, text="SYNC DIAGNOSTICS", font=(_F, 14, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(side="left")
        iid = self._instance.get("instance_id", "??")
        tk.Label(hi, text=f"This instance: {iid}  ({self._instance.get('type','PC')})",
                 font=(_F, 9), bg=C["panel"], fg=C["gold"]).pack(side="right")

        # ---- Instance cards row ----
        cards_frame = tk.Frame(win, bg=C["bg"])
        cards_frame.pack(fill="x", padx=10, pady=6)
        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)

        def _make_instance_card(parent, col, title_text, color, path_obj: Optional[Path]):
            card = tk.Frame(parent, bg=color, padx=10, pady=8,
                            highlightthickness=1, highlightbackground=C["line"])
            card.grid(row=0, column=col, sticky="ew", padx=4)
            tk.Label(card, text=title_text, font=(_F, 9, "bold"),
                     bg=color, fg=C["text"]).pack(anchor="w")
            if path_obj:
                inst = _load_instance_id(path_obj) if path_obj != REPO else self._instance
                iid_s  = inst.get("instance_id", "(none)") if inst else "(none)"
                itype  = inst.get("type", "?") if inst else "?"
                icre   = inst.get("created", "")[:10] if inst else ""
                tk.Label(card, text=f"ID:      {iid_s}", font=("Consolas", 9),
                         bg=color, fg=C["gold"]).pack(anchor="w")
                tk.Label(card, text=f"Type:    {itype}", font=("Consolas", 9),
                         bg=color, fg=C["text"]).pack(anchor="w")
                tk.Label(card, text=f"Path:    {path_obj}", font=("Consolas", 8),
                         bg=color, fg=C["muted"]).pack(anchor="w")
                tk.Label(card, text=f"Created: {icre}", font=("Consolas", 8),
                         bg=color, fg=C["muted"]).pack(anchor="w")
            else:
                tk.Label(card, text="(none selected)", font=(_F, 9),
                         bg=color, fg=C["muted"]).pack(anchor="w")

        src_repo = self._selected_repo or REPO
        dst_usb  = self._selected_usb

        _make_instance_card(cards_frame, 0, "SOURCE  (PC REPO)", C["panel2"], src_repo)
        _make_instance_card(cards_frame, 1, "TARGET  (USB / REMOTE)", C["card"], dst_usb)

        # ---- Discovered endpoints list ----
        tk.Label(win, text="DISCOVERED CITL ENDPOINTS",
                 font=(_F, 8, "bold"), bg=C["bg"], fg=C["faint"],
                 anchor="w").pack(fill="x", padx=14, pady=(8, 2))

        ep_frame = tk.Frame(win, bg=C["panel"], padx=4, pady=4)
        ep_frame.pack(fill="x", padx=10)

        all_endpoints: List[Dict] = []
        # Repos
        for r in self._repos:
            inst = _load_instance_id(r["path"])
            all_endpoints.append({
                "kind": "REPO", "path": r["path"],
                "iid":  inst.get("instance_id", "(no ID)") if inst else "(no ID)",
                "type": inst.get("type", "PC") if inst else "PC",
                "age":  int(r["age_days"]),
                "bundles": None,
            })
        # USBs
        for u in self._usbs:
            inst = _load_instance_id(u)
            nbundles = sum(1 for _, f, e in APP_BUNDLES if (u/f/e).exists())
            all_endpoints.append({
                "kind": "USB",  "path": u,
                "iid":  inst.get("instance_id", "(no ID)") if inst else "(no ID)",
                "type": inst.get("type", "USB") if inst else "USB",
                "age":  None,
                "bundles": nbundles,
            })

        # Track selected src/dst for diagnostics
        diag_src_var = tk.StringVar(value=str(src_repo))
        diag_dst_var = tk.StringVar(value=str(dst_usb) if dst_usb else "")

        for ep in all_endpoints:
            row = tk.Frame(ep_frame, bg=C["card"], padx=6, pady=3)
            row.pack(fill="x", pady=2)
            row.columnconfigure(2, weight=1)
            kind_color = C["out_ok"] if ep["kind"] == "REPO" else C["out_warn"]
            tk.Label(row, text=ep["kind"], font=("Consolas", 8, "bold"),
                     bg=C["card"], fg=kind_color, width=5).grid(row=0, column=0, padx=(0,4))
            tk.Label(row, text=ep["iid"], font=("Consolas", 9, "bold"),
                     bg=C["card"], fg=C["gold"], width=16, anchor="w").grid(row=0, column=1, padx=4)
            detail = str(ep["path"])
            if ep["age"] is not None:
                detail += f"  [{ep['age']}d old]"
            if ep["bundles"] is not None:
                detail += f"  [{ep['bundles']}/{len(APP_BUNDLES)} bundles]"
            tk.Label(row, text=detail, font=("Consolas", 8),
                     bg=C["card"], fg=C["text"], anchor="w").grid(row=0, column=2, sticky="ew")

            def _use_src(p=ep["path"]):
                diag_src_var.set(str(p))
                src_lbl.config(text=f"SRC: {p}")
            def _use_dst(p=ep["path"]):
                diag_dst_var.set(str(p))
                dst_lbl.config(text=f"DST: {p}")
            tk.Button(row, text="USE AS SRC", font=(_F, 7), bg=C["btn"],
                      fg=C["text"], relief="flat", padx=6, pady=2, cursor="hand2",
                      command=_use_src).grid(row=0, column=3, padx=2)
            tk.Button(row, text="USE AS DST", font=(_F, 7), bg=C["btn_acc"],
                      fg=C["text"], relief="flat", padx=6, pady=2, cursor="hand2",
                      command=_use_dst).grid(row=0, column=4, padx=2)

        # ---- Selection display ----
        sel_frame = tk.Frame(win, bg=C["bg"])
        sel_frame.pack(fill="x", padx=10, pady=4)
        src_lbl = tk.Label(sel_frame, text=f"SRC: {src_repo}",
                           font=("Consolas", 8), bg=C["bg"], fg=C["out_ok"], anchor="w")
        src_lbl.pack(fill="x", padx=4)
        dst_lbl = tk.Label(sel_frame,
                           text=f"DST: {dst_usb}" if dst_usb else "DST: (none selected - pick above)",
                           font=("Consolas", 8), bg=C["bg"], fg=C["out_warn"], anchor="w")
        dst_lbl.pack(fill="x", padx=4)

        # ---- Exclusion info ----
        tk.Label(win, text="Exclusions: *.gguf  *.bin  *.blob  ollama/  blobs/  .git/  "
                           "__pycache__/  .venv/  dist/  build/  |  Max file size: 500 MB  "
                           "|  Ollama must be installed via USB bootstrapper",
                 font=(_F, 8), bg=C["bg"], fg=C["faint"],
                 anchor="w", wraplength=860).pack(fill="x", padx=14, pady=(2, 4))

        # ---- Console output ----
        diag_console = scrolledtext.ScrolledText(
            win, bg=C["out_bg"], fg=C["out_fg"],
            font=("Consolas", 8), wrap="none", relief="flat", height=14)
        diag_console.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        diag_console.tag_configure("ok",   foreground=C["out_ok"])
        diag_console.tag_configure("warn", foreground=C["out_warn"])
        diag_console.tag_configure("err",  foreground=C["out_err"])
        diag_console.tag_configure("head", foreground=C["gold"],
                                   font=("Consolas", 8, "bold"))

        def _diag_log(text: str):
            lo = text.lower()
            tag = None
            if "[ok]" in lo or "[ ok ]" in lo or "success" in lo or "newer" in lo:
                tag = "ok"
            elif "[warn]" in lo or "warning" in lo or "extra" in lo:
                tag = "warn"
            elif "[error]" in lo or "failed" in lo or "access denied" in lo:
                tag = "err"
            elif "===" in text or "---" in text:
                tag = "head"
            if tag:
                diag_console.insert("end", text + "\n", tag)
            else:
                diag_console.insert("end", text + "\n")
            diag_console.see("end")

        diag_busy = [False]

        def _run_diag(dry: bool):
            src_p = diag_src_var.get().strip()
            dst_p = diag_dst_var.get().strip()
            if not src_p or not dst_p:
                _diag_log("[ERROR] Select both source and destination first.")
                return
            if diag_busy[0]:
                _diag_log("[WARN] Already running - please wait.")
                return
            diag_busy[0] = True
            diag_console.delete("1.0", "end")
            label = "DRY-RUN PREVIEW" if dry else "LIVE SYNC"
            _diag_log(f"\n{'='*60}")
            _diag_log(f"  SYNC DIAGNOSTICS  --  {label}  --  {datetime.now():%H:%M:%S}")
            _diag_log(f"{'='*60}\n")

            def _work():
                script = (_ps_diagnostic_sync(src_p, dst_p, dry_run=dry)
                          if sys.platform == "win32"
                          else _bash_diagnostic_sync(src_p, dst_p, dry_run=dry))
                rc = _ps(script, _diag_log, timeout=180)
                win.after(0, lambda: _diag_log(
                    f"\n{'[OK]' if rc <= 7 else '[ERROR]'} Exit code: {rc}"))
                diag_busy[0] = False

            threading.Thread(target=_work, daemon=True).start()

        # ---- Action buttons ----
        btn_row = tk.Frame(win, bg=C["bg"])
        btn_row.pack(fill="x", padx=10, pady=(0, 8))
        tk.Button(btn_row, text="Preview (Dry-Run)", font=(_F, 9, "bold"),
                  bg=C["btn"], fg=C["text"], relief="flat", padx=14, pady=6,
                  cursor="hand2", command=lambda: _run_diag(True)).pack(side="left", padx=4)
        tk.Button(btn_row, text="Full Sync (Live)", font=(_F, 9, "bold"),
                  bg=C["accent"], fg="white", relief="flat", padx=14, pady=6,
                  cursor="hand2", command=lambda: _run_diag(False)).pack(side="left", padx=4)
        tk.Button(btn_row, text="Clear Log", font=(_F, 9),
                  bg=C["btn"], fg=C["muted"], relief="flat", padx=10, pady=6,
                  cursor="hand2",
                  command=lambda: diag_console.delete("1.0", "end")).pack(side="left", padx=4)
        tk.Button(btn_row, text="Close", font=(_F, 9),
                  bg=C["btn"], fg=C["muted"], relief="flat", padx=10, pady=6,
                  cursor="hand2", command=win.destroy).pack(side="right", padx=4)

        # Auto-run dry-run preview if both endpoints are set
        if src_repo and dst_usb:
            win.after(400, lambda: _run_diag(True))

    def _run_exfat_repair(self):
        """Directed exFAT diagnosis/salvage/repair flow."""
        if sys.platform != "win32":
            messagebox.showinfo(APP_NAME, "exFAT Repair Utility currently supports Windows only.")
            return

        drives = self._enumerate_drives_for_clone()
        candidates: List[Dict] = []
        for d in drives:
            letter = (d.get("letter") or "").strip().replace("\\", "")
            if len(letter) >= 2 and letter[1] == ":" and letter[0].isalpha():
                fs = str(d.get("fs") or "").lower()
                if d.get("is_usb") or fs in {"exfat", "raw", "unknown"}:
                    candidates.append(d)

        if not candidates:
            for d in drives:
                letter = (d.get("letter") or "").strip().replace("\\", "")
                if len(letter) >= 2 and letter[1] == ":" and letter[0].isalpha():
                    candidates.append(d)

        if not candidates:
            messagebox.showwarning(
                APP_NAME,
                "No drive letters detected.\nAttach the target drive and click Re-Scan Drives."
            )
            return

        drive_choices = []
        default_drive = ""
        for d in candidates:
            letter = (d.get("letter") or "").strip().replace("\\", "")
            fs = d.get("fs") or "unknown"
            label = d.get("label") or "(no label)"
            dtype = "USB" if d.get("is_usb") else (d.get("drive_type") or "drive")
            item = f"{letter} | {fs} | {label} | {dtype}"
            drive_choices.append(item)
            if letter.upper().startswith("F:"):
                default_drive = item
        if not default_drive:
            for item in drive_choices:
                if item.upper().startswith("K:"):
                    default_drive = item
                    break
        if not default_drive:
            default_drive = drive_choices[0]

        picked_drive = self._ask_choice(
            "exFAT Repair Utility",
            "Select drive to inspect/repair:",
            drive_choices,
            default_drive
        )
        if not picked_drive:
            return
        drive_letter = picked_drive.split("|", 1)[0].strip()

        mode_labels = [
            "Inspect only (safe, no writes)",
            "Salvage readable files (safe copy)",
            "Repair scan (admin)",
            "Repair fix /f /x (admin)",
            "Deep repair /f /r /x (admin, slow)",
        ]
        mode_map = {
            mode_labels[0]: "inspect",
            mode_labels[1]: "salvage",
            mode_labels[2]: "repair_scan",
            mode_labels[3]: "repair_fix",
            mode_labels[4]: "repair_deep",
        }
        picked_mode_label = self._ask_choice(
            "exFAT Repair Utility",
            "Select repair mode:",
            mode_labels,
            mode_labels[0]
        )
        if not picked_mode_label:
            return
        mode = mode_map[picked_mode_label]

        if mode in {"repair_fix", "repair_deep"}:
            proceed = messagebox.askyesno(
                APP_NAME,
                f"{mode} will attempt filesystem fixes on {drive_letter} and may lock/disconnect the drive.\n\nProceed?"
            )
            if not proceed:
                return

        timeout_by_mode = {
            "inspect": 420,
            "salvage": 3600,
            "repair_scan": 900,
            "repair_fix": 5400,
            "repair_deep": 21600,
        }
        recovery_root = REPO / "exfat_recovery"
        recovery_root.mkdir(parents=True, exist_ok=True)

        script = _ps_exfat_repair(drive_letter, mode, str(recovery_root))
        tile = next((t for t in TILES if t["id"] == "exfat_repair"), {"title": "exFAT Repair Utility"})
        self._launch_op(
            lambda lf, s=script, to=timeout_by_mode.get(mode, 900): _ps(s, lf, timeout=to),
            tile
        )

    def _enumerate_drives_for_clone(self) -> List[Dict]:
        """
        Full physical drive scan: returns list of dicts with keys:
        letter, label, fs, drive_type, total_gb, free_gb, is_usb,
        is_raw, has_citl, instance_id, disk_model
        Includes RAW/unformatted partitions (critical for flagging).
        """
        drives: List[Dict] = []
        if sys.platform != "win32":
            # Linux: use /proc/mounts + lsblk
            try:
                import subprocess as sp
                r = sp.run(["lsblk", "-o", "NAME,MOUNTPOINT,FSTYPE,SIZE,MODEL,RM,LABEL",
                            "--json", "-b"], capture_output=True, text=True, timeout=10)
                import json as _json
                data = _json.loads(r.stdout)
                for dev in data.get("blockdevices", []):
                    for child in dev.get("children", [dev]):
                        mp = child.get("mountpoint") or ""
                        if not mp:
                            continue
                        root = Path(mp)
                        fs   = child.get("fstype") or "unknown"
                        is_raw = fs in ("", None, "unknown")
                        sz  = int(child.get("size") or 0)
                        free = 0
                        try:
                            import shutil
                            free = shutil.disk_usage(mp).free
                        except Exception:
                            pass
                        inst = _load_instance_id(root)
                        drives.append({
                            "letter": mp, "label": child.get("label") or "",
                            "fs": fs, "drive_type": "Removable" if child.get("rm") else "Fixed",
                            "total_gb": round(sz/1e9, 1), "free_gb": round(free/1e9, 1),
                            "is_usb": bool(child.get("rm")),
                            "is_raw": is_raw,
                            "has_citl": (root / "1-CITL-SYNC").exists() or
                                        (root / "factbook-assistant").exists(),
                            "instance_id": inst.get("instance_id", "") if inst else "",
                            "disk_model": dev.get("model") or "",
                        })
            except Exception:
                pass
            return drives

        # Windows: WMI via PowerShell
        ps = r"""
$result = @()
$vols = Get-Volume -ErrorAction SilentlyContinue
$parts = Get-Partition -ErrorAction SilentlyContinue
$disks = Get-Disk -ErrorAction SilentlyContinue

# First, find all drives with volumes/partitions
foreach ($vol in $vols) {
    if (-not $vol.DriveLetter) { continue }
    $letter = "$($vol.DriveLetter):\"
    $part = $parts | Where-Object { $_.DriveLetter -eq $vol.DriveLetter } | Select-Object -First 1
    $disk = if ($part) { $disks | Where-Object { $_.Number -eq $part.DiskNumber } | Select-Object -First 1 } else { $null }
    $isUsb = ($disk -and $disk.BusType -eq 'USB') -or ($vol.DriveType -eq 'Removable')
    $isRaw = $vol.FileSystemType -in @('Unknown','') -or -not $vol.FileSystemType
    $freeGb = [math]::Round($vol.SizeRemaining / 1GB, 2)
    $totalGb = [math]::Round($vol.Size / 1GB, 2)
    $hasCitl = (Test-Path "${letter}1-CITL-SYNC") -or (Test-Path "${letter}factbook-assistant")
    $instId = ""
    $instPath = "${letter}citl_instance.json"
    if (Test-Path $instPath) {
        try { $instId = (Get-Content $instPath | ConvertFrom-Json).instance_id } catch {}
    }
    $diskModel = if ($disk) { $disk.FriendlyName } else { "" }
    $result += [PSCustomObject]@{
        letter=$letter; label=$vol.FileSystemLabel; fs=$vol.FileSystemType;
        drive_type=$vol.DriveType; total_gb=$totalGb; free_gb=$freeGb;
        is_usb=$isUsb; is_raw=$isRaw; has_citl=$hasCitl;
        instance_id=$instId; disk_model=$diskModel
    }
}

# Find RAW partitions that have a drive letter but no Volume entry
foreach ($part in ($parts | Where-Object { $_.DriveLetter })) {
    $letter = "$($part.DriveLetter):\"
    $exists = $result | Where-Object { $_.letter -eq $letter }
    if (-not $exists) {
        $disk = $disks | Where-Object { $_.Number -eq $part.DiskNumber } | Select-Object -First 1
        $isUsb = $disk -and $disk.BusType -eq 'USB'
        $sizeGb = [math]::Round($part.Size/1GB, 2)
        $diskModel = if ($disk) { $disk.FriendlyName } else { "" }
        $result += [PSCustomObject]@{
            letter=$letter; label="(unformatted)"; fs="RAW";
            drive_type="Removable"; total_gb=$sizeGb; free_gb=0;
            is_usb=$isUsb; is_raw=$true; has_citl=$false;
            instance_id=""; disk_model=$diskModel
        }
    }
}

# CRITICAL: Find completely blank disks with NO partitions at all
# These won't show up in Get-Volume or Get-Partition but are physical disks
foreach ($disk in $disks) {
    $hasPartition = $parts | Where-Object { $_.DiskNumber -eq $disk.Number }
    if (-not $hasPartition -and $disk.Size -gt 0) {
        # This is a completely blank disk - no partitions
        $sizeGb = [math]::Round($disk.Size / 1GB, 2)
        $isUsb = $disk.BusType -eq 'USB'
        $diskModel = $disk.FriendlyName
        # Generate a pseudo-letter for identification (disk number based)
        $pseudoLetter = "Disk$($disk.Number)"
        $result += [PSCustomObject]@{
            letter="$pseudoLetter"; label="(blank disk)"; fs="NO PARTITIONS";
            drive_type="Unpartitioned"; total_gb=$sizeGb; free_gb=0;
            is_usb=$isUsb; is_raw=$true; has_citl=$false;
            instance_id=""; disk_model=$diskModel
        }
    }
}

$result | ConvertTo-Json -Compress
"""
        try:
            import subprocess as sp, json as _json
            r = sp.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=15)
            raw = r.stdout.strip()
            if raw.startswith("["):
                items = _json.loads(raw)
            elif raw.startswith("{"):
                items = [_json.loads(raw)]
            else:
                items = []
            for item in items:
                drives.append({
                    "letter":      item.get("letter", ""),
                    "label":       item.get("label") or "",
                    "fs":          item.get("fs") or "unknown",
                    "drive_type":  item.get("drive_type") or "",
                    "total_gb":    float(item.get("total_gb") or 0),
                    "free_gb":     float(item.get("free_gb") or 0),
                    "is_usb":      bool(item.get("is_usb")),
                    "is_raw":      bool(item.get("is_raw")),
                    "has_citl":    bool(item.get("has_citl")),
                    "instance_id": item.get("instance_id") or "",
                    "disk_model":  item.get("disk_model") or "",
                })
        except Exception:
            pass
        return drives

    def _run_clone_usb(self):
        """Full drive scan dialog: space check, RAW warning, Rufus offer, then clone."""
        win = tk.Toplevel(self)
        win.title("Clone USB Drive — Drive Diagnostic")
        win.configure(bg=C["bg"])
        win.geometry("860x660")
        win.minsize(720, 520)
        win.attributes("-topmost", True)

        # ---- Header ----
        tk.Frame(win, bg=C["accent"], height=4).pack(fill="x")
        hdr = tk.Frame(win, bg=C["panel"], pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="CLONE USB DRIVE", font=(_F, 13, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(side="left", padx=14)
        scan_status = tk.StringVar(value="Scanning drives...")
        tk.Label(hdr, textvariable=scan_status, font=(_F, 9),
                 bg=C["panel"], fg=C["muted"]).pack(side="right", padx=14)

        # ---- Drive list canvas ----
        tk.Label(win, text="DETECTED DRIVES  (all physical + logical)",
                 font=(_F, 8, "bold"), bg=C["bg"], fg=C["faint"],
                 anchor="w").pack(fill="x", padx=12, pady=(8, 2))

        list_frame = tk.Frame(win, bg=C["panel"], padx=4, pady=4)
        list_frame.pack(fill="x", padx=10, pady=2)

        # ---- Source / Target selectors ----
        sel_frame = tk.Frame(win, bg=C["bg"])
        sel_frame.pack(fill="x", padx=10, pady=4)
        sel_frame.columnconfigure(1, weight=1)
        sel_frame.columnconfigure(3, weight=1)

        tk.Label(sel_frame, text="SOURCE:", font=(_F, 9, "bold"),
                 bg=C["bg"], fg=C["out_ok"]).grid(row=0, column=0, padx=(0,4), sticky="e")
        src_var = tk.StringVar(value=str(self._selected_usb) if self._selected_usb else "")
        src_cb = ttk.Combobox(sel_frame, textvariable=src_var, font=(_F, 9),
                              width=28, state="normal")
        src_cb.grid(row=0, column=1, sticky="ew", padx=4)

        tk.Label(sel_frame, text="TARGET:", font=(_F, 9, "bold"),
                 bg=C["bg"], fg=C["out_warn"]).grid(row=0, column=2, padx=(12,4), sticky="e")
        dst_var = tk.StringVar(value="")
        dst_cb = ttk.Combobox(sel_frame, textvariable=dst_var, font=(_F, 9),
                              width=28, state="normal")
        dst_cb.grid(row=0, column=3, sticky="ew", padx=4)

        # ---- Space summary label ----
        space_var = tk.StringVar(value="")
        space_lbl = tk.Label(win, textvariable=space_var, font=("Consolas", 9),
                             bg=C["bg"], fg=C["gold"], anchor="w", wraplength=820)
        space_lbl.pack(fill="x", padx=14, pady=2)

        # ---- Warning banner (RAW drives) ----
        warn_frame = tk.Frame(win, bg="#4A1A00", padx=10, pady=6)
        warn_lbl = tk.Label(warn_frame, text="", font=(_F, 9),
                            bg="#4A1A00", fg="#FFB060", justify="left",
                            wraplength=800, anchor="w")
        warn_lbl.pack(fill="x")
        warn_frame.pack_forget()

        # ---- Mode selector ----
        mode_frame = tk.Frame(win, bg=C["bg"])
        mode_frame.pack(fill="x", padx=10, pady=4)
        tk.Label(mode_frame, text="What to clone:", font=(_F, 9, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(side="left", padx=(0,8))
        mode_var = tk.StringVar(value="all")
        for lbl, val in [("All CITL (recommended)", "all"),
                          ("Sync Hub + App Sync", "sync"),
                          ("Workstation Apps", "workstation"),
                          ("Field Apps", "field"),
                          ("Presentation", "presentation"),
                          ("Ticketing Automation", "ticketing")]:
            tk.Radiobutton(mode_frame, text=lbl, variable=mode_var, value=val,
                           font=(_F, 8), bg=C["bg"], fg=C["text"],
                           selectcolor=C["panel2"],
                           activebackground=C["bg"]).pack(side="left", padx=6)

        # ---- Action buttons ----
        btn_row = tk.Frame(win, bg=C["bg"])
        btn_row.pack(fill="x", padx=10, pady=(4, 8))
        start_btn = tk.Button(btn_row, text="Start Clone", font=(_F, 9, "bold"),
                              bg=C["btn_acc"], fg=C["text"], relief="flat",
                              padx=16, pady=6, cursor="hand2", state="disabled")
        start_btn.pack(side="left", padx=4)
        rufus_btn = tk.Button(btn_row, text="Format with Rufus", font=(_F, 9, "bold"),
                              bg="#8B4500", fg="white", relief="flat",
                              padx=12, pady=6, cursor="hand2")
        rufus_btn.pack(side="left", padx=4)
        winformat_btn = tk.Button(btn_row, text="Format (Windows)", font=(_F, 9),
                                  bg=C["btn"], fg=C["muted"], relief="flat",
                                  padx=10, pady=6, cursor="hand2")
        winformat_btn.pack(side="left", padx=4)
        tk.Button(btn_row, text="Re-Scan", font=(_F, 9),
                  bg=C["btn"], fg=C["muted"], relief="flat",
                  padx=10, pady=6, cursor="hand2",
                  command=lambda: threading.Thread(target=_scan, daemon=True).start()
                  ).pack(side="left", padx=4)
        tk.Button(btn_row, text="Cancel", font=(_F, 9),
                  bg=C["btn"], fg=C["muted"], relief="flat",
                  padx=10, pady=6, cursor="hand2",
                  command=win.destroy).pack(side="right", padx=4)

        state: Dict = {"drives": [], "raw_drives": []}

        def _find_rufus() -> Optional[str]:
            candidates = [
                str(REPO / "rufus-4.11.exe"),
                str(REPO / "rufus-4.5.exe"),
                str(REPO / "rufus.exe"),
                str(self._selected_usb / "rufus-4.11.exe") if self._selected_usb else "",
            ]
            for c in candidates:
                if c and Path(c).exists():
                    return c
            return None

        def _refresh_space(*_):
            src = src_var.get().strip().rstrip("\\/") + "\\"
            dst = dst_var.get().strip().rstrip("\\/") + "\\"
            drives_by_letter = {d["letter"].rstrip("\\") + "\\": d for d in state["drives"]}

            # Estimate CITL content size on source
            src_drive = drives_by_letter.get(src)
            dst_drive = drives_by_letter.get(dst)
            if not src_drive or not dst_drive:
                space_var.set("")
                start_btn.configure(state="disabled")
                return

            # Size estimate: total - free on source (rough) OR measure CITL folders
            src_size = src_drive["total_gb"] - src_drive["free_gb"]
            dst_free = dst_drive["free_gb"]
            fits = dst_free >= src_size
            space_var.set(
                f"SOURCE: {src}  [{src_drive['disk_model']}]  "
                f"{src_drive['fs']}  {src_drive['total_gb']}GB total  "
                f"{src_drive['total_gb']-src_drive['free_gb']:.1f}GB used    |    "
                f"TARGET: {dst}  [{dst_drive['disk_model']}]  "
                f"{dst_drive['fs']}  {dst_drive['total_gb']}GB total  "
                f"{dst_drive['free_gb']:.1f}GB free    |    "
                f"{'[OK] FITS' if fits else '[WARN] NOT ENOUGH SPACE — target needs {src_size:.1f}GB free'}"
            )
            # Enable start only if dst is not RAW and not same as src and fits
            if "Disk" in dst:  # Blank disk
                start_btn.configure(state="disabled")
                rufus_btn.configure(bg="#FF4500", fg="white", text="Format Blank Disk (Rufus)")
                winformat_btn.configure(state="disabled", text="Format (Windows) - N/A")
            elif dst_drive["is_raw"]:
                start_btn.configure(state="disabled")
                rufus_btn.configure(bg="#8B4500", fg="white", text="Format with Rufus")
                winformat_btn.configure(state="normal", text="Format (Windows)")
            elif src == dst:
                start_btn.configure(state="disabled")
                rufus_btn.configure(bg="#8B4500", fg="white", text="Format with Rufus")
                winformat_btn.configure(state="normal", text="Format (Windows)")
            elif not fits:
                start_btn.configure(state="disabled")
                rufus_btn.configure(bg="#8B4500", fg="white", text="Format with Rufus")
                winformat_btn.configure(state="normal", text="Format (Windows)")
            else:
                start_btn.configure(state="normal", bg=C["accent"], fg="white", cursor="hand2")
                rufus_btn.configure(bg="#8B4500", fg="white", text="Format with Rufus")
                winformat_btn.configure(state="normal", text="Format (Windows)")

        src_var.trace_add("write", _refresh_space)
        dst_var.trace_add("write", _refresh_space)

        def _format_rufus():
            dst = dst_var.get().strip()
            rufus = _find_rufus()
            if "Disk" in dst:  # Blank disk
                disk_num = dst.replace("Disk", "")
                if rufus:
                    import subprocess as sp
                    sp.Popen([rufus], shell=False)
                    messagebox.showinfo(APP_NAME,
                        f"Rufus launched for blank disk.\n\n"
                        f"Select disk: Disk {disk_num} ({state['drives'][0]['disk_model'] if state['drives'] else 'Unknown'})\n"
                        f"Partition scheme: GPT\n"
                        f"File system: exFAT\n"
                        f"Cluster size: default\n"
                        f"Volume label: CITL-USB\n\n"
                        f"⚠️  This will ERASE the entire disk!\n"
                        f"After formatting, click Re-Scan in the clone dialog.")
                else:
                    messagebox.showwarning(APP_NAME,
                        "Rufus not found in repo root.\n"
                        "Download rufus-4.11.exe from rufus.ie and place it in the CITL repo folder.\n\n"
                        f"For blank disk {dst}, you can also use Windows Disk Management (diskmgmt.msc).")
            else:  # Normal drive with letter
                if rufus:
                    import subprocess as sp
                    sp.Popen([rufus], shell=False)
                    messagebox.showinfo(APP_NAME,
                        f"Rufus launched.\n\n"
                        f"Select drive: {dst}\n"
                        f"File system: exFAT (recommended for CITL USB)\n"
                        f"Cluster size: default\n"
                        f"Volume label: CITL-USB\n\n"
                        f"After formatting, click Re-Scan in the clone dialog.")
                else:
                    messagebox.showwarning(APP_NAME,
                        "Rufus not found in repo root.\n"
                        "Download rufus-4.11.exe from rufus.ie and place it in the CITL repo folder.")
        rufus_btn.configure(command=_format_rufus)

        def _format_windows():
            dst = dst_var.get().strip().rstrip("\\/")
            if "Disk" in dst:  # Blank disk - can't use Windows format
                messagebox.showwarning(APP_NAME,
                    f"Cannot format blank disk {dst} with Windows tools.\n\n"
                    f"Use Rufus (recommended) or Windows Disk Management:\n"
                    f"1. Press Win+R, type 'diskmgmt.msc', press Enter\n"
                    f"2. Find Disk {dst.replace('Disk', '')} (unallocated)\n"
                    f"3. Right-click → New Simple Volume\n"
                    f"4. Assign drive letter, format as exFAT\n\n"
                    f"Then click Re-Scan in the clone dialog.")
                return

            letter = dst.rstrip(":\\")
            if not letter or len(letter) != 1:
                messagebox.showwarning(APP_NAME, "Select a valid target drive first.")
                return
            if not messagebox.askyesno("Format Drive",
                f"Format {dst} as exFAT?\n\n"
                f"⚠️  ALL DATA ON {dst} WILL BE ERASED.\n\n"
                f"Only do this if the drive is blank or needs reformatting."):
                return
            ps_fmt = f"""
Format-Volume -DriveLetter '{letter}' -FileSystem exFAT -NewFileSystemLabel 'CITL-USB' -Confirm:$false -Force
Write-Host "[OK] Drive {letter}: formatted as exFAT with label CITL-USB"
"""
            tile = next((t for t in TILES if t["id"] == "clone_usb"), TILES[0])
            win.destroy()
            self._launch_op(lambda lf: _ps(ps_fmt, lf, timeout=60), tile)
        winformat_btn.configure(command=_format_windows)

        def _populate_drive_rows(drives: List[Dict]):
            for widget in list_frame.winfo_children():
                widget.destroy()
            # Column headers
            hdr_row = tk.Frame(list_frame, bg=C["card"])
            hdr_row.pack(fill="x", pady=(0, 2))
            for col, w, txt in [
                (0, 8,  "DRIVE"),
                (1, 18, "MODEL"),
                (2, 6,  "FS"),
                (3, 5,  "TYPE"),
                (4, 7,  "TOTAL"),
                (5, 7,  "FREE"),
                (6, 14, "INSTANCE ID"),
                (7, 10, "STATUS"),
            ]:
                tk.Label(hdr_row, text=txt, font=(_F, 7, "bold"),
                         bg=C["card"], fg=C["faint"], width=w,
                         anchor="w").grid(row=0, column=col, padx=3, sticky="w")

            all_letters = []
            for d in drives:
                row = tk.Frame(list_frame, bg=C["panel2"], pady=2,
                               highlightthickness=1,
                               highlightbackground=C["line"])
                row.pack(fill="x", pady=1)

                if d["is_raw"]:
                    if "Disk" in d["letter"]:  # Completely blank disk
                        row_bg = "#5A1A00"
                        status_txt = "⚠ BLANK DISK — NEEDS PARTITIONING"
                        status_fg  = "#FF8080"
                    else:  # RAW partition with drive letter
                        row_bg = "#3A1A00"
                        status_txt = "⚠ RAW PARTITION — NEEDS FORMATTING"
                        status_fg  = "#FFB060"
                elif d["has_citl"]:
                    row_bg = "#1A2A1A"
                    status_txt = "✓ CITL"
                    status_fg  = C["out_ok"]
                else:
                    row_bg = C["panel2"]
                    status_txt = "ready"
                    status_fg  = C["muted"]
                row.configure(bg=row_bg)

                vals = [
                    d["letter"],
                    d["disk_model"][:22],
                    d["fs"] or "RAW",
                    d["drive_type"][:8],
                    f"{d['total_gb']}GB",
                    f"{d['free_gb']}GB",
                    d["instance_id"] or "(none)",
                    status_txt,
                ]
                fg_cols = [C["text"], C["muted"], C["text"], C["muted"],
                           C["text"], C["out_ok"], C["gold"], status_fg]
                widths   = [8, 18, 6, 5, 7, 7, 14, 10]
                for col, (val, fg, w) in enumerate(zip(vals, fg_cols, widths)):
                    tk.Label(row, text=val, font=("Consolas", 8),
                             bg=row_bg, fg=fg, width=w,
                             anchor="w").grid(row=0, column=col, padx=3, sticky="w")

                # SET AS SRC / DST buttons
                def _set_src(letter=d["letter"]):
                    src_var.set(letter)
                def _set_dst(letter=d["letter"], raw=d["is_raw"]):
                    dst_var.set(letter)
                    if raw:
                        warn_frame.pack(fill="x", padx=10, pady=2)
                        if "Disk" in letter:  # Completely blank disk
                            warn_lbl.configure(text=
                                f"🚨 CRITICAL: {letter} is a COMPLETELY BLANK DISK with no partitions!\n"
                                f"    Windows cannot access it until you create a partition and format it.\n"
                                f"    Use Rufus (recommended) or Windows Disk Management to partition and format.\n"
                                f"    Select 'GPT partition scheme' and 'exFAT' file system for USB drives.\n\n"
                                f"    After partitioning/formatting, the drive will get a letter (like F:) and appear as a normal drive.")
                        else:  # RAW partition with drive letter
                            warn_lbl.configure(text=
                                f"⚠️  WARNING: {letter} has a RAW partition — Windows cannot read or write to it.\n"
                                f"    You must format it first (exFAT recommended for USB drives).\n"
                                f"    Click 'Format with Rufus' (recommended) or 'Format (Windows)' below, then Re-Scan.")
                    else:
                        warn_frame.pack_forget()
                tk.Button(row, text="SRC", font=(_F, 7), bg=C["btn"],
                          fg=C["out_ok"], relief="flat", padx=5, pady=1,
                          cursor="hand2", command=_set_src).grid(
                    row=0, column=8, padx=2)
                tk.Button(row, text="DST", font=(_F, 7), bg=C["btn"],
                          fg=C["out_warn"], relief="flat", padx=5, pady=1,
                          cursor="hand2", command=_set_dst).grid(
                    row=0, column=9, padx=2)

                all_letters.append(d["letter"])
            src_cb["values"] = all_letters
            dst_cb["values"] = all_letters
            _refresh_space()

        def _scan():
            win.after(0, lambda: scan_status.set("Scanning all drives..."))
            drives = self._enumerate_drives_for_clone()
            state["drives"] = drives
            state["raw_drives"] = [d for d in drives if d["is_raw"] and d["is_usb"]]
            win.after(0, lambda: _populate_drive_rows(drives))
            win.after(0, lambda: scan_status.set(
                f"{len(drives)} drives found  |  "
                f"{sum(1 for d in drives if d['has_citl'])} with CITL  |  "
                f"{len(state['raw_drives'])} RAW/unformatted USB"))

        threading.Thread(target=_scan, daemon=True).start()

        def _start_clone():
            src = src_var.get().strip()
            dst = dst_var.get().strip()
            mode = mode_var.get()
            if not src or not dst:
                messagebox.showwarning(APP_NAME, "Select both source and target drives.")
                return
            if src.rstrip("\\/") == dst.rstrip("\\/"):
                messagebox.showerror(APP_NAME, "Source and target cannot be the same drive!")
                return
            dst_drive = next((d for d in state["drives"]
                              if d["letter"].rstrip("\\") == dst.rstrip("\\")), None)
            if "Disk" in dst:  # Blank disk
                messagebox.showerror(APP_NAME,
                    f"Cannot clone to blank disk {dst}.\n"
                    "Format it first with Rufus or Windows Disk Management, then Re-Scan.")
                return
            if dst_drive and dst_drive["is_raw"]:
                messagebox.showerror(APP_NAME,
                    f"Target {dst} is RAW/unformatted.\n"
                    "Format it first with Rufus or Windows format, then Re-Scan.")
                return
            win.destroy()
            tile = next((t for t in TILES if t["id"] == "clone_usb"), TILES[0])
            self._launch_op(lambda lf, s=src, d=dst, m=mode: _ps(
                _ps_clone_usb(s, d, m) if sys.platform == "win32"
                else _bash_clone_usb(s, d, m), lf, timeout=600), tile)

        start_btn.configure(command=_start_clone)

    def _run_make_zip(self):
        """Build a portable ZIP archive of all CITL app bundles."""
        repo = str(self._selected_repo or REPO)
        out_choices = [
            repo,
            str(Path.home() / "Desktop"),
            str(Path.home() / "Downloads"),
        ]
        out_dir = self._ask_choice("Make Portable ZIP", "Save ZIP to:", out_choices, out_choices[0])
        if not out_dir:
            return

        tile = next((t for t in TILES if t["id"] == "make_zip"), TILES[0])

        if sys.platform == "win32":
            ps1 = Path(repo) / "scripts" / "windows" / "make_portable_zip.ps1"
            if not ps1.exists():
                messagebox.showerror(APP_NAME,
                    "make_portable_zip.ps1 not found.\nSelect the correct repo.")
                return
            self._launch_op(lambda lf, p=str(ps1), o=out_dir: _ps(
                f"& '{p}' -OutDir '{o}' -Silent", lf, timeout=300), tile)
        else:
            # Linux: build ZIP using Python zipfile + rsync logic
            dist_dir = Path(repo) / "dist"
            stamp = datetime.now().strftime("%Y-%m-%d")
            zip_path = str(Path(out_dir) / f"CITL-Portable-Suite_{stamp}.zip")
            script = f"""
import zipfile, shutil, os, sys
from pathlib import Path
repo   = Path('{repo}')
dist   = Path('{str(dist_dir)}')
zpath  = '{zip_path}'
print("=== CITL PORTABLE ZIP (Linux) ===")
print(f"Output: {{zpath}}")
bundles = list(dist.glob("CITL *")) if dist.exists() else []
if not bundles:
    print("[ERROR] No dist/ bundles found. Build EXEs on Windows first, or zip source.")
    # Zip the Python source as fallback
    bundles = []
    skip_dirs = {{'.git', '__pycache__', '.venv', 'models', 'ollama', 'blobs', 'build', 'dist'}}
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                fp = Path(root) / f
                if fp.stat().st_size > 500*1024*1024: continue
                z.write(fp, fp.relative_to(repo.parent))
    print(f"[OK] Source ZIP: {{zpath}}")
    sys.exit(0)
with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
    for bundle in bundles:
        print(f"Adding {{bundle.name}}...")
        for fp in bundle.rglob('*'):
            if fp.is_file():
                z.write(fp, Path('CITL-Portable-Suite') / bundle.name / fp.relative_to(bundle))
import os
sz = round(os.path.getsize(zpath)/1e6, 1)
print(f"[OK] ZIP created: {{zpath}}  ({{sz}} MB)")
"""
            self._launch_op(lambda lf, s=script: _ps(
                f"python3 -c {repr(s)}", lf, timeout=300), tile)

    def _launch_op(self, fn: Callable, tile: Dict):
        """Launch operation with animated progress dialog + real-time log."""
        self._busy = True
        self._run_btn.configure(state="disabled", bg=C["btn"])

        # ---- Build progress popup ----
        prog_win = tk.Toplevel(self)
        prog_win.title(f"CITL - {tile['title']}")
        prog_win.configure(bg=C["bg"])
        prog_win.resizable(True, True)
        prog_win.geometry("780x480")
        prog_win.minsize(640, 380)
        prog_win.attributes("-topmost", True)
        # Center over main window
        self.update_idletasks()
        mx = self.winfo_x() + (self.winfo_width() - 780) // 2
        my = self.winfo_y() + 60
        prog_win.geometry(f"780x480+{mx}+{my}")

        # Header
        tk.Frame(prog_win, bg=C["accent"], height=4).pack(fill="x")
        hdr = tk.Frame(prog_win, bg=C["panel"], pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=tile["title"].upper(), font=(_F, 13, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(side="left", padx=16)
        self._prog_status_var = tk.StringVar(value="Starting...")
        tk.Label(hdr, textvariable=self._prog_status_var, font=(_F, 9),
                 bg=C["panel"], fg=C["muted"]).pack(side="right", padx=16)

        # Animated indeterminate progress bar
        bar_frame = tk.Frame(prog_win, bg=C["bg"], pady=4)
        bar_frame.pack(fill="x", padx=12)
        style = ttk.Style()
        style.configure("CITL.Horizontal.TProgressbar",
                         troughcolor=C["panel"], background=C["accent"],
                         darkcolor=C["accent"], lightcolor=C["gold"],
                         bordercolor=C["line"], thickness=14)
        self._prog_bar = ttk.Progressbar(
            bar_frame, orient="horizontal", mode="indeterminate",
            style="CITL.Horizontal.TProgressbar", length=750)
        self._prog_bar.pack(fill="x")
        self._prog_bar.start(12)

        # Stats row: files seen, KB transferred
        stats_frame = tk.Frame(prog_win, bg=C["bg"])
        stats_frame.pack(fill="x", padx=14, pady=2)
        self._stat_files_var = tk.StringVar(value="Files: 0")
        self._stat_kb_var    = tk.StringVar(value="Data: 0 KB")
        self._stat_ok_var    = tk.StringVar(value="")
        tk.Label(stats_frame, textvariable=self._stat_files_var,
                 font=("Consolas", 9), bg=C["bg"], fg=C["muted"]).pack(side="left", padx=8)
        tk.Label(stats_frame, textvariable=self._stat_kb_var,
                 font=("Consolas", 9), bg=C["bg"], fg=C["muted"]).pack(side="left", padx=8)
        self._stat_label = tk.Label(stats_frame, textvariable=self._stat_ok_var,
                 font=("Consolas", 9, "bold"), bg=C["bg"], fg=C["out_ok"])
        self._stat_label.pack(side="right", padx=8)

        # Real-time log console
        prog_console = scrolledtext.ScrolledText(
            prog_win, bg=C["out_bg"], fg=C["out_fg"],
            font=("Consolas", 8), wrap="none", relief="flat")
        prog_console.pack(fill="both", expand=True, padx=10, pady=4)
        prog_console.tag_configure("ok",   foreground=C["out_ok"])
        prog_console.tag_configure("warn", foreground=C["out_warn"])
        prog_console.tag_configure("err",  foreground=C["out_err"])
        prog_console.tag_configure("head", foreground=C["gold"],
                                    font=("Consolas", 8, "bold"))

        # Result banner (shown after completion)
        self._result_banner = tk.Frame(prog_win, bg=C["panel2"], pady=0)
        self._result_banner.pack(fill="x", padx=10, pady=(0, 2))
        self._result_banner_lbl = tk.Label(self._result_banner, text="",
                 font=(_F, 10, "bold"), bg=C["panel2"], fg=C["text"],
                 anchor="w", padx=14, pady=8)
        self._result_banner_lbl.pack(fill="x")
        self._result_banner.pack_forget()  # hidden until done

        # Close button (disabled until done)
        close_btn = tk.Button(prog_win, text="Running...", font=(_F, 9, "bold"),
                              bg=C["btn"], fg=C["muted"], relief="flat",
                              padx=20, pady=6, state="disabled", cursor="watch")
        close_btn.pack(pady=(0, 10))

        # Counters for stats
        file_count = [0]
        kb_total   = [0]

        def _prog_log(text: str):
            """Write to progress window console with tagging and stat tracking."""
            lo = text.lower()
            tag = None
            if "[ok]" in lo or "[ ok ]" in lo or "success" in lo or "done" in lo:
                tag = "ok"
            elif "[warn]" in lo or "warning" in lo or "stale" in lo:
                tag = "warn"
            elif "[error]" in lo or "[fail]" in lo or "failed" in lo or "error" in lo or "access denied" in lo:
                tag = "err"
            elif "===" in text or "---" in text:
                tag = "head"

            # Count files and KB from rsync/robocopy output patterns
            import re
            # rsync: "   123,456 100%  1.23MB/s"  or  "sending ... bytes"
            # robocopy: "   New File  ...  12,345  filename"
            kb_match = re.search(r'(\d[\d,]+)\s+bytes', text.replace(',', ''))
            if kb_match:
                kb_total[0] += int(kb_match.group(1).replace(',', '')) // 1024
            if re.search(r'\.(py|cmd|sh|json|txt|exe|dll|so|pyd|yaml|md|cfg)\b', text, re.I):
                file_count[0] += 1

            def _insert():
                if tag:
                    prog_console.insert("end", text + "\n", tag)
                else:
                    prog_console.insert("end", text + "\n")
                prog_console.see("end")
                self._stat_files_var.set(f"Files: {file_count[0]}")
                kb = kb_total[0]
                self._stat_kb_var.set(f"Data: {kb if kb < 1024 else round(kb/1024,1)} {'KB' if kb < 1024 else 'MB'}")
                self._prog_status_var.set(text[:72] + "..." if len(text) > 72 else text)
            prog_win.after(0, _insert)

        # Also mirror to main console
        def _dual_log(text: str):
            _prog_log(text)
            self._log_line(text)

        self._log(f"\n{'='*60}", "head")
        self._log(f"  {tile['title'].upper()}  --  {datetime.now():%H:%M:%S}", "head")
        self._log(f"{'='*60}\n", "head")

        def _work():
            rc = fn(_dual_log)
            success = rc == 0 or (rc is not None and rc <= 7)

            def _finish():
                self._prog_bar.stop()
                # Switch bar to determinate showing 100%
                self._prog_bar.configure(mode="determinate")
                self._prog_bar["value"] = 100
                # Color-code bar: green=success, red=fail
                bar_color = C["out_ok"] if success else C["out_err"]
                style.configure("CITL.Horizontal.TProgressbar", background=bar_color)

                # Result banner
                if success:
                    banner_bg  = "#1A4A1A"
                    banner_fg  = C["out_ok"]
                    banner_txt = f"  SUCCESS  {tile['title']} completed  |  Files: {file_count[0]}  |  Data: {kb_total[0]} KB  |  Exit: {rc}"
                else:
                    banner_bg  = "#4A0A0A"
                    banner_fg  = C["out_err"]
                    banner_txt = f"  FAILED  {tile['title']}  |  Exit code: {rc}  |  Check log above for details"
                self._result_banner.configure(bg=banner_bg)
                self._result_banner_lbl.configure(text=banner_txt, bg=banner_bg, fg=banner_fg)
                self._result_banner.pack(fill="x", padx=10, pady=(0, 2))

                self._stat_ok_var.set("SUCCESS" if success else "FAILED")
                self._stat_label.configure(fg=C["out_ok"] if success else C["out_err"])
                self._prog_status_var.set("Done." if success else "Failed — see log.")

                close_btn.configure(
                    text="Close",
                    bg=C["btn_ok"] if success else C["err"],
                    fg="white",
                    state="normal",
                    cursor="hand2",
                    command=prog_win.destroy)
                self._run_btn.configure(state="normal", bg=C["accent"])
                self._status(f"{tile['title']} {'complete' if success else 'FAILED'} (exit {rc}).")
                self._busy = False
                self._log(f"\n[Exit code: {rc}]\n", "ok" if success else "err")

            prog_win.after(0, _finish)

        threading.Thread(target=_work, daemon=True).start()

    def _run_status_check(self):
        self._busy = True
        self._run_btn.configure(state="disabled", bg=C["btn"])
        self._status("Checking app bundle status...")
        self._log("\n" + "="*60 + "\n  APP BUNDLE STATUS\n" + "="*60 + "\n", "head")

        def _work():
            # Check numbered USB folders
            usb = self._selected_usb
            if usb:
                self._log_line(f"USB target: {usb}")
                for name, folder, exe in APP_BUNDLES:
                    path = usb / folder / exe
                    if path.exists():
                        try:
                            sz = sum(f.stat().st_size for f in (usb/folder).rglob("*")
                                     if f.is_file()) // (1024*1024)
                            mtime = path.stat().st_mtime
                            age = int((time.time() - mtime) / 86400)
                            self._log_line(f"  [OK]   {folder:38s}  {sz} MB  {age}d old")
                        except Exception:
                            self._log_line(f"  [OK]   {folder}")
                    else:
                        self._log_line(f"  [----] {folder:38s}  NOT BUILT")
            else:
                self._log_line("[WARN] No USB selected - skipping USB check")

            # Check local dist/
            repo = self._selected_repo
            if repo:
                self._log_line(f"\nLocal dist/ in: {repo}")
                dist = repo / "dist"
                ticket_dist = repo / "powerflow_builder" / "dist"
                if dist.exists() or ticket_dist.exists():
                    local_roots = {
                        "CITL Ticketing Automation GUI": ticket_dist,
                    }
                    for name, folder, exe in APP_BUNDLES:
                        root = local_roots.get(name, dist)
                        p = root / name / exe
                        if p.exists():
                            sz = sum(f.stat().st_size for f in p.parent.rglob("*")
                                     if f.is_file()) // (1024*1024)
                            self._log_line(f"  [OK]   {name:42s}  {sz} MB")
                        else:
                            self._log_line(f"  [----] {name:42s}  not built")
                else:
                    self._log_line("  dist/ not found - run BUILD_ALL_CITL_EXES_WINDOWS.cmd")
            else:
                self._log_line("[INFO] No local repo selected - skipping dist/ check")

            self.after(0, lambda: self._status("Status check complete."))
            self.after(0, lambda: self._run_btn.configure(state="normal", bg=C["accent"]))
            self.after(0, lambda: setattr(self, "_busy", False))

        threading.Thread(target=_work, daemon=True).start()

    # ------------------------------------------------------------------ Output helpers
    def _log_line(self, line: str):
        """Called from background thread."""
        self.after(0, lambda l=line: self._log(l))

    def _log(self, text: str, tag: Optional[str] = None):
        """Write to output console on main thread."""
        lo = text.lower()
        if tag is None:
            if "[ok]" in lo or "[ ok ]" in lo or "success" in lo or "done" in lo:
                tag = "ok"
            elif any(x in lo for x in ("[warn]", "warning", "stale")):
                tag = "warn"
            elif any(x in lo for x in ("[error]", "[fail]", "failed", "error")):
                tag = "err"
        if tag:
            self._output.insert("end", text + "\n", tag)
        else:
            self._output.insert("end", text + "\n")
        self._output.see("end")

    def _clear_output(self):
        self._output.delete("1.0", "end")

    def _status(self, msg: str):
        self._status_var.set(msg)

    # ------------------------------------------------------------------ Dialogs
    def _ask_choice(self, title: str, prompt: str,
                     choices: List[str], default: str) -> Optional[str]:
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=C["bg"])
        win.grab_set()
        win.geometry("520x180")
        result: List[Optional[str]] = [None]

        tk.Label(win, text=prompt, font=(_F, 10), bg=C["bg"],
                 fg=C["text"]).pack(pady=(16, 6), padx=16, anchor="w")
        var = tk.StringVar(value=default)
        cb = ttk.Combobox(win, textvariable=var, values=choices,
                           font=(_F, 10), width=56, state="normal")
        cb.pack(padx=16, fill="x")

        btns = tk.Frame(win, bg=C["bg"])
        btns.pack(fill="x", padx=16, pady=12)
        def _ok():
            result[0] = var.get().strip()
            win.destroy()
        tk.Button(btns, text="OK", font=(_F, 9, "bold"),
                  bg=C["btn_acc"], fg=C["text"], relief="flat",
                  padx=14, pady=6, cursor="hand2",
                  command=_ok).pack(side="left")
        tk.Button(btns, text="Cancel", font=(_F, 9),
                  bg=C["btn"], fg=C["muted"], relief="flat",
                  padx=10, pady=6, cursor="hand2",
                  command=win.destroy).pack(side="left", padx=6)
        win.wait_window()
        return result[0]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    if sys.platform not in ("win32", "linux", "darwin"):
        print(f"Unsupported platform: {sys.platform}")
        sys.exit(1)
    app = SyncHub()
    app.mainloop()


if __name__ == "__main__":
    main()
