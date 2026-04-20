#!/usr/bin/env python3
"""
citl_repair_all.py  —  CITL Universal Find, Diagnose & Repair
══════════════════════════════════════════════════════════════════
Double-click entry point for the USB repair station.

What it does
────────────
1. QUICK SCAN  — checks ~30 high-probability locations in <2 seconds.
2. DEEP SCAN   — walks every connected drive if quick scan finds nothing
                 (or user clicks "Search All Drives").
3. SELECTION   — if multiple instances found, shows a picker so the user
                 chooses which copy to repair.
4. DIAGNOSTIC  — runs all 18 pipeline stages on the chosen copy.
5. REPAIR      — per-stage Fix buttons + "Fix All Problems" global button.
6. PATCH COPY  — copies the latest diagnostic/heal scripts from THIS USB
                 into the target folder so it is self-healing going forward.

Finds any folder whose name contains "factbook" (case-insensitive) on:
  Windows  — C:\, D:\, E:\, F:\ … plus common install paths
  Ubuntu   — /home, /media, /mnt, /opt, /srv plus $HOME

Usage
─────
    python citl_repair_all.py             # GUI (auto)
    python citl_repair_all.py --cli       # terminal only
    python citl_repair_all.py --path /X   # skip search, repair this path
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# ── Own directory ─────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent          # factbook-assistant/ dir
REPO_ROOT = HERE.parent                          # USB / repo root
USB_ROOT  = REPO_ROOT                           # same thing for USB deploys

# Ensure this dir is importable
for _p in (str(HERE), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Scripts that get patched into a found Factbook copy ──────────────────────
PATCH_SCRIPTS = [
    HERE / "citl_factbook_diagnostic.py",
    HERE / "citl_heal.py",
    HERE / "citl_heal_panel.py",
    HERE / "citl_rag_patch.py",
    REPO_ROOT / "citl_bootstrap.py",
]

# ── CITL app markers: (display_name, marker_file_relative_to_root) ───────────
APP_MARKERS = [
    ("Factbook Assistant",      "factbook-assistant/factbook_assistant_gui.py"),
    ("Factbook Assistant",      "factbook_assistant_gui.py"),
    ("FLEX Troubleshooter",     "citl_flex_troubleshooter/flex_troubleshooter_gui.py"),
    ("FLEX Troubleshooter",     "flex_troubleshooter_gui.py"),
    ("App Sync",                "factbook-assistant/citl_app_sync.py"),
    ("App Sync",                "citl_app_sync.py"),
]

# ══════════════════════════════════════════════════════════════════════════════
# FINDER
# ══════════════════════════════════════════════════════════════════════════════

def _all_drives() -> List[Path]:
    """Return all mounted/available root paths."""
    drives: List[Path] = []
    if platform.system() == "Windows":
        import string
        for letter in string.ascii_uppercase:
            p = Path(f"{letter}:/")
            if p.exists():
                drives.append(p)
    else:
        drives = [Path("/")]
        for mp in ["/media", "/mnt", "/opt", "/srv"]:
            p = Path(mp)
            if p.is_dir():
                drives.append(p)
        home = Path.home()
        if home.is_dir():
            drives.append(home)
    return drives


def _quick_candidates() -> List[Path]:
    """~30 high-probability locations, checked in <1s."""
    cands: List[Path] = []
    drives = _all_drives()

    for root in drives:
        # Root-level CITL folders
        for name in ["CITL", "citl", "1-CITL-SYNC", "3-CITL-WORKSTATION-APPS"]:
            p = root / name
            if p.is_dir():
                cands.append(p)
        # Common install paths
        for rel in [
            "Users/Doc_M/CITL",
            "Users/Public/CITL",
            "opt/citl",
            "home/citl",
            "srv/citl",
        ]:
            p = root / rel
            if p.is_dir():
                cands.append(p)
        # USB root itself
        cands.append(root)

    # Also add this script's own ancestor directories
    for anc in [HERE, REPO_ROOT, REPO_ROOT.parent]:
        if anc.is_dir():
            cands.append(anc)

    # Deduplicate preserving order
    seen = set()
    out = []
    for c in cands:
        k = str(c.resolve())
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def _is_factbook_root(path: Path) -> bool:
    """True if this directory looks like a Factbook repo root."""
    for _, marker in APP_MARKERS:
        if (path / marker).exists():
            return True
    # Also: contains a subfolder with "factbook" in its name
    try:
        for child in path.iterdir():
            if child.is_dir() and "factbook" in child.name.lower():
                return True
    except PermissionError:
        pass
    return False


def _dir_mtime(path: Path) -> float:
    """Most-recent mtime across key files in a candidate dir."""
    best = 0.0
    for _, marker in APP_MARKERS:
        f = path / marker
        if f.exists():
            try:
                best = max(best, f.stat().st_mtime)
            except Exception:
                pass
    return best


def quick_search(log: Callable[[str], None] = print) -> List[Path]:
    """Fast search: check known hot-spots and immediate subdirs."""
    log("Quick search — checking common locations...")
    found: List[Path] = []
    seen: set = set()

    for cand in _quick_candidates():
        # Cand itself
        if _is_factbook_root(cand):
            k = str(cand.resolve())
            if k not in seen:
                seen.add(k)
                found.append(cand)
                log(f"  Found: {cand}")
        # Immediate children
        try:
            for child in cand.iterdir():
                if not child.is_dir():
                    continue
                if any(skip in child.parts for skip in
                       ("__pycache__", ".git", ".venv", "node_modules",
                        "System Volume Information")):
                    continue
                if _is_factbook_root(child):
                    k = str(child.resolve())
                    if k not in seen:
                        seen.add(k)
                        found.append(child)
                        log(f"  Found: {child}")
        except PermissionError:
            pass

    log(f"Quick search complete: {len(found)} instance(s) found.")
    return sorted(found, key=lambda p: _dir_mtime(p), reverse=True)


def deep_search(
    log: Callable[[str], None] = print,
    stop_event: Optional[threading.Event] = None,
    max_depth: int = 6,
) -> List[Path]:
    """Comprehensive walk of all drives. May take 30-120 seconds."""
    log("Deep search — scanning all drives (this may take a minute)...")
    found: List[Path] = []
    seen: set = set()

    # Also match any directory whose NAME contains "factbook"
    def _matches(p: Path) -> bool:
        if "factbook" in p.name.lower():
            return True
        return _is_factbook_root(p)

    _SKIP = {
        "__pycache__", ".git", ".venv", "node_modules",
        "System Volume Information", "$Recycle.Bin", "Windows",
        "Program Files", "Program Files (x86)", "ProgramData",
    }

    def _walk(root: Path, depth: int):
        if depth > max_depth:
            return
        if stop_event and stop_event.is_set():
            return
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                if child.name in _SKIP or child.name.startswith("."):
                    continue
                if _matches(child):
                    k = str(child.resolve())
                    if k not in seen:
                        seen.add(k)
                        found.append(child)
                        log(f"  Found: {child}")
                _walk(child, depth + 1)
        except (PermissionError, OSError):
            pass

    for drive in _all_drives():
        log(f"  Scanning {drive}...")
        _walk(drive, 0)

    log(f"Deep search complete: {len(found)} instance(s) found.")
    return sorted(found, key=lambda p: _dir_mtime(p), reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# PATCHER — copy repair scripts INTO the target factbook folder
# ══════════════════════════════════════════════════════════════════════════════

def patch_target(target_root: Path, log: Callable[[str], None] = print) -> List[str]:
    """
    Copy the latest diagnostic / heal scripts from this USB into the target.
    Returns list of files successfully patched.
    """
    # Determine dest dir: prefer target_root/factbook-assistant, else root
    fa_dir = target_root / "factbook-assistant"
    dest = fa_dir if fa_dir.is_dir() else target_root

    patched = []
    for src in PATCH_SCRIPTS:
        if not src.exists():
            log(f"  SKIP {src.name} — not found on this USB")
            continue
        dst = dest / src.name
        try:
            shutil.copy2(src, dst)
            log(f"  Patched: {dst}")
            patched.append(str(dst))
        except Exception as e:
            log(f"  WARN: could not copy {src.name} -> {dst}: {e}")

    # Also copy the launchers if they don't exist
    for launcher_src in [
        REPO_ROOT / "DIAGNOSE_FACTBOOK.cmd",
        REPO_ROOT / "diagnose_factbook.sh",
        REPO_ROOT / "LAUNCH_FACTBOOK.cmd",
        REPO_ROOT / "launch_factbook.sh",
        REPO_ROOT / "citl_bootstrap.py",
    ]:
        if not launcher_src.exists():
            continue
        dst = target_root / launcher_src.name
        if not dst.exists():
            try:
                shutil.copy2(launcher_src, dst)
                log(f"  Added launcher: {dst.name}")
                patched.append(str(dst))
            except Exception as e:
                log(f"  WARN: {launcher_src.name}: {e}")

    log(f"Patch complete: {len(patched)} file(s) deployed to {dest}")
    return patched


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC RUNNER (imports citl_factbook_diagnostic dynamically)
# ══════════════════════════════════════════════════════════════════════════════

def run_diagnostic_on(target_root: Path,
                      on_result: Callable = None,
                      log: Callable[[str], None] = print):
    """
    Run the 18-stage diagnostic against a specific Factbook root.
    Temporarily adds it to sys.path so the modules resolve.
    """
    fa_dir = target_root / "factbook-assistant"
    search_dir = fa_dir if fa_dir.is_dir() else target_root

    # Prepend target paths so imports resolve to target versions
    old_path = sys.path[:]
    for p in (str(search_dir), str(target_root)):
        if p not in sys.path:
            sys.path.insert(0, p)

    try:
        import importlib
        # Force reload so we pick up the target's version
        if "citl_factbook_diagnostic" in sys.modules:
            del sys.modules["citl_factbook_diagnostic"]

        diag = importlib.import_module("citl_factbook_diagnostic")

        # Monkey-patch HERE inside the module to point at the target
        diag.HERE = search_dir
        diag.DATA_DIR = search_dir / "data"
        diag.LIB_RAW  = search_dir / "data" / "library_raw"
        diag.IDX_DIR  = search_dir / "data" / "indexes"
        diag.EMB_JSON = search_dir / "factbook_embeddings.json"

        log(f"Running diagnostic on: {target_root}")
        return diag.run_diagnostic(on_result=on_result)

    except ImportError as e:
        log(f"citl_factbook_diagnostic not found in {search_dir}: {e}")
        log("Patching scripts first...")
        patch_target(target_root, log)
        # Retry once
        try:
            if "citl_factbook_diagnostic" in sys.modules:
                del sys.modules["citl_factbook_diagnostic"]
            diag = importlib.import_module("citl_factbook_diagnostic")
            return diag.run_diagnostic(on_result=on_result)
        except Exception as e2:
            log(f"Still cannot load diagnostic: {e2}")
            return []
    finally:
        sys.path[:] = old_path


# ══════════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════════

_T = {
    "bg":     "#04080F",  "fg":     "#D0E8F0",  "accent": "#00D4AA",
    "hi":     "#0A1F2E",  "btn":    "#0D2838",  "btn_fg": "#A8DCE8",
    "txt_bg": "#020608",  "txt_fg": "#A8D4DC",  "status": "#00E5C8",
    "ok":     "#06D6A0",  "warn":   "#FFD166",  "err":    "#FF6B6B",
    "skip":   "#5A7080",  "panel":  "#071520",
}


def run_gui(start_path: Optional[Path] = None):
    try:
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
    except ImportError:
        print("Tkinter not available — run: sudo apt install python3-tk")
        run_cli(start_path=start_path)
        return

    root = tk.Tk()
    root.title("CITL Repair Station")
    root.geometry("1060x760")
    root.configure(bg=_T["bg"])
    root.resizable(True, True)

    # ── Title banner ───────────────────────────────────────────────────────
    banner = tk.Frame(root, bg=_T["accent"], pady=0)
    banner.pack(fill="x")
    tk.Label(banner,
             text="  CITL REPAIR STATION  —  Find · Diagnose · Fix · Patch",
             fg=_T["bg"], bg=_T["accent"],
             font=("Consolas", 13, "bold")).pack(side="left", padx=10, pady=8)
    tk.Label(banner,
             text="Windows & Ubuntu  |  USB-ready",
             fg=_T["bg"], bg=_T["accent"],
             font=("Consolas", 9)).pack(side="right", padx=10)

    # ── Status bar ─────────────────────────────────────────────────────────
    status_var = tk.StringVar(value="  Ready. Click 'Quick Search' or 'Search All Drives'.")
    status_lbl = tk.Label(root, textvariable=status_var,
                          fg=_T["status"], bg=_T["hi"],
                          font=("Consolas", 9), anchor="w", padx=8, pady=3)
    status_lbl.pack(fill="x")

    # ── Main paned ─────────────────────────────────────────────────────────
    main = tk.PanedWindow(root, orient="horizontal",
                          bg=_T["hi"], sashwidth=5, sashrelief="flat")
    main.pack(fill="both", expand=True, padx=4, pady=4)

    # ── LEFT: found instances + actions ───────────────────────────────────
    left = tk.Frame(main, bg=_T["panel"], width=320)
    main.add(left, minsize=260)

    tk.Label(left, text="Found Factbook Instances",
             fg=_T["accent"], bg=_T["panel"],
             font=("Consolas", 10, "bold")).pack(fill="x", padx=8, pady=(8, 2))

    list_frame = tk.Frame(left, bg=_T["panel"])
    list_frame.pack(fill="both", expand=True, padx=8)

    lb = tk.Listbox(list_frame, bg=_T["txt_bg"], fg=_T["txt_fg"],
                    selectbackground=_T["accent"], selectforeground=_T["bg"],
                    font=("Consolas", 9), activestyle="none",
                    relief="flat", borderwidth=0)
    lb_vsb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=lb_vsb.set)
    lb_vsb.pack(side="right", fill="y")
    lb.pack(side="left", fill="both", expand=True)

    _found_paths: List[Path] = []
    _selected_path: List[Optional[Path]] = [None]

    def _set_status(msg: str, color: str = _T["status"]):
        status_var.set(f"  {msg}")
        status_lbl.configure(fg=color)

    def _refresh_list(paths: List[Path]):
        _found_paths.clear()
        _found_paths.extend(paths)
        lb.delete(0, "end")
        for i, p in enumerate(paths):
            mtime = _dir_mtime(p)
            age = ""
            if mtime:
                dt = datetime.fromtimestamp(mtime)
                age = f"  [{dt.strftime('%Y-%m-%d')}]"
            lb.insert("end", f"{p.name}{age}")
            # Highlight the most recent
            if i == 0 and len(paths) > 1:
                lb.itemconfig(i, fg=_T["ok"])

        if paths:
            lb.selection_set(0)
            _selected_path[0] = paths[0]
            _set_status(f"{len(paths)} instance(s) found — select one, then Diagnose & Fix")
        else:
            _selected_path[0] = None
            _set_status("No Factbook instances found. Try 'Search All Drives'.", _T["warn"])

    def _on_lb_select(event=None):
        sel = lb.curselection()
        if sel and sel[0] < len(_found_paths):
            _selected_path[0] = _found_paths[sel[0]]
            _set_status(f"Selected: {_selected_path[0]}")

    lb.bind("<<ListboxSelect>>", _on_lb_select)

    # Search buttons
    btn_row = tk.Frame(left, bg=_T["panel"])
    btn_row.pack(fill="x", padx=8, pady=4)

    _stop_deep = threading.Event()
    _searching = [False]

    def _btn(parent, text, color, cmd):
        return tk.Button(parent, text=text, bg=color, fg=_T["bg"],
                         activebackground=_T["status"], activeforeground=_T["bg"],
                         relief="flat", padx=6, pady=4, cursor="hand2",
                         font=("Consolas", 8, "bold"), command=cmd)

    def _do_quick():
        if _searching[0]: return
        _searching[0] = True
        _set_status("Quick search in progress...")
        def _bg():
            results = quick_search(lambda s: root.after(0, lambda m=s: _set_status(m)))
            root.after(0, lambda: _refresh_list(results))
            root.after(0, lambda: _searching.__setitem__(0, False))
        threading.Thread(target=_bg, daemon=True).start()

    def _do_deep():
        if _searching[0]: return
        _stop_deep.clear()
        _searching[0] = True
        _set_status("Deep search running — scanning all drives...")

        def _bg():
            results = deep_search(
                log=lambda s: root.after(0, lambda m=s: _set_status(m[:80])),
                stop_event=_stop_deep,
            )
            root.after(0, lambda: _refresh_list(results))
            root.after(0, lambda: _searching.__setitem__(0, False))
        threading.Thread(target=_bg, daemon=True).start()

    def _do_stop():
        _stop_deep.set()
        _set_status("Search stopped.", _T["warn"])
        _searching[0] = False

    def _do_browse():
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Select Factbook root folder")
        if d:
            p = Path(d)
            _found_paths.insert(0, p)
            lb.insert(0, p.name)
            lb.selection_clear(0, "end")
            lb.selection_set(0)
            _selected_path[0] = p
            _set_status(f"Manually selected: {p}")

    _btn(btn_row, "Quick Search",     _T["accent"], _do_quick).pack(fill="x", pady=1)
    _btn(btn_row, "Search All Drives",_T["warn"],   _do_deep).pack(fill="x", pady=1)
    _btn(btn_row, "Stop Search",      _T["err"],    _do_stop).pack(fill="x", pady=1)
    _btn(btn_row, "Browse...",        _T["btn"],    _do_browse).pack(fill="x", pady=1)

    # Selected path label
    sel_lbl = tk.Label(left,
                       text="No instance selected",
                       fg=_T["warn"], bg=_T["panel"],
                       font=("Consolas", 8), wraplength=280, justify="left")
    sel_lbl.pack(fill="x", padx=8, pady=2)

    def _watch_selected():
        p = _selected_path[0]
        sel_lbl.configure(text=str(p) if p else "No instance selected",
                          fg=_T["ok"] if p else _T["warn"])
        root.after(500, _watch_selected)
    _watch_selected()

    # ── RIGHT: diagnostic + log ────────────────────────────────────────────
    right = tk.Frame(main, bg=_T["bg"])
    main.add(right, minsize=620)

    right_nb = ttk.Notebook(right)
    right_nb.pack(fill="both", expand=True)

    # ── Tab 1: Diagnose & Fix ─────────────────────────────────────────────
    diag_tab = tk.Frame(right_nb, bg=_T["bg"])
    right_nb.add(diag_tab, text=" Diagnose & Fix ")

    # Action toolbar
    atb = tk.Frame(diag_tab, bg=_T["bg"], pady=4)
    atb.pack(fill="x", padx=4)

    diag_status_var = tk.StringVar(value="Select an instance then click Diagnose.")
    tk.Label(atb, textvariable=diag_status_var,
             fg=_T["status"], bg=_T["bg"],
             font=("Consolas", 9), anchor="w").pack(side="left", fill="x", expand=True)

    # Stage canvas
    canv_outer = tk.Frame(diag_tab, bg=_T["bg"])
    canv_outer.pack(fill="both", expand=True, padx=4)
    canv = tk.Canvas(canv_outer, bg=_T["bg"], highlightthickness=0)
    vsb = ttk.Scrollbar(canv_outer, orient="vertical", command=canv.yview)
    stage_frame = tk.Frame(canv, bg=_T["bg"])
    stage_frame.bind("<Configure>",
                     lambda e: canv.configure(scrollregion=canv.bbox("all")))
    canv.create_window((0, 0), window=stage_frame, anchor="nw")
    canv.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canv.pack(side="left", fill="both", expand=True)
    canv.bind("<Enter>",
              lambda e: canv.bind_all("<MouseWheel>",
                  lambda ev: canv.yview_scroll(int(-1*(ev.delta/120)), "units")))
    canv.bind("<Leave>", lambda e: canv.unbind_all("<MouseWheel>"))

    _result_store: List = []
    _diag_counts = {"pass": 0, "fail": 0, "warn": 0, "skip": 0}
    _DOT_COLOR = {"pass": _T["ok"], "fail": _T["err"],
                  "warn": _T["warn"], "skip": _T["skip"]}

    # Fix log
    fix_log_frame = tk.Frame(diag_tab, bg=_T["bg"])
    fix_log_frame.pack(fill="x", padx=4, pady=(2, 0))
    tk.Label(fix_log_frame, text="Fix Action Log",
             fg=_T["accent"], bg=_T["bg"],
             font=("Consolas", 8, "bold"), anchor="w").pack(anchor="w")
    fix_log = ScrolledText(fix_log_frame, height=6, state="disabled",
                           bg=_T["txt_bg"], fg=_T["txt_fg"],
                           font=("Consolas", 8), relief="flat")
    fix_log.pack(fill="x")
    fix_log.tag_configure("ok",  foreground=_T["ok"])
    fix_log.tag_configure("err", foreground=_T["err"])
    fix_log.tag_configure("cmd", foreground=_T["accent"])

    def _flog(line: str):
        def _do():
            fix_log.configure(state="normal")
            low = line.lower()
            tag = ("ok"  if ("ok" in low or "fixed" in low or "done" in low) else
                   "err" if ("error" in low or "fail" in low or "cannot" in low) else
                   "cmd" if line.startswith(("$", "Running", "Pulling", "Fix", "Patch")) else
                   "")
            fix_log.insert("end", line + "\n", tag or ())
            fix_log.configure(state="disabled")
            fix_log.see("end")
        root.after(0, _do)

    def _add_stage_row(r):
        def _ui():
            dot_color = _DOT_COLOR.get(r.status, _T["fg"])
            row = tk.Frame(stage_frame, bg=_T["bg"])
            row.pack(fill="x", pady=1, padx=2)
            tk.Label(row, text="●", fg=dot_color, bg=_T["bg"],
                     font=("Consolas", 11)).pack(side="left", padx=(4, 4))
            info = tk.Frame(row, bg=_T["bg"])
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info,
                     text=f"[{r.status.upper():4s}] S{r.stage:02d}: {r.name}  ({r.duration_ms:.0f}ms)",
                     fg=dot_color, bg=_T["bg"],
                     font=("Consolas", 8, "bold"), anchor="w").pack(anchor="w")
            first_line = (r.detail or "").split("\n")[0][:90]
            tk.Label(info, text=first_line, fg=_T["fg"], bg=_T["bg"],
                     font=("Consolas", 8), wraplength=400,
                     justify="left", anchor="w").pack(anchor="w")

            btns = tk.Frame(row, bg=_T["bg"])
            btns.pack(side="right", padx=2)

            # Detail toggle
            _ex = [False]; _df = [None]
            def _tog(rr=r, ex=_ex, df=_df, p=info):
                if ex[0]:
                    if df[0]: df[0].destroy(); df[0] = None; ex[0] = False
                else:
                    df[0] = tk.Frame(p, bg=_T["hi"], padx=6, pady=4)
                    df[0].pack(fill="x")
                    tk.Label(df[0], text=rr.detail,
                             fg=_T["warn"] if rr.failed else _T["fg"],
                             bg=_T["hi"],
                             font=("Consolas", 7), justify="left",
                             wraplength=520, anchor="w").pack(anchor="w")
                    if rr.fix_cmds:
                        tk.Label(df[0],
                                 text="$ " + "\n$ ".join(rr.fix_cmds),
                                 fg=_T["accent"], bg=_T["hi"],
                                 font=("Consolas", 7), anchor="w").pack(anchor="w")
                    ex[0] = True
            tk.Button(btns, text="Detail", bg=_T["btn"], fg=_T["status"],
                      activebackground=_T["hi"],
                      relief="flat", padx=4, pady=1, cursor="hand2",
                      font=("Consolas", 7), command=_tog).pack(side="left", padx=1)

            # Fix button
            if hasattr(r, "fix_fn") and r.fix_fn and not r.passed:
                def _fix(rr=r):
                    _flog(f"Fixing S{rr.stage}: {rr.name}")
                    diag_status_var.set(f"Fixing: {rr.name}...")
                    def _bg():
                        try:
                            ok = rr.fix_fn(rr, _flog)
                            root.after(0, lambda o=ok, n=rr.name: (
                                _flog(f"{'Fixed' if o else 'Incomplete'}: {n}"),
                                diag_status_var.set(f"{'Fixed' if o else 'Incomplete'}: {n}  — re-run to verify")
                            ))
                        except Exception as ex:
                            root.after(0, lambda e=ex: _flog(f"ERROR: {e}"))
                    threading.Thread(target=_bg, daemon=True).start()
                tk.Button(btns, text=f"Fix",
                          bg=_T["err"], fg=_T["bg"],
                          activebackground=_T["warn"],
                          relief="flat", padx=4, pady=1, cursor="hand2",
                          font=("Consolas", 7, "bold"),
                          command=_fix).pack(side="left", padx=1)

            tk.Frame(stage_frame, height=1, bg=_T["hi"]).pack(fill="x")
        root.after(0, _ui)

    def _run_diag():
        p = _selected_path[0]
        if not p:
            _set_status("Select a Factbook instance first.", _T["warn"])
            return
        for w in stage_frame.winfo_children():
            w.destroy()
        _result_store.clear()
        _diag_counts.update({"pass": 0, "fail": 0, "warn": 0, "skip": 0})
        diag_status_var.set(f"Running diagnostic on {p.name}...")

        def _on_r(r):
            _result_store.append(r)
            _diag_counts[r.status] = _diag_counts.get(r.status, 0) + 1
            _add_stage_row(r)
            root.after(0, lambda: diag_status_var.set(
                f"S{r.stage}/18: {r.name} [{r.status.upper()}]  "
                f"| {_diag_counts['pass']}P  {_diag_counts['fail']}F  {_diag_counts['warn']}W"))

        def _bg():
            run_diagnostic_on(p, on_result=_on_r, log=_flog)
            failed = [r for r in _result_store if r.failed]
            def _done():
                if failed:
                    diag_status_var.set(
                        f"COMPLETE: {_diag_counts['pass']} passed, "
                        f"{_diag_counts['fail']} FAILED — click Fix buttons above")
                    status_lbl.configure(fg=_T["err"])
                else:
                    diag_status_var.set(
                        f"ALL CLEAR: {_diag_counts['pass']} passed, "
                        f"{_diag_counts['warn']} warnings")
                    status_lbl.configure(fg=_T["ok"])
            root.after(0, _done)
        threading.Thread(target=_bg, daemon=True).start()

    def _fix_all():
        fixable = [r for r in _result_store if not r.passed
                   and hasattr(r, "fix_fn") and r.fix_fn]
        if not fixable:
            _flog("No fixable issues (or run Diagnose first)")
            return
        _flog(f"Auto-fixing {len(fixable)} issue(s)...")
        def _bg():
            for r in fixable:
                _flog(f"\n--- Fixing S{r.stage}: {r.name} ---")
                try:
                    ok = r.fix_fn(r, _flog)
                    _flog(f"{'FIXED' if ok else 'INCOMPLETE'}: {r.name}")
                except Exception as e:
                    _flog(f"ERROR: {e}")
            root.after(0, lambda: _flog("\nAuto-fix complete. Re-run Diagnose to verify."))
        threading.Thread(target=_bg, daemon=True).start()

    def _patch_target():
        p = _selected_path[0]
        if not p:
            _set_status("Select a Factbook instance first.", _T["warn"])
            return
        _flog(f"Patching scripts into {p}...")
        threading.Thread(target=lambda: patch_target(p, _flog), daemon=True).start()

    # Action buttons row
    act_row = tk.Frame(diag_tab, bg=_T["bg"], pady=4)
    act_row.pack(fill="x", padx=4)

    def _abtn(text, color, cmd):
        return tk.Button(act_row, text=text, bg=color, fg=_T["bg"],
                         activebackground=_T["status"],
                         relief="flat", padx=10, pady=4, cursor="hand2",
                         font=("Consolas", 9, "bold"), command=cmd)

    _abtn("Diagnose Selected",  _T["accent"], _run_diag).pack(side="left", padx=4)
    _abtn("Fix All Problems",   _T["err"],    _fix_all).pack(side="left", padx=2)
    _abtn("Patch Scripts In",   _T["warn"],   _patch_target).pack(side="left", padx=2)
    _abtn("Diagnose + Fix All", _T["ok"],
          lambda: (threading.Thread(target=lambda: (
              time.sleep(0.1), _run_diag(),
              time.sleep(8), _fix_all()
          ), daemon=True).start())).pack(side="left", padx=2)

    # ── Tab 2: Patch Log ──────────────────────────────────────────────────
    patch_tab = tk.Frame(right_nb, bg=_T["bg"])
    right_nb.add(patch_tab, text=" Patch Log ")
    patch_log = ScrolledText(patch_tab, state="disabled",
                             bg=_T["txt_bg"], fg=_T["txt_fg"],
                             font=("Consolas", 9), relief="flat", padx=6)
    patch_log.pack(fill="both", expand=True)
    patch_log.tag_configure("ok",  foreground=_T["ok"])
    patch_log.tag_configure("cmd", foreground=_T["accent"])

    def _plog(line: str):
        def _d():
            patch_log.configure(state="normal")
            tag = "ok" if ("patched" in line.lower() or "added" in line.lower() or
                           "complete" in line.lower()) else "cmd"
            patch_log.insert("end", line + "\n", tag)
            patch_log.configure(state="disabled")
            patch_log.see("end")
        root.after(0, _d)

    # ── Tab 3: About ──────────────────────────────────────────────────────
    about_tab = tk.Frame(right_nb, bg=_T["bg"])
    right_nb.add(about_tab, text=" About ")
    about_text = f"""CITL Repair Station  v1.0
USB-resident · Windows + Ubuntu

WHAT IT DOES
  1. Quick Search  — checks ~30 common locations in <2s
  2. Deep Search   — walks all drives (30-120s, stoppable)
  3. Selection     — pick from list if multiple found
  4. Diagnostic    — 18-stage live pipeline test
  5. Fix           — per-stage Fix buttons + Fix All
  6. Patch         — copies latest heal scripts into target

SEARCH MATCHES
  Any folder containing 'factbook' (case-insensitive)
  or containing a known CITL marker file.
  Results sorted by most recent modification date.

SCRIPTS PATCHED INTO TARGET
{chr(10).join('  ' + str(s.name) for s in PATCH_SCRIPTS if s.exists())}

THIS INSTANCE
  Script:     {__file__}
  USB root:   {REPO_ROOT}
  Host:       {socket.gethostname()}
  OS:         {platform.platform()}
"""
    tk.Label(about_tab, text=about_text,
             fg=_T["txt_fg"], bg=_T["bg"],
             font=("Consolas", 9), justify="left", anchor="nw",
             padx=16, pady=16).pack(fill="both", expand=True)

    # ── Auto-start ─────────────────────────────────────────────────────────
    if start_path:
        _found_paths.append(start_path)
        lb.insert("end", start_path.name)
        lb.selection_set(0)
        _selected_path[0] = start_path
        root.after(400, _run_diag)
    else:
        root.after(300, _do_quick)

    root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def run_cli(start_path: Optional[Path] = None, auto_fix: bool = False):
    if platform.system() == "Windows":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
        except Exception:
            pass

    print("=" * 66)
    print("  CITL Repair Station  (CLI mode)")
    print("=" * 66)

    if start_path:
        found = [start_path]
    else:
        found = quick_search()
        if not found:
            print("Quick search found nothing. Running deep search...")
            found = deep_search()

    if not found:
        print("No Factbook instances found on this device.")
        print("Try:  python citl_repair_all.py --path /path/to/factbook")
        return

    print(f"\nFound {len(found)} instance(s):")
    for i, p in enumerate(found):
        mark = " [MOST RECENT]" if i == 0 else ""
        print(f"  [{i+1}] {p}{mark}")

    if len(found) > 1 and sys.stdin.isatty():
        choice = input(f"\nSelect instance [1-{len(found)}] (Enter=1): ").strip()
        try:
            idx = int(choice) - 1
            target = found[idx]
        except Exception:
            target = found[0]
    else:
        target = found[0]

    print(f"\nTarget: {target}")
    print("Patching diagnostic scripts...")
    patch_target(target)

    print(f"\nRunning 18-stage diagnostic on {target}...\n")
    results = run_diagnostic_on(target, log=print)

    passed  = [r for r in results if r.status == "pass"]
    failed  = [r for r in results if r.status == "fail"]
    warned  = [r for r in results if r.status == "warn"]

    print(f"\n{'=' * 66}")
    print(f"  {len(passed)} passed  |  {len(failed)} failed  |  {len(warned)} warnings")
    print(f"{'=' * 66}")

    if auto_fix:
        fixable = [r for r in failed + warned
                   if hasattr(r, "fix_fn") and r.fix_fn]
        if fixable:
            print(f"\nAuto-fixing {len(fixable)} issue(s)...")
            for r in fixable:
                print(f"  Fixing: {r.name}")
                try:
                    ok = r.fix_fn(r, print)
                    print(f"  {'FIXED' if ok else 'INCOMPLETE'}: {r.name}")
                except Exception as e:
                    print(f"  ERROR: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="CITL Repair Station — Find, Diagnose & Fix all CITL apps")
    ap.add_argument("--cli",   action="store_true", help="CLI mode (no GUI)")
    ap.add_argument("--fix",   action="store_true", help="Auto-fix in CLI mode")
    ap.add_argument("--path",  type=str, default="",
                    help="Skip search; repair this specific path")
    args = ap.parse_args()

    start_path = Path(args.path).resolve() if args.path else None

    if args.cli:
        run_cli(start_path=start_path, auto_fix=args.fix)
    else:
        try:
            import tkinter  # noqa
            run_gui(start_path=start_path)
        except ImportError:
            run_cli(start_path=start_path, auto_fix=args.fix)


if __name__ == "__main__":
    main()
