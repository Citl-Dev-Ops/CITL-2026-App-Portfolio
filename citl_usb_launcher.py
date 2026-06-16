#!/usr/bin/env python3
"""
CITL USB Launcher
=================
Single-window hub for all CITL apps on this USB drive.
Double-click any tile to launch. EXE preferred, Python fallback.
Green = EXE ready | Orange = Python script only | Gray = not found
"""
from __future__ import annotations
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    sys.exit("tkinter is required")

# ---------------------------------------------------------------------------
# Root detection (works frozen as EXE or as plain .py)
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _SCRIPT = Path(sys.executable).resolve()
else:
    _SCRIPT = Path(__file__).resolve()

# Walk up until we find a CITL-like root (has citl_fixer.py or CITL-REIMAGER)
ROOT = _SCRIPT.parent
for _ in range(6):
    if (ROOT / "citl_fixer.py").exists() or (ROOT / "CITL-REIMAGER").exists():
        break
    ROOT = ROOT.parent

DIST = ROOT / "dist"
FA = ROOT / "factbook-assistant"

# ---------------------------------------------------------------------------
# App catalogue
# ---------------------------------------------------------------------------
# Each entry: (display_name, dist_subdir, exe_name, script_path, launcher_cmd)
APPS = [
    (
        "CITL Re-Imager",
        "CITL Re-Imager",
        "CITL Re-Imager.exe",
        ROOT / "CITL-REIMAGER" / "citl_reimager.py",
        ROOT / "LAUNCH_CITL_REIMAGER_WINDOWS.cmd",
        "#0d2030", "#58a6ff",
        "Create & restore bootable disk images",
    ),
    (
        "CITL FLEX Troubleshooter",
        "CITL FLEX Troubleshooter",
        "CITL FLEX Troubleshooter.exe",
        ROOT / "citl_flex_troubleshooter" / "flex_assistant_gui.py",
        ROOT / "RUN_CITL_FLEX_WINDOWS.cmd",
        "#0d2210", "#7eefc0",
        "FLEX diagnostic & AI knowledge assistant",
    ),
    (
        "CITL Fixer",
        "CITL Fixer",
        "CITL Fixer.exe",
        ROOT / "citl_fixer.py",
        ROOT / "RUN_CITL_FIXER_WINDOWS.cmd",
        "#2a1a00", "#f0883e",
        "Diagnose & auto-repair CITL installations",
    ),
    (
        "CITL Bundle Automation",
        "CITL Bundle Automation",
        "CITL Bundle Automation.exe",
        ROOT / "CITL-REIMAGER" / "citl_bundle_automation.py",
        ROOT / "CITL_BUNDLE_AUTOMATION_WINDOWS.cmd",
        "#1a0d30", "#c084fc",
        "Build & package CITL USB bundles",
    ),
    (
        "CITL App Updater",
        "CITL App Updater",
        "CITL App Updater.exe",
        ROOT / "CITL-REIMAGER" / "citl_app_updater.py",
        None,
        "#1a2a30", "#56d1e0",
        "Update apps between USB drives or to machine",
    ),
    (
        "CITL LLMOps Suite",
        "CITL LLMOps Presentation Suite",
        "CITL LLMOps Presentation Suite.exe",
        FA / "citl_llmops_suite.py",
        ROOT / "RUN_LLMOPS_WINDOWS.cmd",
        "#1a1a0a", "#d4a017",
        "LLMOps presentation & inference tools",
    ),
    (
        "CITL Factbook Assistant",
        "CITL Factbook Assistant",
        "CITL Factbook Assistant.exe",
        FA / "factbook_assistant_gui.py",
        ROOT / "RUN_FACTBOOK_WINDOWS.cmd",
        "#0a1a2a", "#79c0ff",
        "RAG-powered institutional knowledge base",
    ),
    (
        "CITL Sync Hub",
        "CITL Sync Hub",
        "CITL Sync Hub.exe",
        FA / "citl_sync_hub.py",
        ROOT / "RUN_SYNC_HUB_WINDOWS.cmd",
        "#1a0a1a", "#d2a8ff",
        "Sync apps between machines & USB drives",
    ),
    (
        "CITL AV IT Operations",
        "CITL AV IT Operations",
        "CITL AV IT Operations.exe",
        FA / "citl_av_it_ops.py",
        ROOT / "RUN_AV_IT_OPS_WINDOWS.cmd",
        "#1a1500", "#e3b341",
        "AV & IT operations management",
    ),
    (
        "CITL Document Composer",
        "CITL Document Composer",
        "CITL Document Composer.exe",
        FA / "citl_doc_composer.py",
        ROOT / "RUN_DOC_COMPOSER_WINDOWS.cmd",
        "#0a1a1a", "#56d1e0",
        "Professional document creation & templating",
    ),
    (
        "CITL Field Apps",
        "CITL Field Apps",
        "CITL Field Apps.exe",
        FA / "citl_field_apps.py",
        ROOT / "RUN_FIELD_APPS_WINDOWS.cmd",
        "#001a10", "#56e09a",
        "Field operations & mobile tools",
    ),
    (
        "CITL Workstation Apps",
        "CITL Workstation Apps",
        "CITL Workstation Apps.exe",
        FA / "citl_workstation_apps.py",
        ROOT / "RUN_WORKSTATION_APPS_WINDOWS.cmd",
        "#001a1a", "#56d1e0",
        "Desktop workstation app suite",
    ),
]

# ---------------------------------------------------------------------------
# Status detection
# ---------------------------------------------------------------------------
def _find_exe(dist_subdir: str, exe_name: str) -> Optional[Path]:
    for candidate in (
        DIST / dist_subdir / exe_name,
        DIST / exe_name,
        ROOT / dist_subdir / exe_name,
    ):
        if candidate.exists():
            return candidate
    return None


def _find_python() -> Optional[str]:
    for cmd in ("py", "python", "python3"):
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True, timeout=3)
            if r.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return None


# ---------------------------------------------------------------------------
# Launcher logic
# ---------------------------------------------------------------------------
def _launch(name: str, dist_subdir: str, exe_name: str,
            script: Path, launcher_cmd: Optional[Path]) -> None:
    exe = _find_exe(dist_subdir, exe_name)
    if exe:
        subprocess.Popen([str(exe)], close_fds=True)
        return

    if launcher_cmd and launcher_cmd.exists():
        subprocess.Popen(["cmd", "/c", str(launcher_cmd)], close_fds=True)
        return

    if script.exists():
        py = _find_python()
        if py:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(FA) + os.pathsep + str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            subprocess.Popen([py, str(script)], env=env, close_fds=True)
            return

    messagebox.showerror(
        "Not Found",
        f"{name} is not installed on this USB drive.\n\n"
        f"Expected EXE:\n  {DIST / dist_subdir / exe_name}\n\n"
        f"Run BUILD_ALL_CITL_EXES_WINDOWS.cmd to build it.",
    )


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
BG       = "#0d1117"
PANEL    = "#161b22"
BORDER   = "#30363d"
FG       = "#e6edf3"
FG_DIM   = "#7d8590"
FONT_HDR = ("Segoe UI", 10, "bold")
FONT_SUB = ("Segoe UI", 9)
FONT_BIG = ("Segoe UI", 16, "bold")


class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CITL App Launcher")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.geometry("900x640")
        self.minsize(700, 480)
        self._build()
        self.after(100, self._check_status)

    def _build(self) -> None:
        # Header
        hdr = tk.Frame(self, bg="#0d1f3c", pady=12)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="CITL App Launcher",
            bg="#0d1f3c", fg="#58a6ff",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left", padx=20)
        tk.Label(
            hdr, text=f"USB Root: {ROOT}",
            bg="#0d1f3c", fg=FG_DIM,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=10)

        # Status legend
        leg = tk.Frame(self, bg=BG, pady=4)
        leg.pack(fill="x", padx=14)
        for color, label in (("#2ea043", "EXE ready"), ("#f0883e", "Python only"), ("#484f58", "Not found")):
            dot = tk.Label(leg, text="  ", bg=color, width=2)
            dot.pack(side="left", padx=(0, 2))
            tk.Label(leg, text=label + "   ", bg=BG, fg=FG_DIM, font=FONT_SUB).pack(side="left")

        # Scrollable tile grid
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=10, pady=6)

        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._grid = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=self._grid, anchor="nw")
        self._grid.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(
            int(-1 * (e.delta / 120)), "units"))

        self._tiles: list[tk.Frame] = []
        self._status_dots: list[tk.Label] = []
        self._status_labels: list[tk.Label] = []

        COLS = 3
        for idx, entry in enumerate(APPS):
            name, dist_sub, exe_name, script, launcher_cmd, tile_bg, accent, desc = entry
            row, col = divmod(idx, COLS)
            tile = tk.Frame(
                self._grid, bg=tile_bg,
                relief="flat", bd=0,
                padx=12, pady=10,
                highlightbackground=BORDER, highlightthickness=1,
            )
            tile.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
            self._grid.columnconfigure(col, weight=1)

            top = tk.Frame(tile, bg=tile_bg)
            top.pack(fill="x")

            dot = tk.Label(top, text=" ", bg="#484f58", width=2, relief="flat")
            dot.pack(side="right", padx=(4, 0))
            self._status_dots.append(dot)

            tk.Label(
                top, text=name,
                bg=tile_bg, fg=accent,
                font=FONT_HDR, anchor="w",
            ).pack(side="left", fill="x", expand=True)

            tk.Label(
                tile, text=desc,
                bg=tile_bg, fg=FG_DIM,
                font=FONT_SUB, anchor="w", wraplength=240,
            ).pack(fill="x", pady=(2, 6))

            status_lbl = tk.Label(tile, text="Checking...", bg=tile_bg, fg=FG_DIM, font=FONT_SUB)
            status_lbl.pack(anchor="w")
            self._status_labels.append(status_lbl)

            btn = tk.Button(
                tile,
                text="Launch",
                bg=accent, fg=BG,
                activebackground=FG, activeforeground=BG,
                font=FONT_HDR,
                relief="flat", padx=14, pady=5,
                cursor="hand2",
                command=lambda n=name, d=dist_sub, e=exe_name, s=script, l=launcher_cmd:
                    threading.Thread(target=_launch, args=(n, d, e, s, l), daemon=True).start(),
            )
            btn.pack(anchor="e", pady=(4, 0))
            self._tiles.append(tile)

        # Bottom bar
        bar = tk.Frame(self, bg=PANEL, pady=6)
        bar.pack(fill="x")
        tk.Label(
            bar, text="Build EXEs: run  BUILD_ALL_CITL_EXES_WINDOWS.cmd  on your dev machine,  then sync to USB",
            bg=PANEL, fg=FG_DIM, font=FONT_SUB,
        ).pack(side="left", padx=14)
        tk.Button(
            bar, text="Refresh Status", command=self._check_status,
            bg="#1c2d4a", fg="#58a6ff",
            relief="flat", padx=10, pady=4, cursor="hand2",
        ).pack(side="right", padx=10)

    def _check_status(self) -> None:
        for idx, entry in enumerate(APPS):
            _, dist_sub, exe_name, script, _, _, _, _ = entry
            exe = _find_exe(dist_sub, exe_name)
            dot = self._status_dots[idx]
            lbl = self._status_labels[idx]
            if exe:
                dot.configure(bg="#2ea043")
                lbl.configure(text=f"EXE: {exe.name}", fg="#7eefc0")
            elif script.exists():
                dot.configure(bg="#f0883e")
                lbl.configure(text="Python script available (no EXE)", fg="#f0883e")
            else:
                dot.configure(bg="#484f58")
                lbl.configure(text="Not installed on this USB", fg="#484f58")


def main() -> None:
    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
