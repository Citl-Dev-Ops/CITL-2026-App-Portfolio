#!/usr/bin/env python3
"""
CITL Screen Recorder
====================
Window-focused recorder for CITL applications using FFmpeg.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except Exception:
    print("tkinter is required for CITL Screen Recorder.")
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

_WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


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


def _find_ffmpeg() -> Optional[str]:
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    candidates = [
        REPO / "bin" / "ffmpeg.exe",
        REPO / "bin" / "windows" / "ffmpeg.exe",
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "FFmpeg" / "bin" / "ffmpeg.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
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
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            stderr=subprocess.STDOUT,
            timeout=8,
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
    on_log: Optional[Callable[[str], None]] = None
    on_done: Optional[Callable[[int, str], None]] = None

    proc: Optional[subprocess.Popen] = None
    running: bool = False
    start_time: float = 0.0

    def _cmd(self) -> List[str]:
        cmd: List[str] = [
            self.ffmpeg_path,
            "-hide_banner",
            "-f", "gdigrab",
            "-framerate", str(self.fps),
            "-i", (f"hwnd={self.window_hwnd}" if self.window_hwnd else f"title={self.window_title}"),
            "-vcodec", str(self.fmt["vcodec"]),
        ]
        vflags = list(self.fmt.get("vflags", []))
        if "-crf" in vflags:
            idx = vflags.index("-crf")
            if idx + 1 < len(vflags):
                vflags[idx + 1] = self.quality_crf
        cmd.extend(vflags)
        if self.fmt["vcodec"] in ("libx264", "libvpx-vp9"):
            cmd.extend(["-pix_fmt", "yuv420p"])

        supports_audio = bool(self.fmt.get("audio"))
        if supports_audio and self.audio_enabled and self.audio_device and sys.platform == "win32":
            cmd.extend(["-f", "dshow", "-i", f"audio={self.audio_device}"])
            acodec = str(self.fmt.get("acodec") or "")
            if acodec:
                cmd.extend(["-acodec", acodec])
            cmd.extend(list(self.fmt.get("aflags", [])))
        elif supports_audio:
            cmd.append("-an")
        else:
            cmd.append("-an")

        cmd.extend(["-y", self.output_path])
        return cmd

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

        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self._refresh_windows()
        self._refresh_recent_recordings()
        self._start_window_watch()
        self.root.after(400, self._update_ffmpeg_label)

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
        self.window_combo.pack(fill="x", padx=8, pady=(0, 6))
        tk.Button(wbox, text="Refresh Windows", command=self._refresh_windows, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(anchor="w", padx=8, pady=(0, 8))

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

        controls = tk.Frame(body, bg=COLORS["bg"])
        controls.pack(fill="x", pady=(2, 8))
        self.btn_start = tk.Button(controls, text="Start Recording", command=self._start_recording, bg=COLORS["btn_acc"], fg=COLORS["text"], relief="flat", font=(FONT, 11, "bold"), padx=14, pady=6)
        self.btn_start.pack(side="left")
        self.btn_stop = tk.Button(controls, text="Stop Recording", command=self._stop_recording, bg=COLORS["btn"], fg=COLORS["muted"], relief="flat", state="disabled", font=(FONT, 11, "bold"), padx=14, pady=6)
        self.btn_stop.pack(side="left", padx=8)
        tk.Label(controls, textvariable=self.elapsed_var, bg=COLORS["bg"], fg=COLORS["text"], font=(FONT, 12, "bold")).pack(side="left", padx=(8, 0))
        tk.Label(controls, textvariable=self.size_var, bg=COLORS["bg"], fg=COLORS["muted"], font=(FONT, 10)).pack(side="left", padx=8)
        tk.Label(controls, textvariable=self.status_var, bg=COLORS["bg"], fg=COLORS["accent"], font=(FONT, 9, "bold")).pack(side="right")

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

    def _update_ffmpeg_label(self):
        if self.ffmpeg:
            self.ffmpeg_var.set(f"{self.ffmpeg} [{_ffmpeg_version(self.ffmpeg)}]")
        else:
            self.ffmpeg_var.set("NOT FOUND - install FFmpeg for recording")

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
            messagebox.showerror(APP_NAME, "FFmpeg not found.")
            return
        title = self._clean_selected_title()
        if not title or "no CITL windows open" in title.lower():
            messagebox.showwarning(APP_NAME, "Select a window to record first.")
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
        if sys.platform == "win32":
            if not _is_valid_hwnd(hwnd):
                self._refresh_windows(auto_select_new=False, log=False)
                hwnd = self._resolve_hwnd_for_title(title)
            if not _is_valid_hwnd(hwnd):
                messagebox.showwarning(
                    APP_NAME,
                    "Target window handle not found.\n"
                    "Refresh windows and select the target app again.",
                )
                return

        self._release_topmost()
        if _is_valid_hwnd(hwnd):
            _focus_window(hwnd)
            if self.pin_target_var.get() and _set_window_topmost(hwnd, True):
                self._topmost_hwnd = hwnd

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
            on_log=safe_log,
            on_done=safe_done,
        )
        try:
            self.session.start()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Failed to start recording:\n{exc}")
            self.session = None
            return

        self.btn_start.config(state="disabled", bg=COLORS["btn"])
        self.btn_stop.config(state="normal", bg="#6b1c1c", fg=COLORS["text"])
        self.status_var.set(f"Recording: {out_path.name}")
        self._tick_timer()

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
            self.status_var.set(f"Recording ended (code {rc})")
            self._log(f"[WARN] FFmpeg exit code {rc}\n")
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
            os.startfile(str(p))
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
            os.startfile(str(p))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open recording:\n{exc}")

    def _open_screenshots_folder(self):
        try:
            SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(SCREENSHOTS_DIR))
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
