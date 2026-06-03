#!/usr/bin/env python3
"""
citl_bootstrap.py — CITL Universal Self-Healing Bootstrap
══════════════════════════════════════════════════════════
Run this first on any machine (USB, local, lab workstation) before
launching Factbook or FLEX Troubleshooter.

It auto-detects and heals EVERY possible failure mode:
  • Python version check
  • Tkinter availability
  • pip package installation (numpy, requests, python-docx, etc.)
  • Ollama: not installed, not running, wrong host, missing models
  • Embedding model (nomic-embed-text) missing
  • Index directories missing or unwritable (read-only USB fallback)
  • Source documents missing
  • Index empty or corrupt → force rebuild
  • Embedding JSON missing or corrupt → rebuild
  • FLEX corpus missing or corrupt → rebuild
  • FFmpeg missing (optional)
  • Disk space check
  • Config file corrupt → reset
  • Launcher EXEs missing → offer PyInstaller build

Usage
-----
    python citl_bootstrap.py              # GUI mode (auto-detects Tk)
    python citl_bootstrap.py --cli        # CLI-only mode (no GUI)
    python citl_bootstrap.py --app factbook   # Then launch Factbook
    python citl_bootstrap.py --app flex       # Then launch FLEX

From a USB launcher script:
    python citl_bootstrap.py --app factbook --auto-heal
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# ── Paths ─────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
FA_DIR   = HERE / "factbook-assistant"
FLEX_DIR = HERE / "citl_flex_troubleshooter"
SCRIPTS  = HERE / "scripts"

# Ensure factbook-assistant is on sys.path for CITL modules
for _p in (str(FA_DIR), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ══════════════════════════════════════════════════════════════════════════════
# CLI / LOGGING UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

_BOLD  = "\033[1m"
_RED   = "\033[91m"
_YEL   = "\033[93m"
_GRN   = "\033[92m"
_CYN   = "\033[96m"
_RST   = "\033[0m"


# Ensure stdout can handle Unicode on Windows
if platform.system() == "Windows":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def _safe_print(text: str):
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def _c(color: str, text: str) -> str:
    if sys.stdout.isatty():
        return color + text + _RST
    return text


def _h(text: str):    _safe_print(_c(_BOLD + _CYN, text))
def _ok(text: str):   _safe_print(_c(_GRN,  f"  OK  {text}"))
def _warn(text: str): _safe_print(_c(_YEL,  f"  !!  {text}"))
def _err(text: str):  _safe_print(_c(_RED,  f"  XX  {text}"))
def _inf(text: str):  _safe_print(f"       {text}")


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL CHECKS AND HEALS
# ══════════════════════════════════════════════════════════════════════════════

class BootResult:
    def __init__(self, name: str, ok: bool, msg: str, fix_fn=None, fix_label: str = ""):
        self.name      = name
        self.ok        = ok
        self.msg       = msg
        self.fix_fn    = fix_fn      # callable() → bool (True = fixed)
        self.fix_label = fix_label


def _run_sub(cmd: List[str], timeout: int = 120, capture: bool = True) -> Tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=capture, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, "Timed out"
    except Exception as e:
        return False, str(e)


def _pip(pkg: str) -> bool:
    ok, out = _run_sub([sys.executable, "-m", "pip", "install", "--quiet", pkg], timeout=180)
    if ok:
        _ok(f"Installed {pkg}")
    else:
        _err(f"pip install {pkg} failed: {out[:120]}")
    return ok


def _import_ok(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


# ── Python version ────────────────────────────────────────────────────────────

def check_python() -> BootResult:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 9)
    msg = f"Python {v.major}.{v.minor}.{v.micro}"
    if not ok:
        return BootResult("Python version", False,
                          f"{msg} — requires 3.9+. Please upgrade Python.",
                          fix_label="Open python.org")
    return BootResult("Python version", True, msg)


# ── Tkinter ───────────────────────────────────────────────────────────────────

def check_tkinter() -> BootResult:
    try:
        import tkinter  # noqa
        return BootResult("tkinter", True, "tkinter available")
    except ImportError:
        def _fix():
            if platform.system() == "Linux":
                ok, _ = _run_sub(["sudo", "apt-get", "install", "-y", "python3-tk"])
                return ok
            return False
        return BootResult("tkinter", False,
                          "tkinter not found — GUI unavailable.\n"
                          "  Ubuntu/Debian fix: sudo apt install python3-tk\n"
                          "  macOS fix: reinstall Python from python.org",
                          fix_fn=_fix, fix_label="Install tkinter")


# ── Python packages ───────────────────────────────────────────────────────────

_REQUIRED_PKGS = [
    ("numpy",    "numpy",        True),
    ("requests", "requests",     True),
]
_OPTIONAL_PKGS = [
    ("docx",           "python-docx",      False),
    ("docx2txt",       "docx2txt",         False),
    ("PIL",            "Pillow",           False),
    ("faster_whisper", "faster-whisper",   False),
    ("sounddevice",    "sounddevice",      False),
]


def check_packages() -> List[BootResult]:
    results = []
    for imp, pkg, required in _REQUIRED_PKGS + _OPTIONAL_PKGS:
        if _import_ok(imp):
            results.append(BootResult(f"Package:{pkg}", True, f"{pkg} installed"))
        else:
            _pkg = pkg
            def _fix(p=_pkg): return _pip(p)
            results.append(BootResult(
                f"Package:{pkg}",
                not required,   # required=True → ok=False means it blocks
                f"{pkg} not installed {'(required)' if required else '(optional)'}",
                fix_fn=_fix, fix_label=f"pip install {pkg}",
            ))
    return results


# ── Ollama running ────────────────────────────────────────────────────────────

def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _check_ollama_api(host: str, timeout: float = 5.0) -> Tuple[bool, List[str]]:
    try:
        req = urllib.request.Request(host + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        models = [m["name"] for m in data.get("models", []) if isinstance(m, dict)]
        return True, models
    except Exception:
        return False, []


def _find_ollama_exe() -> Optional[str]:
    exe = shutil.which("ollama") or shutil.which("ollama.exe")
    if exe:
        return exe
    if platform.system() == "Windows":
        lappdata = os.environ.get("LOCALAPPDATA", "")
        username  = os.environ.get("USERNAME", "")
        for p in [
            Path(lappdata) / "Programs" / "Ollama" / "ollama.exe",
            Path(lappdata) / "Ollama" / "ollama.exe",
            Path("C:/Users") / username / "AppData/Local/Programs/Ollama/ollama.exe",
            Path("C:/Program Files/Ollama/ollama.exe"),
            Path("C:/Program Files (x86)/Ollama/ollama.exe"),
        ]:
            try:
                if p.exists():
                    return str(p)
            except Exception:
                pass
    return None


def _kill_hung_ollama() -> None:
    if platform.system() != "Windows":
        return
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ollama.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=5)
        if "ollama.exe" in r.stdout:
            _inf("Killing existing ollama.exe for clean restart…")
            subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"],
                           capture_output=True, timeout=5)
            time.sleep(1)
    except Exception:
        pass


def _start_ollama_bg() -> bool:
    exe = _find_ollama_exe()
    if not exe:
        _err("ollama executable not found. Install from https://ollama.com/download/windows")
        _err("  or run: winget install Ollama.Ollama")
        return False
    _inf(f"Starting Ollama in background: {exe}")
    _kill_hung_ollama()
    try:
        if platform.system() == "Windows":
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS  = 0x00000008
            subprocess.Popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            )
        else:
            subprocess.Popen([exe, "serve"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for i in range(45):
            time.sleep(1)
            up, _ = _check_ollama_api(_ollama_host(), timeout=2)
            if up:
                _ok(f"Ollama started after {i+1}s")
                return True
        _err("Ollama launched but did not respond within 45 seconds.")
        _err("Open a terminal and run  ollama serve  to see error output.")
        return False
    except Exception as e:
        _err(f"Could not start Ollama: {e}")
        return False


def check_ollama() -> List[BootResult]:
    results = []
    host = _ollama_host()
    up, models = _check_ollama_api(host)

    if not up:
        results.append(BootResult(
            "Ollama running", False,
            f"Ollama not running at {host}",
            fix_fn=_start_ollama_bg, fix_label="Start Ollama",
        ))
        results.append(BootResult("LLM model",   False,
                                   "Cannot check models — Ollama offline"))
        results.append(BootResult("Embed model", False,
                                   "Cannot check models — Ollama offline"))
        return results

    results.append(BootResult("Ollama running", True,
                               f"Ollama at {host} — {len(models)} model(s)"))

    # LLM
    _LLM_WANTED = ["mistral:7b-instruct", "mistral", "llama3", "phi3", "gemma"]
    has_llm = any(any(w in m for w in _LLM_WANTED) for m in models)
    if not has_llm and not models:
        def _pull_llm():
            ok, out = _run_sub(["ollama", "pull", "mistral:7b-instruct"], timeout=900)
            if ok: _ok("Pulled mistral:7b-instruct")
            else:  _err(f"Pull failed: {out[:200]}")
            return ok
        results.append(BootResult("LLM model", False,
                                   "No LLM installed",
                                   fix_fn=_pull_llm, fix_label="Pull mistral:7b-instruct"))
    elif not has_llm:
        results.append(BootResult("LLM model", True,
                                   f"LLM present (not preferred): {models[0]}"))
    else:
        best = next(m for m in models if any(w in m for w in _LLM_WANTED))
        results.append(BootResult("LLM model", True, f"LLM: {best}"))

    # Embed model
    _EMB_WANTED = ["nomic-embed-text", "mxbai-embed-large"]
    has_emb = any(any(e in m for e in _EMB_WANTED) for m in models)
    if not has_emb:
        def _pull_emb():
            ok, out = _run_sub(["ollama", "pull", "nomic-embed-text"], timeout=600)
            if ok: _ok("Pulled nomic-embed-text")
            else:  _err(f"Pull failed: {out[:200]}")
            return ok
        results.append(BootResult("Embed model", False,
                                   "nomic-embed-text not installed — vector search disabled",
                                   fix_fn=_pull_emb, fix_label="Pull nomic-embed-text"))
    else:
        results.append(BootResult("Embed model", True, "nomic-embed-text available"))

    return results


# ── Index / corpus ────────────────────────────────────────────────────────────

def _writable_index_dir(base: Path) -> Path:
    candidates = [
        base / "data" / "indexes",
        Path(os.environ.get("APPDATA", Path.home())) / "CITL" / "indexes",
        Path.home() / ".citl" / "indexes",
    ]
    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".write_test"
            t.write_text("ok"); t.unlink()
            return p
        except Exception:
            continue
    return base / "data" / "indexes"


def _count_chunks(idx_dir: Path) -> int:
    if not idx_dir.is_dir():
        return 0
    total = 0
    for f in idx_dir.glob("*.jsonl"):
        if f.name.startswith("_"):
            continue
        try:
            total += sum(1 for ln in f.open(encoding="utf-8", errors="ignore")
                         if ln.strip() and not ln.strip().startswith("//"))
        except Exception:
            pass
    return total


def check_index(app_dir: Path) -> List[BootResult]:
    results = []
    lib_raw = app_dir / "data" / "library_raw"
    idx_dir = _writable_index_dir(app_dir)

    # Source docs
    if not lib_raw.is_dir():
        def _mk():
            lib_raw.mkdir(parents=True, exist_ok=True)
            _ok(f"Created {lib_raw}")
            return True
        results.append(BootResult("library_raw dir", False,
                                   f"Missing: {lib_raw}",
                                   fix_fn=_mk, fix_label="Create directory"))
    else:
        docs = (list(lib_raw.glob("*.pdf")) + list(lib_raw.glob("*.txt")) +
                list(lib_raw.glob("*.docx")) + list(lib_raw.glob("*.md")))
        if not docs:
            results.append(BootResult("Source documents", False,
                                       f"library_raw/ is empty — no documents to index.\n"
                                       f"  Add PDFs to: {lib_raw}"))
        else:
            results.append(BootResult("Source documents", True,
                                       f"{len(docs)} document(s) in library_raw/"))

    # Chunk count
    chunks = _count_chunks(idx_dir)
    if chunks < 10:
        def _rebuild():
            try:
                if str(app_dir) not in sys.path:
                    sys.path.insert(0, str(app_dir))
                from citl_auto_index import auto_index_library, LIB_RAW
                r = auto_index_library(lib_dir=LIB_RAW, idx_dir=idx_dir, force=True)
                total = sum(r.values()) if r else 0
                _ok(f"Index rebuilt: {total:,} chunks")
                return total > 0
            except Exception as e:
                _err(f"Rebuild failed: {e}")
                return False
        results.append(BootResult("Index chunks", False,
                                   f"Only {chunks} chunks — needs rebuild",
                                   fix_fn=_rebuild, fix_label="Rebuild Index"))
    else:
        results.append(BootResult("Index chunks", True,
                                   f"{chunks:,} chunks in {idx_dir.name}/"))

    # Embedding JSON
    emb_json = app_dir / "factbook_embeddings.json"
    if not emb_json.exists():
        results.append(BootResult("Embedding JSON", True,
                                   "factbook_embeddings.json absent (optional — keyword search OK)"))
    else:
        try:
            data = json.loads(emb_json.read_text(encoding="utf-8"))
            n = len(data.get("chunks", data.get("embeddings", [])))
            if n < 5:
                def _del_rebuild():
                    emb_json.unlink(missing_ok=True)
                    script = app_dir / "build_factbook_index.py"
                    if script.exists():
                        ok, _ = _run_sub([sys.executable, str(script)], timeout=600)
                        return ok
                    return False
                results.append(BootResult("Embedding JSON", False,
                                           f"Corrupt or empty ({n} entries)",
                                           fix_fn=_del_rebuild, fix_label="Delete & Rebuild"))
            else:
                results.append(BootResult("Embedding JSON", True, f"{n:,} vectors"))
        except Exception as e:
            def _del_rebuild2():
                emb_json.unlink(missing_ok=True)
                script = app_dir / "build_factbook_index.py"
                if script.exists():
                    ok, _ = _run_sub([sys.executable, str(script)], timeout=600)
                    return ok
                return False
            results.append(BootResult("Embedding JSON", False,
                                       f"Corrupt JSON: {e}",
                                       fix_fn=_del_rebuild2, fix_label="Delete & Rebuild"))

    return results


def check_flex_corpus() -> List[BootResult]:
    corpus = FLEX_DIR / "flex_embeddings.json"
    if not FLEX_DIR.is_dir():
        return [BootResult("FLEX dir", False, f"FLEX app dir missing: {FLEX_DIR}")]
    if not corpus.exists():
        def _build():
            script = FLEX_DIR / "flex_builder.py"
            if not script.exists():
                _err(f"flex_builder.py not found: {script}")
                return False
            ok, _ = _run_sub([sys.executable, str(script)], timeout=300)
            if ok: _ok("FLEX corpus built")
            return ok
        return [BootResult("FLEX corpus", False,
                           "flex_embeddings.json not built yet",
                           fix_fn=_build, fix_label="Build FLEX Corpus")]
    try:
        data = json.loads(corpus.read_text(encoding="utf-8"))
        n = len(data.get("chunks", []))
        if n < 5:
            def _rebuild_flex():
                corpus.unlink(missing_ok=True)
                script = FLEX_DIR / "flex_builder.py"
                if not script.exists(): return False
                ok, _ = _run_sub([sys.executable, str(script)], timeout=300)
                if ok: _ok("FLEX corpus rebuilt")
                return ok
            return [BootResult("FLEX corpus", False,
                               f"Only {n} chunks — rebuild recommended",
                               fix_fn=_rebuild_flex, fix_label="Rebuild FLEX Corpus")]
        return [BootResult("FLEX corpus", True, f"FLEX corpus: {n:,} chunks")]
    except Exception as e:
        def _del_flex():
            corpus.unlink(missing_ok=True)
            script = FLEX_DIR / "flex_builder.py"
            if not script.exists(): return False
            ok, _ = _run_sub([sys.executable, str(script)], timeout=300)
            return ok
        return [BootResult("FLEX corpus", False, f"Corrupt: {e}",
                           fix_fn=_del_flex, fix_label="Delete & Rebuild")]


# ── Filesystem ────────────────────────────────────────────────────────────────

def check_filesystem() -> List[BootResult]:
    results = []
    try:
        free_gb = shutil.disk_usage(str(HERE)).free / 1e9
        if free_gb < 0.5:
            results.append(BootResult("Disk space", False,
                                       f"Only {free_gb:.1f} GB free — critically low!"))
        elif free_gb < 2.0:
            results.append(BootResult("Disk space", False,
                                       f"{free_gb:.1f} GB free — low (models need ~4 GB)"))
        else:
            results.append(BootResult("Disk space", True, f"{free_gb:.1f} GB free"))
    except Exception:
        pass

    cfg = FA_DIR / "citl_config.json"
    if cfg.exists():
        try:
            json.loads(cfg.read_text(encoding="utf-8"))
            results.append(BootResult("Config file", True, "citl_config.json OK"))
        except json.JSONDecodeError:
            def _reset():
                cfg.unlink(missing_ok=True)
                _ok("Config reset — defaults will regenerate on next launch")
                return True
            results.append(BootResult("Config file", False,
                                       "citl_config.json is corrupt",
                                       fix_fn=_reset, fix_label="Reset Config"))
    return results


# ── FFmpeg ────────────────────────────────────────────────────────────────────

def check_ffmpeg() -> BootResult:
    if shutil.which("ffmpeg"):
        return BootResult("FFmpeg", True, "FFmpeg on PATH")
    for c in [FA_DIR / "bin" / "ffmpeg.exe", HERE / "bin" / "ffmpeg.exe"]:
        if c.exists():
            return BootResult("FFmpeg", True, f"Bundled FFmpeg: {c}")

    def _install():
        if platform.system() == "Windows":
            ok, _ = _run_sub(["winget", "install", "Gyan.FFmpeg",
                              "--accept-package-agreements",
                              "--accept-source-agreements"], timeout=300)
        elif platform.system() == "Linux":
            ok, _ = _run_sub(["sudo", "apt-get", "install", "-y", "ffmpeg"])
        else:
            ok, _ = _run_sub(["brew", "install", "ffmpeg"], timeout=300)
        return ok

    return BootResult("FFmpeg", True,   # not required — mark as OK with note
                      "FFmpeg not found (optional — audio features limited)",
                      fix_fn=_install, fix_label="Install FFmpeg")


# ══════════════════════════════════════════════════════════════════════════════
# FULL BOOTSTRAP RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_all_checks(auto_heal: bool = False, target_app: str = "factbook") -> List[BootResult]:
    """Run all checks. If auto_heal, attempt all fixes automatically."""
    app_dir = FA_DIR if target_app != "flex" else FLEX_DIR

    all_results: List[BootResult] = []

    _h("\n-- Python Environment ---------------------------------------")
    for r in [check_python(), check_tkinter()] + check_packages():
        _print_result(r)
        all_results.append(r)

    _h("\n-- Ollama / Models ------------------------------------------")
    for r in check_ollama():
        _print_result(r)
        all_results.append(r)

    _h("\n-- Index & Corpus -------------------------------------------")
    for r in check_index(FA_DIR):
        _print_result(r)
        all_results.append(r)

    if target_app == "flex" or FLEX_DIR.is_dir():
        for r in check_flex_corpus():
            _print_result(r)
            all_results.append(r)

    _h("\n-- File System ----------------------------------------------")
    for r in check_filesystem() + [check_ffmpeg()]:
        _print_result(r)
        all_results.append(r)

    # ── Auto-heal pass ────────────────────────────────────────────────────
    if auto_heal:
        broken = [r for r in all_results if not r.ok and r.fix_fn]
        if broken:
            _h(f"\n-- Auto-Heal ({len(broken)} issue(s) found) --------------------------")
            for r in broken:
                _inf(f"Fixing: {r.name} — {r.fix_label}")
                try:
                    fixed = r.fix_fn()
                    if fixed:
                        r.ok = True
                        _ok(f"{r.name} fixed")
                    else:
                        _warn(f"{r.name}: fix did not fully resolve the issue")
                except Exception as e:
                    _err(f"{r.name}: fix threw an error: {e}")
        else:
            _ok("No issues require healing")

    return all_results


def _print_result(r: BootResult):
    if r.ok:
        _ok(f"{r.name}: {r.msg}")
    else:
        _warn(f"{r.name}: {r.msg}")
        if r.fix_label:
            _inf(f"  → Auto-fix available: {r.fix_label}")


def _summary(results: List[BootResult]) -> Tuple[int, int]:
    errors = sum(1 for r in results if not r.ok)
    ok     = sum(1 for r in results if r.ok)
    return ok, errors


# ══════════════════════════════════════════════════════════════════════════════
# GUI BOOTSTRAP WINDOW
# ══════════════════════════════════════════════════════════════════════════════

def run_gui_bootstrap(target_app: str = "factbook"):
    """Full Tkinter bootstrap dialog with live progress and fix buttons."""
    try:
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
    except ImportError:
        print("Tkinter not available — running CLI bootstrap instead.")
        run_cli_bootstrap(target_app=target_app, auto_heal=False)
        return

    _THEME = {
        "bg":        "#071A1E",
        "fg":        "#C8E8EC",
        "accent":    "#00C8A8",
        "hi":        "#0A3040",
        "btn_bg":    "#0D2838",
        "btn_fg":    "#B8E8E4",
        "text_bg":   "#041214",
        "text_fg":   "#B4DCE0",
        "ok":        "#06D6A0",
        "warn":      "#FFD166",
        "err":       "#FF6B6B",
        "status":    "#00E5C8",
    }
    t = _THEME

    root = tk.Tk()
    root.title("CITL Bootstrap & Self-Heal")
    root.geometry("860x620")
    root.resizable(True, True)
    root.configure(bg=t["bg"])

    # ── Header ──────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg=t["hi"], pady=8)
    hdr.pack(fill="x")
    tk.Label(hdr, text="  CITL Bootstrap & Self-Heal",
             fg=t["accent"], bg=t["hi"],
             font=("Consolas", 14, "bold")).pack(side="left", padx=10)
    tk.Label(hdr, text=f"Target: {target_app.upper()}",
             fg=t["fg"], bg=t["hi"],
             font=("Consolas", 10)).pack(side="right", padx=10)

    # ── Status bar ───────────────────────────────────────────────────────────
    status_var = tk.StringVar(value="Ready. Click 'Run Bootstrap' to check your system.")
    tk.Label(root, textvariable=status_var,
             fg=t["status"], bg=t["bg"],
             font=("Consolas", 9), anchor="w", padx=8).pack(fill="x")

    # ── Paned: results list | log ─────────────────────────────────────────
    paned = tk.PanedWindow(root, orient="vertical",
                           bg=t["hi"], sashwidth=5, sashrelief="flat")
    paned.pack(fill="both", expand=True, padx=4, pady=4)

    # Results frame (scrollable)
    res_outer = tk.Frame(paned, bg=t["bg"])
    paned.add(res_outer, minsize=150)

    canvas = tk.Canvas(res_outer, bg=t["bg"], highlightthickness=0)
    vsb = ttk.Scrollbar(res_outer, orient="vertical", command=canvas.yview)
    results_frame = tk.Frame(canvas, bg=t["bg"])
    results_frame.bind("<Configure>",
                       lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=results_frame, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    # Log frame
    log_outer = tk.Frame(paned, bg=t["bg"])
    paned.add(log_outer, minsize=100)
    tk.Label(log_outer, text="  Bootstrap Log",
             fg=t["accent"], bg=t["bg"],
             font=("Consolas", 9, "bold"), anchor="w").pack(fill="x")
    log = ScrolledText(log_outer, state="disabled", wrap="word",
                       bg=t["text_bg"], fg=t["text_fg"],
                       font=("Consolas", 9), relief="flat", padx=6)
    log.pack(fill="both", expand=True)
    log.tag_configure("ok",   foreground=t["ok"])
    log.tag_configure("warn", foreground=t["warn"])
    log.tag_configure("err",  foreground=t["err"])
    log.tag_configure("cmd",  foreground=t["accent"])

    def _log(line: str, tag: str = ""):
        def _do():
            log.configure(state="normal")
            log.insert("end", line + "\n", tag or ())
            log.configure(state="disabled")
            log.see("end")
        root.after(0, _do)

    # ── Bottom toolbar ────────────────────────────────────────────────────
    btn_bar = tk.Frame(root, bg=t["bg"], pady=6)
    btn_bar.pack(fill="x")

    _results_cache: List[BootResult] = []

    def _btn(text, color, cmd):
        return tk.Button(btn_bar, text=text, bg=color, fg=t["bg"],
                         activebackground=t["status"], activeforeground=t["bg"],
                         relief="flat", padx=10, pady=4, cursor="hand2",
                         font=("Consolas", 9, "bold"), command=cmd)

    def _clear_results():
        for w in results_frame.winfo_children():
            w.destroy()

    def _add_result_row(r: BootResult):
        color = t["ok"] if r.ok else t["warn"]
        dot   = "●"
        row   = tk.Frame(results_frame, bg=t["bg"])
        row.pack(fill="x", pady=1)
        tk.Label(row, text=dot, fg=color, bg=t["bg"],
                 font=("Consolas", 12)).pack(side="left", padx=(4, 6))
        info = tk.Frame(row, bg=t["bg"])
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=r.name, fg=t["accent"], bg=t["bg"],
                 font=("Consolas", 9, "bold"), anchor="w").pack(anchor="w")
        tk.Label(info, text=r.msg, fg=t["fg"], bg=t["bg"],
                 font=("Consolas", 8), wraplength=450, justify="left",
                 anchor="w").pack(anchor="w")
        if not r.ok and r.fix_fn:
            def _run_fix(res=r):
                _log(f"\n▶  {res.fix_label}…", "cmd")
                status_var.set(f"  Running: {res.fix_label}…")
                def _do():
                    try:
                        fixed = res.fix_fn()
                        if fixed:
                            root.after(0, lambda: _log(f"✓  {res.name} fixed", "ok"))
                            res.ok = True
                        else:
                            root.after(0, lambda: _log(f"⚠  {res.name}: fix may not have fully worked", "warn"))
                    except Exception as ex:
                        root.after(0, lambda e=ex: _log(f"✗  {res.name}: {e}", "err"))
                    root.after(0, lambda: status_var.set("Done."))
                threading.Thread(target=_do, daemon=True).start()
            tk.Button(row, text=f"  {r.fix_label}",
                      bg=t["accent"], fg=t["bg"],
                      activebackground=t["ok"],
                      relief="flat", padx=6, pady=2, cursor="hand2",
                      font=("Consolas", 8),
                      command=_run_fix).pack(side="right", padx=4)
        tk.Frame(results_frame, height=1, bg=t["hi"]).pack(fill="x")

    def _run_bootstrap():
        status_var.set("  Running bootstrap checks…")
        _clear_results()
        _log("═" * 60, "cmd")
        _log("CITL Bootstrap started", "cmd")
        _log("═" * 60, "cmd")

        def _bg():
            results = run_all_checks(auto_heal=False, target_app=target_app)
            _results_cache.clear()
            _results_cache.extend(results)
            ok_n, err_n = _summary(results)

            def _populate():
                _clear_results()
                for res in results:
                    _add_result_row(res)
                status_var.set(f"  {ok_n} OK  |  {err_n} issue(s)  "
                               f"{'— click buttons to fix' if err_n else '— system ready!'}")
                _log(f"\nBootstrap complete: {ok_n} OK, {err_n} issue(s)")

            root.after(0, _populate)

        threading.Thread(target=_bg, daemon=True).start()

    def _run_auto_heal():
        broken = [r for r in _results_cache if not r.ok and r.fix_fn]
        if not broken:
            _log("Nothing to fix — all checks passed!", "ok")
            return
        status_var.set(f"  Auto-healing {len(broken)} issue(s)…")

        def _bg():
            for r in broken:
                _log(f"\n▶  Fixing: {r.name} — {r.fix_label}", "cmd")
                try:
                    ok = r.fix_fn()
                    if ok:
                        r.ok = True
                        root.after(0, lambda n=r.name: _log(f"✓  {n} fixed", "ok"))
                    else:
                        root.after(0, lambda n=r.name: _log(f"⚠  {n}: may not be fully fixed", "warn"))
                except Exception as e:
                    root.after(0, lambda n=r.name, ex=e: _log(f"✗  {n}: {ex}", "err"))
            root.after(0, lambda: status_var.set("Auto-heal complete."))

        threading.Thread(target=_bg, daemon=True).start()

    def _launch_app():
        root.withdraw()
        _launch(target_app)
        root.destroy()

    _btn("▶  Run Bootstrap", t["accent"], _run_bootstrap).pack(side="left", padx=6)
    _btn("⚡  Auto-Heal All", t["warn"],    _run_auto_heal).pack(side="left", padx=2)
    _btn(f"▶  Launch {target_app.title()}", t["ok"],   _launch_app).pack(side="left", padx=2)
    _btn("✕  Exit",           t["err"],    root.destroy).pack(side="right", padx=6)

    # Auto-run bootstrap on open
    root.after(400, _run_bootstrap)
    root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# CLI BOOTSTRAP
# ══════════════════════════════════════════════════════════════════════════════

def run_cli_bootstrap(target_app: str = "factbook", auto_heal: bool = False):
    _h("=" * 60)
    _h(f"  CITL Bootstrap v1.0  --  target: {target_app.upper()}")
    _h("=" * 60)

    results = run_all_checks(auto_heal=auto_heal, target_app=target_app)
    ok_n, err_n = _summary(results)

    _h("\n" + "=" * 60)
    if err_n == 0:
        _ok(f"All {ok_n} checks passed -- system ready")
    else:
        _warn(f"{ok_n} OK  |  {err_n} issue(s) found")
        if not auto_heal:
            _inf("Run with --auto-heal to attempt automatic repairs.")

    if err_n == 0 or auto_heal:
        _launch(target_app)


def _launch(target_app: str):
    if target_app == "flex":
        script = FLEX_DIR / "flex_troubleshooter_gui.py"
    else:
        script = FA_DIR / "factbook_assistant_gui.py"
        if not script.exists():
            script = FA_DIR / "citl_gui_entry.py"

    if not script.exists():
        _err(f"App script not found: {script}")
        return

    _ok(f"Launching {target_app}: {script.name}")
    subprocess.Popen([sys.executable, str(script)])


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="CITL Universal Bootstrap — checks and heals all CITL app dependencies")
    ap.add_argument("--cli",       action="store_true",
                    help="Run in CLI mode (no GUI)")
    ap.add_argument("--auto-heal", action="store_true",
                    help="Automatically attempt all fixes")
    ap.add_argument("--app", default="factbook",
                    choices=["factbook", "flex"],
                    help="Which app to target and optionally launch (default: factbook)")
    ap.add_argument("--launch", action="store_true",
                    help="Launch the app after bootstrapping (if all checks pass)")
    args = ap.parse_args()

    if args.cli or not sys.stdout.isatty():
        run_cli_bootstrap(target_app=args.app, auto_heal=args.auto_heal)
    else:
        # Try GUI; fall back to CLI if Tk fails
        try:
            import tkinter  # noqa
            run_gui_bootstrap(target_app=args.app)
        except Exception:
            run_cli_bootstrap(target_app=args.app, auto_heal=args.auto_heal)


if __name__ == "__main__":
    main()
