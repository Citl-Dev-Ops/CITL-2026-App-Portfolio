#!/usr/bin/env python3
"""
CITL Video Post Editor
----------------------
Simple post-production editor for CITL walkthrough recordings.

Features:
- Load a source video
- Add timed overlays (text, arrows, lines, boxes, lower-third bars)
- Save/load project JSON
- Render edited MP4 with FFmpeg
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import traceback
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import List, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except Exception:
    print("tkinter is required.")
    sys.exit(1)


APP_NAME = "CITL Video Post Editor"
APP_VERSION = "v0.2"

HERE = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    env_repo = os.environ.get("CITL_REPO", "").strip()
    if env_repo and Path(env_repo).is_dir():
        REPO = Path(env_repo)
    else:
        REPO = Path(sys.executable).resolve().parent.parent.parent
else:
    REPO = HERE.parent

DEFAULT_RECORDINGS_DIR = REPO / "recordings"

COLORS = {
    "bg": "#140a0a",
    "panel": "#1e0f0f",
    "card": "#221010",
    "border": "#6b2c2c",
    "text": "#f5eeee",
    "muted": "#c4a0a0",
    "accent": "#d84444",
    "btn": "#4a1a1a",
    "btn_hi": "#6e2525",
    "ok": "#84f6a0",
    "warn": "#ffd369",
    "notebk": "#180c0c",
}
FONT = "Segoe UI" if sys.platform == "win32" else "Ubuntu"

OVERLAY_TYPES = [
    "text",
    "arrow",
    "underline",
    "box",
    "square",
    "circle",
    "lower_third",
    "gradient_lower_third",
]

ANIMATION_CHOICES = [
    "fade",
    "steady",
    "blink",
    "pulse",
]

FONT_CHOICES = [
    "Helvetica",
    "Arial",
    "Avenir",
    "Avenir Next",
    "Neue Helvetica",
    "FF DIN",
    "DIN Next",
    "Frutiger",
    "Trade Gothic",
    "Proxima Nova",
    "Univers",
    "Futura",
    "Century Gothic",
    "Segoe UI",
    "Calibri",
    "Georgia",
    "Times New Roman",
]

STYLE_PRESETS = {
    "CITL Headline Box": {
        "kind": "text",
        "animation": "fade",
        "size": 44,
        "font": "Helvetica",
        "color": "white",
        "bg_color": "#102733@0.90",
        "w": 900,
        "h": 120,
        "x": 90,
        "y": 80,
    },
    "CITL Step Callout": {
        "kind": "text",
        "animation": "pulse",
        "size": 36,
        "font": "Avenir",
        "color": "white",
        "bg_color": "#1D5F86@0.78",
        "w": 780,
        "h": 96,
        "x": 110,
        "y": 110,
    },
    "CITL Lower Third": {
        "kind": "lower_third",
        "animation": "fade",
        "size": 38,
        "font": "Helvetica",
        "color": "white",
        "bg_color": "#0E2D41@0.82",
        "w": 1280,
        "h": 168,
        "x": 72,
        "y": 48,
    },
    "CITL News Bar": {
        "kind": "gradient_lower_third",
        "animation": "steady",
        "size": 34,
        "font": "Frutiger",
        "color": "white",
        "bg_color": "black@0.70",
        "w": 1280,
        "h": 150,
        "x": 72,
        "y": 24,
    },
}


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


def _safe_float(raw: str, default: float) -> float:
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _safe_int(raw: str, default: int) -> int:
    try:
        return int(float(str(raw).strip()))
    except Exception:
        return default


def _esc_drawtext_text(text: str) -> str:
    out = (text or "")
    out = out.replace("\\", "\\\\")
    out = out.replace(":", "\\:")
    out = out.replace("'", "\\'")
    out = out.replace("%", "\\%")
    out = out.replace("\n", "\\n")
    return out


@dataclass
class OverlayItem:
    kind: str = "text"
    animation: str = "fade"
    text: str = "Step title"
    start: float = 0.0
    end: float = 4.0
    fade_in: float = 0.25
    fade_out: float = 0.25
    x: int = 80
    y: int = 80
    w: int = 480
    h: int = 120
    size: int = 36
    color: str = "white"
    bg_color: str = "black@0.45"
    font: str = "Helvetica"
    pulse_strength: float = 0.08


OVERLAY_FIELD_NAMES = {f.name for f in fields(OverlayItem)}


class VideoPostEditor:
    def __init__(self, root: tk.Tk, initial_input: Optional[str] = None):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.configure(bg=COLORS["bg"])
        self.root.minsize(1080, 760)

        self.ffmpeg = _find_ffmpeg()
        self.items: List[OverlayItem] = []
        self._render_proc: Optional[subprocess.Popen] = None

        DEFAULT_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

        self.input_var = tk.StringVar(value=initial_input or "")
        self.output_var = tk.StringVar(value="")
        self.ffmpeg_var = tk.StringVar(value=self.ffmpeg or "NOT FOUND")
        self.status_var = tk.StringVar(value="Ready")

        self.kind_var = tk.StringVar(value="text")
        self.animation_var = tk.StringVar(value="fade")
        self.style_var = tk.StringVar(value="CITL Headline Box")
        self.text_var = tk.StringVar(value="Step title")
        self.start_var = tk.StringVar(value="0.0")
        self.end_var = tk.StringVar(value="4.0")
        self.fade_in_var = tk.StringVar(value="0.25")
        self.fade_out_var = tk.StringVar(value="0.25")
        self.x_var = tk.StringVar(value="80")
        self.y_var = tk.StringVar(value="80")
        self.w_var = tk.StringVar(value="480")
        self.h_var = tk.StringVar(value="120")
        self.size_var = tk.StringVar(value="36")
        self.color_var = tk.StringVar(value="white")
        self.bg_color_var = tk.StringVar(value="black@0.45")
        self.font_var = tk.StringVar(value="Helvetica")
        self.pulse_var = tk.DoubleVar(value=0.08)

        self._build_ui()
        self._bind_events()
        self._seed_defaults()
        self._refresh_output_name()

    def _build_ui(self):
        top = tk.Frame(self.root, bg=COLORS["panel"], padx=12, pady=8)
        top.pack(fill="x")
        tk.Label(top, text=APP_NAME, font=(FONT, 16, "bold"), bg=COLORS["panel"], fg=COLORS["text"]).pack(side="left")
        tk.Label(top, text=APP_VERSION, font=(FONT, 10), bg=COLORS["panel"], fg=COLORS["accent"]).pack(side="left", padx=8)
        tk.Label(top, textvariable=self.ffmpeg_var, font=(FONT, 8), bg=COLORS["panel"], fg=COLORS["muted"]).pack(side="right")

        io = tk.LabelFrame(self.root, text="Video", font=(FONT, 9, "bold"), bg=COLORS["card"], fg=COLORS["text"], bd=1, relief="solid")
        io.pack(fill="x", padx=12, pady=(10, 8))

        row1 = tk.Frame(io, bg=COLORS["card"])
        row1.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(row1, text="Input", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8), width=8, anchor="w").pack(side="left")
        ttk.Entry(row1, textvariable=self.input_var).pack(side="left", fill="x", expand=True)
        tk.Button(row1, text="...", width=4, command=self._browse_input, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left", padx=4)
        tk.Button(row1, text="Open", command=self._open_input_folder, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left")

        row2 = tk.Frame(io, bg=COLORS["card"])
        row2.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(row2, text="Output", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8), width=8, anchor="w").pack(side="left")
        ttk.Entry(row2, textvariable=self.output_var).pack(side="left", fill="x", expand=True)
        tk.Button(row2, text="...", width=4, command=self._browse_output, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left", padx=4)
        tk.Button(row2, text="Open", command=self._open_output_folder, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left")

        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=4)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = tk.LabelFrame(body, text="Overlay Timeline", font=(FONT, 9, "bold"), bg=COLORS["card"], fg=COLORS["text"], bd=1, relief="solid")
        left.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        self.listbox = tk.Listbox(left, width=44, height=20, bg=COLORS["notebk"], fg=COLORS["text"], selectbackground=COLORS["btn_hi"], relief="flat")
        self.listbox.pack(fill="both", expand=True, padx=8, pady=8)

        lb = tk.Frame(left, bg=COLORS["card"])
        lb.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(lb, text="Add", command=self._add_item, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left")
        tk.Button(lb, text="Duplicate", command=self._duplicate_item, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left", padx=4)
        tk.Button(lb, text="Remove", command=self._remove_item, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left", padx=4)
        tk.Button(lb, text="Up", command=lambda: self._move_item(-1), bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left", padx=4)
        tk.Button(lb, text="Down", command=lambda: self._move_item(1), bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left")

        right = tk.LabelFrame(body, text="Overlay Properties", font=(FONT, 9, "bold"), bg=COLORS["card"], fg=COLORS["text"], bd=1, relief="solid")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)

        row = 0
        self._label(right, "Type").grid(row=row, column=0, sticky="w", padx=8, pady=(8, 2))
        ttk.Combobox(right, textvariable=self.kind_var, values=OVERLAY_TYPES, state="readonly").grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=(8, 2)); row += 1
        self._label(right, "Animation").grid(row=row, column=0, sticky="w", padx=8, pady=2)
        ttk.Combobox(right, textvariable=self.animation_var, values=ANIMATION_CHOICES, state="readonly").grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2); row += 1
        preset_row = tk.Frame(right, bg=COLORS["card"])
        preset_row.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 2))
        preset_row.columnconfigure(1, weight=1)
        tk.Label(preset_row, text="Style", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=0, sticky="w")
        ttk.Combobox(preset_row, textvariable=self.style_var, values=sorted(STYLE_PRESETS.keys()), state="readonly").grid(row=0, column=1, sticky="ew", padx=(6, 8))
        tk.Button(preset_row, text="Apply Preset", command=self._apply_style_preset, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").grid(row=0, column=2, sticky="e")
        row += 1
        self._label(right, "Text").grid(row=row, column=0, sticky="w", padx=8, pady=2)
        ttk.Entry(right, textvariable=self.text_var).grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2); row += 1

        time_row = tk.Frame(right, bg=COLORS["card"])
        time_row.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(6, 2))
        for i in range(8):
            time_row.columnconfigure(i, weight=1 if i % 2 == 1 else 0)
        tk.Label(time_row, text="Start (s)", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=0, sticky="w")
        ttk.Entry(time_row, textvariable=self.start_var, width=8).grid(row=0, column=1, sticky="ew", padx=(4, 10))
        tk.Label(time_row, text="End (s)", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=2, sticky="w")
        ttk.Entry(time_row, textvariable=self.end_var, width=8).grid(row=0, column=3, sticky="ew", padx=(4, 10))
        tk.Label(time_row, text="Fade In", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=4, sticky="w")
        ttk.Entry(time_row, textvariable=self.fade_in_var, width=8).grid(row=0, column=5, sticky="ew", padx=(4, 10))
        tk.Label(time_row, text="Fade Out", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=6, sticky="w")
        ttk.Entry(time_row, textvariable=self.fade_out_var, width=8).grid(row=0, column=7, sticky="ew", padx=(4, 0)); row += 1

        tk.Scale(right, from_=0.0, to=5.0, resolution=0.05, orient="horizontal", variable=self.fade_in_var, label="Fade In Slider (seconds)",
                 bg=COLORS["card"], fg=COLORS["muted"], troughcolor=COLORS["notebk"], highlightthickness=0, font=(FONT, 8)).grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 2)); row += 1
        tk.Scale(right, from_=0.0, to=5.0, resolution=0.05, orient="horizontal", variable=self.fade_out_var, label="Fade Out Slider (seconds)",
                 bg=COLORS["card"], fg=COLORS["muted"], troughcolor=COLORS["notebk"], highlightthickness=0, font=(FONT, 8)).grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 6)); row += 1

        geo = tk.Frame(right, bg=COLORS["card"])
        geo.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 2))
        for i in range(8):
            geo.columnconfigure(i, weight=1 if i % 2 == 1 else 0)
        tk.Label(geo, text="X", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=0, sticky="w")
        ttk.Entry(geo, textvariable=self.x_var, width=8).grid(row=0, column=1, sticky="ew", padx=(4, 10))
        tk.Label(geo, text="Y", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=2, sticky="w")
        ttk.Entry(geo, textvariable=self.y_var, width=8).grid(row=0, column=3, sticky="ew", padx=(4, 10))
        tk.Label(geo, text="W", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=4, sticky="w")
        ttk.Entry(geo, textvariable=self.w_var, width=8).grid(row=0, column=5, sticky="ew", padx=(4, 10))
        tk.Label(geo, text="H", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=6, sticky="w")
        ttk.Entry(geo, textvariable=self.h_var, width=8).grid(row=0, column=7, sticky="ew", padx=(4, 0)); row += 1

        style_row = tk.Frame(right, bg=COLORS["card"])
        style_row.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 2))
        style_row.columnconfigure(5, weight=1)
        tk.Label(style_row, text="Size", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=0, sticky="w")
        ttk.Entry(style_row, textvariable=self.size_var, width=8).grid(row=0, column=1, sticky="w", padx=(4, 10))
        tk.Label(style_row, text="Color", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=2, sticky="w")
        ttk.Entry(style_row, textvariable=self.color_var, width=14).grid(row=0, column=3, sticky="w", padx=(4, 10))
        tk.Label(style_row, text="Bg", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=4, sticky="w")
        ttk.Entry(style_row, textvariable=self.bg_color_var, width=14).grid(row=0, column=5, sticky="ew", padx=(4, 0)); row += 1

        self._label(right, "Font").grid(row=row, column=0, sticky="w", padx=8, pady=2)
        ttk.Combobox(right, textvariable=self.font_var, values=FONT_CHOICES, state="readonly").grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2); row += 1
        pulse_row = tk.Frame(right, bg=COLORS["card"])
        pulse_row.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 2))
        pulse_row.columnconfigure(1, weight=1)
        tk.Label(pulse_row, text="Pulse Strength", bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8)).grid(row=0, column=0, sticky="w")
        ttk.Entry(pulse_row, textvariable=self.pulse_var, width=10).grid(row=0, column=1, sticky="w", padx=(6, 8))
        tk.Scale(
            pulse_row, from_=0.00, to=0.40, resolution=0.01, orient="horizontal",
            variable=self.pulse_var, showvalue=False, length=180,
            bg=COLORS["card"], fg=COLORS["muted"], troughcolor=COLORS["notebk"],
            highlightthickness=0
        ).grid(row=0, column=2, sticky="e")
        row += 1

        buttons = tk.Frame(right, bg=COLORS["card"])
        buttons.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 8))
        tk.Button(buttons, text="Save Project", command=self._save_project, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left")
        tk.Button(buttons, text="Load Project", command=self._load_project, bg=COLORS["btn"], fg=COLORS["text"], relief="flat").pack(side="left", padx=4)
        tk.Button(buttons, text="Render MP4", command=self._render, bg=COLORS["btn_hi"], fg=COLORS["text"], relief="flat").pack(side="right")

        log_box = tk.LabelFrame(self.root, text="Render Log", font=(FONT, 9, "bold"), bg=COLORS["card"], fg=COLORS["text"], bd=1, relief="solid")
        log_box.pack(fill="both", expand=False, padx=12, pady=(0, 8))
        self.log = scrolledtext.ScrolledText(log_box, height=11, bg=COLORS["notebk"], fg="#90c090", insertbackground=COLORS["text"], relief="flat", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

        status = tk.Frame(self.root, bg=COLORS["panel"], padx=10, pady=6)
        status.pack(fill="x")
        tk.Label(status, textvariable=self.status_var, bg=COLORS["panel"], fg=COLORS["accent"], font=(FONT, 9, "bold")).pack(side="left")

    def _bind_events(self):
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.input_var.trace_add("write", lambda *_: self._refresh_output_name())

    def _label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=COLORS["card"], fg=COLORS["muted"], font=(FONT, 8), anchor="w")

    def _seed_defaults(self):
        if not self.input_var.get().strip():
            self.input_var.set(str(DEFAULT_RECORDINGS_DIR / ""))
        self._add_item()

    def _log(self, text: str):
        self.log.insert("end", text)
        self.log.see("end")

    def _browse_input(self):
        f = filedialog.askopenfilename(
            title="Select video",
            initialdir=str(DEFAULT_RECORDINGS_DIR),
            filetypes=[("Video files", "*.mp4;*.mkv;*.mov;*.avi;*.webm"), ("All files", "*.*")],
        )
        if f:
            self.input_var.set(f)

    def _browse_output(self):
        f = filedialog.asksaveasfilename(
            title="Save edited video as",
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4")],
            initialdir=str(DEFAULT_RECORDINGS_DIR),
            initialfile=Path(self.output_var.get().strip() or "citl_edited.mp4").name,
        )
        if f:
            self.output_var.set(f)

    def _open_input_folder(self):
        p = Path(self.input_var.get().strip())
        if p.exists():
            self._open_path(p.parent if p.is_file() else p)

    def _open_output_folder(self):
        p = Path(self.output_var.get().strip())
        if p.exists():
            self._open_path(p.parent if p.is_file() else p)
        elif p.parent.exists():
            self._open_path(p.parent)

    def _open_path(self, path: Path):
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    def _refresh_output_name(self):
        inp = Path(self.input_var.get().strip())
        if inp.suffix.lower() in (".mp4", ".mkv", ".mov", ".avi", ".webm"):
            self.output_var.set(str(inp.with_name(inp.stem + "_edited.mp4")))

    def _selected_index(self) -> int:
        sel = self.listbox.curselection()
        return int(sel[0]) if sel else -1

    def _add_item(self):
        self._store_current_item()
        self.items.append(OverlayItem())
        self._refresh_list()
        idx = len(self.items) - 1
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self._load_item(idx)

    def _duplicate_item(self):
        idx = self._selected_index()
        if idx < 0 or idx >= len(self.items):
            return
        self._store_current_item()
        clone = OverlayItem(**asdict(self.items[idx]))
        clone.start = max(0.0, clone.start + 0.25)
        clone.end = max(clone.start + 0.10, clone.end + 0.25)
        self.items.insert(idx + 1, clone)
        self._refresh_list()
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx + 1)
        self._load_item(idx + 1)

    def _remove_item(self):
        idx = self._selected_index()
        if idx < 0 or idx >= len(self.items):
            return
        self.items.pop(idx)
        self._refresh_list()
        if self.items:
            new_idx = min(idx, len(self.items) - 1)
            self.listbox.selection_set(new_idx)
            self._load_item(new_idx)

    def _move_item(self, delta: int):
        idx = self._selected_index()
        if idx < 0:
            return
        j = idx + delta
        if j < 0 or j >= len(self.items):
            return
        self._store_current_item()
        self.items[idx], self.items[j] = self.items[j], self.items[idx]
        self._refresh_list()
        self.listbox.selection_set(j)
        self._load_item(j)

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        for i, item in enumerate(self.items, start=1):
            label = (
                f"{i:02d}. [{item.kind}/{item.animation}] "
                f"{item.start:.2f}s-{item.end:.2f}s : {item.text or '(no text)'}"
            )
            self.listbox.insert("end", label)

    def _on_select(self, _event=None):
        idx = self._selected_index()
        if idx >= 0:
            self._load_item(idx)

    def _load_item(self, idx: int):
        if idx < 0 or idx >= len(self.items):
            return
        item = self.items[idx]
        self.kind_var.set(item.kind)
        self.animation_var.set(item.animation or "fade")
        self.text_var.set(item.text)
        self.start_var.set(str(item.start))
        self.end_var.set(str(item.end))
        self.fade_in_var.set(str(item.fade_in))
        self.fade_out_var.set(str(item.fade_out))
        self.x_var.set(str(item.x))
        self.y_var.set(str(item.y))
        self.w_var.set(str(item.w))
        self.h_var.set(str(item.h))
        self.size_var.set(str(item.size))
        self.color_var.set(item.color)
        self.bg_color_var.set(item.bg_color)
        self.font_var.set(item.font)
        self.pulse_var.set(float(item.pulse_strength))

    def _store_current_item(self):
        idx = self._selected_index()
        if idx < 0 or idx >= len(self.items):
            return
        item = self.items[idx]
        item.kind = self.kind_var.get().strip() or "text"
        item.animation = self.animation_var.get().strip() or "fade"
        item.text = self.text_var.get().strip()
        item.start = _safe_float(self.start_var.get(), item.start)
        item.end = max(item.start + 0.01, _safe_float(self.end_var.get(), item.end))
        item.fade_in = max(0.0, _safe_float(self.fade_in_var.get(), item.fade_in))
        item.fade_out = max(0.0, _safe_float(self.fade_out_var.get(), item.fade_out))
        item.x = _safe_int(self.x_var.get(), item.x)
        item.y = _safe_int(self.y_var.get(), item.y)
        item.w = max(1, _safe_int(self.w_var.get(), item.w))
        item.h = max(1, _safe_int(self.h_var.get(), item.h))
        item.size = max(8, _safe_int(self.size_var.get(), item.size))
        item.color = self.color_var.get().strip() or "white"
        item.bg_color = self.bg_color_var.get().strip() or "black@0.45"
        item.font = self.font_var.get().strip() or "Helvetica"
        item.pulse_strength = min(0.9, max(0.0, _safe_float(self.pulse_var.get(), item.pulse_strength)))
        self._refresh_list()
        self.listbox.selection_set(idx)

    def _apply_style_preset(self):
        idx = self._selected_index()
        if idx < 0 or idx >= len(self.items):
            return
        preset_name = self.style_var.get().strip()
        preset = STYLE_PRESETS.get(preset_name)
        if not preset:
            return
        item = self.items[idx]
        for key, val in preset.items():
            if hasattr(item, key):
                setattr(item, key, val)
        self._load_item(idx)
        self._refresh_list()

    def _alpha_expr(self, item: OverlayItem) -> str:
        s = max(0.0, item.start)
        e = max(s + 0.01, item.end)
        fi = max(0.0, min(item.fade_in, e - s))
        fo = max(0.0, min(item.fade_out, e - s))
        if fi <= 0 and fo <= 0:
            return "1"
        if fi <= 0:
            return f"if(lt(t,{e - fo:.3f}),1,max(0,({e:.3f}-t)/{fo:.3f}))"
        if fo <= 0:
            return f"if(lt(t,{s + fi:.3f}),max(0,(t-{s:.3f})/{fi:.3f}),1)"
        return (
            f"if(lt(t,{s + fi:.3f}),max(0,(t-{s:.3f})/{fi:.3f}),"
            f"if(gt(t,{e - fo:.3f}),max(0,({e:.3f}-t)/{fo:.3f}),1))"
        )

    def _animated_alpha_expr(self, item: OverlayItem) -> str:
        base = self._alpha_expr(item)
        mode = (item.animation or "fade").strip().lower()
        if mode == "steady":
            return "1"
        if mode == "blink":
            return f"({base})*(0.25+0.75*abs(sin(18*t)))"
        return base

    def _fontsize_expr(self, item: OverlayItem) -> str:
        size = max(8, int(item.size))
        mode = (item.animation or "fade").strip().lower()
        if mode == "pulse":
            amp = min(0.90, max(0.01, float(item.pulse_strength or 0.08)))
            return f"({size})*(1+({amp:.3f})*sin(9*t))"
        return str(size)

    def _build_filters(self) -> str:
        self._store_current_item()
        filters: List[str] = []
        for item in self.items:
            enable = f"between(t,{item.start:.3f},{item.end:.3f})"
            alpha = self._animated_alpha_expr(item)
            size_expr = self._fontsize_expr(item)
            text = _esc_drawtext_text(item.text or "")
            font = (item.font or "Helvetica").replace("'", "")
            if item.kind in ("text", "arrow"):
                if item.kind == "arrow" and not text:
                    text = "->"
                filters.append(
                    "drawtext="
                    f"font='{font}':text='{text}':x={item.x}:y={item.y}:fontsize={size_expr}:"
                    f"fontcolor={item.color}:alpha='{alpha}':box=1:boxcolor={item.bg_color}:"
                    f"enable='{enable}'"
                )
            elif item.kind == "underline":
                filters.append(
                    f"drawbox=x={item.x}:y={item.y}:w={item.w}:h=4:color={item.color}:t=fill:enable='{enable}'"
                )
            elif item.kind == "box":
                filters.append(
                    f"drawbox=x={item.x}:y={item.y}:w={item.w}:h={item.h}:color={item.bg_color}:t=fill:enable='{enable}'"
                )
            elif item.kind == "square":
                side = min(item.w, item.h)
                filters.append(
                    f"drawbox=x={item.x}:y={item.y}:w={side}:h={side}:color={item.bg_color}:t=fill:enable='{enable}'"
                )
            elif item.kind == "circle":
                filters.append(
                    "drawtext="
                    f"font='{font}':text='O':x={item.x}:y={item.y}:fontsize={size_expr}:"
                    f"fontcolor={item.color}:alpha='{alpha}':enable='{enable}'"
                )
            elif item.kind == "lower_third":
                y_expr = f"ih-{item.h}-{max(0, item.y)}"
                filters.append(
                    f"drawbox=x=0:y={y_expr}:w=iw:h={item.h}:color={item.bg_color}:t=fill:enable='{enable}'"
                )
                filters.append(
                    "drawtext="
                    f"font='{font}':text='{text}':x={item.x}:y={y_expr}+{int(item.h * 0.32)}:fontsize={size_expr}:"
                    f"fontcolor={item.color}:alpha='{alpha}':enable='{enable}'"
                )
            elif item.kind == "gradient_lower_third":
                y_expr = f"ih-{item.h}-{max(0, item.y)}"
                half = max(1, item.h // 2)
                filters.append(
                    f"drawbox=x=0:y={y_expr}:w=iw:h={half}:color=black@0.65:t=fill:enable='{enable}'"
                )
                filters.append(
                    f"drawbox=x=0:y={y_expr}+{half}:w=iw:h={item.h - half}:color=black@0.25:t=fill:enable='{enable}'"
                )
                filters.append(
                    "drawtext="
                    f"font='{font}':text='{text}':x={item.x}:y={y_expr}+{int(item.h * 0.32)}:fontsize={size_expr}:"
                    f"fontcolor={item.color}:alpha='{alpha}':enable='{enable}'"
                )
        return ",".join(filters) if filters else "null"

    def _save_project(self):
        self._store_current_item()
        f = filedialog.asksaveasfilename(
            title="Save project",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=str(DEFAULT_RECORDINGS_DIR),
            initialfile="citl_video_project.json",
        )
        if not f:
            return
        payload = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "input": self.input_var.get().strip(),
            "output": self.output_var.get().strip(),
            "overlays": [asdict(i) for i in self.items],
        }
        Path(f).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.status_var.set(f"Project saved: {Path(f).name}")

    def _load_project(self):
        f = filedialog.askopenfilename(
            title="Load project",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialdir=str(DEFAULT_RECORDINGS_DIR),
        )
        if not f:
            return
        payload = json.loads(Path(f).read_text(encoding="utf-8"))
        self.input_var.set(str(payload.get("input") or ""))
        self.output_var.set(str(payload.get("output") or ""))
        overlays = payload.get("overlays") or []
        parsed: List[OverlayItem] = []
        for obj in overlays:
            if not isinstance(obj, dict):
                continue
            safe_obj = {k: v for k, v in obj.items() if k in OVERLAY_FIELD_NAMES}
            parsed.append(OverlayItem(**safe_obj))
        self.items = parsed
        if not self.items:
            self.items = [OverlayItem()]
        self._refresh_list()
        self.listbox.selection_set(0)
        self._load_item(0)
        self.status_var.set(f"Project loaded: {Path(f).name}")

    def _render(self):
        if self._render_proc:
            messagebox.showinfo(APP_NAME, "A render is already running.")
            return
        if not self.ffmpeg:
            messagebox.showerror(APP_NAME, "FFmpeg was not found.")
            return
        inp = Path(self.input_var.get().strip())
        out = Path(self.output_var.get().strip())
        if not inp.exists() or not inp.is_file():
            messagebox.showwarning(APP_NAME, "Select a valid input video.")
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        vf = self._build_filters()

        cmd = [
            self.ffmpeg,
            "-hide_banner",
            "-y",
            "-i",
            str(inp),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "21",
            "-c:a",
            "copy",
            str(out),
        ]
        self._log("[FFMPEG] " + " ".join(cmd) + "\n")
        self.status_var.set("Rendering...")

        def _run():
            rc = -1
            try:
                self._render_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=0x08000000 if sys.platform == "win32" else 0,
                )
                assert self._render_proc.stdout is not None
                for line in self._render_proc.stdout:
                    self.root.after(0, lambda ln=line: self._log(ln))
                rc = self._render_proc.wait()
            except Exception as exc:
                self.root.after(0, lambda: self._log(f"[ERROR] {exc}\n"))
                rc = -1
            finally:
                self._render_proc = None
                if rc == 0:
                    self.root.after(0, lambda: self.status_var.set(f"Done: {out.name}"))
                else:
                    self.root.after(0, lambda: self.status_var.set(f"Render failed (code {rc})"))

        threading.Thread(target=_run, daemon=True).start()


def main(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--input", dest="input_video", default="", help="Optional input video path")
    args = parser.parse_args(argv)

    root = tk.Tk()
    try:
        VideoPostEditor(root, initial_input=args.input_video or None)
        root.mainloop()
    except Exception:
        crash = HERE / "citl_video_post_editor_crash.log"
        crash.write_text(f"[{APP_NAME}]\n{traceback.format_exc()}\n", encoding="utf-8")
        try:
            messagebox.showerror(APP_NAME, f"Startup error.\nSee:\n{crash}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
