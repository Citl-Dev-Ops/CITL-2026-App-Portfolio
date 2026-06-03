#!/usr/bin/env python3
"""
CITL Screen Recorder
====================
Window-focused recorder for CITL applications using FFmpeg.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# ── Windows-only Win32 imports ────────────────────────────────────────────────
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wintypes
    _WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
else:
    ctypes = None      # type: ignore[assignment]
    wintypes = None    # type: ignore[assignment]
    _WNDENUMPROC = None

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except Exception:
    print("tkinter is required for CITL Screen Recorder.")
    print("Ubuntu fix: sudo apt install python3-tk")
    sys.exit(1)


APP_NAME = "CITL Screen Recorder"
APP_VERSION = "v1.2"

def check_for_updates() -> Optional[str]:
    """
    Check if there's a newer version of this app available in the CITL repo.
    Returns the path to the newer version if found, None otherwise.
    """
    try:
        # Check if we're running from a repo
        if getattr(sys, "frozen", False):
            # Running as exe - check the repo path
            repo_path = os.environ.get("CITL_REPO", "").strip()
            if not repo_path or not Path(repo_path).is_dir():
                return None
            repo = Path(repo_path)
        else:
            # Running as script - check parent directory
            repo = _HERE.parent

        # Look for newer version in repo
        script_path = repo / "factbook-assistant" / "citl_screen_recorder.py"
        if not script_path.exists():
            return None

        # Check if the repo version is newer by comparing file modification times
        current_path = Path(__file__)
        if script_path.stat().st_mtime > current_path.stat().st_mtime:
            return str(script_path)

        return None
    except Exception:
        return None

def update_from_repo() -> bool:
    """
    Update this app from the newer version in the CITL repo.
    Returns True if update was successful.
    """
    try:
        newer_path = check_for_updates()
        if not newer_path:
            return False

        # Backup current version
        current_path = Path(__file__)
        backup_path = current_path.with_suffix('.bak')
        if backup_path.exists():
            backup_path.unlink()
        current_path.rename(backup_path)

        # Copy newer version
        import shutil
        shutil.copy2(newer_path, current_path)

        return True
    except Exception:
        return False

_HERE = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    env_repo = os.environ.get("CITL_REPO", "").strip()
    if env_repo and Path(env_repo).is_dir():
        REPO = Path(env_repo)
    else:
        REPO = Path(sys.executable).resolve().parent.parent.parent
else:
    REPO = _HERE.parent

RECORDINGS_DIR = REPO / "recordings"
SCREENSHOTS_DIR = RECORDINGS_DIR / "screenshots"
RECORDER_SIGNAL_PATH = RECORDINGS_DIR / "citl_recorder_target_signal.json"
WINDOW_WATCH_MS = 1200
TARGET_SIGNAL_TTL_SEC = 15.0
RETARGET_START_DELAY_MS = 700
VIDEO_GLOB_PATTERNS: Tuple[str, ...] = ("*.mp4", "*.mkv", "*.mov", "*.avi", "*.webm")

COLORS = {
    "bg": "#140a0a",
    "panel": "#1e0f0f",
    "panel_alt": "#271414",
    "card": "#221010",
    "border": "#6b2c2c",
    "text": "#f5eeee",
    "muted": "#c4a0a0",
    "faint": "#8a7070",
    "accent": "#d84444",
    "btn": "#4a1a1a",
    "btn_hi": "#6e2525",
    "btn_acc": "#7a1e1e",
    "ok": "#84f6a0",
    "warn": "#ffd369",
    "danger": "#ff8b8b",
    "notebk": "#180c0c",
}
FONT = "Segoe UI" if sys.platform == "win32" else "Ubuntu"


CITL_KNOWN: Dict[str, Dict[str, str]] = {
    "CITL LLMOps Presentation Suite": {
        "title_prefix": "CITL LLMOps Presentation Suite",
        "launcher_win": "RUN_LLMOPS_WINDOWS.cmd",
        "icon": "[LLMOPS]",
    },
    "CITL Factbook Assistant": {
        "title_prefix": "CITL Desktop LLM Assistant",
        "launcher_win": "RUN_FACTBOOK_WINDOWS.cmd",
        "icon": "[FACTBOOK]",
    },
    "CITL App Sync": {
        "title_prefix": "CITL App Sync Utility",
        "launcher_win": "RUN_APP_SYNC_WINDOWS.cmd",
        "icon": "[SYNC]",
    },
    "CITL Document Composer": {
        "title_prefix": "CITL Document Composer",
        "launcher_win": "factbook-assistant/citl_doc_composer.py",
        "icon": "[DOC]",
    },
    "CITL Technical Writing and Tutorial Creator": {
        "title_prefix": "CITL Technical Writing and Tutorial Creator",
        "launcher_win": "RUN_TECHNICAL_WRITER_CREATOR_WINDOWS.cmd",
        "icon": "[TUTORIAL]",
    },
    "CITL Toolkit": {
        "title_prefix": "CITL Toolkit",
        "launcher_win": "CITL_Toolkit/CITL_Launcher.ps1",
        "icon": "[TOOLKIT]",
    },
}

EXPORT_FORMATS: Dict[str, Dict[str, object]] = {
    "MP4 - H264 AAC": {
        "ext": ".mp4",
        "vcodec": "libx264",
        "acodec": "aac",
        "vflags": ["-preset", "medium", "-crf", "21"],
        "aflags": ["-b:a", "192k"],
        "audio": True,
    },
    "WebM - VP9 Opus": {
        "ext": ".webm",
        "vcodec": "libvpx-vp9",
        "acodec": "libopus",
        "vflags": ["-crf", "32", "-b:v", "0", "-deadline", "realtime"],
        "aflags": ["-b:a", "128k"],
        "audio": True,
    },
    "MKV - H264 AAC": {
        "ext": ".mkv",
        "vcodec": "libx264",
        "acodec": "aac",
        "vflags": ["-preset", "medium", "-crf", "21"],
        "aflags": ["-b:a", "192k"],
        "audio": True,
    },
    "MOV - H264 AAC": {
        "ext": ".mov",
        "vcodec": "libx264",
        "acodec": "aac",
        "vflags": ["-preset", "medium", "-crf", "21"],
        "aflags": ["-b:a", "192k"],
        "audio": True,
    },
    "AVI - HuffYUV": {
        "ext": ".avi",
        "vcodec": "huffyuv",
        "acodec": "pcm_s16le",
        "vflags": [],
        "aflags": [],
        "audio": True,
    },
}
FPS_OPTIONS = ["10", "15", "20", "24", "30", "60"]


def _enum_visible_windows() -> List[Tuple[int, str]]:
    """Return list of visible top-level windows as (hwnd, title)."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    windows: List[Tuple[int, str]] = []

    def _cb(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if title:
            windows.append((hwnd, title))
        return True

    user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return windows


def _find_citl_windows(all_windows: List[Tuple[int, str]]) -> List[Tuple[str, str, int]]:
    found: List[Tuple[str, str, int]] = []
    for app_name, meta in CITL_KNOWN.items():
        needle = str(meta.get("title_prefix", "")).lower()
        if not needle:
            continue
        for hwnd, title in all_windows:
            if needle in title.lower():
                found.append((app_name, title, hwnd))
    return found


def _is_valid_hwnd(hwnd: Optional[int]) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        return bool(ctypes.windll.user32.IsWindow(int(hwnd)))
    except Exception:
        return False


def _focus_window(hwnd: Optional[int]) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(int(hwnd), 5)  # SW_SHOW
        user32.SetForegroundWindow(int(hwnd))
    except Exception:
        pass


def _set_window_topmost(hwnd: Optional[int], enabled: bool) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        target = HWND_TOPMOST if enabled else HWND_NOTOPMOST
        ok = user32.SetWindowPos(int(hwnd), target, 0, 0, 0, 0, flags)
        return bool(ok)
    except Exception:
        return False


def _get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Return (x, y, w, h) screen rect of a window, or None."""
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        rect = wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
            x, y = rect.left, rect.top
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w > 0 and h > 0:
                return x, y, w, h
    except Exception:
        pass
    return None


def _find_ffmpeg() -> Optional[str]:
    """Locate FFmpeg on Windows or Ubuntu. Returns full path or None."""
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    if sys.platform == "win32":
        candidates = [
            REPO / "bin" / "ffmpeg.exe",
            REPO / "bin" / "windows" / "ffmpeg.exe",
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" /
                "Packages" / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe" /
                "ffmpeg-7.1-full_build" / "bin" / "ffmpeg.exe",
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "FFmpeg" / "bin" / "ffmpeg.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "FFmpeg" / "bin" / "ffmpeg.exe",
        ]
    else:
        candidates = [
            Path("/usr/bin/ffmpeg"),
            Path("/usr/local/bin/ffmpeg"),
            Path.home() / ".local/bin/ffmpeg",
            REPO / "bin" / "ffmpeg",
            REPO / "bin" / "linux" / "ffmpeg",
        ]
    for p in candidates:
        try:
            if p and p.exists():
                return str(p)
        except Exception:
            pass
    return None


def _run_silent(cmd: List[str], timeout: int = 10) -> Tuple[bool, str]:
    """Run command, return (success, output). Never raises."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, "Timed out"
    except Exception as e:
        return False, str(e)


def _install_ffmpeg(log: Callable[[str], None]) -> Optional[str]:
    """Install FFmpeg on Windows (winget/choco/direct) or Ubuntu (apt).
    Returns new ffmpeg path on success, None on failure."""
    if sys.platform == "win32":
        # Try winget
        if shutil.which("winget"):
            log("Installing FFmpeg via winget (Gyan.FFmpeg)...")
            ok, out = _run_silent(
                ["winget", "install", "Gyan.FFmpeg",
                 "--silent", "--accept-source-agreements"], timeout=300)
            for line in out.splitlines():
                log(line)
            # Reload PATH after install
            try:
                new_path = subprocess.check_output(
                    ["powershell", "-Command",
                     "[Environment]::GetEnvironmentVariable('PATH','Machine') + ';' + "
                     "[Environment]::GetEnvironmentVariable('PATH','User')"],
                    text=True, timeout=10
                ).strip()
                os.environ["PATH"] = new_path
            except Exception:
                pass
            found = _find_ffmpeg()
            if found:
                log(f"FFmpeg installed: {found}")
                return found

        # Try chocolatey
        if shutil.which("choco"):
            log("Installing FFmpeg via Chocolatey...")
            ok, out = _run_silent(["choco", "install", "ffmpeg", "-y"], timeout=300)
            for line in out.splitlines():
                log(line)
            found = _find_ffmpeg()
            if found:
                log(f"FFmpeg installed: {found}")
                return found

        # Direct download to C:\ffmpeg
        log("Attempting direct FFmpeg download to C:\\ffmpeg\\bin\\...")
        dl_script = (
            "$url='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip';"
            "$out='$env:TEMP\\ffmpeg.zip';"
            "Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing;"
            "$dest='C:\\ffmpeg';"
            "Expand-Archive -Path $out -DestinationPath $dest -Force;"
            "$binDir=(Get-ChildItem -Path $dest -Recurse -Filter 'ffmpeg.exe' | "
            "Select-Object -First 1).DirectoryName;"
            "[Environment]::SetEnvironmentVariable('PATH',$env:PATH+';'+$binDir,'Machine');"
            "Write-Host ('Installed to: '+$binDir)"
        )
        ok, out = _run_silent(["powershell", "-Command", dl_script], timeout=600)
        for line in out.splitlines():
            log(line)
        # Also add C:\ffmpeg\... dynamically
        for sub in Path("C:/ffmpeg").rglob("ffmpeg.exe"):
            os.environ["PATH"] = str(sub.parent) + ";" + os.environ.get("PATH", "")
            break
        found = _find_ffmpeg()
        if found:
            log(f"FFmpeg installed: {found}")
            return found
        log("FFmpeg automatic install failed. Download manually from https://ffmpeg.org/download.html")
        return None

    else:  # Ubuntu / Linux
        # Try apt
        if shutil.which("apt-get"):
            log("Installing FFmpeg via apt-get...")
            ok, out = _run_silent(
                ["sudo", "apt-get", "install", "-y", "ffmpeg"], timeout=300)
            for line in out.splitlines():
                log(line)
            found = _find_ffmpeg()
            if found:
                log(f"FFmpeg installed: {found}")
                return found
        # Try snap
        if shutil.which("snap"):
            log("Trying snap install ffmpeg...")
            ok, out = _run_silent(["sudo", "snap", "install", "ffmpeg"], timeout=300)
            for line in out.splitlines():
                log(line)
            found = _find_ffmpeg()
            if found:
                return found
        log("FFmpeg install failed. Run: sudo apt install ffmpeg")
        return None


def _ffmpeg_version(ffmpeg_path: str) -> str:
    try:
        out = subprocess.check_output(
            [ffmpeg_path, "-version"],
            stderr=subprocess.STDOUT,
            timeout=5,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        first = out.decode("utf-8", errors="replace").splitlines()[0]
        m = re.search(r"ffmpeg version (\S+)", first)
        return m.group(1) if m else first[:60]
    except Exception:
        return "unknown"


def _list_audio_devices(ffmpeg_path: str) -> List[str]:
    """Return audio device names for the current platform."""
    if sys.platform == "win32":
        # DirectShow devices
        try:
            out = subprocess.check_output(
                [ffmpeg_path, "-hide_banner", "-list_devices", "true",
                 "-f", "dshow", "-i", "dummy"],
                stderr=subprocess.STDOUT, timeout=8,
                creationflags=0x08000000,
            )
            text = out.decode("utf-8", errors="replace")
        except Exception:
            return []
        devices: List[str] = []
        in_audio = False
        for line in text.splitlines():
            if "DirectShow audio devices" in line:
                in_audio = True
                continue
            if in_audio and "DirectShow video devices" in line:
                break
            if not in_audio:
                continue
            m = re.search(r'"([^"]+)"', line)
            if m:
                devices.append(m.group(1))
        return devices

    else:
        # PulseAudio (most Ubuntu installs)
        devices: List[str] = []
        pa_ok, pa_out = _run_silent(["pactl", "list", "short", "sources"], timeout=5)
        if pa_ok and pa_out.strip():
            for line in pa_out.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    src = parts[1]
                    if not src.endswith(".monitor") or not devices:
                        devices.append(src)
            if devices:
                return devices

        # ALSA fallback
        alsa_ok, alsa_out = _run_silent(
            ["arecord", "-l"], timeout=5)
        if alsa_ok:
            for line in alsa_out.splitlines():
                m = re.search(r"card (\d+):.*device (\d+):", line)
                if m:
                    devices.append(f"hw:{m.group(1)},{m.group(2)}")
            if devices:
                return devices

        # Default fallback — always works with pulse
        return ["default", "pulse"]


def _get_screen_size() -> Tuple[int, int]:
    """Return (width, height) of the primary screen."""
    try:
        if sys.platform == "win32" and ctypes:
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        else:
            # xrandr / xdpyinfo fallback
            ok, out = _run_silent(["xdpyinfo"], timeout=5)
            if ok:
                m = re.search(r"dimensions:\s+(\d+)x(\d+)", out)
                if m:
                    return int(m.group(1)), int(m.group(2))
            ok2, out2 = _run_silent(["xrandr", "--query"], timeout=5)
            if ok2:
                m2 = re.search(r"current (\d+) x (\d+)", out2)
                if m2:
                    return int(m2.group(1)), int(m2.group(2))
    except Exception:
        pass
    return 1920, 1080   # Safe default


def _open_path(p: Path) -> None:
    """Open a file or folder cross-platform."""
    p = Path(p)
    if sys.platform == "win32":
        os.startfile(str(p))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def _diagnose_ffmpeg() -> List[str]:
    """Return list of problem strings for the current environment."""
    issues: List[str] = []
    ff = _find_ffmpeg()
    if not ff:
        issues.append("FFmpeg not found on this system.")
        return issues
    # Check gdigrab / x11grab availability
    ok, out = _run_silent([ff, "-hide_banner", "-devices"], timeout=5)
    if sys.platform == "win32" and "gdigrab" not in out:
        issues.append("FFmpeg is installed but gdigrab is not available. "
                      "Re-install a full FFmpeg build.")
    if sys.platform != "win32" and "x11grab" not in out:
        issues.append("FFmpeg is installed but x11grab is not available. "
                      "Install: sudo apt install ffmpeg")
    # Check libx264 encoder
    ok2, enc_out = _run_silent([ff, "-hide_banner", "-encoders"], timeout=5)
    if "libx264" not in enc_out:
        issues.append("libx264 encoder not found in this FFmpeg build. "
                      "Install a full build: sudo apt install ffmpeg  "
                      "or get the full Windows build from gyan.dev")
    return issues


def _startup_repair_dialog(root: tk.Tk, issues: List[str],
                           on_fixed: Callable[[str], None]) -> None:
    """Show a modal repair dialog if FFmpeg or capture deps are missing."""
    win = tk.Toplevel(root)
    win.title("CITL Screen Recorder — Repair Required")
    win.configure(bg=COLORS["bg"])
    win.geometry("620x400")
    win.grab_set()

    tk.Label(win, text="  Setup Problems Found",
             font=(FONT, 13, "bold"), bg=COLORS["panel"],
             fg=COLORS["danger"]).pack(fill="x", pady=(0, 8))

    log_w = scrolledtext.ScrolledText(
        win, height=8, bg=COLORS["notebk"], fg=COLORS["text"],
        font=("Courier New", 9), relief="flat")
    log_w.pack(fill="both", expand=True, padx=12, pady=4)

    for iss in issues:
        log_w.insert("end", f"  PROBLEM: {iss}\n")
    log_w.configure(state="disabled")

    status = tk.StringVar(value="Click 'Fix Now' to auto-repair.")
    tk.Label(win, textvariable=status, bg=COLORS["bg"],
             fg=COLORS["warn"], font=(FONT, 9)).pack(fill="x", padx=12)

    def _append(line: str):
        def _do():
            log_w.configure(state="normal")
            log_w.insert("end", line + "\n")
            log_w.configure(state="disabled")
            log_w.see("end")
        win.after(0, _do)

    def _fix():
        fix_btn.config(state="disabled")
        status.set("Fixing… this may take a few minutes.")
        def _bg():
            found = _install_ffmpeg(_append)
            def _done():
                if found:
                    status.set(f"Fixed! FFmpeg: {found}")
                    on_fixed(found)
                    win.after(1500, win.destroy)
                else:
                    status.set("Auto-fix failed — see log above. Install FFmpeg manually.")
                    fix_btn.config(state="normal")
            win.after(0, _done)
        threading.Thread(target=_bg, daemon=True).start()

    btn_row = tk.Frame(win, bg=COLORS["bg"])
    btn_row.pack(fill="x", padx=12, pady=8)
    fix_btn = tk.Button(btn_row, text="Fix Now (Auto-Install FFmpeg)",
                        bg=COLORS["accent"], fg=COLORS["text"],
                        font=(FONT, 10, "bold"), relief="flat",
                        padx=10, pady=6, command=_fix)
    fix_btn.pack(side="left")
    tk.Button(btn_row, text="Continue Anyway",
              bg=COLORS["btn"], fg=COLORS["muted"],
              relief="flat", padx=10, pady=6,
              command=win.destroy).pack(side="left", padx=8)

    def _manual():
        url = ("https://ffmpeg.org/download.html" if sys.platform == "win32"
               else "https://ffmpeg.org/download.html#build-linux")
        import webbrowser
        webbrowser.open(url)
    tk.Button(btn_row, text="Open ffmpeg.org",
              bg=COLORS["btn"], fg=COLORS["muted"],
              relief="flat", padx=8, pady=6,
              command=_manual).pack(side="left")


@dataclass
class RecordingSession:
    ffmpeg_path: str
    window_title: str
    window_hwnd: Optional[int]
    output_path: str
    fmt: Dict[str, object]
    fps: int
    audio_enabled: bool
    audio_device: Optional[str]
    quality_crf: str
    crop_region: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h) screen coords
    on_log: Optional[Callable[[str], None]] = None
    on_done: Optional[Callable[[int, str], None]] = None

    proc: Optional[subprocess.Popen] = None
    running: bool = False
    start_time: float = 0.0

    def _cmd(self) -> List[str]:
        cmd: List[str] = [self.ffmpeg_path, "-hide_banner"]

        if sys.platform == "win32":
            if self.crop_region:
                # Region capture: gdigrab desktop with offset + size
                x, y, w, h = self.crop_region
                w = w - (w % 2)
                h = h - (h % 2)
                cmd.extend([
                    "-f", "gdigrab",
                    "-framerate", str(self.fps),
                    "-offset_x", str(x),
                    "-offset_y", str(y),
                    "-video_size", f"{w}x{h}",
                    "-i", "desktop",
                ])
            else:
                # Full window capture by HWND or title
                cmd.extend([
                    "-f", "gdigrab",
                    "-framerate", str(self.fps),
                    "-i", (f"hwnd={self.window_hwnd}"
                           if self.window_hwnd else f"title={self.window_title}"),
                ])
        else:
            # Ubuntu / Linux: x11grab
            display = os.environ.get("DISPLAY", ":0")
            sw, sh = _get_screen_size()
            if self.crop_region:
                cx, cy, cw, ch = self.crop_region
                cw = cw - (cw % 2)
                ch = ch - (ch % 2)
                cmd.extend([
                    "-f", "x11grab",
                    "-framerate", str(self.fps),
                    "-video_size", f"{cw}x{ch}",
                    "-i", f"{display}+{cx},{cy}",
                ])
            else:
                wgeo = self._get_window_geometry_linux()
                if wgeo:
                    x, y, ww, wh = wgeo
                    ww = ww - (ww % 2)
                    wh = wh - (wh % 2)
                    cmd.extend([
                        "-f", "x11grab",
                        "-framerate", str(self.fps),
                        "-video_size", f"{ww}x{wh}",
                        "-i", f"{display}+{x},{y}",
                    ])
                else:
                    cmd.extend([
                        "-f", "x11grab",
                        "-framerate", str(self.fps),
                        "-video_size", f"{sw}x{sh}",
                        "-i", display,
                    ])

        cmd.extend(["-vcodec", str(self.fmt["vcodec"])])
        vflags = list(self.fmt.get("vflags", []))
        if "-crf" in vflags:
            idx = vflags.index("-crf")
            if idx + 1 < len(vflags):
                vflags[idx + 1] = self.quality_crf
        cmd.extend(vflags)
        if self.fmt["vcodec"] in ("libx264", "libvpx-vp9"):
            cmd.extend(["-pix_fmt", "yuv420p"])
            # libx264/vp9 require even dimensions; gdigrab hwnd capture can
            # produce odd sizes (e.g. 857px wide) that cause encoder failure.
            cmd.extend(["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"])

        supports_audio = bool(self.fmt.get("audio"))
        if supports_audio and self.audio_enabled and self.audio_device:
            if sys.platform == "win32":
                cmd.extend(["-f", "dshow", "-i", f"audio={self.audio_device}"])
            else:
                # Ubuntu: prefer pulse then alsa
                dev = self.audio_device or "default"
                if dev in ("default", "pulse") or dev.startswith("alsa_"):
                    cmd.extend(["-f", "pulse", "-i", dev])
                elif dev.startswith("hw:"):
                    cmd.extend(["-f", "alsa", "-i", dev])
                else:
                    cmd.extend(["-f", "pulse", "-i", dev])
            acodec = str(self.fmt.get("acodec") or "")
            if acodec:
                cmd.extend(["-acodec", acodec])
            cmd.extend(list(self.fmt.get("aflags", [])))
        else:
            cmd.append("-an")

        cmd.extend(["-y", self.output_path])
        return cmd

    def _get_window_geometry_linux(self) -> Optional[Tuple[int, int, int, int]]:
        """Return (x, y, w, h) of the target window on Linux using xdotool."""
        if sys.platform == "win32" or not self.window_title:
            return None
        try:
            # Find window by name
            ok, wid = _run_silent(
                ["xdotool", "search", "--name", self.window_title], timeout=3)
            if not ok or not wid.strip():
                # Try partial match
                ok, wid = _run_silent(
                    ["xdotool", "search", "--name",
                     self.window_title.split()[0]], timeout=3)
            if ok and wid.strip():
                wid_clean = wid.strip().splitlines()[0]
                ok2, geo = _run_silent(
                    ["xdotool", "getwindowgeometry", "--shell", wid_clean], timeout=3)
                if ok2 and geo:
                    vals: Dict[str, int] = {}
                    for line in geo.splitlines():
                        if "=" in line:
                            k, _, v = line.partition("=")
                            try:
                                vals[k.strip()] = int(v.strip())
                            except ValueError:
                                pass
                    if all(k in vals for k in ("X", "Y", "WIDTH", "HEIGHT")):
                        return vals["X"], vals["Y"], vals["WIDTH"], vals["HEIGHT"]
        except Exception:
            pass
        return None

    def _emit(self, text: str):
        if self.on_log:
            self.on_log(text)

    def start(self):
        if self.running:
            return
        cmd = self._cmd()
        self._emit("[FFMPEG] " + " ".join(cmd) + "\n")
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        self.running = True
        self.start_time = time.time()
        threading.Thread(target=self._pump_output, daemon=True).start()

    def _pump_output(self):
        rc = -1
        try:
            assert self.proc is not None
            if self.proc.stdout:
                for line in self.proc.stdout:
                    self._emit(line)
            rc = self.proc.wait()
        except Exception as exc:
            self._emit(f"[ERROR] {exc}\n")
            rc = -1
        finally:
            self.running = False
            if self.on_done:
                self.on_done(rc, self.output_path)

    def stop(self):
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.write("q\n")
                self.proc.stdin.flush()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=6)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.running = False


# ── Codec / preflight verification ───────────────────────────────────────────

def _verify_codec(ffmpeg: str, vcodec: str, acodec: Optional[str] = None
                  ) -> Tuple[bool, List[str]]:
    """Test that codec(s) are usable in this FFmpeg build. Returns (ok, problems)."""
    problems: List[str] = []
    ok, enc_out = _run_silent([ffmpeg, "-hide_banner", "-encoders"], timeout=5)
    if not ok:
        problems.append("Could not query FFmpeg encoders — FFmpeg may be broken.")
        return False, problems
    if vcodec not in enc_out:
        problems.append(
            f"Video codec '{vcodec}' not available in this FFmpeg build.\n"
            f"  Fix: install full FFmpeg build (winget install Gyan.FFmpeg  "
            f"or  sudo apt install ffmpeg)")
    if acodec and acodec not in enc_out:
        problems.append(
            f"Audio codec '{acodec}' not available in this FFmpeg build.\n"
            f"  Fix: install full FFmpeg build (same as above)")
    return len(problems) == 0, problems


def _check_disk_space(out_dir: Path, fps: int, width: int, height: int,
                       vcodec: str) -> Tuple[bool, str]:
    """Estimate required disk space and check it's available.
    Returns (ok, message)."""
    try:
        stat = shutil.disk_usage(str(out_dir))
        free_gb = stat.free / (1024 ** 3)
        # Rough bitrate estimate per codec (Mbps)
        bitrates = {
            "libx264": 8, "libvpx-vp9": 4, "huffyuv": 120,
            "libx265": 5, "libvpx": 6,
        }
        mbps = bitrates.get(vcodec, 8)
        # Estimate for 10 minutes in MB
        est_10min_mb = mbps * 60 * 10 / 8
        if free_gb < 0.5:
            return False, (f"CRITICAL: Only {free_gb:.2f} GB free in {out_dir}. "
                           f"Need at least 500 MB. Free up disk space first.")
        if est_10min_mb / 1024 > free_gb * 0.8:
            return True, (f"Low disk space warning: {free_gb:.1f} GB free. "
                          f"Estimated ~{est_10min_mb:.0f} MB per 10 min at current settings.")
        return True, (f"Disk OK: {free_gb:.1f} GB free  "
                      f"(~{est_10min_mb:.0f} MB per 10 min estimated)")
    except Exception as e:
        return True, f"Could not check disk space: {e}"


def _preflight_check(ffmpeg: str, fmt_name: str, fmt: Dict,
                     out_dir: Path, fps: int,
                     window_title: str, hwnd: Optional[int],
                     screen_w: int, screen_h: int) -> Tuple[bool, List[str], List[str]]:
    """Full pre-recording preflight. Returns (go, errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []

    # 1. FFmpeg executable
    if not ffmpeg or not Path(ffmpeg).exists():
        errors.append("FFmpeg not found. Click 'Repair FFmpeg' to install.")
        return False, errors, warnings

    # 2. Codec availability
    vcodec = str(fmt.get("vcodec", "libx264"))
    acodec = str(fmt.get("acodec", ""))
    codec_ok, codec_problems = _verify_codec(ffmpeg, vcodec, acodec or None)
    if not codec_ok:
        errors.extend(codec_problems)

    # 3. Output directory writable
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        test = out_dir / ".preflight_test"
        test.write_bytes(b"x")
        test.unlink()
    except Exception as e:
        errors.append(f"Output folder not writable: {out_dir}\n  Error: {e}\n"
                      f"  Fix: choose a different output folder.")

    # 4. Disk space
    disk_ok, disk_msg = _check_disk_space(out_dir, fps, screen_w, screen_h, vcodec)
    if not disk_ok:
        errors.append(disk_msg)
    elif "warning" in disk_msg.lower():
        warnings.append(disk_msg)

    # 5. Window handle (Windows only)
    if sys.platform == "win32" and not _is_valid_hwnd(hwnd):
        errors.append(
            f"Window '{window_title}' is not accessible.\n"
            f"  Fix: refresh the window list and re-select the target.")

    # 6. Capture backend
    ok_dev, dev_out = _run_silent([ffmpeg, "-hide_banner", "-devices"], timeout=5)
    backend = "gdigrab" if sys.platform == "win32" else "x11grab"
    if backend not in dev_out:
        errors.append(
            f"Capture backend '{backend}' not available in this FFmpeg.\n"
            f"  Fix: install full FFmpeg (winget install Gyan.FFmpeg  or  "
            f"sudo apt install ffmpeg).")

    return len(errors) == 0, errors, warnings


def _show_preflight_dialog(root: tk.Tk, errors: List[str], warnings: List[str],
                           on_proceed: Callable[[], None]) -> None:
    """Show go/no-go dialog before recording starts."""
    if not errors and not warnings:
        on_proceed()
        return

    win = tk.Toplevel(root)
    win.title("Pre-Recording Check")
    win.configure(bg=COLORS["bg"])
    win.geometry("640x380")
    win.grab_set()
    win.resizable(True, True)

    all_clear = not errors
    header_color = COLORS["ok"] if all_clear else COLORS["danger"]
    header_text = ("Preflight: Warnings Only — Ready to Record"
                   if all_clear else "Preflight: Problems Found — Cannot Record")

    tk.Label(win, text=f"  {header_text}",
             font=(FONT, 12, "bold"), bg=COLORS["panel"],
             fg=header_color, anchor="w").pack(fill="x", pady=(0, 6))

    body = scrolledtext.ScrolledText(
        win, height=10, bg=COLORS["notebk"], fg=COLORS["text"],
        font=("Courier New", 9), relief="flat", state="normal")
    body.pack(fill="both", expand=True, padx=10, pady=4)
    body.tag_configure("err",  foreground=COLORS["danger"])
    body.tag_configure("warn", foreground=COLORS["warn"])
    body.tag_configure("ok",   foreground=COLORS["ok"])

    for e in errors:
        body.insert("end", f"  ERROR: {e}\n\n", "err")
    for w in warnings:
        body.insert("end", f"  WARN:  {w}\n\n", "warn")
    if all_clear:
        body.insert("end", "  All preflight checks passed.\n", "ok")
    body.configure(state="disabled")

    btn_row = tk.Frame(win, bg=COLORS["bg"])
    btn_row.pack(fill="x", padx=10, pady=8)

    if all_clear:
        tk.Button(btn_row, text="Record Now",
                  bg=COLORS["ok"], fg=COLORS["bg"],
                  font=(FONT, 10, "bold"), relief="flat",
                  padx=12, pady=6,
                  command=lambda: (win.destroy(), on_proceed())).pack(side="left")
        tk.Button(btn_row, text="Cancel",
                  bg=COLORS["btn"], fg=COLORS["muted"],
                  relief="flat", padx=10, pady=6,
                  command=win.destroy).pack(side="left", padx=8)
    else:
        tk.Label(btn_row,
                 text="Fix the errors above before recording.",
                 fg=COLORS["danger"], bg=COLORS["bg"],
                 font=(FONT, 9)).pack(side="left")
        tk.Button(btn_row, text="Close",
                  bg=COLORS["btn"], fg=COLORS["text"],
                  relief="flat", padx=10, pady=6,
                  command=win.destroy).pack(side="right")


# ── Region selector (drag-to-crop overlay) ────────────────────────────────────

class RegionSelector:
    """Full-screen transparent overlay.  User drags a rectangle.
    Calls on_select(x, y, w, h) with screen coordinates on confirm,
    or on_cancel() if ESC / closed."""

    def __init__(self, root: tk.Tk,
                 on_select: Callable[[int, int, int, int], None],
                 on_cancel: Callable[[], None]):
        self.root = root
        self.on_select = on_select
        self.on_cancel = on_cancel
        self._sx = self._sy = self._ex = self._ey = 0
        self._dragging = False
        self._rect_id: Optional[int] = None
        self._label_id: Optional[int] = None

        sw, sh = _get_screen_size()

        self.win = tk.Toplevel(root)
        self.win.attributes("-fullscreen", True)
        self.win.attributes("-topmost", True)
        # Semi-transparent dark overlay
        self.win.attributes("-alpha", 0.35)
        self.win.configure(bg="black")
        self.win.overrideredirect(True)

        self.canvas = tk.Canvas(self.win, cursor="crosshair",
                                bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Instructions
        self.canvas.create_text(
            sw // 2, 40,
            text="Drag to select recording region    |    ESC to cancel    |    Release mouse to confirm",
            fill="#00E5C8", font=("Consolas", 13, "bold"),
            tags="hint"
        )

        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.win.bind("<Escape>", lambda _: self._cancel())
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        self.win.focus_force()

    def _on_press(self, e):
        self._sx, self._sy = e.x_root, e.y_root
        self._dragging = True
        if self._rect_id:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_drag(self, e):
        self._ex, self._ey = e.x_root, e.y_root
        if self._rect_id:
            self.canvas.delete(self._rect_id)
        if self._label_id:
            self.canvas.delete(self._label_id)
        x1 = min(self._sx, self._ex)
        y1 = min(self._sy, self._ey)
        x2 = max(self._sx, self._ex)
        y2 = max(self._sy, self._ey)
        # White selection rectangle
        self._rect_id = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="#FFFFFF", width=2, fill="", dash=(4, 2)
        )
        w, h = x2 - x1, y2 - y1
        self._label_id = self.canvas.create_text(
            x1 + 4, y1 - 14,
            text=f"{w} × {h}",
            fill="#FFFFFF", font=("Consolas", 11, "bold"),
            anchor="sw"
        )

    def _on_release(self, e):
        if not self._dragging:
            return
        self._dragging = False
        self._ex, self._ey = e.x_root, e.y_root
        x1, y1 = min(self._sx, self._ex), min(self._sy, self._ey)
        x2, y2 = max(self._sx, self._ex), max(self._sy, self._ey)
        w, h = x2 - x1, y2 - y1
        if w < 16 or h < 16:
            # Too small — let user try again
            return
        self.win.destroy()
        # Make dimensions codec-safe (even numbers)
        w = w - (w % 2)
        h = h - (h % 2)
        self.on_select(x1, y1, w, h)

    def _cancel(self):
        self.win.destroy()
        self.on_cancel()


class RecordingBorderOverlay:
    """
    Screen-share-style colored border drawn around the recording target window.
    Transparent interior, always-on-top, click-through — like Zoom / Teams / OBS.
    """

    THICKNESS     = 3
    COLOR_REC     = "#d84444"   # COLORS["accent"] — active recording
    COLOR_PREVIEW = "#ffd369"   # COLORS["warn"]   — preview flash
    TRANSPARENT   = "black"     # transparentcolor key; must match canvas bg
    LABEL_BG      = "#5a1010"
    LABEL_FG      = "#f5eeee"
    POLL_MS       = 250

    def __init__(self, root: tk.Tk):
        self.root        = root
        self._win: Optional[tk.Toplevel] = None
        self._canvas: Optional[tk.Canvas] = None
        self._poll_job: Optional[str] = None
        self._hwnd: Optional[int] = None
        self._color: str = self.COLOR_REC
        self._label_text: str = "● REC"
        self._last_geom: Optional[Tuple[int, int, int, int]] = None
        self._active: bool = False

    # ── public API ────────────────────────────────────────────────────────────

    def start(self, hwnd: Optional[int],
              color: str = COLOR_REC, label: str = "● REC"):
        """Show border around hwnd and begin tracking."""
        self._hwnd = hwnd
        self._color = color
        self._label_text = label
        self._last_geom = None
        self._active = True
        self._ensure_win()
        self._schedule_poll()

    def update_hwnd(self, hwnd: Optional[int]):
        """Update the tracked window without restarting."""
        if self._hwnd != hwnd:
            self._hwnd = hwnd
            self._last_geom = None

    def stop(self):
        """Hide the border and tear down the overlay window."""
        self._active = False
        self._hwnd = None
        if self._poll_job:
            try:
                self.root.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None
        self._canvas = None
        self._last_geom = None

    def preview(self, hwnd: Optional[int], duration_ms: int = 2500):
        """Flash the border for duration_ms then stop (used by Preview button)."""
        self.start(hwnd, color=self.COLOR_PREVIEW, label="● PREVIEW")
        self.root.after(duration_ms, self._end_preview)

    def _end_preview(self):
        if self._active and self._color == self.COLOR_PREVIEW:
            self.stop()

    # ── internals ─────────────────────────────────────────────────────────────

    def _ensure_win(self):
        if self._win:
            return
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", self.TRANSPARENT)
        win.configure(bg=self.TRANSPARENT)
        win.withdraw()

        canvas = tk.Canvas(win, bg=self.TRANSPARENT, highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        # Make the entire overlay click-through on Windows via WS_EX_TRANSPARENT
        if sys.platform == "win32":
            win.update_idletasks()
            try:
                inner = int(win.winfo_id())
                # GA_ROOT=2: walk up to the actual top-level HWND
                GA_ROOT = 2
                outer = ctypes.windll.user32.GetAncestor(inner, GA_ROOT)
                target = outer if outer else inner
                GWL_EXSTYLE    = -20
                WS_EX_LAYERED  = 0x00080000
                WS_EX_TRANSPARENT = 0x00000020
                style = ctypes.windll.user32.GetWindowLongW(target, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(
                    target, GWL_EXSTYLE,
                    style | WS_EX_LAYERED | WS_EX_TRANSPARENT,
                )
            except Exception:
                pass

        self._win    = win
        self._canvas = canvas

    def _schedule_poll(self):
        if not self._active:
            return
        self._poll_job = self.root.after(self.POLL_MS, self._tick)

    def _tick(self):
        if not self._active or not self._win:
            return
        rect = _get_window_rect(self._hwnd) if self._hwnd else None
        B = self.THICKNESS

        if rect:
            x, y, w, h = rect
            ox, oy = x - B, y - B
            ow, oh = w + 2 * B, h + 2 * B
            geom = (ox, oy, ow, oh)

            if geom != self._last_geom:
                self._last_geom = geom
                self._win.geometry(f"{ow}x{oh}+{ox}+{oy}")
                self._draw(ow, oh)

            if not self._win.winfo_viewable():
                self._win.deiconify()
        else:
            if self._win.winfo_viewable():
                self._win.withdraw()

        self._schedule_poll()

    def _draw(self, w: int, h: int):
        c = self._canvas
        if not c:
            return
        c.delete("all")
        B = self.THICKNESS

        # Full-window rectangle: opaque colored border, transparent interior
        c.create_rectangle(
            0, 0, w - 1, h - 1,
            outline=self._color, width=B * 2,
            fill=self.TRANSPARENT,
        )

        # Small label pill anchored to top-left corner of the border
        lx, ly = B + 6, B + 6
        lw, lh = 66, 18
        c.create_rectangle(
            lx, ly, lx + lw, ly + lh,
            fill=self.LABEL_BG, outline=self._color, width=1,
        )
        c.create_text(
            lx + lw // 2, ly + lh // 2,
            text=self._label_text,
            fill=self._color,
            font=("Consolas", 8, "bold"),
            anchor="center",
        )


_FFMPEG_ERROR_PATTERNS: List[Tuple[str, str]] = [
    # (match fragment, human description)
    ("Could not find a valid device",       "capture device not found"),
    ("device open failed",                  "capture device failed to open"),
    ("No such file or directory",           "output path not writable"),
    ("Permission denied",                   "permission denied — check output folder"),
    ("Invalid argument",                    "invalid FFmpeg argument"),
    ("Encoder libx264 not found",           "libx264 encoder missing"),
    ("Encoder libvpx-vp9 not found",        "libvpx-vp9 encoder missing"),
    ("gdigrab",                             "gdigrab (Windows screen capture) failed"),
    ("x11grab",                             "x11grab (Linux screen capture) failed — is DISPLAY set?"),
    ("Connection refused",                  "screen capture connection refused"),
    ("Unable to find a suitable output",    "incompatible output format"),
    ("moov atom not found",                 "output file corrupt — disk may be full"),
    ("No space left",                       "disk full — free up space and retry"),
    ("Error initializing output stream",    "could not open output stream"),
    ("hwnd=",                               "window handle invalid — re-select target window"),
    ("title=",                              "window title not found — re-select target window"),
    ("pulse",                               "PulseAudio error — try different audio device or disable audio"),
    ("alsa",                                "ALSA audio error — try different audio device or disable audio"),
    ("dshow",                               "DirectShow audio error — try different audio device or disable audio"),
]


def _parse_ffmpeg_error(log_text: str) -> str:
    """Scan FFmpeg log output and return a human-readable cause."""
    for fragment, description in _FFMPEG_ERROR_PATTERNS:
        if fragment.lower() in log_text.lower():
            return description
    # Last-resort: extract last "Error" line
    for line in reversed(log_text.splitlines()):
        if "error" in line.lower() and len(line.strip()) > 10:
            return line.strip()[:120]
    return "unknown error — see log below"


def _ffmpeg_fix_hint(cause: str) -> str:
    """Return a one-line actionable hint for a given error cause."""
    hints = {
        "capture device not found":     "Refresh Windows list and re-select target, or check DISPLAY env var on Ubuntu",
        "capture device failed":        "Try 'Show all windows', re-select target, or reboot and retry",
        "output path not writable":     "Change Output folder to a writable directory (e.g. Desktop/Recordings)",
        "permission denied":            "Run as administrator (Windows) or check folder permissions (Ubuntu: chmod 755)",
        "libx264 encoder missing":      "Re-install FFmpeg full build: winget install Gyan.FFmpeg  or  sudo apt install ffmpeg",
        "libvpx-vp9 encoder missing":   "Switch format to MP4-H264 or re-install full FFmpeg",
        "disk full":                    "Free up disk space or change Output folder to a drive with more space",
        "window handle invalid":        "Click 'Refresh Windows' then re-select the target window",
        "window title not found":       "Click 'Refresh Windows' then re-select the target window",
        "PulseAudio error":             "Disable audio capture, or run: pulseaudio --start",
        "ALSA audio error":             "Disable audio capture or switch to 'pulse' audio device",
        "DirectShow audio error":       "Disable audio capture or click 'Detect Audio Devices' and choose a different device",
        "gdigrab":                      "Re-select target window; if problem persists re-install FFmpeg full build",
        "x11grab":                      "Ensure DISPLAY=:0 is set and you are running in a graphical session",
    }
    for key, hint in hints.items():
        if key in cause:
            return hint
    return "See FFMPEG output in the log below for details"


class ScreenRecorderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.configure(bg=COLORS["bg"])
        self.root.minsize(780, 660)

        self.ffmpeg = _find_ffmpeg()
        self.session: Optional[RecordingSession] = None
        self._window_watch_job: Optional[str] = None
        self._last_seen_hwnds: set[int] = set()
        self._signal_mtime_ns: int = 0
        self._pending_target_prefix: str = ""
        self._pending_target_deadline: float = 0.0
        self._all_windows: List[Tuple[int, str]] = []
        self._citl_windows: List[Tuple[str, str, int]] = []
        self._retarget_pending_title: str = ""
        self._topmost_hwnd: Optional[int] = None
        self._last_saved_video: Optional[Path] = None
        self._recent_recordings: List[Path] = []
        self.recent_listbox: Optional[tk.Listbox] = None
        self.studio_status_var = tk.StringVar(value="Studio: no recordings indexed yet.")
        self.auto_open_editor_var = tk.BooleanVar(value=False)

        self.window_var = tk.StringVar()
        self.format_var = tk.StringVar(value=list(EXPORT_FORMATS.keys())[0])
        self.fps_var = tk.StringVar(value="30")
        self.crf_var = tk.StringVar(value="21")
        self.audio_var = tk.BooleanVar(value=False)
        self.audio_dev_var = tk.StringVar(value="(no audio)")
        self.output_var = tk.StringVar(value=str(RECORDINGS_DIR))
        self.status_var = tk.StringVar(value="Ready")
        self.elapsed_var = tk.StringVar(value="00:00:00")
        self.size_var = tk.StringVar(value="-")
        self.ffmpeg_var = tk.StringVar(value=self.ffmpeg or "NOT FOUND")
        self.show_all_var = tk.BooleanVar(value=False)
        self.launch_var = tk.StringVar(value=list(CITL_KNOWN.keys())[0])
        self.auto_retarget_var = tk.BooleanVar(value=True)
        self.pin_target_var = tk.BooleanVar(value=True)

        # Recording border overlay (screen-share-style crop indicator)
        self._overlay = RecordingBorderOverlay(self.root)
        self._win_status_label: Optional[tk.Label] = None

        # Region / crop state
        self._crop_region: Optional[Tuple[int, int, int, int]] = None
        self._region_var = tk.StringVar(value="Full window / screen")
        self._preflight_var = tk.StringVar(value="Preflight: not checked yet")
        self._disk_var = tk.StringVar(value="")

        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self._refresh_windows()
        self._refresh_recent_recordings()
        self._start_window_watch()
        self.root.after(400, self._update_ffmpeg_label)
        self.root.after(600, self._run_startup_diagnostic)
        self.root.after(800, self._update_disk_estimate)

    def _build_ui(self):
        top = tk.Frame(self.root, bg=COLORS["panel"], padx=12, pady=8)
        top.pack(fill="x")
        tk.Label(top, text=APP_NAME, font=(FONT, 16, "bold"), bg=COLORS["panel"], fg=COLORS["text"]).pack(side="left")
        tk.Label(top, text=APP_VERSION, font=(FONT, 10), bg=COLORS["panel"], fg=COLORS["accent"]).pack(side="left", padx=8)
        tk.Label(top, textvariable=self.ffmpeg_var, font=(FONT, 8), bg=COLORS["panel"], fg=COLORS["muted"]).pack(side="right")

        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=10)

        wbox = tk.LabelFrame(body, text="Target Window", font=(FONT, 9, "bold"), bg=COLORS["card"], fg=COLORS["text"], bd=1, relief="solid")
        wbox.pack(fill="x", pady=(0, 8))
        tk.Checkbutton(
            wbox,
            text="Show all windows",
            variable=self.show_all_var,
            command=self._refresh_windows,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            activebackground=COLORS["card"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["card"],
            font=(FONT, 8),
        ).pack(anchor="w", padx=8, pady=4)
        tk.Checkbutton(
            wbox,
            text="Auto-switch target when CITL Suite launches another app",
            variable=self.auto_retarget_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            activebackground=COLORS["card"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["card"],
            font=(FONT, 8),
        ).pack(anchor="w", padx=8, pady=(0, 2))
        tk.Checkbutton(
            wbox,
            text="Pin target window on top while recording",
            variable=self.pin_target_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            activebackground=COLORS["card"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["card"],
            font=(FONT, 8),
        ).pack(anchor="w", padx=8, pady=(0, 4))
        self.window_combo = ttk.Combobox(wbox, textvariable=self.window_var, state="readonly")
        self.window_combo.pack(fill="x", padx=8, pady=(0, 4))
        self.window_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_win_status())

        # Live window-status indicator row
        status_row = tk.Frame(wbox, bg=COLORS["card"])
        status_row.pack(fill="x", padx=8, pady=(0, 4))
        self._win_status_label = tk.Label(
            status_row, text="",
            bg=COLORS["card"], fg=COLORS["muted"],
            font=("Consolas", 8), anchor="w",
        )
        self._win_status_label.pack(side="left", fill="x", expand=True)

        btn_row_w = tk.Frame(wbox, bg=COLORS["card"])
        btn_row_w.pack(anchor="w", padx=8, pady=(0, 8))
        tk.Button(btn_row_w, text="Refresh Windows", command=self._refresh_windows,
                  bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left")
        tk.Button(
            btn_row_w, text="Preview Target",
            command=self._preview_target,
            bg=COLORS["btn_hi"], fg=COLORS["text"], relief="flat",
        ).pack(side="left", padx=6)
        tk.Button(btn_row_w, text="Repair FFmpeg",
                  command=self._repair_ffmpeg,
                  bg=COLORS["btn_acc"], fg=COLORS["text"], relief="flat").pack(side="left")

        cfg = tk.LabelFrame(body, text="Recording Options", font=(FONT, 9, "bold"), bg=COLORS["card"], fg=COLORS["text"], bd=1, relief="solid")
        cfg.pack(fill="x", pady=(0, 8))
        grid = tk.Frame(cfg, bg=COLORS["card"])
        grid.pack(fill="x", padx=8, pady=8)

        tk.Label(grid, text="Format", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=0, sticky="w")
        ttk.Combobox(grid, textvariable=self.format_var, state="readonly", values=list(EXPORT_FORMATS.keys()), width=28).grid(row=0, column=1, sticky="w", padx=(6, 14))
        tk.Label(grid, text="FPS", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=2, sticky="w")
        ttk.Combobox(grid, textvariable=self.fps_var, state="readonly", values=FPS_OPTIONS, width=8).grid(row=0, column=3, sticky="w", padx=(6, 14))
        tk.Label(grid, text="CRF", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=4, sticky="w")
        ttk.Entry(grid, textvariable=self.crf_var, width=8).grid(row=0, column=5, sticky="w", padx=(6, 0))

        tk.Checkbutton(
            grid,
            text="Capture audio",
            variable=self.audio_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            activebackground=COLORS["card"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["card"],
            font=(FONT, 8),
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.audio_combo = ttk.Combobox(grid, textvariable=self.audio_dev_var, state="readonly", width=35)
        self.audio_combo.grid(row=1, column=1, columnspan=3, sticky="w", padx=(6, 14), pady=(8, 0))
        tk.Button(grid, text="Detect Audio Devices", command=self._refresh_audio_devices, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").grid(row=1, column=4, columnspan=2, sticky="w", padx=(6, 0), pady=(8, 0))

        out = tk.LabelFrame(body, text="Output", font=(FONT, 9, "bold"), bg=COLORS["card"], fg=COLORS["text"], bd=1, relief="solid")
        out.pack(fill="x", pady=(0, 8))
        out_row = tk.Frame(out, bg=COLORS["card"])
        out_row.pack(fill="x", padx=8, pady=8)
        ttk.Entry(out_row, textvariable=self.output_var).pack(side="left", fill="x", expand=True)
        tk.Button(out_row, text="...", command=self._browse_output, bg=COLORS["btn"], fg=COLORS["text"], relief="flat", width=4).pack(side="left", padx=4)
        tk.Button(out_row, text="Open", command=self._open_output, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left")
        tk.Button(out_row, text="Post Editor", command=self._open_post_editor, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left", padx=(4, 0))

        launch = tk.LabelFrame(body, text="Launch + Record", font=(FONT, 9, "bold"), bg=COLORS["card"], fg=COLORS["text"], bd=1, relief="solid")
        launch.pack(fill="x", pady=(0, 8))
        lrow = tk.Frame(launch, bg=COLORS["card"])
        lrow.pack(fill="x", padx=8, pady=8)
        ttk.Combobox(lrow, textvariable=self.launch_var, state="readonly", values=list(CITL_KNOWN.keys()), width=42).pack(side="left", fill="x", expand=True)
        tk.Button(lrow, text="Start + Record", command=self._launch_and_record, bg=COLORS["btn_acc"], fg=COLORS["text"], relief="flat").pack(side="left", padx=(8, 0))

        # ── Region / crop selection ───────────────────────────────────────────
        region_box = tk.LabelFrame(body, text="Capture Region",
                                   font=(FONT, 9, "bold"),
                                   bg=COLORS["card"], fg=COLORS["text"],
                                   bd=1, relief="solid")
        region_box.pack(fill="x", pady=(0, 6))
        rrow = tk.Frame(region_box, bg=COLORS["card"])
        rrow.pack(fill="x", padx=8, pady=6)
        tk.Button(rrow, text="Select Region (drag to crop)",
                  command=self._select_region,
                  bg=COLORS["btn_hi"], fg=COLORS["text"],
                  relief="flat", padx=8, pady=4).pack(side="left")
        self._btn_clear_region = tk.Button(
            rrow, text="Clear Region (full screen/window)",
            command=self._clear_region,
            bg=COLORS["btn"], fg=COLORS["muted"],
            relief="flat", padx=8, pady=4, state="disabled")
        self._btn_clear_region.pack(side="left", padx=6)
        tk.Label(rrow, textvariable=self._region_var,
                 bg=COLORS["card"], fg=COLORS["ok"],
                 font=(FONT, 9, "bold")).pack(side="left", padx=8)

        # ── Preflight / disk status ───────────────────────────────────────────
        pfrow = tk.Frame(body, bg=COLORS["bg"])
        pfrow.pack(fill="x", pady=(0, 4))
        tk.Label(pfrow, textvariable=self._preflight_var,
                 bg=COLORS["bg"], fg=COLORS["warn"],
                 font=(FONT, 8), anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(pfrow, textvariable=self._disk_var,
                 bg=COLORS["bg"], fg=COLORS["muted"],
                 font=(FONT, 8), anchor="e").pack(side="right")

        # ── Recording controls ────────────────────────────────────────────────
        controls = tk.Frame(body, bg=COLORS["bg"])
        controls.pack(fill="x", pady=(2, 8))
        self.btn_start = tk.Button(controls, text="▶  Start Recording",
                                   command=self._start_recording,
                                   bg=COLORS["btn_acc"], fg=COLORS["text"],
                                   relief="flat", font=(FONT, 11, "bold"),
                                   padx=14, pady=6)
        self.btn_start.pack(side="left")
        self.btn_stop = tk.Button(controls, text="■  Stop Recording",
                                  command=self._stop_recording,
                                  bg=COLORS["btn"], fg=COLORS["muted"],
                                  relief="flat", state="disabled",
                                  font=(FONT, 11, "bold"), padx=14, pady=6)
        self.btn_stop.pack(side="left", padx=8)
        tk.Button(controls, text="Preflight Check",
                  command=self._run_preflight_ui,
                  bg=COLORS["btn"], fg=COLORS["text"],
                  relief="flat", padx=8, pady=6).pack(side="left", padx=(0, 8))
        tk.Label(controls, textvariable=self.elapsed_var, bg=COLORS["bg"],
                 fg=COLORS["text"], font=(FONT, 12, "bold")).pack(side="left", padx=(8, 0))
        tk.Label(controls, textvariable=self.size_var, bg=COLORS["bg"],
                 fg=COLORS["muted"], font=(FONT, 10)).pack(side="left", padx=8)
        tk.Label(controls, textvariable=self.status_var, bg=COLORS["bg"],
                 fg=COLORS["accent"], font=(FONT, 9, "bold")).pack(side="right")

        studio = tk.LabelFrame(
            body,
            text="Recording + Editing Studio",
            font=(FONT, 9, "bold"),
            bg=COLORS["card"],
            fg=COLORS["text"],
            bd=1,
            relief="solid",
        )
        studio.pack(fill="both", expand=False, pady=(0, 8))

        studio_inner = tk.Frame(studio, bg=COLORS["card"])
        studio_inner.pack(fill="both", expand=True, padx=8, pady=8)
        studio_inner.grid_columnconfigure(0, weight=3)
        studio_inner.grid_columnconfigure(1, weight=2)
        studio_inner.grid_rowconfigure(1, weight=1)

        tk.Label(
            studio_inner,
            text="Past Recordings (newest first)",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(FONT, 8, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            studio_inner,
            textvariable=self.studio_status_var,
            bg=COLORS["card"],
            fg=COLORS["faint"],
            font=(FONT, 8),
        ).grid(row=0, column=1, sticky="e")

        self.recent_listbox = tk.Listbox(
            studio_inner,
            height=7,
            bg=COLORS["notebk"],
            fg=COLORS["text"],
            selectbackground=COLORS["btn_hi"],
            relief="flat",
            font=("Consolas", 9),
        )
        self.recent_listbox.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(4, 2))
        self.recent_listbox.bind("<Double-Button-1>", lambda _e: self._open_selected_in_post_editor())

        studio_btns = tk.Frame(studio_inner, bg=COLORS["card"])
        studio_btns.grid(row=1, column=1, sticky="nsew", pady=(4, 2))
        studio_btns.grid_columnconfigure(0, weight=1)
        tk.Button(studio_btns, text="Refresh Recent", command=self._refresh_recent_recordings, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").grid(row=0, column=0, sticky="ew", pady=2)
        tk.Button(studio_btns, text="Open Selected Video", command=self._open_selected_recording_file, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").grid(row=1, column=0, sticky="ew", pady=2)
        tk.Button(studio_btns, text="Edit Selected in Post Editor", command=self._open_selected_in_post_editor, bg=COLORS["btn_hi"], fg=COLORS["text"], relief="flat").grid(row=2, column=0, sticky="ew", pady=2)
        tk.Button(studio_btns, text="Open Screenshots Folder", command=self._open_screenshots_folder, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").grid(row=3, column=0, sticky="ew", pady=2)
        tk.Button(studio_btns, text="Open Technical Writer Studio", command=self._open_technical_writer_studio, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").grid(row=4, column=0, sticky="ew", pady=2)
        tk.Checkbutton(
            studio_btns,
            text="Auto-open Post Editor after save",
            variable=self.auto_open_editor_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            activebackground=COLORS["card"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["card"],
            font=(FONT, 8),
        ).grid(row=5, column=0, sticky="w", pady=(8, 0))

        self.log = scrolledtext.ScrolledText(
            body,
            height=12,
            bg=COLORS["notebk"],
            fg="#90c090",
            insertbackground=COLORS["text"],
            font=("Courier New", 8),
            relief="flat",
        )
        self.log.pack(fill="both", expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _run_startup_diagnostic(self):
        """Check FFmpeg and capture support. Show repair dialog if broken."""
        def _bg():
            issues = []
            if not self.ffmpeg:
                issues.append("FFmpeg not found. Recording is not possible without it.")
            else:
                issues.extend(_diagnose_ffmpeg())
            if issues:
                self.root.after(0, lambda: _startup_repair_dialog(
                    self.root, issues,
                    on_fixed=lambda path: (
                        setattr(self, "ffmpeg", path),
                        self._update_ffmpeg_label(),
                        self._log(f"[FIX] FFmpeg installed: {path}\n"),
                    )
                ))
        threading.Thread(target=_bg, daemon=True).start()

    def _update_ffmpeg_label(self):
        if self.ffmpeg:
            self.ffmpeg_var.set(f"{self.ffmpeg} [{_ffmpeg_version(self.ffmpeg)}]")
        else:
            self.ffmpeg_var.set("NOT FOUND — click Repair FFmpeg in the log area")

    def _log(self, text: str):
        self.log.insert("end", text)
        self.log.see("end")

    def _clean_selected_title(self) -> str:
        raw = self.window_var.get().strip()
        return re.sub(r"^\[[^\]]+\]\s*", "", raw).strip()

    def _set_selected_window(self, title: str) -> bool:
        title = (title or "").strip()
        if not title:
            return False
        if self.show_all_var.get():
            self.window_combo.set(title)
            return True
        for app_name, win_title, _ in self._citl_windows:
            if win_title == title:
                icon = CITL_KNOWN.get(app_name, {}).get("icon", "[APP]")
                self.window_combo.set(f"{icon} {win_title}")
                return True
        self.window_combo.set(title)
        return True

    def _resolve_hwnd_for_title(self, title: str) -> Optional[int]:
        needle = (title or "").strip()
        if not needle:
            return None
        for app_name, win_title, hwnd in self._citl_windows:
            if win_title == needle:
                return hwnd
        for hwnd, win_title in self._all_windows:
            if win_title == needle:
                return hwnd
        return None

    def _release_topmost(self):
        if self._topmost_hwnd:
            _set_window_topmost(self._topmost_hwnd, False)
            self._topmost_hwnd = None

    def _request_retarget(self, title: str):
        target = (title or "").strip()
        if not target:
            return

        if self.session and self.session.running:
            current = (self.session.window_title or "").strip()
            if current.lower() == target.lower():
                self.status_var.set(f"Target window: {target}")
                return
            if self._retarget_pending_title and self._retarget_pending_title.lower() == target.lower():
                return
            self._retarget_pending_title = target
            self._set_selected_window(target)
            self.status_var.set(f"Switching target: {target}")
            self._log(f"[TARGET] Retarget requested: {target}\n")
            self.session.stop()
            return

        self._set_selected_window(target)
        self.status_var.set(f"Target window: {target}")

    def _refresh_windows(self, auto_select_new: bool = False, log: bool = True):
        prev_selected = self._clean_selected_title()
        prev_hwnds = set(self._last_seen_hwnds)

        self._all_windows = _enum_visible_windows()
        self._citl_windows = _find_citl_windows(self._all_windows)
        current_hwnds = {hwnd for _, _, hwnd in self._citl_windows}
        new_hwnds = current_hwnds - prev_hwnds
        self._last_seen_hwnds = current_hwnds

        if self.show_all_var.get():
            entries = [title for _, title in self._all_windows if title.strip()]
        else:
            entries = []
            for app_name, title, _ in self._citl_windows:
                icon = CITL_KNOWN.get(app_name, {}).get("icon", "[APP]")
                entries.append(f"{icon} {title}")
            if not entries:
                entries.append("(no CITL windows open - launch an app first)")

        self.window_combo["values"] = entries

        selected_title: Optional[str] = None
        if auto_select_new and new_hwnds:
            for _, title, hwnd in reversed(self._citl_windows):
                if hwnd in new_hwnds:
                    selected_title = title
                    break
        if not selected_title:
            selected_title = prev_selected

        if selected_title:
            self._set_selected_window(selected_title)
        elif entries:
            self.window_combo.set(entries[0])

        if log:
            self._log(
                f"[INFO] Found {len(self._citl_windows)} CITL window(s) "
                f"({len(self._all_windows)} total)\n"
            )

    def _select_window_by_prefix(self, prefix: str) -> Optional[str]:
        needle = (prefix or "").strip().lower()
        if not needle:
            return None
        for _, title, _ in reversed(self._citl_windows):
            if needle in title.lower():
                self._set_selected_window(title)
                return title
        for _, title in reversed(self._all_windows):
            if needle in title.lower():
                self._set_selected_window(title)
                return title
        return None

    def _queue_target_prefix(self, prefix: str, source: str = "signal"):
        prefix = (prefix or "").strip()
        if not prefix:
            return
        self._pending_target_prefix = prefix
        self._pending_target_deadline = time.time() + TARGET_SIGNAL_TTL_SEC
        self._log(f"[TARGET] Queued ({source}): {prefix}\n")

    def _consume_target_signal(self):
        p = RECORDER_SIGNAL_PATH
        if not p.exists():
            return
        try:
            mtime_ns = p.stat().st_mtime_ns
        except Exception:
            return
        if mtime_ns <= self._signal_mtime_ns:
            return
        self._signal_mtime_ns = mtime_ns
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        prefix = str(payload.get("title_prefix") or "").strip()
        app_name = str(payload.get("app_name") or "").strip()
        if prefix:
            self._queue_target_prefix(prefix, source=app_name or "suite")

    def _start_window_watch(self):
        if self._window_watch_job:
            try:
                self.root.after_cancel(self._window_watch_job)
            except Exception:
                pass
        self._window_watch_job = self.root.after(WINDOW_WATCH_MS, self._window_watch_tick)

    def _window_watch_tick(self):
        self._consume_target_signal()
        auto_switch = not (self.session and self.session.running)
        self._refresh_windows(auto_select_new=auto_switch, log=False)
        self._update_win_status()
        if self._pending_target_prefix:
            matched = self._select_window_by_prefix(self._pending_target_prefix)
            if matched:
                if self.session and self.session.running and self.auto_retarget_var.get():
                    self._request_retarget(matched)
                else:
                    self.status_var.set(f"Target window: {matched}")
                self._pending_target_prefix = ""
                self._pending_target_deadline = 0.0
            elif time.time() > self._pending_target_deadline:
                self._log(f"[WARN] Target not found: {self._pending_target_prefix}\n")
                self._pending_target_prefix = ""
                self._pending_target_deadline = 0.0
        self._window_watch_job = self.root.after(WINDOW_WATCH_MS, self._window_watch_tick)

    # ── Window status indicator + preview ─────────────────────────────────────

    def _update_win_status(self):
        """Refresh the live window-status label below the combo."""
        if not self._win_status_label:
            return
        title = self._clean_selected_title()
        if not title or "no CITL windows open" in title.lower():
            self._win_status_label.config(text="", fg=COLORS["muted"])
            return
        hwnd = self._resolve_hwnd_for_title(title)
        if hwnd and _is_valid_hwnd(hwnd):
            rect = _get_window_rect(hwnd)
            dim = f"  {rect[2]}×{rect[3]}" if rect else ""
            self._win_status_label.config(
                text=f"● HWND {hwnd}{dim}  —  window accessible",
                fg=COLORS["ok"],
            )
        else:
            self._win_status_label.config(
                text="● window handle not found — click Refresh Windows",
                fg=COLORS["danger"],
            )

    def _preview_target(self):
        """Flash the recording border around the currently selected window for 2.5 s."""
        if self.session and self.session.running:
            return  # overlay already showing as REC border
        title = self._clean_selected_title()
        hwnd  = self._resolve_hwnd_for_title(title) if title else None
        if not hwnd or not _is_valid_hwnd(hwnd):
            self._log("[PREVIEW] Window not found — select a valid target first.\n")
            return
        self._log(f"[PREVIEW] Highlighting: {title}\n")
        self._overlay.preview(hwnd, duration_ms=2500)

    # ── Region selection ──────────────────────────────────────────────────────

    def _select_region(self):
        """Open full-screen drag-to-crop overlay."""
        if self.session and self.session.running:
            messagebox.showwarning(APP_NAME, "Stop recording before changing the region.")
            return
        # Minimise main window so user can see the whole screen
        self.root.iconify()
        self.root.after(250, self._open_region_selector)

    def _open_region_selector(self):
        def _on_select(x: int, y: int, w: int, h: int):
            self._crop_region = (x, y, w, h)
            self._region_var.set(f"Region: {w}×{h} at ({x},{y})")
            self._btn_clear_region.config(state="normal")
            self._log(f"[REGION] Selected: {w}×{h} at screen pos ({x},{y})\n")
            self.root.deiconify()
            self._update_disk_estimate()

        def _on_cancel():
            self.root.deiconify()
            self._log("[REGION] Cancelled — using full window/screen\n")

        RegionSelector(self.root, on_select=_on_select, on_cancel=_on_cancel)

    def _clear_region(self):
        self._crop_region = None
        self._region_var.set("Full window / screen")
        self._btn_clear_region.config(state="disabled")
        self._log("[REGION] Cleared — will capture full window\n")
        self._update_disk_estimate()

    def _update_disk_estimate(self):
        """Refresh the disk space label based on current settings."""
        def _bg():
            try:
                out_dir = Path(self.output_var.get().strip() or str(RECORDINGS_DIR))
                out_dir.mkdir(parents=True, exist_ok=True)
                fmt = EXPORT_FORMATS.get(self.format_var.get(), {})
                vcodec = str(fmt.get("vcodec", "libx264"))
                sw, sh = _get_screen_size()
                _, msg = _check_disk_space(out_dir, 30, sw, sh, vcodec)
                self.root.after(0, lambda: self._disk_var.set(msg))
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True).start()

    # ── Preflight ─────────────────────────────────────────────────────────────

    def _run_preflight_ui(self, on_proceed: Optional[Callable[[], None]] = None):
        """Run full preflight check and show results dialog."""
        title = self._clean_selected_title()
        hwnd  = self._resolve_hwnd_for_title(title) if title else None
        fmt_name = self.format_var.get()
        fmt = EXPORT_FORMATS.get(fmt_name, EXPORT_FORMATS[list(EXPORT_FORMATS.keys())[0]])
        out_dir = Path(self.output_var.get().strip() or str(RECORDINGS_DIR))
        sw, sh = _get_screen_size()

        def _bg():
            go, errors, warnings = _preflight_check(
                ffmpeg=self.ffmpeg or "",
                fmt_name=fmt_name, fmt=fmt,
                out_dir=out_dir,
                fps=30, window_title=title or "",
                hwnd=hwnd, screen_w=sw, screen_h=sh,
            )
            def _ui():
                if go:
                    self._preflight_var.set(
                        f"Preflight OK  {len(warnings)} warning(s)")
                else:
                    self._preflight_var.set(
                        f"Preflight FAILED — {len(errors)} error(s)")
                _show_preflight_dialog(
                    self.root, errors, warnings,
                    on_proceed=on_proceed or (lambda: None)
                )
            self.root.after(0, _ui)
        threading.Thread(target=_bg, daemon=True).start()

    def _repair_ffmpeg(self):
        """Show the FFmpeg repair dialog and re-check."""
        issues = []
        if not self.ffmpeg:
            issues.append("FFmpeg not found on this machine.")
        else:
            issues.extend(_diagnose_ffmpeg())
            if not issues:
                messagebox.showinfo(APP_NAME,
                    f"FFmpeg OK: {self.ffmpeg}\nVersion: {_ffmpeg_version(self.ffmpeg)}")
                return
        if not issues:
            issues = ["FFmpeg may have a problem. Click Fix Now to reinstall."]
        _startup_repair_dialog(
            self.root, issues,
            on_fixed=lambda path: (
                setattr(self, "ffmpeg", path),
                self._update_ffmpeg_label(),
                self._log(f"[FIX] FFmpeg repaired: {path}\n"),
            )
        )

    def _refresh_audio_devices(self):
        if not self.ffmpeg:
            messagebox.showwarning(APP_NAME, "FFmpeg not found.")
            return
        devs = _list_audio_devices(self.ffmpeg)
        if devs:
            self.audio_combo["values"] = devs
            self.audio_dev_var.set(devs[0])
            self._log(f"[INFO] Audio devices: {', '.join(devs)}\n")
        else:
            self._log("[WARN] No DirectShow audio devices found.\n")

    def _next_output_path(self) -> Path:
        fmt = EXPORT_FORMATS[self.format_var.get()]
        ext = str(fmt["ext"])
        out_dir = Path(self.output_var.get().strip() or str(RECORDINGS_DIR))
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return out_dir / f"citl_demo_{stamp}{ext}"

    def _start_recording(self):
        if not self.ffmpeg:
            messagebox.showerror(APP_NAME,
                "FFmpeg not found.\nClick 'Repair FFmpeg' to install it automatically.")
            return
        title = self._clean_selected_title()
        if not title or "no CITL windows open" in title.lower():
            messagebox.showwarning(APP_NAME,
                "Select a window to record first.\n"
                "Launch a CITL app, then click 'Refresh Windows'.")
            return
        if self.session and self.session.running:
            return

        fmt = EXPORT_FORMATS[self.format_var.get()]
        try:
            fps = int(self.fps_var.get().strip())
        except Exception:
            fps = 30
        crf = self.crf_var.get().strip() or "21"
        out_path = self._next_output_path()
        hwnd = self._resolve_hwnd_for_title(title)

        if sys.platform == "win32" and not self._crop_region:
            # Re-validate hwnd (may have changed)
            if not _is_valid_hwnd(hwnd):
                self._refresh_windows(auto_select_new=False, log=False)
                hwnd = self._resolve_hwnd_for_title(title)
            if not _is_valid_hwnd(hwnd):
                messagebox.showwarning(APP_NAME,
                    "Target window handle not found.\n"
                    "Click 'Refresh Windows', re-select the target, or use "
                    "'Select Region' to specify the capture area manually.")
                return

        # Run preflight — show go/no-go dialog first, then start if approved
        out_dir = out_path.parent
        sw, sh = _get_screen_size()

        def _do_start():
            """Actually start the recording session."""
            self._release_topmost()
            if not self._crop_region and _is_valid_hwnd(hwnd):
                _focus_window(hwnd)
                if self.pin_target_var.get() and _set_window_topmost(hwnd, True):
                    self._topmost_hwnd = hwnd

            # Show screen-share-style recording border
            if sys.platform == "win32" and hwnd and _is_valid_hwnd(hwnd):
                self._overlay.start(hwnd)

            def safe_log(msg: str):
                self.root.after(0, lambda: self._log(msg))

            def safe_done(rc: int, path: str):
                self.root.after(0, lambda: self._on_recording_done(rc, path))

            self.session = RecordingSession(
                ffmpeg_path=self.ffmpeg,
                window_title=title,
                window_hwnd=hwnd,
                output_path=str(out_path),
                fmt=fmt,
                fps=fps,
                audio_enabled=bool(self.audio_var.get()),
                audio_device=(self.audio_dev_var.get() if self.audio_var.get() else None),
                quality_crf=crf,
                crop_region=self._crop_region,
                on_log=safe_log,
                on_done=safe_done,
            )
            try:
                self.session.start()
            except Exception as exc:
                region_hint = (" — if window capture fails, use 'Select Region' "
                               "to drag a capture area instead.") if not self._crop_region else ""
                messagebox.showerror(APP_NAME,
                    f"Failed to start recording:\n{exc}{region_hint}")
                self.session = None
                return

            self.btn_start.config(state="disabled", bg=COLORS["btn"])
            self.btn_stop.config(state="normal", bg="#6b1c1c", fg=COLORS["text"])
            region_label = (f"[{self._crop_region[2]}×{self._crop_region[3]}]"
                            if self._crop_region else "")
            self.status_var.set(f"Recording {region_label}: {out_path.name}")
            self._tick_timer()

        # Run preflight in background, then call _do_start if go
        def _preflight_bg():
            go, errors, warnings = _preflight_check(
                ffmpeg=self.ffmpeg,
                fmt_name=self.format_var.get(), fmt=fmt,
                out_dir=out_dir, fps=fps,
                window_title=title, hwnd=hwnd,
                screen_w=sw, screen_h=sh,
            )
            if go:
                self._preflight_var.set(
                    f"Preflight OK  {len(warnings)} warning(s)")
            else:
                self._preflight_var.set(
                    f"Preflight FAILED — {len(errors)} error(s)")
            self.root.after(0, lambda: _show_preflight_dialog(
                self.root, errors, warnings, on_proceed=_do_start))

        threading.Thread(target=_preflight_bg, daemon=True).start()

    def _tick_timer(self):
        if self.session and self.session.running:
            elapsed = int(time.time() - self.session.start_time)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self.elapsed_var.set(f"{h:02d}:{m:02d}:{s:02d}")
            out = Path(self.session.output_path)
            if out.exists():
                self.size_var.set(f"{out.stat().st_size / (1024 * 1024):.1f} MB")
            self.root.after(1000, self._tick_timer)
        else:
            self.elapsed_var.set("00:00:00")
            self.size_var.set("-")

    def _stop_recording(self):
        if self.session:
            self.status_var.set("Stopping...")
            self.session.stop()

    def _on_recording_done(self, rc: int, path: str):
        self._overlay.stop()
        self.btn_start.config(state="normal", bg=COLORS["btn_acc"])
        self.btn_stop.config(state="disabled", bg=COLORS["btn"], fg=COLORS["muted"])
        next_title = self._retarget_pending_title.strip()
        self._retarget_pending_title = ""
        if rc == 0:
            p = Path(path)
            mb = p.stat().st_size / (1024 * 1024) if p.exists() else 0
            self._last_saved_video = p if p.exists() else None
            self.status_var.set(f"Saved: {p.name} ({mb:.1f} MB)")
            self._log(f"[DONE] Saved {p.name} ({mb:.1f} MB)\n")
            self._refresh_recent_recordings()
            if self.auto_open_editor_var.get() and self._last_saved_video and self._last_saved_video.exists():
                self.root.after(300, lambda p=self._last_saved_video: self._open_post_editor(input_override=p))
        else:
            # Parse known FFmpeg failure patterns from the log widget
            log_text = self.log.get("1.0", "end")
            cause = _parse_ffmpeg_error(log_text)
            self.status_var.set(f"Recording failed (code {rc}): {cause}")
            self._log(f"[ERROR] FFmpeg exit code {rc}: {cause}\n")
            self._log("[HINT]  " + _ffmpeg_fix_hint(cause) + "\n")
        self.session = None
        self.elapsed_var.set("00:00:00")
        self._release_topmost()

        if next_title:
            self._set_selected_window(next_title)
            self.status_var.set(f"Retargeting: {next_title}")
            self._log(f"[TARGET] Starting next segment on: {next_title}\n")
            self.root.after(RETARGET_START_DELAY_MS, self._start_recording)

    def _launch_and_record(self):
        app_name = self.launch_var.get().strip()
        meta = CITL_KNOWN.get(app_name)
        if not meta:
            return
        launcher = REPO / str(meta["launcher_win"])
        if not launcher.exists():
            messagebox.showwarning(APP_NAME, f"Launcher not found:\n{launcher}")
            return
        try:
            ext = launcher.suffix.lower()
            if ext in (".cmd", ".bat"):
                subprocess.Popen(["cmd", "/c", str(launcher)], cwd=str(REPO), creationflags=0x08000000)
            elif ext == ".ps1":
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher)],
                    cwd=str(REPO),
                    creationflags=0x08000000,
                )
            elif ext == ".py":
                subprocess.Popen([sys.executable, str(launcher)], cwd=str(launcher.parent), creationflags=0x08000000)
            else:
                os.startfile(str(launcher))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Launch failed:\n{exc}")
            return

        prefix = str(meta.get("title_prefix") or "").strip()
        self._queue_target_prefix(prefix, source=f"launch:{app_name}")
        self.status_var.set(f"Launched {app_name} - waiting for window...")
        self._log(f"[LAUNCH] {app_name} ({launcher.name})\n")

        deadline = time.time() + 15.0

        def _try_capture():
            self._refresh_windows(auto_select_new=True, log=False)
            matched = self._select_window_by_prefix(prefix)
            if matched:
                self._log(f"[WINDOW] Found: {matched}\n")
                self.status_var.set(f"Target window ready: {matched}")
                self.root.after(0, self._start_recording)
                return
            if time.time() < deadline:
                self.root.after(600, _try_capture)
                return
            self._log(f"[WARN] Could not find window for {app_name}\n")
            self.status_var.set(f"Target window not found: {app_name}")

        self.root.after(900, _try_capture)

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select output folder", initialdir=self.output_var.get())
        if d:
            self.output_var.set(d)
            self._refresh_recent_recordings()

    def _open_output(self):
        p = Path(self.output_var.get().strip())
        if p.exists():
            _open_path(p)
        else:
            messagebox.showinfo(APP_NAME, f"Folder not found:\n{p}")

    def _recent_videos(self, limit: int = 40) -> List[Path]:
        out_dir = Path(self.output_var.get().strip() or str(RECORDINGS_DIR))
        if not out_dir.exists():
            return []
        videos: List[Path] = []
        for pattern in VIDEO_GLOB_PATTERNS:
            videos.extend(p for p in out_dir.glob(pattern) if p.is_file())
        videos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return videos[: max(1, int(limit))]

    def _format_recent_label(self, p: Path) -> str:
        try:
            ts = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            size_mb = p.stat().st_size / (1024 * 1024)
            return f"{ts}  {p.name}  ({size_mb:.1f} MB)"
        except Exception:
            return p.name

    def _refresh_recent_recordings(self):
        if self.recent_listbox is None:
            return
        self._recent_recordings = self._recent_videos(limit=60)
        lb = self.recent_listbox
        lb.delete(0, "end")
        for p in self._recent_recordings:
            lb.insert("end", self._format_recent_label(p))
        if self._recent_recordings:
            lb.selection_clear(0, "end")
            lb.selection_set(0)
            self.studio_status_var.set(
                f"Studio: {len(self._recent_recordings)} recording(s) indexed. "
                f"Newest: {self._recent_recordings[0].name}"
            )
        else:
            self.studio_status_var.set("Studio: no recordings found in output folder.")

    def _selected_recent_recording(self) -> Optional[Path]:
        if self.recent_listbox is None:
            return None
        idxs = list(self.recent_listbox.curselection())
        if not idxs:
            return self._recent_recordings[0] if self._recent_recordings else None
        idx = int(idxs[0])
        if idx < 0 or idx >= len(self._recent_recordings):
            return None
        return self._recent_recordings[idx]

    def _open_selected_recording_file(self):
        p = self._selected_recent_recording()
        if p is None or not p.exists():
            messagebox.showinfo(APP_NAME, "Select a recording first.")
            return
        try:
            _open_path(p)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open recording:\n{exc}")

    def _open_screenshots_folder(self):
        try:
            SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            _open_path(SCREENSHOTS_DIR)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open screenshots folder:\n{exc}")

    def _open_technical_writer_studio(self):
        script = REPO / "factbook-assistant" / "citl_technical_writing_tutorial_creator.py"
        if not script.exists():
            messagebox.showwarning(APP_NAME, f"Technical Writer Studio not found:\n{script}")
            return
        try:
            subprocess.Popen(
                [sys.executable, str(script)],
                cwd=str(script.parent),
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            self.status_var.set("Opened Technical Writer Studio")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open Technical Writer Studio:\n{exc}")

    def _open_selected_in_post_editor(self):
        p = self._selected_recent_recording()
        if p is None or not p.exists():
            messagebox.showinfo(APP_NAME, "Select a recording first.")
            return
        self._open_post_editor(input_override=p)

    def _open_post_editor(self, input_override: Optional[Path] = None):
        script = REPO / "factbook-assistant" / "citl_video_post_editor.py"
        if not script.exists():
            messagebox.showwarning(APP_NAME, f"Post editor not found:\n{script}")
            return

        cmd = [sys.executable, str(script)]
        explicit = input_override if (input_override and input_override.exists()) else None
        if explicit is not None:
            cmd.extend(["--input", str(explicit)])
        elif self._last_saved_video and self._last_saved_video.exists():
            cmd.extend(["--input", str(self._last_saved_video)])
        else:
            newest = self._recent_videos(limit=1)
            if newest:
                cmd.extend(["--input", str(newest[0])])

        try:
            subprocess.Popen(
                cmd,
                cwd=str(script.parent),
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            self.status_var.set("Opened post editor")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open post editor:\n{exc}")

    def _on_close(self):
        if self._window_watch_job:
            try:
                self.root.after_cancel(self._window_watch_job)
            except Exception:
                pass
            self._window_watch_job = None
        if self.session and self.session.running:
            try:
                self.session.stop()
            except Exception:
                pass
        self._overlay.stop()
        self._release_topmost()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ScreenRecorderApp(root)
        root.mainloop()
    except Exception:
        crash = _HERE / "citl_screen_recorder_crash.log"
        crash.write_text(f"[{datetime.now()}]\n{traceback.format_exc()}\n", encoding="utf-8")
        try:
            messagebox.showerror(APP_NAME, f"Startup error.\nSee:\n{crash}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
