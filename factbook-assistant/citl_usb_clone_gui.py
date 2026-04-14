#!/usr/bin/env python3
"""
Cross-platform USB Clone GUI for CITL
======================================

Hardened Tkinter GUI for cloning CITL USB repositories to new USB drives.

Features:
- Real-time progress tracking (file-by-file, KB transferred)
- Automatic USB device detection
- Source/destination device selection
- Optional format/wipe before clone (diskpart on Windows, mkfs.exfat on Linux)
- Bootstrap and Ollama model sync options
- Cross-platform: Windows 10/11, Ubuntu 22.04+
- Cancel support with graceful cleanup
- Comprehensive diagnostics panel
- Smoke test: verifies critical files exist on destination

Usage:
  python citl_usb_clone_gui.py
  python citl_usb_clone_gui.py --source F:\\
  python citl_usb_clone_gui.py --dry-run
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import string
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

# ── Try to import tkinter ─────────────────────────────────────────────────────
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, simpledialog
    HAS_TK = True
except ImportError:
    HAS_TK = False

# ── Platform detection ────────────────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

# ── Excludes (mirror citl_app_sync DEFAULT_EXCLUDES) ─────────────────────────
DEFAULT_EXCLUDES = [
    ".git/",
    "__pycache__/",
    "*.pyc",
    "node_modules/",
    "*.bak",
    "*.tmp",
    ".edge_headless_tmp/",
    "CITL-Portable-Suite_*.zip",
]

DATA_EXCLUDES = ["data/indexes/", "data/corpus/"]
MODEL_EXCLUDES = ["models/", "ollama/"]

# ── Smoke-test manifest: critical files that must exist after a successful clone
SMOKE_TEST_MANIFEST = [
    "factbook-assistant/citl_app_sync.py",
    "factbook-assistant/factbook_assistant_gui.py",
    "RUN_APP_SYNC_WINDOWS.cmd",
    "RUN_APP_SYNC_UBUNTU.sh",
    "COPY_THIS_USB_TO_NEXT_WINDOWS.cmd",
    "COPY_THIS_USB_TO_NEXT_UBUNTU.sh",
    "factbook-assistant/citl_usb_clone_gui.py",
]

# ── RTC dark-theme palette ────────────────────────────────────────────────────
COLORS = {
    "bg":       "#1a1a2e",
    "panel":    "#16213e",
    "accent":   "#e94560",
    "success":  "#0f9b58",
    "warn":     "#f5a623",
    "text":     "#e0e0e0",
    "muted":    "#888ba8",
    "border":   "#0f3460",
    "log_bg":   "#0d0d0d",
    "log_fg":   "#00ff41",
}


# ─────────────────────────────────────────────────────────────────────────────
#  Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UsbDevice:
    path: str
    label: str
    total_bytes: int
    used_bytes: int
    filesystem: str
    is_removable: bool

    @property
    def free_bytes(self) -> int:
        return max(0, self.total_bytes - self.used_bytes)

    @property
    def display_name(self) -> str:
        free_gb = self.free_bytes / (1024 ** 3)
        total_gb = self.total_bytes / (1024 ** 3)
        label = self.label or "USB"
        fs = self.filesystem or "?"
        return f"{label} ({self.path}) — {free_gb:.1f} GB free / {total_gb:.1f} GB  [{fs}]"


@dataclass
class CloneProgress:
    total_files: int = 0
    done_files: int = 0
    copied_files: int = 0
    skipped_files: int = 0
    error_files: int = 0
    bytes_copied: int = 0
    current_file: str = ""
    phase: str = "Idle"
    start_time: float = field(default_factory=time.time)
    cancelled: bool = False
    finished: bool = False
    messages: List[str] = field(default_factory=list)

    # Thread-safe append
    def log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.messages.append(f"[{ts}] {msg}")
        if len(self.messages) > 2000:
            self.messages = self.messages[-2000:]

    @property
    def pct(self) -> int:
        if self.total_files <= 0:
            return 0
        return min(100, int(100 * self.done_files / self.total_files))

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    @property
    def bytes_copied_kb(self) -> float:
        return self.bytes_copied / 1024

    @property
    def speed_kbps(self) -> float:
        e = self.elapsed
        return self.bytes_copied / 1024 / e if e > 0 else 0.0

    @property
    def eta_sec(self) -> float:
        if self.done_files <= 0 or self.total_files <= 0:
            return 0.0
        rate = self.done_files / self.elapsed if self.elapsed > 0 else 0
        return (self.total_files - self.done_files) / rate if rate > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  USB device detection
# ─────────────────────────────────────────────────────────────────────────────

def _win_drive_label(letter: str) -> str:
    """Volume label for a Windows drive letter (e.g. 'F')."""
    try:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.kernel32.GetVolumeInformationW(
            f"{letter}:\\", buf, 256, None, None, None, None, 0
        )
        return buf.value or f"Drive {letter}:"
    except Exception:
        return f"Drive {letter}:"


def _win_filesystem(letter: str) -> str:
    """Filesystem type for a Windows drive letter."""
    try:
        buf = ctypes.create_unicode_buffer(64)
        ctypes.windll.kernel32.GetVolumeInformationW(
            f"{letter}:\\", None, 0, None, None, None, buf, 64
        )
        return buf.value.lower() or "?"
    except Exception:
        return "?"


def get_usb_devices() -> List[UsbDevice]:
    """Return all removable USB drives detected on this machine."""
    devices: List[UsbDevice] = []

    if IS_WINDOWS:
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            try:
                dtype = ctypes.windll.kernel32.GetDriveTypeW(drive)
                if dtype != 2:          # 2 = DRIVE_REMOVABLE
                    continue
                total = ctypes.c_ulonglong(0)
                free  = ctypes.c_ulonglong(0)
                ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    drive,
                    ctypes.byref(free),
                    ctypes.byref(total),
                    None,
                )
                if not ok:
                    continue
                devices.append(UsbDevice(
                    path=drive,
                    label=_win_drive_label(letter),
                    total_bytes=total.value,
                    used_bytes=total.value - free.value,
                    filesystem=_win_filesystem(letter),
                    is_removable=True,
                ))
            except Exception:
                pass

    elif IS_LINUX:
        try:
            result = subprocess.run(
                ["lsblk", "-J", "-b", "-o", "NAME,RM,FSTYPE,MOUNTPOINT,SIZE,LABEL"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for disk in data.get("blockdevices", []):
                    if not disk.get("rm"):
                        continue
                    for part in disk.get("children", [disk]):
                        mp = part.get("mountpoint") or ""
                        if not mp:
                            continue
                        try:
                            st = shutil.disk_usage(mp)
                            devices.append(UsbDevice(
                                path=mp,
                                label=part.get("label") or part.get("name") or mp,
                                total_bytes=st.total,
                                used_bytes=st.used,
                                filesystem=(part.get("fstype") or "?").lower(),
                                is_removable=True,
                            ))
                        except Exception:
                            pass
        except Exception as e:
            print(f"[WARN] lsblk failed: {e}", file=sys.stderr)

    return devices


def citl_marker_present(path: str) -> bool:
    """Return True if path looks like a CITL repository root."""
    p = Path(path)
    return (
        (p / "factbook-assistant" / "citl_app_sync.py").exists()
        or (p / "RUN_APP_SYNC_WINDOWS.cmd").exists()
        or (p / "RUN_FACTBOOK.sh").exists()
        or (p / "1-CITL-SYNC").exists()
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Copy engine (real implementation with progress callbacks)
# ─────────────────────────────────────────────────────────────────────────────

def _build_excludes(include_data: bool, include_models: bool) -> List[str]:
    excludes = list(DEFAULT_EXCLUDES)
    if not include_data:
        excludes.extend(DATA_EXCLUDES)
    if not include_models:
        excludes.extend(MODEL_EXCLUDES)
    return excludes


def _is_excluded(rel_posix: str, excludes: List[str]) -> bool:
    import fnmatch
    for pat in excludes:
        if pat.endswith("/"):
            # Directory prefix match
            if rel_posix.startswith(pat) or ("/" + pat in rel_posix):
                return True
            # Also match bare name
            seg = pat.rstrip("/")
            if rel_posix == seg or rel_posix.startswith(seg + "/"):
                return True
        else:
            if fnmatch.fnmatch(rel_posix, pat):
                return True
            base = Path(rel_posix).name
            if fnmatch.fnmatch(base, pat):
                return True
    return False


def _count_files(source: Path, excludes: List[str]) -> int:
    """Count files that will be copied (for progress bar denominator)."""
    count = 0
    for root, dirs, files in os.walk(source):
        root_path = Path(root)
        rel = root_path.relative_to(source)
        rel_posix = rel.as_posix() if str(rel) != "." else ""
        # Prune excluded dirs
        dirs[:] = [
            d for d in dirs
            if not _is_excluded((rel_posix + "/" + d).lstrip("/"), excludes)
        ]
        for f in files:
            rel_file = (rel_posix + "/" + f).lstrip("/")
            if not _is_excluded(rel_file, excludes):
                count += 1
    return count


def run_copy(
    source: Path,
    dest: Path,
    progress: CloneProgress,
    include_data: bool,
    include_models: bool,
) -> None:
    """
    Copy source → dest, updating `progress` in-place as files are processed.
    Runs in a background thread; GUI polls `progress` via root.after().
    """
    excludes = _build_excludes(include_data, include_models)

    progress.phase = "Scanning files..."
    progress.log(f"Scanning {source} ...")
    progress.total_files = _count_files(source, excludes)
    progress.log(f"Files to process: {progress.total_files}")
    progress.phase = "Transferring"

    dest.mkdir(parents=True, exist_ok=True)
    source = source.resolve()

    for root, dirs, files in os.walk(source):
        if progress.cancelled:
            progress.log("Cancelled by user.")
            return

        root_path = Path(root)
        rel = root_path.relative_to(source)
        rel_posix = rel.as_posix() if str(rel) != "." else ""

        # Prune excluded dirs in-place so os.walk skips them
        dirs[:] = [
            d for d in dirs
            if not _is_excluded((rel_posix + "/" + d).lstrip("/"), excludes)
        ]

        for fname in files:
            if progress.cancelled:
                progress.log("Cancelled by user.")
                return

            rel_file = (rel_posix + "/" + fname).lstrip("/")
            if _is_excluded(rel_file, excludes):
                progress.skipped_files += 1
                progress.done_files += 1
                continue

            src_file = root_path / fname
            dst_file = dest / rel_file
            progress.current_file = rel_file

            try:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                src_stat = src_file.stat()
                needs_copy = (
                    not dst_file.exists()
                    or dst_file.stat().st_size != src_stat.st_size
                    or dst_file.stat().st_mtime < src_stat.st_mtime - 1.0
                )
                if needs_copy:
                    shutil.copy2(src_file, dst_file)
                    progress.bytes_copied += src_stat.st_size
                    progress.copied_files += 1
                else:
                    progress.skipped_files += 1
            except Exception as exc:
                progress.error_files += 1
                progress.log(f"ERROR copying {rel_file}: {exc}")

            progress.done_files += 1

    progress.phase = "Installing launchers"
    _install_launchers(dest, progress)

    progress.phase = "Generating Ubuntu bootstrap"
    _port_ubuntu(dest, progress)

    progress.phase = "Smoke test"
    _smoke_test(dest, progress)

    progress.phase = "Done" if progress.error_files == 0 else "Done (with errors)"
    progress.finished = True
    progress.log(
        f"Clone complete — copied={progress.copied_files} skipped={progress.skipped_files} "
        f"errors={progress.error_files} KB={progress.bytes_copied_kb:.1f} "
        f"elapsed={progress.elapsed:.0f}s"
    )


def _install_launchers(dest: Path, progress: CloneProgress) -> None:
    """Ensure the two USB clone launchers exist on the destination."""
    win_cmd = dest / "COPY_THIS_USB_TO_NEXT_WINDOWS.cmd"
    ub_sh   = dest / "COPY_THIS_USB_TO_NEXT_UBUNTU.sh"

    if not win_cmd.exists():
        win_cmd.write_text(
            "@echo off\r\n"
            ":: CITL USB Clone Launcher (Windows)\r\n"
            "cd /d \"%~dp0\"\r\n"
            "for /r \"%~dp0\" %%f in (citl_usb_clone_gui.py) do (\r\n"
            "    python \"%%f\" && goto :done\r\n"
            ")\r\n"
            "echo [ERROR] citl_usb_clone_gui.py not found on this drive.\r\n"
            ":done\r\n"
            "pause\r\n",
            encoding="utf-8",
        )
        progress.log("Installed COPY_THIS_USB_TO_NEXT_WINDOWS.cmd")

    if not ub_sh.exists():
        ub_sh.write_text(
            "#!/usr/bin/env bash\n"
            "# CITL USB Clone Launcher (Ubuntu/Linux)\n"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'GUI=$(find "$SCRIPT_DIR" -name "citl_usb_clone_gui.py" | head -1)\n'
            'if [ -z "$GUI" ]; then\n'
            '  echo "[ERROR] citl_usb_clone_gui.py not found on this drive."\n'
            '  exit 1\n'
            'fi\n'
            'python3 "$GUI" "$@"\n',
            encoding="utf-8",
        )
        try:
            ub_sh.chmod(0o755)
        except Exception:
            pass
        progress.log("Installed COPY_THIS_USB_TO_NEXT_UBUNTU.sh")


def _port_ubuntu(dest: Path, progress: CloneProgress) -> None:
    """Create/update Ubuntu launch scripts on the destination repo."""
    scripts = {
        "RUN_APP_SYNC_UBUNTU.sh": (
            "#!/usr/bin/env bash\n"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'python3 "$SCRIPT_DIR/factbook-assistant/citl_app_sync.py" "$@"\n'
        ),
        "COPY_THIS_USB_TO_NEXT_UBUNTU.sh": (
            "#!/usr/bin/env bash\n"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'GUI=$(find "$SCRIPT_DIR" -name "citl_usb_clone_gui.py" | head -1)\n'
            '[ -z "$GUI" ] && echo "[ERROR] clone GUI not found" && exit 1\n'
            'python3 "$GUI" "$@"\n'
        ),
    }
    for name, content in scripts.items():
        out = dest / name
        if not out.exists():
            try:
                out.write_text(content, encoding="utf-8")
                try:
                    out.chmod(0o755)
                except Exception:
                    pass
                progress.log(f"Installed {name}")
            except Exception as e:
                progress.log(f"WARN: could not write {name}: {e}")


def _smoke_test(dest: Path, progress: CloneProgress) -> None:
    """Verify that all critical CITL files are present on the destination."""
    progress.log("--- Smoke test ---")
    passed = 0
    failed = 0
    for rel in SMOKE_TEST_MANIFEST:
        target = dest / rel
        if target.exists():
            progress.log(f"  OK  {rel}")
            passed += 1
        else:
            progress.log(f"  MISSING  {rel}")
            failed += 1
            progress.error_files += 1
    progress.log(f"Smoke test: {passed} passed, {failed} missing")


# ─────────────────────────────────────────────────────────────────────────────
#  Format helpers
# ─────────────────────────────────────────────────────────────────────────────

def format_drive_windows(drive_letter: str, progress: CloneProgress) -> bool:
    """Format a Windows removable drive as exFAT using diskpart."""
    script = (
        f"select volume {drive_letter}\n"
        "format fs=exfat quick label=CITL\n"
        "exit\n"
    )
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="ascii")
    try:
        tmp.write(script)
        tmp.close()
        progress.log(f"Running diskpart format on {drive_letter}: ...")
        r = subprocess.run(
            ["diskpart", "/s", tmp.name],
            capture_output=True, text=True, timeout=60
        )
        progress.log(r.stdout.strip() or "(no output)")
        if r.returncode != 0:
            progress.log(f"diskpart error: {r.stderr.strip()}")
            return False
        return True
    except Exception as e:
        progress.log(f"Format failed: {e}")
        return False
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def format_drive_linux(mount_point: str, progress: CloneProgress) -> bool:
    """Unmount and format a Linux partition as exFAT."""
    try:
        # Get device from mount
        r = subprocess.run(["findmnt", "-n", "-o", "SOURCE", mount_point],
                           capture_output=True, text=True, timeout=10)
        device = r.stdout.strip()
        if not device:
            progress.log(f"Cannot find device for {mount_point}")
            return False
        progress.log(f"Unmounting {mount_point} ...")
        subprocess.run(["umount", mount_point], timeout=15)
        progress.log(f"Formatting {device} as exFAT ...")
        r2 = subprocess.run(["mkfs.exfat", "-n", "CITL", device],
                            capture_output=True, text=True, timeout=60)
        if r2.returncode != 0:
            progress.log(f"mkfs.exfat error: {r2.stderr.strip()}")
            return False
        progress.log("Format OK — remounting ...")
        subprocess.run(["mount", device, mount_point], timeout=15)
        return True
    except Exception as e:
        progress.log(f"Format failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Main GUI
# ─────────────────────────────────────────────────────────────────────────────

class CloneGui:
    def __init__(self, root: tk.Tk, source_usb: str = "", dry_run: bool = False):
        self.root = root
        self.source_usb = source_usb
        self.dry_run = dry_run
        self.devices: List[UsbDevice] = []
        self.progress = CloneProgress()
        self._clone_thread: Optional[threading.Thread] = None
        self._poll_job: Optional[str] = None
        self._log_tail_pos = 0

        # Widget attributes — declared here so type checkers can see them
        # (assigned in _build_* methods called from _build_ui)
        self.source_var: tk.StringVar
        self.dest_var: tk.StringVar
        self.source_combo: ttk.Combobox
        self.dest_combo: ttk.Combobox
        self.src_marker_var: tk.StringVar
        self.dst_marker_var: tk.StringVar
        self.format_var: tk.BooleanVar
        self.data_var: tk.BooleanVar
        self.models_var: tk.BooleanVar
        self.bootstrap_var: tk.BooleanVar
        self.progress_bar: ttk.Progressbar
        self.phase_var: tk.StringVar
        self.metrics_var: tk.StringVar
        self.log_text: tk.Text
        self.clone_btn: tk.Button
        self.cancel_btn: tk.Button

        self._apply_theme()
        self._build_ui()
        self._detect_devices()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        c = COLORS
        style.configure(".", background=c["bg"], foreground=c["text"],
                        fieldbackground=c["panel"], bordercolor=c["border"])
        style.configure("TLabel", background=c["bg"], foreground=c["text"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabelframe", background=c["panel"], foreground=c["text"],
                        bordercolor=c["border"])
        style.configure("TLabelframe.Label", background=c["panel"], foreground=c["accent"])
        style.configure("TCombobox", fieldbackground=c["panel"], foreground=c["text"],
                        background=c["panel"])
        style.configure("TProgressbar", troughcolor=c["panel"],
                        background=c["success"], thickness=18)
        style.configure("TCheckbutton", background=c["panel"], foreground=c["text"])
        self.root.config(bg=c["bg"])

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        c = COLORS
        self.root.title("CITL USB Clone Utility")
        self.root.geometry("1020x740")
        self.root.resizable(True, True)

        outer = tk.Frame(self.root, bg=c["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        # Title bar
        tk.Label(
            outer,
            text="CITL USB Clone Utility",
            font=("Segoe UI", 15, "bold"),
            bg=c["bg"], fg=c["accent"],
        ).pack(anchor=tk.W, pady=(0, 8))

        self._build_device_panel(outer)
        self._build_options_panel(outer)
        self._build_progress_panel(outer)
        self._build_log_panel(outer)
        self._build_buttons(outer)

    def _lf(self, parent: tk.Widget, text: str, expand: bool = False) -> tk.LabelFrame:
        """Create a styled LabelFrame, pack it, and return it."""
        c = COLORS
        lf = tk.LabelFrame(
            parent, text=text,
            font=("Segoe UI", 9, "bold"),
            bg=c["panel"], fg=c["accent"],
            padx=8, pady=6,
            relief=tk.RIDGE, bd=1,
        )
        lf.pack(fill=tk.BOTH if expand else tk.X, expand=expand, pady=(0, 8))
        return lf

    def _build_device_panel(self, parent: tk.Widget) -> None:
        c = COLORS
        lf = self._lf(parent, "Device Selection")

        for label_text, is_source in [("Source USB:", True), ("Dest. USB:", False)]:
            row = tk.Frame(lf, bg=c["panel"])
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=label_text, width=11, anchor=tk.W,
                     bg=c["panel"], fg=c["text"],
                     font=("Segoe UI", 9)).pack(side=tk.LEFT)
            var = tk.StringVar()
            combo = ttk.Combobox(row, textvariable=var, width=72, state="normal")
            combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
            if is_source:
                self.source_var = var
                self.source_combo = combo
            else:
                self.dest_var = var
                self.dest_combo = combo

        # Browse + Detect
        btn_row = tk.Frame(lf, bg=c["panel"])
        btn_row.pack(anchor=tk.W, pady=(4, 0))
        self._btn(btn_row, "Browse Source", self._browse_source, c["muted"]).pack(side=tk.LEFT, padx=(0, 6))
        self._btn(btn_row, "Detect Drives", self._detect_devices, c["accent"]).pack(side=tk.LEFT)

        # CITL marker indicators
        ind_row = tk.Frame(lf, bg=c["panel"])
        ind_row.pack(fill=tk.X, pady=(4, 0))
        self.src_marker_var = tk.StringVar(value="")
        self.dst_marker_var = tk.StringVar(value="")
        tk.Label(ind_row, textvariable=self.src_marker_var, bg=c["panel"],
                 font=("Consolas", 8), fg=c["muted"]).pack(side=tk.LEFT)
        tk.Label(ind_row, textvariable=self.dst_marker_var, bg=c["panel"],
                 font=("Consolas", 8), fg=c["muted"]).pack(side=tk.LEFT, padx=(20, 0))

        self.source_var.trace_add("write", lambda *_: self._check_markers())
        self.dest_var.trace_add("write", lambda *_: self._check_markers())

    def _build_options_panel(self, parent: tk.Widget) -> None:
        c = COLORS
        lf = self._lf(parent, "Options")

        self.format_var  = tk.BooleanVar(value=False)
        self.data_var    = tk.BooleanVar(value=False)
        self.models_var  = tk.BooleanVar(value=False)
        self.bootstrap_var = tk.BooleanVar(value=True)

        opts = [
            (self.format_var,    "Format dest. as exFAT first  (WARNING: destroys all data!)", c["warn"]),
            (self.data_var,      "Include data/ and index folders  (larger, slower)",          c["text"]),
            (self.models_var,    "Include models/ and ollama/ folders",                        c["text"]),
            (self.bootstrap_var, "Generate Ubuntu bootstrap launchers  (recommended)",         c["text"]),
        ]
        for var, txt, fg in opts:
            tk.Checkbutton(
                lf, text=txt, variable=var,
                bg=c["panel"], fg=fg, selectcolor=c["border"],
                activebackground=c["panel"], activeforeground=fg,
                font=("Segoe UI", 9),
            ).pack(anchor=tk.W, pady=1)

    def _build_progress_panel(self, parent: tk.Widget) -> None:
        c = COLORS
        lf = self._lf(parent, "Progress")

        self.progress_bar = ttk.Progressbar(lf, maximum=100, mode="determinate", length=400)
        self.progress_bar.pack(fill=tk.X, pady=(0, 6))

        self.phase_var   = tk.StringVar(value="Idle")
        self.metrics_var = tk.StringVar(value="Files: 0 | Copied: 0 | Skipped: 0 | Errors: 0 | KB: 0 | Speed: — | Elapsed: 0s")

        tk.Label(lf, textvariable=self.phase_var,
                 bg=c["panel"], fg=c["accent"], font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        tk.Label(lf, textvariable=self.metrics_var,
                 bg=c["panel"], fg=c["muted"], font=("Consolas", 8)).pack(anchor=tk.W)

    def _build_log_panel(self, parent: tk.Widget) -> None:
        c = COLORS
        lf = self._lf(parent, "Diagnostics & File Log", expand=True)

        sb = ttk.Scrollbar(lf)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text = tk.Text(
            lf, height=10,
            font=("Consolas", 8),
            bg=c["log_bg"], fg=c["log_fg"],
            insertbackground=c["log_fg"],
            yscrollcommand=sb.set,
            wrap=tk.WORD, state=tk.DISABLED,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.log_text.yview)

    def _build_buttons(self, parent: tk.Widget) -> None:
        c = COLORS
        row = tk.Frame(parent, bg=c["bg"])
        row.pack(fill=tk.X)

        self.clone_btn = self._btn(row, "▶  START CLONE", self._start_clone,
                                   c["success"], font=("Segoe UI", 11, "bold"), padx=28, pady=8)
        self.clone_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.cancel_btn = self._btn(row, "Cancel", self._cancel_clone,
                                    c["muted"], pady=8, state="disabled")
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._btn(row, "Exit", self.root.destroy, c["border"], pady=8).pack(side=tk.RIGHT)

    @staticmethod
    def _btn(parent: tk.Widget, text: str, cmd: Callable, bg: str,
             font: tuple = ("Segoe UI", 10), padx: int = 16, pady: int = 6,
             state: str = "normal") -> tk.Button:
        return tk.Button(parent, text=text, command=cmd,  # type: ignore[arg-type]
                         bg=bg, fg="white", activebackground=bg,
                         font=font, padx=padx, pady=pady,
                         relief=tk.FLAT, cursor="hand2", state=state)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        """Append a line to the log widget (call from main thread only)."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _detect_devices(self) -> None:
        self.devices = get_usb_devices()
        names = [d.display_name for d in self.devices]
        self.source_combo["values"] = names
        self.dest_combo["values"]   = names

        # Auto-populate source if it contains CITL
        if not self.source_var.get():
            for i, d in enumerate(self.devices):
                if citl_marker_present(d.path):
                    self.source_var.set(names[i])
                    break

        if self.source_usb and not self.source_var.get():
            self.source_var.set(self.source_usb)

        self._log(f"Detected {len(self.devices)} removable drive(s)")
        self._check_markers()

    def _resolve_path_from_combo(self, var: tk.StringVar) -> Optional[str]:
        """
        Resolve the actual filesystem path from a combobox value.
        The display name format is: "Label (X:\\) — ..."
        We also accept raw paths typed directly.
        """
        val = var.get().strip()
        if not val:
            return None
        # Match the display_name pattern: "... (path) —"
        m = re.search(r'\(([A-Za-z]:\\[^)]*|/[^)]*)\)', val)
        if m:
            return m.group(1)
        # Maybe user typed or browsed a raw path
        if os.path.exists(val):
            return val
        # Try matching against devices list by display_name equality
        for d in self.devices:
            if d.display_name == val:
                return d.path
        return val  # Return as-is and let validation catch bad paths

    def _browse_source(self) -> None:
        path = filedialog.askdirectory(title="Select CITL source USB or repository folder")
        if path:
            self.source_var.set(path)

    def _check_markers(self) -> None:
        src = self._resolve_path_from_combo(self.source_var)
        dst = self._resolve_path_from_combo(self.dest_var)
        self.src_marker_var.set(
            f"Source CITL: {'✓' if src and citl_marker_present(src) else '✗ no marker'}"
            if src else ""
        )
        self.dst_marker_var.set(
            f"Dest CITL: {'✓ existing repo' if dst and citl_marker_present(dst) else '○ new (blank OK)'}"
            if dst else ""
        )

    # ── Clone flow ────────────────────────────────────────────────────────────

    def _start_clone(self) -> None:
        src_path = self._resolve_path_from_combo(self.source_var)
        dst_path = self._resolve_path_from_combo(self.dest_var)

        if not src_path:
            messagebox.showerror("Missing source", "Please select or enter a source USB path.")
            return
        if not dst_path:
            messagebox.showerror("Missing destination", "Please select a destination USB device.")
            return
        if not os.path.isdir(src_path):
            messagebox.showerror("Invalid source", f"Source path does not exist:\n{src_path}")
            return
        if not os.path.isdir(dst_path):
            messagebox.showerror("Invalid destination", f"Destination path does not exist:\n{dst_path}")
            return
        if os.path.abspath(src_path) == os.path.abspath(dst_path):
            messagebox.showerror("Same path", "Source and destination are the same path.")
            return

        if not citl_marker_present(src_path):
            if not messagebox.askyesno(
                "No CITL marker",
                f"Source does not look like a CITL repository:\n{src_path}\n\nContinue anyway?"
            ):
                return

        # Check free space
        try:
            src_used  = shutil.disk_usage(src_path).used
            dst_free  = shutil.disk_usage(dst_path).free
            if src_used > dst_free:
                mb_short = (src_used - dst_free) / (1024 * 1024)
                messagebox.showerror(
                    "Not enough space",
                    f"Destination has {dst_free/(1024**3):.2f} GB free but "
                    f"source uses {src_used/(1024**3):.2f} GB.\n"
                    f"Need {mb_short:.0f} MB more."
                )
                return
        except Exception:
            pass

        # Format confirmation
        if self.format_var.get():
            if not messagebox.askyesno(
                "CONFIRM FORMAT",
                f"⚠️  ALL DATA on the destination will be ERASED!\n\n"
                f"Destination: {dst_path}\n\nThis cannot be undone. Proceed?"
            ):
                return
            confirm = simpledialog.askstring("Confirm", 'Type  ERASE  to confirm format:')
            if (confirm or "").strip().upper() != "ERASE":
                messagebox.showinfo("Cancelled", "Format cancelled.")
                return

        # Reset progress state
        self.progress = CloneProgress()
        self._log_tail_pos = 0
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.progress_bar["value"] = 0

        self.clone_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)

        if self.dry_run:
            self._log("DRY-RUN mode — no files will be copied")

        self._clone_thread = threading.Thread(
            target=self._worker,
            args=(src_path, dst_path),
            daemon=True,
        )
        self._clone_thread.start()
        self._poll()

    def _worker(self, src_path: str, dst_path: str) -> None:
        """Runs in background thread."""
        prog = self.progress
        prog.log(f"Clone started: {src_path}  →  {dst_path}")
        prog.log(f"Dry-run: {self.dry_run}")

        try:
            # Format step
            if self.format_var.get() and not self.dry_run:
                prog.phase = "Formatting destination"
                prog.log("Formatting destination drive ...")
                if IS_WINDOWS:
                    letter = Path(dst_path).drive.rstrip(":\\")
                    ok = format_drive_windows(letter, prog)
                else:
                    ok = format_drive_linux(dst_path, prog)
                if not ok:
                    prog.log("Format failed — aborting.")
                    prog.finished = True
                    return

            if self.dry_run:
                # Simulate copy for testing UI
                prog.phase = "Scanning files..."
                prog.log("Dry-run: counting files ...")
                excludes = _build_excludes(self.data_var.get(), self.models_var.get())
                prog.total_files = _count_files(Path(src_path), excludes)
                prog.log(f"Dry-run: {prog.total_files} files would be copied")
                prog.phase = "Transferring (dry-run)"
                for i in range(prog.total_files):
                    if prog.cancelled:
                        break
                    prog.done_files = i + 1
                    prog.copied_files = i + 1
                    prog.bytes_copied += 1024
                    time.sleep(0.005)
                prog.phase = "Done (dry-run)"
                prog.finished = True
                prog.log("Dry-run complete — no files were actually copied.")
                return

            run_copy(
                Path(src_path),
                Path(dst_path),
                prog,
                include_data=self.data_var.get(),
                include_models=self.models_var.get(),
            )

        except Exception as exc:
            prog.log(f"FATAL ERROR: {exc}")
            prog.error_files += 1
            prog.phase = "Error"
            prog.finished = True

    def _poll(self) -> None:
        """Called every 150ms in the main thread to refresh UI from progress."""
        prog = self.progress

        # Update progress bar
        self.progress_bar["value"] = prog.pct

        # Phase label
        self.phase_var.set(f"{prog.phase}  ({prog.pct}%)")

        # Metrics
        speed = prog.speed_kbps
        speed_str = f"{speed:.0f} KB/s" if speed > 0 else "—"
        eta = prog.eta_sec
        eta_str = f"ETA {eta:.0f}s" if eta > 1 else ""
        self.metrics_var.set(
            f"Files: {prog.done_files}/{prog.total_files} | "
            f"Copied: {prog.copied_files} | Skipped: {prog.skipped_files} | "
            f"Errors: {prog.error_files} | "
            f"KB: {prog.bytes_copied_kb:.1f} | "
            f"Speed: {speed_str}  {eta_str} | "
            f"Elapsed: {prog.elapsed:.0f}s"
        )

        # Drain new log messages into log widget
        new_msgs = prog.messages[self._log_tail_pos:]
        if new_msgs:
            self._log_tail_pos = len(prog.messages)
            self.log_text.config(state=tk.NORMAL)
            for msg in new_msgs:
                self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        if prog.finished or prog.cancelled:
            self.clone_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)
            self.progress_bar["value"] = 100 if prog.finished and not prog.cancelled else prog.pct
            if prog.finished:
                if prog.error_files == 0:
                    messagebox.showinfo("Complete", "USB clone completed successfully!")
                else:
                    messagebox.showwarning(
                        "Complete with errors",
                        f"Clone finished with {prog.error_files} error(s).\n"
                        "See diagnostics log for details."
                    )
            return  # Stop polling

        self._poll_job = self.root.after(150, self._poll)

    def _cancel_clone(self) -> None:
        self.progress.cancelled = True
        self.progress.phase = "Cancelled"
        self._log("Cancellation requested...")
        self.cancel_btn.config(state=tk.DISABLED)


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main(args=None) -> int:
    parser = argparse.ArgumentParser(description="CITL USB Clone Utility")
    parser.add_argument("--source",   default="", help="Source USB or repo path")
    parser.add_argument("--dry-run",  action="store_true", help="Simulate without copying")
    parsed = parser.parse_args(args)

    if not HAS_TK:
        print("[ERROR] Tkinter is not available. Install python-tk.", file=sys.stderr)
        return 1

    root = tk.Tk()
    try:
        CloneGui(root, source_usb=parsed.source, dry_run=parsed.dry_run)
        root.mainloop()
        return 0
    except Exception as exc:
        try:
            messagebox.showerror("Fatal Error", str(exc))
        except Exception:
            print(f"[FATAL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
