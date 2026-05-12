#!/usr/bin/env python3
"""
citl_fixer.py  —  CITL Fixer  |  USB Repair & Launch Station  (Ubuntu 24 LTS)
══════════════════════════════════════════════════════════════════════════════
Comprehensive GUI that runs directly from the USB drive.

Covers every known failure mode for Ubuntu deployments:
  • numpy / Python packages missing
  • Ollama not running or wrong host
  • Missing / corrupt embedding JSON
  • Windows config paths left in citl_config.json / data/config.json
  • Duplicate or malformed JSONL index files
  • TTK theme / scrollbar layout errors (from Windows builds)
  • Index empty or < threshold
  • Pre-query regex / text-extraction failures
  • FFmpeg missing
  • Disk space

Usage
─────
    python3 citl_fixer.py           # auto-detect GUI / CLI
    python3 citl_fixer.py --cli     # terminal-only
    bash "CITL Fixer.sh"            # via launcher
    (double-click) CITL Fixer.desktop
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import ctypes
import glob
import signal
import struct
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# ── Locate USB root (where THIS file lives) ────────────────────────────────────
USB_ROOT  = Path(__file__).resolve().parent
FA_DIR    = USB_ROOT / "factbook-assistant"
SCRIPTS   = USB_ROOT / "scripts"
DIST      = USB_ROOT / "dist"
IS_WIN    = platform.system() == "Windows"
IS_LINUX  = platform.system() == "Linux"
AUTO_PATCH_RUNNER_WIN = USB_ROOT / "PATCH_CITL_48H_AUTO_WINDOWS.cmd"
AUTO_PATCH_STATE = USB_ROOT / "bootstrap" / "citl_fixer_auto_patch_state.json"
AUTO_PATCH_MIN_INTERVAL_SEC = 20 * 60
LOGS_DIR = USB_ROOT / "logs"

# Make our modules importable
for _p in (str(FA_DIR), str(USB_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── CITL dark-teal theme ───────────────────────────────────────────────────────
T = {
    "bg":      "#04080F",  "fg":      "#C8E8EC",  "accent":  "#00C8A8",
    "hi":      "#071A1E",  "btn":     "#0D2838",   "btn_fg":  "#A8DCE8",
    "txt_bg":  "#020608",  "txt_fg":  "#A8D4DC",   "status":  "#00E5C8",
    "ok":      "#06D6A0",  "warn":    "#FFD166",   "err":     "#FF6B6B",
    "skip":    "#5A7080",  "panel":   "#071520",   "hl2":     "#0A3040",
}

# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASS (no external deps)
# ══════════════════════════════════════════════════════════════════════════════

class CheckResult:
    __slots__ = ("name", "ok", "msg", "fix_fn", "fix_label", "detail")
    def __init__(self, name: str, ok: bool, msg: str,
                 fix_fn=None, fix_label: str = "", detail: str = ""):
        self.name      = name
        self.ok        = ok
        self.msg       = msg
        self.fix_fn    = fix_fn
        self.fix_label = fix_label
        self.detail    = detail


# ══════════════════════════════════════════════════════════════════════════════
# SUBPROCESS HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _run(cmd: List[str], timeout: int = 180,
         log: Callable[[str], None] = print) -> Tuple[bool, str]:
    log(f"$ {' '.join(str(c) for c in cmd)}")
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace"
        )
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            log(f"  exit {r.returncode}: {out[:200]}")
        return r.returncode == 0, out
    except FileNotFoundError:
        log(f"  ERROR: command not found: {cmd[0]}")
        return False, f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        log("  ERROR: timed out")
        return False, "timed out"
    except Exception as e:
        log(f"  ERROR: {e}")
        return False, str(e)


def _maybe_run_windows_auto_patch(
    log: Callable[[str], None] = print,
    *,
    force: bool = False,
) -> bool:
    """Run CITL patch cadence from Fixer on Windows, throttled by a local stamp."""
    if not IS_WIN:
        return False
    if os.environ.get("CITL_DISABLE_AUTO_PATCH", "").strip() == "1":
        log("[AUTO-PATCH] disabled via CITL_DISABLE_AUTO_PATCH=1")
        return False
    if not AUTO_PATCH_RUNNER_WIN.exists():
        log(f"[AUTO-PATCH][WARN] runner not found: {AUTO_PATCH_RUNNER_WIN}")
        return False

    now_ts = time.time()
    if not force:
        try:
            if AUTO_PATCH_STATE.exists():
                data = json.loads(AUTO_PATCH_STATE.read_text(encoding="utf-8"))
                last_ts = float(data.get("last_run_ts") or 0.0)
                if last_ts > 0 and (now_ts - last_ts) < AUTO_PATCH_MIN_INTERVAL_SEC:
                    mins = int((AUTO_PATCH_MIN_INTERVAL_SEC - (now_ts - last_ts)) // 60)
                    log(f"[AUTO-PATCH] skipped (recent run). retry in ~{max(0, mins)} min.")
                    return False
        except Exception:
            pass

    log("[AUTO-PATCH] running PATCH_CITL_48H_AUTO_WINDOWS.cmd ...")
    ok, out = _run(
        ["cmd.exe", "/c", str(AUTO_PATCH_RUNNER_WIN)],
        timeout=1800,
        log=log,
    )
    try:
        AUTO_PATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
        AUTO_PATCH_STATE.write_text(
            json.dumps(
                {
                    "last_run_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "last_run_ts": now_ts,
                    "ok": bool(ok),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    if ok:
        log("[AUTO-PATCH] completed.")
    else:
        preview = (out or "").strip().splitlines()
        tail = preview[-1] if preview else "no output"
        log(f"[AUTO-PATCH][WARN] runner reported failure: {tail}")
    return ok


def _run_usb_clone_from_fixer(
    target_arg: str,
    *,
    source_arg: str = "auto",
    log: Callable[[str], None] = print,
) -> int:
    """Clone latest CITL repo payload to a replacement USB target."""
    if not IS_WIN:
        log("[CLONE][ERROR] USB clone shortcut is currently implemented for Windows only.")
        return 2
    cloner = USB_ROOT / "scripts" / "windows" / "citl_usb_repair_clone.py"
    if not cloner.exists():
        log(f"[CLONE][ERROR] Missing cloner script: {cloner}")
        return 2
    target_clean = (target_arg or "").strip() or "auto"
    source_clean = (source_arg or "").strip() or "auto"
    cmd = [
        sys.executable,
        str(cloner),
        "--action",
        "clone",
        "--source",
        source_clean,
        "--target",
        target_clean,
    ]
    log(f"[CLONE] launching: {' '.join(cmd)}")
    ok, _ = _run(cmd, timeout=7200, log=log)
    if ok:
        log(f"[CLONE] completed for target={target_clean}")
        return 0
    log(f"[CLONE][ERROR] failed for target={target_clean}")
    return 1


def _write_crash_log(prefix: str = "citl_fixer_crash") -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = LOGS_DIR / f"{prefix}_{stamp}.log"
    out.write_text(traceback.format_exc(), encoding="utf-8")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# OLLAMA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _ollama_api(timeout: float = 5.0) -> Tuple[bool, List[str]]:
    try:
        req = urllib.request.Request(_ollama_host() + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        models = [m["name"] for m in data.get("models", []) if isinstance(m, dict)]
        return True, models
    except Exception:
        return False, []


def _start_ollama(log: Callable[[str], None] = print) -> bool:
    log("Starting Ollama in background…")
    try:
        subprocess.Popen(["ollama", "serve"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(15):
            time.sleep(1)
            up, _ = _ollama_api(timeout=2)
            if up:
                log("  Ollama started successfully.")
                return True
        log("  ERROR: Ollama did not respond within 15 seconds.")
        return False
    except FileNotFoundError:
        log("  ERROR: 'ollama' not found. Install from https://ollama.com/download")
        return False
    except Exception as e:
        log(f"  ERROR: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def check_python() -> CheckResult:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 9)
    msg = f"Python {v.major}.{v.minor}.{v.micro}"
    if not ok:
        return CheckResult("Python version", False, f"{msg} — requires 3.9+")
    return CheckResult("Python version", True, msg)


def check_tkinter() -> CheckResult:
    try:
        import tkinter  # noqa
        return CheckResult("tkinter", True, "tkinter available")
    except ImportError:
        if IS_WIN:
            def _fix(log=print):
                log("Install/repair Python from python.org with Tcl/Tk enabled.")
                return False
            return CheckResult(
                "tkinter",
                False,
                "tkinter not found — GUI unavailable",
                fix_fn=_fix,
                fix_label="Repair Python install (include Tcl/Tk)",
                detail="Download and repair Python from https://www.python.org/downloads/windows/",
            )

        def _fix(log=print):
            ok, _ = _run(["sudo", "apt-get", "install", "-y", "python3-tk"], log=log)
            return ok
        return CheckResult("tkinter", False,
                           "tkinter not found — GUI unavailable",
                           fix_fn=_fix, fix_label="apt install python3-tk",
                           detail="sudo apt install python3-tk")


def check_numpy() -> CheckResult:
    try:
        import numpy  # noqa
        return CheckResult("numpy", True, f"numpy {numpy.__version__}")
    except ImportError:
        def _fix(log=print):
            ok, out = _run([sys.executable, "-m", "pip", "install",
                            "--quiet", "numpy"], log=log, timeout=120)
            if ok:
                log("  numpy installed successfully.")
            return ok
        return CheckResult("numpy", False,
                           "numpy not installed — embedding/vector search disabled",
                           fix_fn=_fix, fix_label="pip install numpy",
                           detail="pip3 install numpy")


def check_packages() -> List[CheckResult]:
    results = []
    pkgs = [
        ("requests", "requests", True),
        ("PIL",       "Pillow",  False),
        ("docx",      "python-docx", False),
        ("faster_whisper", "faster-whisper", False),
    ]
    for imp, pkg, required in pkgs:
        try:
            importlib.import_module(imp)
            results.append(CheckResult(f"pkg:{pkg}", True, f"{pkg} OK"))
        except ImportError:
            _pkg = pkg
            def _fix(p=_pkg, log=print):
                ok, _ = _run([sys.executable, "-m", "pip", "install",
                               "--quiet", p], log=log, timeout=120)
                return ok
            results.append(CheckResult(
                f"pkg:{pkg}", not required,
                f"{pkg} missing {'(required)' if required else '(optional)'}",
                fix_fn=_fix, fix_label=f"pip install {pkg}",
            ))
    return results


def check_ollama() -> List[CheckResult]:
    results = []
    host = _ollama_host()
    up, models = _ollama_api()
    if not up:
        def _fix(log=print): return _start_ollama(log)
        results.append(CheckResult("Ollama running", False,
                                   f"Ollama not reachable at {host}",
                                   fix_fn=_fix, fix_label="Start Ollama",
                                   detail=f"ollama serve   # or: systemctl start ollama"))
        results.append(CheckResult("LLM model",   False, "Cannot check — Ollama offline"))
        results.append(CheckResult("Embed model", False, "Cannot check — Ollama offline"))
        return results

    results.append(CheckResult("Ollama running", True,
                               f"Ollama at {host} — {len(models)} model(s)"))

    _LLM = ["mistral", "llama3", "phi3", "gemma", "olmo", "citl-custom"]
    has_llm = any(any(w in m for w in _LLM) for m in models)
    if not has_llm:
        def _pull_llm(log=print):
            ok, _ = _run(["ollama", "pull", "mistral:7b-instruct"],
                         timeout=900, log=log)
            return ok
        results.append(CheckResult("LLM model", False, "No usable LLM installed",
                                   fix_fn=_pull_llm, fix_label="Pull mistral:7b-instruct"))
    else:
        best = next((m for m in models if any(w in m for w in _LLM)), models[0])
        results.append(CheckResult("LLM model", True, f"LLM: {best}"))

    _EMB = ["nomic-embed-text", "mxbai-embed-large"]
    has_emb = any(any(e in m for e in _EMB) for m in models)
    if not has_emb:
        def _pull_emb(log=print):
            ok, _ = _run(["ollama", "pull", "nomic-embed-text"],
                         timeout=600, log=log)
            return ok
        results.append(CheckResult("Embed model", False,
                                   "nomic-embed-text not installed",
                                   fix_fn=_pull_emb,
                                   fix_label="Pull nomic-embed-text"))
    else:
        results.append(CheckResult("Embed model", True, "nomic-embed-text available"))

    return results


def check_ffmpeg() -> CheckResult:
    if shutil.which("ffmpeg"):
        return CheckResult("FFmpeg", True, "FFmpeg on PATH")
    for p in [USB_ROOT / "bin" / "ffmpeg", FA_DIR / "bin" / "ffmpeg"]:
        if p.exists():
            return CheckResult("FFmpeg", True, f"Bundled FFmpeg: {p.name}")
    def _fix(log=print):
        ok, _ = _run(["sudo", "apt-get", "install", "-y", "ffmpeg"],
                     log=log, timeout=180)
        return ok
    return CheckResult("FFmpeg", True,
                       "FFmpeg not found (optional — audio features limited)",
                       fix_fn=_fix, fix_label="apt install ffmpeg")


def check_disk() -> CheckResult:
    try:
        free_gb = shutil.disk_usage(str(USB_ROOT)).free / 1e9
        if free_gb < 0.5:
            return CheckResult("Disk space", False,
                               f"Only {free_gb:.1f} GB free — critically low!")
        if free_gb < 2.0:
            return CheckResult("Disk space", False,
                               f"{free_gb:.1f} GB free — low (models need ~4 GB)")
        return CheckResult("Disk space", True, f"{free_gb:.1f} GB free")
    except Exception as e:
        return CheckResult("Disk space", True, f"Cannot check: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# FACTBOOK INSTANCE CHECKS  (Ubuntu-specific issues)
# ══════════════════════════════════════════════════════════════════════════════

# ── Any CITL app presence on this machine triggers discovery ─────────────────
_CITL_MARKERS = [
    # Core fixer / bootstrap
    "citl_fixer.py",
    "citl_bootstrap.py",
    # Factbook / RAG assistant
    "factbook-assistant/factbook_assistant_gui.py",
    "factbook_assistant_gui.py",
    "factbook-assistant/citl_factbook_diagnostic.py",
    # Troubleshooter / repair
    "citl_repair_all.py",
    "factbook-assistant/citl_repair_all.py",
    # Staff tools / workstation / LLMOps
    "citl_staff_toolkit.py",
    "factbook-assistant/citl_staff_toolkit.py",
    "citl_workstation_apps.py",
    "factbook-assistant/citl_workstation_apps.py",
    "citl_llmops_suite.py",
    "factbook-assistant/citl_llmops_suite.py",
    # Screen recorder
    "citl_screen_recorder.py",
    "factbook-assistant/citl_screen_recorder.py",
    # Academic advisor
    "citl_academic_advisor.py",
    "factbook-assistant/citl_academic_advisor.py",
]

_SKIP_DIRS = {"__pycache__", ".git", ".venv", "node_modules",
              "System Volume Information", "$Recycle.Bin", "Windows",
              "Program Files", "Program Files (x86)"}


def _is_citl_root(p: Path) -> bool:
    return any((p / m).exists() for m in _CITL_MARKERS)


def _discover_citl_installs() -> List[Path]:
    """Search common locations for ANY CITL app install (not just factbook)."""
    candidates: List[Path] = []
    seen: set = set()

    # Windows-specific roots (drive letters A-Z)
    win_roots: List[Path] = []
    if IS_WIN:
        import string
        for letter in string.ascii_uppercase:
            d = Path(letter + ":\\")
            if d.exists():
                win_roots.append(d)

    search_roots: List[Path] = list(dict.fromkeys([
        USB_ROOT,
        USB_ROOT.parent,
        Path.home(),
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        # Linux mount points
        Path("/media"),
        Path("/mnt"),
        Path("/opt"),
        Path("/srv"),
        Path("/home"),
    ] + win_roots))

    def _add(p: Path):
        try:
            k = str(p.resolve())
        except OSError:
            return
        if k not in seen:
            seen.add(k)
            candidates.append(p)

    for sr in search_roots:
        if not sr.is_dir():
            continue
        if _is_citl_root(sr):
            _add(sr)
        try:
            for child in sr.iterdir():
                if not child.is_dir() or child.name in _SKIP_DIRS:
                    continue
                if _is_citl_root(child):
                    _add(child)
                try:
                    for gc in child.iterdir():
                        if gc.is_dir() and gc.name not in _SKIP_DIRS and _is_citl_root(gc):
                            _add(gc)
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError):
            pass

    # Always include USB_ROOT itself even if no markers found yet
    if not any(str(c.resolve()) == str(USB_ROOT.resolve()) for c in candidates):
        candidates.insert(0, USB_ROOT)
    return candidates


# Legacy alias kept so old call-sites still work
def _all_factbook_roots() -> List[Path]:
    return _discover_citl_installs()


def check_config_paths(fb_root: Path) -> CheckResult:
    """Detect Windows-style absolute paths left in config files."""
    cfg_paths = [
        fb_root / "factbook-assistant" / "data" / "config.json",
        fb_root / "factbook-assistant" / "citl_config.json",
        fb_root / "data" / "config.json",
    ]
    broken: List[Tuple[Path, str]] = []
    for cp in cfg_paths:
        if not cp.exists():
            continue
        try:
            raw = cp.read_text(encoding="utf-8", errors="replace")
            if re.search(r'[A-Z]:\\', raw) or re.search(r'[A-Z]:/', raw):
                broken.append((cp, raw))
        except Exception:
            pass

    if not broken:
        return CheckResult("Config paths", True, "No Windows paths in config files")

    def _fix(log=print):
        fixed_any = False
        for cp, raw in broken:
            try:
                # Reset problematic Windows-only keys
                data = json.loads(raw)
                changed = False
                for key in ("modelfile_path", "audio_in_device",
                            "audio_device_id", "audio_device_name"):
                    if key in data and (
                        isinstance(data[key], str) and
                        re.search(r'[A-Z]:[/\\]', data[key])
                    ):
                        data[key] = ""
                        changed = True
                        log(f"  Cleared Windows path in {cp.name}: {key}")
                if changed:
                    cp.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    fixed_any = True
                    log(f"  Saved: {cp}")
            except Exception as e:
                log(f"  WARN: could not fix {cp}: {e}")
        return fixed_any

    names = ", ".join(p.name for p, _ in broken)
    return CheckResult("Config paths", False,
                       f"Windows paths found in: {names}",
                       fix_fn=_fix, fix_label="Clear Windows paths from config",
                       detail="\n".join(str(p) for p, _ in broken))


def check_index_health(fb_root: Path) -> List[CheckResult]:
    """Check JSONL index integrity — duplicates, tiny chunks, corruption."""
    results = []
    fa = fb_root / "factbook-assistant"
    idx_dir = fa / "data" / "indexes" if fa.is_dir() else fb_root / "data" / "indexes"

    if not idx_dir.is_dir():
        return [CheckResult("Index dir", False, f"Not found: {idx_dir}",
                            detail=f"mkdir -p {idx_dir}")]

    jsonl_files = list(idx_dir.glob("*.jsonl"))
    if not jsonl_files:
        return [CheckResult("Index chunks", False, "No .jsonl index files found",
                            detail=f"Re-run: python3 {fa}/build_factbook_index.py")]

    # Detect duplicate source files (same source name, different filename encoding)
    by_source: dict = {}
    for f in jsonl_files:
        if f.name.startswith("_"):
            continue
        # Normalise name: double underscores → single
        norm = re.sub(r'_{2,}', '_', f.stem)
        by_source.setdefault(norm, []).append(f)

    dupes = {k: v for k, v in by_source.items() if len(v) > 1}
    if dupes:
        def _fix_dupes(log=print):
            for norm_name, files in dupes.items():
                # Keep the file with the most lines
                best = max(files, key=lambda f: sum(
                    1 for _ in f.open(encoding="utf-8", errors="ignore")))
                for f in files:
                    if f != best:
                        try:
                            bak = f.with_suffix(".jsonl.dedup_bak")
                            f.rename(bak)
                            log(f"  Moved duplicate: {f.name} → {bak.name}")
                        except Exception as e:
                            log(f"  WARN: {f.name}: {e}")
            return True

        dupe_names = "; ".join(f"{k}: {len(v)} copies" for k, v in dupes.items())
        results.append(CheckResult("Index duplicates", False,
                                   f"Duplicate index files: {dupe_names}",
                                   fix_fn=_fix_dupes, fix_label="Remove duplicate indexes",
                                   detail=dupe_names))
    else:
        results.append(CheckResult("Index duplicates", True, "No duplicate index files"))

    # Count total chunks
    total = 0
    tiny: List[Path] = []
    for f in jsonl_files:
        if f.name.startswith("_"):
            continue
        try:
            n = sum(1 for ln in f.open(encoding="utf-8", errors="ignore")
                    if ln.strip() and not ln.strip().startswith("//"))
            total += n
            if 0 < n < 10:
                tiny.append(f)
        except Exception:
            pass

    if total < 100:
        fb_py = fa / "build_factbook_index.py"

        def _rebuild(log=print):
            if fb_py.exists():
                ok, _ = _run([sys.executable, str(fb_py)], timeout=600, log=log)
                return ok
            log(f"  build_factbook_index.py not found at {fb_py}")
            return False

        results.append(CheckResult("Index chunks", False,
                                   f"Only {total} chunks — needs rebuild",
                                   fix_fn=_rebuild, fix_label="Rebuild factbook index",
                                   detail=f"python3 {fb_py}"))
    else:
        results.append(CheckResult("Index chunks", True,
                                   f"{total:,} total chunks across {len(jsonl_files)} files"))

    if tiny:
        tiny_names = ", ".join(f.name for f in tiny)
        results.append(CheckResult("Tiny indexes", False,
                                   f"Under-indexed files (<10 chunks): {tiny_names}",
                                   detail="These files may need re-indexing"))
    return results


def check_embedding_json(fb_root: Path) -> CheckResult:
    fa = fb_root / "factbook-assistant"
    emb = (fa if fa.is_dir() else fb_root) / "factbook_embeddings.json"
    if not emb.exists():
        return CheckResult("Embedding JSON", True,
                           "factbook_embeddings.json absent (keyword search still works)")
    try:
        data = json.loads(emb.read_text(encoding="utf-8"))
        n = len(data.get("chunks", data.get("embeddings", [])))
        if n < 5:
            def _fix(log=print):
                emb.unlink(missing_ok=True)
                script = (fa if fa.is_dir() else fb_root) / "build_factbook_index.py"
                if script.exists():
                    ok, _ = _run([sys.executable, str(script)], timeout=600, log=log)
                    return ok
                log(f"  build_factbook_index.py not found")
                return False

            return CheckResult("Embedding JSON", False,
                               f"Corrupt or empty ({n} entries)",
                               fix_fn=_fix, fix_label="Delete & rebuild embeddings")
        return CheckResult("Embedding JSON", True, f"{n:,} embedding vectors")
    except Exception as e:
        def _fix2(log=print):
            emb.unlink(missing_ok=True)
            log(f"  Deleted corrupt {emb.name}")
            return True

        return CheckResult("Embedding JSON", False,
                           f"Corrupt JSON: {e}",
                           fix_fn=_fix2, fix_label="Delete corrupt embeddings file")


def check_ttk_theme(fb_root: Path) -> CheckResult:
    """Detect and fix Windows-only TTK theme references left in Python files."""
    fa = fb_root / "factbook-assistant"
    search_dir = fa if fa.is_dir() else fb_root
    bad_files: List[Path] = []
    pattern = re.compile(
        r'(?:Suite|Custom)\.(TScrollbar|TButton|TEntry|TLabel|TFrame|TNotebook)',
        re.IGNORECASE
    )
    for py_file in search_dir.glob("*.py"):
        try:
            txt = py_file.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(txt):
                bad_files.append(py_file)
        except Exception:
            pass

    if not bad_files:
        return CheckResult("TTK theme refs", True,
                           "No Windows-only TTK theme references found")

    def _fix(log=print):
        fixed = []
        for f in bad_files:
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
                # Replace "Suite.TScrollbar" etc. with plain "TScrollbar"
                new = pattern.sub(lambda m: m.group(1), txt)
                if new != txt:
                    bak = f.with_suffix(".py.ttk_bak")
                    shutil.copy2(f, bak)
                    f.write_text(new, encoding="utf-8")
                    log(f"  Fixed TTK refs in: {f.name}  (backup: {bak.name})")
                    fixed.append(f.name)
            except Exception as e:
                log(f"  WARN: {f.name}: {e}")
        return bool(fixed)

    names = ", ".join(f.name for f in bad_files)
    return CheckResult("TTK theme refs", False,
                       f"Windows TTK theme refs in: {names}",
                       fix_fn=_fix, fix_label="Patch TTK theme references",
                       detail="Removes 'Suite.' / 'Custom.' prefix from ttk widget names")


def check_ollama_live_embed(log: Callable[[str], None] = print) -> CheckResult:
    """Perform a live embedding call to verify the pipeline end-to-end."""
    up, models = _ollama_api()
    if not up:
        return CheckResult("Embed live test", False,
                           "Ollama offline — cannot test embeddings")
    emb_model = next((m for m in models
                      if "nomic-embed" in m or "mxbai-embed" in m), None)
    if not emb_model:
        return CheckResult("Embed live test", False,
                           "No embedding model installed",
                           detail="ollama pull nomic-embed-text")
    try:
        payload = json.dumps({
            "model": emb_model, "prompt": "CITL self-test"
        }).encode()
        req = urllib.request.Request(
            _ollama_host() + "/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        vec = data.get("embedding", [])
        if not vec or len(vec) < 8:
            return CheckResult("Embed live test", False,
                               f"Empty/short vector ({len(vec)} dims)")
        return CheckResult("Embed live test", True,
                           f"Live embed OK — {len(vec)}-dim vector from {emb_model}")
    except Exception as e:
        return CheckResult("Embed live test", False, f"Embed call failed: {e}",
                           detail=traceback.format_exc(limit=4))


def check_regex_prequery(fb_root: Path) -> CheckResult:
    """Check that the query/search pipeline imports cleanly (no regex compile errors)."""
    fa = fb_root / "factbook-assistant"
    search_dir = fa if fa.is_dir() else fb_root
    problem_modules = []
    for mod_name in ("query_factbook", "query_router", "citl_factbook_diagnostic",
                     "citl_auto_index", "parsers"):
        mod_file = search_dir / f"{mod_name}.py"
        if not mod_file.exists():
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"_citl_test_{mod_name}", mod_file)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        except SyntaxError as e:
            problem_modules.append(f"{mod_name}.py: SyntaxError line {e.lineno}")
        except re.error as e:
            problem_modules.append(f"{mod_name}.py: bad regex — {e}")
        except Exception:
            pass  # import-time side effects are expected; only catch compile errors

    if problem_modules:
        detail = "\n".join(problem_modules)
        return CheckResult("Pre-query modules", False,
                           f"{len(problem_modules)} module(s) have errors",
                           detail=detail)
    return CheckResult("Pre-query modules", True, "Query pipeline modules OK")


# ══════════════════════════════════════════════════════════════════════════════
# EXPANDED SYSTEM-LEVEL CHECKS  —  Professional IT diagnostic suite
# Every check that can cause ANY CITL app to fail, with a fix action.
# ══════════════════════════════════════════════════════════════════════════════

# ── Hardware & OS ─────────────────────────────────────────────────────────────

def check_ram() -> CheckResult:
    try:
        if IS_WIN:
            import ctypes as _ct
            class _MEM(_ct.Structure):
                _fields_ = [("dwLength", _ct.c_ulong), ("dwMemoryLoad", _ct.c_ulong),
                             ("ullTotalPhys", _ct.c_ulonglong), ("ullAvailPhys", _ct.c_ulonglong),
                             ("ullTotalPageFile", _ct.c_ulonglong), ("ullAvailPageFile", _ct.c_ulonglong),
                             ("ullTotalVirtual", _ct.c_ulonglong), ("ullAvailVirtual", _ct.c_ulonglong),
                             ("ullAvailExtendedVirtual", _ct.c_ulonglong)]
            m = _MEM(); m.dwLength = _ct.sizeof(_MEM)
            _ct.windll.kernel32.GlobalMemoryStatusEx(_ct.byref(m))
            total_gb = m.ullTotalPhys / 1e9
            avail_gb = m.ullAvailPhys / 1e9
        else:
            with open("/proc/meminfo") as f:
                info = {k.strip(): int(v.split()[0])
                        for k, v in (l.split(":", 1) for l in f if ":" in l)}
            total_gb = info.get("MemTotal", 0) / 1e6
            avail_gb = info.get("MemAvailable", info.get("MemFree", 0)) / 1e6
        if avail_gb < 1.0:
            return CheckResult("RAM available", False,
                               f"{avail_gb:.1f} GB free / {total_gb:.1f} GB total — critically low",
                               detail="Close all unused applications before running CITL apps.")
        if avail_gb < 4.0:
            return CheckResult("RAM available", False,
                               f"{avail_gb:.1f} GB free — low (Ollama needs >=4 GB)",
                               detail="Close Chrome/VS Code/Teams before running Ollama models.")
        return CheckResult("RAM available", True,
                           f"{avail_gb:.1f} GB free / {total_gb:.1f} GB total")
    except Exception as e:
        return CheckResult("RAM available", True, f"Cannot check RAM: {e}")


def check_gpu() -> CheckResult:
    try:
        ok, out = _run(["nvidia-smi",
                        "--query-gpu=name,memory.total,memory.free",
                        "--format=csv,noheader,nounits"], timeout=10)
        if ok and out.strip():
            msgs = []
            for line in out.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    try:
                        msgs.append(f"{parts[0]}  {int(parts[2])//1024:.1f} GB VRAM free")
                    except ValueError:
                        msgs.append(parts[0])
            if msgs:
                return CheckResult("GPU (NVIDIA)", True, " | ".join(msgs))
    except FileNotFoundError:
        pass
    try:
        ok2, out2 = _run(["rocm-smi", "--showmeminfo", "vram"], timeout=10)
        if ok2 and "GPU" in out2:
            return CheckResult("GPU (AMD ROCm)", True, "AMD GPU detected via rocm-smi")
    except FileNotFoundError:
        pass
    return CheckResult("GPU", True,
                       "No discrete GPU — CPU-only inference (functional but slower)")


def check_python_arch() -> CheckResult:
    bits = struct.calcsize("P") * 8
    if bits < 64:
        def _fix(log=print):
            log("  Install 64-bit Python 3.9+ from https://python.org/downloads")
            return False
        return CheckResult("Python arch", False,
                           f"{bits}-bit Python — AI/audio packages require 64-bit",
                           fix_fn=_fix, fix_label="Install 64-bit Python",
                           detail="Download 64-bit installer from python.org")
    return CheckResult("Python arch", True, f"64-bit Python  ({sys.executable})")


def check_locale_encoding() -> CheckResult:
    enc = sys.getdefaultencoding()
    if enc.lower().replace("-", "") != "utf8":
        def _fix(log=print):
            log("  Add PYTHONUTF8=1 to your environment variables.")
            return False
        return CheckResult("Encoding", False,
                           f"Default encoding '{enc}' — must be UTF-8 for CITL files",
                           fix_fn=_fix, fix_label="Set PYTHONUTF8=1",
                           detail="Add PYTHONUTF8=1 to system environment variables")
    return CheckResult("Encoding", True, "UTF-8 default encoding confirmed")


# ── Python / pip / venv ───────────────────────────────────────────────────────

def check_pip() -> CheckResult:
    ok, out = _run([sys.executable, "-m", "pip", "--version"], timeout=15)
    if not ok:
        def _fix(log=print):
            ok2, _ = _run([sys.executable, "-m", "ensurepip", "--upgrade"], log=log)
            return ok2
        return CheckResult("pip", False, "pip not working or missing",
                           fix_fn=_fix, fix_label="ensurepip --upgrade",
                           detail="python -m ensurepip --upgrade")
    m = re.search(r"pip (\S+)", out)
    return CheckResult("pip", True, f"pip {m.group(1) if m else '?'}")


def check_venv() -> CheckResult:
    sub = "Scripts" if IS_WIN else "bin"
    exe = "python.exe" if IS_WIN else "python"
    venv_py = USB_ROOT / ".venv" / sub / exe
    if not venv_py.exists():
        def _fix(log=print):
            ok, _ = _run([sys.executable, "-m", "venv", str(USB_ROOT / ".venv")],
                         timeout=120, log=log)
            if ok:
                log("  .venv created. Next: pip install -r requirements.txt")
            return ok
        return CheckResult(".venv", False,
                           f"USB .venv not found ({venv_py})",
                           fix_fn=_fix, fix_label="Create .venv on USB",
                           detail=f"python -m venv {USB_ROOT / '.venv'}")
    ok, out = _run([str(venv_py), "--version"], timeout=10)
    if not ok:
        return CheckResult(".venv", False, ".venv Python not responding — recreate it",
                           detail="Delete .venv folder and run: python -m venv .venv")
    return CheckResult(".venv", True, f"USB .venv OK  ({out.strip()})")


def check_requirements_installed() -> List[CheckResult]:
    req_files = [USB_ROOT / "requirements-base.txt", USB_ROOT / "requirements.txt"]
    req_file = next((r for r in req_files if r.exists()), None)
    if not req_file:
        return [CheckResult("requirements.txt", True, "No requirements file on USB (skipped)")]
    try:
        lines = req_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        pkgs = [l.strip() for l in lines
                if l.strip() and not l.startswith("#") and not l.startswith("-")]
    except Exception as e:
        return [CheckResult("requirements.txt", True, f"Cannot read: {e}")]
    missing = []
    for pkg in pkgs[:30]:
        name = re.split(r"[>=<!;\[]", pkg)[0].strip().lower().replace("-", "_")
        if not name:
            continue
        try:
            importlib.import_module(name)
        except ImportError:
            try:
                importlib.import_module(name.replace("_", "-"))
            except ImportError:
                missing.append(pkg)
    if missing:
        def _fix(log=print, _f=req_file):
            ok, _ = _run([sys.executable, "-m", "pip", "install",
                          "--quiet", "-r", str(_f)], log=log, timeout=300)
            return ok
        return [CheckResult("requirements.txt", False,
                            f"{len(missing)} pkg(s) missing: {', '.join(missing[:5])}{'...' if len(missing)>5 else ''}",
                            fix_fn=_fix, fix_label=f"pip install -r {req_file.name}",
                            detail="\n".join(missing))]
    return [CheckResult("requirements.txt", True, f"All {len(pkgs)} requirement(s) satisfied")]


# ── Network & Ports ───────────────────────────────────────────────────────────

def check_ollama_port() -> CheckResult:
    try:
        s = socket.create_connection(("127.0.0.1", 11434), timeout=3)
        s.close()
        return CheckResult("Ollama port 11434", True, "Port 11434 open (TCP)")
    except ConnectionRefusedError:
        def _fix(log=print): return _start_ollama(log)
        return CheckResult("Ollama port 11434", False,
                           "Port 11434 refused — Ollama not running",
                           fix_fn=_fix, fix_label="Start Ollama service",
                           detail="ollama serve")
    except OSError as e:
        return CheckResult("Ollama port 11434", False, f"Port 11434 unreachable: {e}")


def check_port_conflicts() -> List[CheckResult]:
    results = []
    for port, label in [(8080, "API/Advisor"), (8501, "Streamlit"),
                        (8502, "Streamlit-alt")]:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            results.append(CheckResult(f"Port {port}", True,
                                       f"Port {port} ({label}): service responding"))
        except (ConnectionRefusedError, OSError):
            results.append(CheckResult(f"Port {port}", True,
                                       f"Port {port} ({label}): free (no conflict)"))
    return results


# ── Platform: Windows ─────────────────────────────────────────────────────────

def check_powershell_policy() -> CheckResult:
    if not IS_WIN:
        return CheckResult("PowerShell policy", True, "N/A (not Windows)")
    try:
        ok, out = _run(
            ["powershell", "-NoProfile", "-Command", "Get-ExecutionPolicy"],
            timeout=10)
        policy = out.strip() if ok else "Unknown"
        if policy.lower() in ("restricted", "allsigned"):
            def _fix(log=print):
                ok2, _ = _run([
                    "powershell", "-NoProfile", "-Command",
                    "Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force"
                ], log=log, timeout=15)
                return ok2
            return CheckResult("PowerShell policy", False,
                               f"Policy '{policy}' — .ps1 launchers blocked",
                               fix_fn=_fix, fix_label="Set RemoteSigned (CurrentUser)",
                               detail="Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force")
        return CheckResult("PowerShell policy", True, f"PowerShell policy: {policy}")
    except Exception as e:
        return CheckResult("PowerShell policy", True, f"Cannot check: {e}")


def check_long_paths_windows() -> CheckResult:
    if not IS_WIN:
        return CheckResult("Long paths", True, "N/A (not Windows)")
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SYSTEM\CurrentControlSet\Control\FileSystem")
        val, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
        winreg.CloseKey(key)
        if val == 1:
            return CheckResult("Long paths (Win)", True, "LongPathsEnabled = 1")
        def _fix(log=print):
            try:
                import winreg as _wr
                k = _wr.OpenKey(_wr.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Control\FileSystem",
                                access=_wr.KEY_SET_VALUE)
                _wr.SetValueEx(k, "LongPathsEnabled", 0, _wr.REG_DWORD, 1)
                _wr.CloseKey(k)
                log("  LongPathsEnabled=1 (reboot to apply).")
                return True
            except PermissionError:
                log("  Requires Administrator. Run as Admin and retry.")
                return False
        return CheckResult("Long paths (Win)", False,
                           "LongPathsEnabled=0 — deep install paths may fail",
                           fix_fn=_fix, fix_label="Enable LongPaths (needs Admin)")
    except Exception as e:
        return CheckResult("Long paths (Win)", True, f"Cannot check: {e}")


def check_windows_defender_exclusion() -> CheckResult:
    if not IS_WIN:
        return CheckResult("Defender exclusion", True, "N/A (not Windows)")
    try:
        ok, out = _run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-MpPreference).ExclusionPath -join '|'"],
            timeout=12)
        if ok:
            excluded = [p.strip() for p in out.strip().split("|") if p.strip()]
            usb_str = str(USB_ROOT).lower()
            if any(usb_str.startswith(e.lower()) for e in excluded):
                return CheckResult("Defender exclusion", True,
                                   "USB path excluded from Defender scanning")
            def _fix(log=print):
                ok2, _ = _run([
                    "powershell", "-NoProfile", "-Command",
                    f"Add-MpPreference -ExclusionPath '{USB_ROOT}'"
                ], log=log, timeout=15)
                return ok2
            return CheckResult("Defender exclusion", False,
                               "USB not excluded — Defender may block/slow scripts",
                               fix_fn=_fix, fix_label="Add USB to Defender exclusions",
                               detail=f"Add-MpPreference -ExclusionPath '{USB_ROOT}'")
        return CheckResult("Defender exclusion", True,
                           "Cannot query Defender (non-admin) — skipped")
    except Exception as e:
        return CheckResult("Defender exclusion", True, f"Cannot check: {e}")


# ── Platform: Ubuntu ──────────────────────────────────────────────────────────

def check_display_server() -> CheckResult:
    if IS_WIN:
        return CheckResult("Display server", True, "N/A (Windows)")
    d = os.environ.get("DISPLAY", "")
    w = os.environ.get("WAYLAND_DISPLAY", "")
    if d or w:
        return CheckResult("Display server", True,
                           f"{'DISPLAY=' + d if d else 'WAYLAND_DISPLAY=' + w}")
    def _fix(log=print):
        log("  Run: export DISPLAY=:0  then re-launch from a graphical terminal.")
        return False
    return CheckResult("Display server", False,
                       "No DISPLAY or WAYLAND_DISPLAY — GUI cannot open",
                       fix_fn=_fix, fix_label="export DISPLAY=:0",
                       detail="export DISPLAY=:0  (run from a graphical terminal session)")


def check_apt_available() -> CheckResult:
    if IS_WIN:
        return CheckResult("apt-get", True, "N/A (Windows)")
    if shutil.which("apt-get"):
        return CheckResult("apt-get", True, "apt-get available")
    return CheckResult("apt-get", False,
                       "apt-get not found — package-install fix actions unavailable")


def check_systemd_ollama() -> CheckResult:
    if IS_WIN:
        return CheckResult("ollama.service", True, "N/A (Windows)")
    try:
        ok, out = _run(["systemctl", "is-active", "ollama"], timeout=8)
        state = out.strip()
        if state == "active":
            return CheckResult("ollama.service", True, "systemd ollama.service: active")
        def _fix(log=print):
            ok2, _ = _run(["sudo", "systemctl", "start", "ollama"], log=log, timeout=20)
            return ok2
        return CheckResult("ollama.service", False,
                           f"ollama.service: {state or 'not installed'}",
                           fix_fn=_fix, fix_label="systemctl start ollama",
                           detail="sudo systemctl start ollama")
    except FileNotFoundError:
        return CheckResult("ollama.service", True, "systemd not available (skipped)")


# ── App-Specific Dependencies ─────────────────────────────────────────────────

def check_screen_recorder_deps() -> List[CheckResult]:
    DEPS = [("mss",    "mss",           True),
            ("cv2",    "opencv-python",  True),
            ("pynput", "pynput",         False),
            ("pyaudio","PyAudio",        False)]
    results = []
    for imp, pkg, req in DEPS:
        try:
            importlib.import_module(imp)
            results.append(CheckResult(f"screen:{imp}", True, f"{pkg} OK"))
        except ImportError:
            _p = pkg
            def _fix(p=_p, log=print):
                ok, _ = _run([sys.executable, "-m", "pip", "install",
                               "--quiet", p], log=log, timeout=180)
                return ok
            results.append(CheckResult(f"screen:{imp}", req,
                                       f"{pkg} missing {'(required)' if req else '(optional)'}",
                                       fix_fn=_fix, fix_label=f"pip install {pkg}"))
    return results


def check_staff_toolkit_deps() -> List[CheckResult]:
    results = []
    try:
        importlib.import_module("requests")
        results.append(CheckResult("toolkit:requests", True, "requests OK"))
    except ImportError:
        def _fix(log=print):
            ok, _ = _run([sys.executable, "-m", "pip", "install",
                          "--quiet", "requests"], log=log, timeout=60)
            return ok
        results.append(CheckResult("toolkit:requests", True,
                                   "requests missing (optional for O365 SSO)",
                                   fix_fn=_fix, fix_label="pip install requests"))
    cfg = FA_DIR / "staff_toolkit_config.json"
    if cfg.exists():
        try:
            json.loads(cfg.read_text(encoding="utf-8"))
            results.append(CheckResult("toolkit:config", True,
                                       "staff_toolkit_config.json valid"))
        except json.JSONDecodeError as e:
            def _fix2(log=print, _c=cfg):
                _c.write_text("{}", encoding="utf-8")
                log(f"  Reset {_c.name} to empty config.")
                return True
            results.append(CheckResult("toolkit:config", False,
                                       f"staff_toolkit_config.json corrupt: {e}",
                                       fix_fn=_fix2, fix_label="Reset toolkit config"))
    return results


def check_workstation_app_deps() -> List[CheckResult]:
    if IS_WIN:
        have = bool(shutil.which("powershell") or shutil.which("powershell.exe"))
        return [CheckResult("workstation:ps1", have,
                            "powershell.exe " + ("available" if have
                                                 else "NOT FOUND — display tool will fail"))]
    if shutil.which("xrandr"):
        return [CheckResult("workstation:xrandr", True, "xrandr available")]
    def _fix(log=print):
        ok, _ = _run(["sudo", "apt-get", "install", "-y", "x11-xserver-utils"],
                     log=log, timeout=90)
        return ok
    return [CheckResult("workstation:xrandr", False,
                        "xrandr not found — display port detection limited",
                        fix_fn=_fix, fix_label="apt install x11-xserver-utils")]


def check_advisor_api_deps() -> List[CheckResult]:
    DEPS = [("fastapi", "fastapi", True),
            ("uvicorn", "uvicorn", True),
            ("httpx",   "httpx",   False)]
    results = []
    for imp, pkg, req in DEPS:
        try:
            importlib.import_module(imp)
            results.append(CheckResult(f"advisor:{imp}", True, f"{pkg} OK"))
        except ImportError:
            _p = pkg
            def _fix(p=_p, log=print):
                ok, _ = _run([sys.executable, "-m", "pip", "install",
                               "--quiet", p], log=log, timeout=90)
                return ok
            results.append(CheckResult(f"advisor:{imp}", req,
                                       f"{pkg} missing {'(required)' if req else '(optional)'}",
                                       fix_fn=_fix, fix_label=f"pip install {pkg}"))
    return results


def check_key_citl_scripts() -> List[CheckResult]:
    CRITICAL = [
        (USB_ROOT / "citl_fixer.py",               "Fixer"),
        (USB_ROOT / "citl_bootstrap.py",            "Bootstrap"),
        (USB_ROOT / "citl_patcher.py",              "Patcher"),
        (FA_DIR   / "factbook_assistant_gui.py",    "Factbook GUI"),
        (FA_DIR   / "citl_factbook_diagnostic.py",  "Diagnostic"),
        (FA_DIR   / "citl_repair_all.py",           "Repair All (Troubleshooter)"),
        (FA_DIR   / "citl_screen_recorder.py",      "Screen Recorder"),
        (FA_DIR   / "citl_staff_toolkit.py",        "Staff Toolkit"),
        (FA_DIR   / "citl_workstation_apps.py",     "Workstation Apps"),
        (FA_DIR   / "citl_llmops_suite.py",         "LLMOps Suite"),
        (FA_DIR   / "build_factbook_index.py",      "Index Builder"),
        (FA_DIR   / "query_factbook.py",            "Query Engine"),
        (FA_DIR   / "citl_heal.py",                 "Self-Heal"),
        (FA_DIR   / "citl_heal_panel.py",           "Heal Panel"),
    ]
    results = []
    for path, label in CRITICAL:
        if not path.exists():
            results.append(CheckResult(f"script:{label}", False,
                                       f"{label} — {path.name} NOT FOUND on USB",
                                       detail=f"Expected: {path}\nRe-sync from CITL repo."))
        elif path.stat().st_size < 100:
            results.append(CheckResult(f"script:{label}", False,
                                       f"{label} — {path.name} suspiciously small "
                                       f"({path.stat().st_size} B — may be truncated)",
                                       detail=f"Truncated file: {path}"))
        else:
            results.append(CheckResult(f"script:{label}", True,
                                       f"{label} OK  ({path.stat().st_size // 1024} KB)"))
    return results


# ── File System Integrity ─────────────────────────────────────────────────────

def check_usb_write_access() -> CheckResult:
    test_file = USB_ROOT / ".citl_write_test"
    try:
        test_file.write_bytes(b"ok")
        test_file.unlink()
        return CheckResult("USB write access", True, "USB drive is writable")
    except OSError as e:
        return CheckResult("USB write access", False,
                           f"USB appears write-protected: {e}",
                           detail="Check the physical write-protect switch on the USB drive.\n"
                                  "Re-format and re-sync if the switch is off.")


def check_json_config_integrity() -> List[CheckResult]:
    results = []
    for sdir in [USB_ROOT, FA_DIR / "data", FA_DIR]:
        if not sdir.is_dir():
            continue
        for jf in sdir.glob("*.json"):
            if jf.name.startswith(".") or jf.stat().st_size == 0:
                continue
            try:
                json.loads(jf.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError as e:
                _jf = jf
                def _fix(log=print, f=_jf):
                    bak = f.with_suffix(".json.corrupt_bak")
                    shutil.copy2(f, bak)
                    f.write_text("{}", encoding="utf-8")
                    log(f"  Reset {f.name} to {{}} (backup: {bak.name})")
                    return True
                results.append(CheckResult(f"json:{jf.name}", False,
                                           f"{jf.name} invalid JSON: {e}",
                                           fix_fn=_fix, fix_label=f"Reset {jf.name}"))
    if not results:
        results.append(CheckResult("JSON configs", True, "All JSON config files parse cleanly"))
    return results


def check_log_file_sizes() -> List[CheckResult]:
    results = []
    for ldir in [USB_ROOT / "logs", USB_ROOT / "recordings", FA_DIR]:
        if not ldir.is_dir():
            continue
        for lf in ldir.glob("*.log"):
            size_mb = lf.stat().st_size / 1e6
            if size_mb > 50:
                _lf = lf
                def _fix(log=print, f=_lf):
                    bak = f.with_suffix(
                        f".log.{datetime.now().strftime('%Y%m%d')}.bak")
                    f.rename(bak)
                    log(f"  Rotated {f.name} -> {bak.name}")
                    return True
                results.append(CheckResult(f"log:{lf.name}", False,
                                           f"{lf.name} is {size_mb:.0f} MB — should be rotated",
                                           fix_fn=_fix, fix_label=f"Rotate {lf.name}"))
    if not results:
        results.append(CheckResult("Log files", True, "No oversized log files"))
    return results


# ── Running Processes ─────────────────────────────────────────────────────────

def check_running_citl_processes() -> List[CheckResult]:
    results = []
    try:
        if IS_WIN:
            ok, out = _run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                timeout=10)
            if ok:
                count = sum(1 for l in out.splitlines() if "python" in l.lower())
                if count > 3:
                    results.append(CheckResult(
                        "Python processes", False,
                        f"{count} python.exe instances running — possible stuck processes",
                        detail="Open Task Manager and end unresponsive python.exe processes."))
                else:
                    results.append(CheckResult(
                        "Python processes", True,
                        f"{count} python.exe running (normal)"))
        else:
            ok, out = _run(["pgrep", "-a", "-f", "citl|factbook|ollama"], timeout=8)
            if ok and out.strip():
                procs = [l.strip() for l in out.strip().splitlines() if l.strip()]
                results.append(CheckResult("CITL processes", True,
                                           f"{len(procs)} CITL/Ollama process(es) running"))
            else:
                results.append(CheckResult("CITL processes", True,
                                           "No stuck CITL processes detected"))
    except Exception as e:
        results.append(CheckResult("CITL processes", True, f"Cannot check processes: {e}"))
    return results


# ── Git & Repo Health ─────────────────────────────────────────────────────────

def check_git() -> CheckResult:
    if shutil.which("git"):
        ok, out = _run(["git", "--version"], timeout=8)
        return CheckResult("git", True, out.strip() if ok else "git found")
    if IS_WIN:
        for p in [Path("C:/Program Files/Git/bin/git.exe"),
                  Path("C:/Program Files (x86)/Git/bin/git.exe")]:
            if p.exists():
                return CheckResult("git", True, f"git found at {p}")
        def _fix(log=print):
            log("  Install Git from: https://git-scm.com/download/win")
            return False
        return CheckResult("git", False,
                           "git not found — repo-age checks and USB clone disabled",
                           fix_fn=_fix, fix_label="Install Git for Windows",
                           detail="https://git-scm.com/download/win")
    def _fix_lin(log=print):
        ok, _ = _run(["sudo", "apt-get", "install", "-y", "git"], log=log, timeout=120)
        return ok
    return CheckResult("git", False, "git not found — install via apt",
                       fix_fn=_fix_lin, fix_label="apt install git")


def check_git_user_modified_dates() -> CheckResult:
    if not shutil.which("git"):
        return CheckResult("git log dates", True, "git not available — skipped")
    try:
        ok, out = _run(
            ["git", "-C", str(USB_ROOT), "log",
             "--format=%ai %ae", "--diff-filter=M", "-1", "--", "citl_fixer.py"],
            timeout=10)
        if ok and out.strip():
            parts = out.strip().split()
            date_str = f"{parts[0]} {parts[1]}" if len(parts) >= 2 else out.strip()
            author   = parts[3] if len(parts) >= 4 else "unknown"
            return CheckResult("git log dates", True,
                               f"citl_fixer.py last user commit: {date_str}  ({author})")
        return CheckResult("git log dates", True, "git log OK (no recent user commits)")
    except Exception as e:
        return CheckResult("git log dates", True, f"git log error: {e}")


def check_usb_repo_dirty() -> CheckResult:
    if not shutil.which("git"):
        return CheckResult("USB repo state", True, "git not available — skipped")
    try:
        ok, out = _run(
            ["git", "-C", str(USB_ROOT), "status", "--porcelain"], timeout=10)
        if ok:
            changed = [l for l in out.splitlines() if l.strip()]
            if changed:
                return CheckResult("USB repo state", False,
                                   f"{len(changed)} uncommitted change(s) on USB repo",
                                   detail="\n".join(changed[:10]))
            return CheckResult("USB repo state", True, "USB git repo: clean")
        return CheckResult("USB repo state", True, "Not a git repo (skipped)")
    except Exception as e:
        return CheckResult("USB repo state", True, f"Cannot check git status: {e}")


# ── Ollama Version ────────────────────────────────────────────────────────────

def check_ollama_version() -> CheckResult:
    if not shutil.which("ollama"):
        def _fix(log=print):
            if IS_WIN:
                log("  Download from: https://ollama.com/download/windows")
                return False
            ok, _ = _run(
                ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                timeout=300, log=log)
            return ok
        return CheckResult("Ollama binary", False, "ollama not found on PATH",
                           fix_fn=_fix, fix_label="Install Ollama",
                           detail="https://ollama.com/download")
    ok, out = _run(["ollama", "--version"], timeout=8)
    ver = out.strip() if ok else "?"
    m = re.search(r"(\d+)\.(\d+)", ver)
    if m and (int(m.group(1)), int(m.group(2))) < (0, 3):
        def _upd(log=print):
            if IS_WIN:
                log("  Download latest: https://ollama.com/download/windows")
                return False
            ok2, _ = _run(
                ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                timeout=300, log=log)
            return ok2
        return CheckResult("Ollama version", False,
                           f"{ver} — upgrade to >=0.3 for /api/embed support",
                           fix_fn=_upd, fix_label="Upgrade Ollama")
    return CheckResult("Ollama version", True, ver or "Ollama installed")


def patch_scripts(fb_root: Path, log: Callable[[str], None] = print) -> List[str]:
    """Copy the latest repair/heal scripts from this USB into the target install."""
    fa = fb_root / "factbook-assistant"
    dest = fa if fa.is_dir() else fb_root
    sources = [
        FA_DIR / "citl_factbook_diagnostic.py",
        FA_DIR / "citl_heal.py",
        FA_DIR / "citl_heal_panel.py",
        FA_DIR / "citl_rag_patch.py",
        USB_ROOT / "citl_bootstrap.py",
        USB_ROOT / "citl_fixer.py",
    ]
    patched = []
    for src in sources:
        if not src.exists():
            continue
        dst = dest / src.name
        try:
            shutil.copy2(src, dst)
            log(f"  Patched: {dst.name}")
            patched.append(dst.name)
        except Exception as e:
            log(f"  WARN: {src.name} → {dst}: {e}")
    log(f"Patch complete: {len(patched)} file(s) → {dest}")
    return patched


# ══════════════════════════════════════════════════════════════════════════════
# FULL CHECK SUITE
# ══════════════════════════════════════════════════════════════════════════════

def run_all_checks(fb_root: Optional[Path] = None,
                  log: Callable[[str], None] = print) -> List[CheckResult]:
    """Full IT-grade diagnostic across all CITL apps and system dependencies."""
    results: List[CheckResult] = []

    log("── Python Environment ──────────────────────────────")
    results += [check_python(), check_tkinter(), check_numpy()]
    results += check_packages()

    log("── System Hardware ─────────────────────────────────")
    results += [check_ram(), check_gpu(), check_python_arch(), check_locale_encoding()]

    log("── pip / venv / requirements ────────────────────────")
    results += [check_pip(), check_venv()]
    results += check_requirements_installed()

    log("── Ollama / Models ─────────────────────────────────")
    results += check_ollama()

    log("── Embedding Live Test ──────────────────────────────")
    results.append(check_ollama_live_embed(log))

    log("── Ollama Version ───────────────────────────────────")
    results += [check_ollama_version()]

    log("── Network & Ports ──────────────────────────────────")
    results += [check_ollama_port()]
    results += check_port_conflicts()

    log("── File System ─────────────────────────────────────")
    results += [check_disk(), check_ffmpeg()]

    log("── USB File Integrity ───────────────────────────────")
    results += [check_usb_write_access()]
    results += check_key_citl_scripts()
    results += check_json_config_integrity()
    results += check_log_file_sizes()

    log("── CITL App Dependencies ────────────────────────────")
    results += check_screen_recorder_deps()
    results += check_staff_toolkit_deps()
    results += check_workstation_app_deps()
    results += check_advisor_api_deps()

    log("── Running Processes ────────────────────────────────")
    results += check_running_citl_processes()

    log("── Git & Repo ───────────────────────────────────────")
    results += [check_git(), check_git_user_modified_dates(), check_usb_repo_dirty()]

    if IS_WIN:
        log("── Platform: Windows ────────────────────────────────")
        results += [check_powershell_policy(), check_long_paths_windows(),
                    check_windows_defender_exclusion()]
    else:
        log("── Platform: Ubuntu / Linux ─────────────────────────")
        results += [check_display_server(), check_apt_available(), check_systemd_ollama()]

    install_root = fb_root
    if install_root and install_root.is_dir():
        log(f"── CITL Install: {install_root.name} ──────────────────")
        results.append(check_config_paths(install_root))
        results += check_index_health(install_root)
        results.append(check_embedding_json(install_root))
        results.append(check_ttk_theme(install_root))
        results.append(check_regex_prequery(install_root))

    fails = sum(1 for r in results if not r.ok)
    log(f"── Done — {len(results)} checks, {fails} issue(s) ──────────────")
    return results


def auto_fix_all(results: List[CheckResult],
                 log: Callable[[str], None] = print) -> int:
    fixable = [r for r in results if not r.ok and r.fix_fn]
    log(f"Auto-fix: {len(fixable)} fixable issue(s) found.")
    fixed = 0
    for r in fixable:
        log(f"  Fixing: {r.name} — {r.fix_label}")
        try:
            ok = r.fix_fn(log)
            if ok:
                r.ok = True
                fixed += 1
                log(f"    ✓ Fixed: {r.name}")
            else:
                log(f"    ✗ Fix did not fully resolve: {r.name}")
        except Exception as e:
            log(f"    ✗ Fix threw exception: {r.name}: {e}")
    log(f"Auto-fix complete: {fixed}/{len(fixable)} resolved.")
    return fixed


# ══════════════════════════════════════════════════════════════════════════════
# CLI MODE
# ══════════════════════════════════════════════════════════════════════════════

def run_cli(auto_fix: bool = False):
    BOLD = "\033[1m"; RED = "\033[91m"; YEL = "\033[93m"
    GRN = "\033[92m"; CYN = "\033[96m"; RST = "\033[0m"

    def h(t): print(BOLD + CYN + t + RST)
    def ok(t): print(GRN + f"  ✓  {t}" + RST)
    def warn(t): print(YEL + f"  !  {t}" + RST)
    def err(t): print(RED + f"  ✗  {t}" + RST)

    print()
    h("╔══════════════════════════════════════════════╗")
    h("║   CITL FIXER  —  Repair & Launch Station    ║")
    h("╚══════════════════════════════════════════════╝")
    print()

    roots = _all_factbook_roots()
    fb_root = roots[0] if roots else None
    if fb_root:
        h(f"CITL install: {fb_root}")
    else:
        warn("No CITL install found locally — running USB system checks.")

    results = run_all_checks(fb_root, log=print)
    print()
    h("Results:")
    for r in results:
        if r.ok:
            ok(f"{r.name}: {r.msg}")
        else:
            err(f"{r.name}: {r.msg}")
            if r.fix_label:
                print(f"      → Fix: {r.fix_label}")

    fails = [r for r in results if not r.ok]
    print()
    if not fails:
        ok("All checks passed — system is healthy.")
    elif auto_fix:
        h(f"Auto-fixing {len(fails)} issue(s)…")
        auto_fix_all(results, log=print)
    else:
        warn(f"{len(fails)} issue(s) found. Run with --fix to auto-fix.")


# ══════════════════════════════════════════════════════════════════════════════
# GUI MODE
# ══════════════════════════════════════════════════════════════════════════════

def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog
        from tkinter.scrolledtext import ScrolledText
    except ImportError:
        print("Tkinter not available — run: sudo apt install python3-tk")
        run_cli(auto_fix=False)
        return

    # ── Root window ────────────────────────────────────────────────────────────
    root = tk.Tk()
    root.title("CITL Fixer  |  Repair · Diagnose · Launch  — Windows & Ubuntu")
    root.geometry("1100x780")
    root.configure(bg=T["bg"])
    root.resizable(True, True)

    # ── Banner ─────────────────────────────────────────────────────────────────
    banner = tk.Frame(root, bg=T["accent"], pady=0)
    banner.pack(fill="x")
    tk.Label(banner,
             text="  CITL FIXER  —  Repair · Diagnose · Bootstrap · Launch",
             fg=T["bg"], bg=T["accent"],
             font=("Consolas", 13, "bold")).pack(side="left", padx=10, pady=8)
    tk.Label(banner, text="Windows & Ubuntu  |  USB Edition",
             fg=T["bg"], bg=T["accent"],
             font=("Consolas", 9)).pack(side="right", padx=10)

    # ── Status bar ─────────────────────────────────────────────────────────────
    status_var = tk.StringVar(value="  Ready.  Click 'Run All Checks' or select a tab.")
    status_lbl = tk.Label(root, textvariable=status_var,
                          fg=T["status"], bg=T["hi"],
                          font=("Consolas", 9), anchor="w", padx=8, pady=3)
    status_lbl.pack(fill="x")

    def _set_status(msg: str, color: str = T["status"]):
        status_var.set(f"  {msg}")
        status_lbl.configure(fg=color)

    # ── Notebook ───────────────────────────────────────────────────────────────
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TNotebook", background=T["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=T["btn"], foreground=T["btn_fg"],
                    padding=[12, 6], font=("Consolas", 9, "bold"))
    style.map("TNotebook.Tab",
              background=[("selected", T["accent"])],
              foreground=[("selected", T["bg"])])
    style.configure("TScrollbar", background=T["hi"], troughcolor=T["bg"],
                    borderwidth=0, arrowcolor=T["accent"])
    style.configure("Vertical.TScrollbar", background=T["hi"],
                    troughcolor=T["bg"], borderwidth=0, arrowcolor=T["accent"])
    style.configure("Horizontal.TScrollbar", background=T["hi"],
                    troughcolor=T["bg"], borderwidth=0, arrowcolor=T["accent"])

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=4, pady=(2, 4))

    # ── Helper: shared log widget builder ─────────────────────────────────────
    def _make_log(parent: tk.Widget, height: int = 10) -> ScrolledText:
        w = ScrolledText(parent, height=height, state="disabled",
                         bg=T["txt_bg"], fg=T["txt_fg"],
                         font=("Consolas", 8), relief="flat",
                         insertbackground=T["accent"])
        w.tag_configure("ok",   foreground=T["ok"])
        w.tag_configure("err",  foreground=T["err"])
        w.tag_configure("warn", foreground=T["warn"])
        w.tag_configure("cmd",  foreground=T["accent"])
        w.tag_configure("hdr",  foreground=T["status"], font=("Consolas", 8, "bold"))
        return w

    def _log_write(w: ScrolledText, line: str):
        def _do():
            w.configure(state="normal")
            low = line.lower()
            tag = ("ok"   if any(x in low for x in ("✓", " ok", "fixed", "passed", "success")) else
                   "err"  if any(x in low for x in ("✗", "error", "fail", "cannot", "traceback")) else
                   "warn" if any(x in low for x in ("warn", "!  ", "missing", "not found")) else
                   "cmd"  if line.lstrip().startswith("$") else
                   "hdr"  if line.startswith("──") else "")
            w.insert("end", line + "\n", tag or ())
            w.configure(state="disabled")
            w.see("end")
        root.after(0, _do)

    def _btn(parent, text: str, color: str, cmd, side="top", **kw):
        b = tk.Button(parent, text=text, bg=color, fg=T["bg"],
                      activebackground=T["status"], activeforeground=T["bg"],
                      relief="flat", padx=8, pady=5, cursor="hand2",
                      font=("Consolas", 9, "bold"), command=cmd, **kw)
        b.pack(fill="x" if side == "top" else None,
               side="left" if side == "left" else "top",
               pady=2, padx=2)
        return b

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — SYSTEM HEALTH + ALL CITL APP REPAIR
    # ══════════════════════════════════════════════════════════════════════════
    tab_diag = tk.Frame(nb, bg=T["bg"])
    nb.add(tab_diag, text="  Diagnose & Fix  ")

    paned = tk.PanedWindow(tab_diag, orient="horizontal",
                           bg=T["hi"], sashwidth=5, sashrelief="flat")
    paned.pack(fill="both", expand=True)

    # LEFT: controls
    left = tk.Frame(paned, bg=T["panel"], width=290)
    paned.add(left, minsize=240)

    tk.Label(left, text="CITL App Location",
             fg=T["accent"], bg=T["panel"],
             font=("Consolas", 10, "bold")).pack(fill="x", padx=8, pady=(8, 2))

    _fb_roots: List[Path] = []
    _sel_root: List[Optional[Path]] = [None]

    lb_frame = tk.Frame(left, bg=T["panel"])
    lb_frame.pack(fill="both", expand=True, padx=8)
    lb = tk.Listbox(lb_frame, bg=T["txt_bg"], fg=T["txt_fg"],
                    selectbackground=T["accent"], selectforeground=T["bg"],
                    font=("Consolas", 8), activestyle="none",
                    relief="flat", borderwidth=0)
    lb_sb = ttk.Scrollbar(lb_frame, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=lb_sb.set)
    lb_sb.pack(side="right", fill="y")
    lb.pack(side="left", fill="both", expand=True)

    def _populate_lb(paths: List[Path]):
        _fb_roots.clear()
        _fb_roots.extend(paths)
        lb.delete(0, "end")
        for p in paths:
            lb.insert("end", p.name)
        if paths:
            lb.selection_set(0)
            _sel_root[0] = paths[0]
            _set_status(f"{len(paths)} install(s) found — select one and click Run Checks")
        else:
            _sel_root[0] = None
            _set_status("No CITL installs found on this machine. Try Browse.", T["warn"])

    def _on_lb_sel(e=None):
        sel = lb.curselection()
        if sel and sel[0] < len(_fb_roots):
            _sel_root[0] = _fb_roots[sel[0]]
            _set_status(f"Selected: {_sel_root[0]}")

    lb.bind("<<ListboxSelect>>", _on_lb_sel)

    sel_lbl = tk.Label(left, text="No location selected",
                       fg=T["warn"], bg=T["panel"],
                       font=("Consolas", 7), wraplength=260, justify="left")
    sel_lbl.pack(fill="x", padx=8, pady=2)

    def _watch_sel():
        p = _sel_root[0]
        sel_lbl.configure(text=str(p) if p else "No install selected",
                          fg=T["ok"] if p else T["warn"])
        root.after(600, _watch_sel)
    _watch_sel()

    ctrl = tk.Frame(left, bg=T["panel"])
    ctrl.pack(fill="x", padx=8, pady=4)

    def _do_scan():
        _set_status("Scanning for CITL App installs…")
        def _bg():
            paths = _discover_citl_installs()
            root.after(0, lambda: _populate_lb(paths))
        threading.Thread(target=_bg, daemon=True).start()

    def _do_browse():
        d = filedialog.askdirectory(title="Select Factbook root folder")
        if d:
            p = Path(d)
            _fb_roots.insert(0, p)
            lb.insert(0, p.name)
            lb.selection_clear(0, "end")
            lb.selection_set(0)
            _sel_root[0] = p
            _set_status(f"Manual: {p}")

    _btn(ctrl, "Scan for Installs", T["accent"], _do_scan)
    _btn(ctrl, "Browse…",           T["btn"],    _do_browse)

    # RIGHT: results
    right = tk.Frame(paned, bg=T["bg"])
    paned.add(right, minsize=600)

    # Result canvas
    diag_status_var = tk.StringVar(value="Click 'Run All Checks' to begin.")
    tk.Label(right, textvariable=diag_status_var,
             fg=T["status"], bg=T["bg"],
             font=("Consolas", 9), anchor="w", padx=4).pack(fill="x", pady=(4, 0))

    # Toolbar
    tbr = tk.Frame(right, bg=T["bg"])
    tbr.pack(fill="x", padx=4, pady=2)

    canv_outer = tk.Frame(right, bg=T["bg"])
    canv_outer.pack(fill="both", expand=True, padx=4)
    canv = tk.Canvas(canv_outer, bg=T["bg"], highlightthickness=0)
    vsb = ttk.Scrollbar(canv_outer, orient="vertical", command=canv.yview)
    stage_frame = tk.Frame(canv, bg=T["bg"])
    stage_frame.bind("<Configure>",
                     lambda e: canv.configure(scrollregion=canv.bbox("all")))
    canv.create_window((0, 0), window=stage_frame, anchor="nw")
    canv.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canv.pack(side="left", fill="both", expand=True)
    def _bind_scroll(e):
        canv.bind_all("<Button-4>", lambda ev: canv.yview_scroll(-1, "units"))
        canv.bind_all("<Button-5>", lambda ev: canv.yview_scroll(1, "units"))
    def _unbind_scroll(e):
        canv.unbind_all("<Button-4>")
        canv.unbind_all("<Button-5>")
    canv.bind("<Enter>", _bind_scroll)
    canv.bind("<Leave>", _unbind_scroll)

    _check_results: List[CheckResult] = []
    fix_log = _make_log(right, height=5)
    tk.Label(right, text="Fix / Action Log",
             fg=T["accent"], bg=T["bg"],
             font=("Consolas", 8, "bold"), anchor="w", padx=4).pack(anchor="w")
    fix_log.pack(fill="x", padx=4, pady=(0, 4))

    _full_log_mirror: list = [None]  # set after full_log is created

    def _flog(msg: str):
        _log_write(fix_log, msg)
        if _full_log_mirror[0] is not None:
            _log_write(_full_log_mirror[0], msg)

    def _clear_stages():
        for w in stage_frame.winfo_children():
            w.destroy()

    def _add_result_row(r: CheckResult):
        def _ui():
            dot = "●"
            color = T["ok"] if r.ok else T["err"]
            row = tk.Frame(stage_frame, bg=T["bg"])
            row.pack(fill="x", pady=1, padx=2)
            tk.Label(row, text=dot, fg=color, bg=T["bg"],
                     font=("Consolas", 11)).pack(side="left", padx=(4, 4))
            info = tk.Frame(row, bg=T["bg"])
            info.pack(side="left", fill="x", expand=True)
            label = f"{'OK  ' if r.ok else 'FAIL'} {r.name}: {r.msg[:70]}"
            tk.Label(info, text=label, fg=color, bg=T["bg"],
                     font=("Consolas", 8, "bold"), anchor="w").pack(anchor="w")

            btns = tk.Frame(row, bg=T["bg"])
            btns.pack(side="right", padx=2)

            if r.detail:
                _ex = [False]; _df = [None]
                def _tog(rr=r, ex=_ex, df=_df, p=info):
                    if ex[0]:
                        if df[0]: df[0].destroy(); df[0] = None; ex[0] = False
                    else:
                        df[0] = tk.Frame(p, bg=T["hl2"], padx=6, pady=4)
                        df[0].pack(fill="x")
                        tk.Label(df[0], text=rr.detail,
                                 fg=T["warn"] if not rr.ok else T["fg"],
                                 bg=T["hl2"],
                                 font=("Consolas", 7), justify="left",
                                 anchor="w", wraplength=400).pack(anchor="w")
                        ex[0] = True
                    canv.configure(scrollregion=canv.bbox("all"))
                tk.Button(btns, text="▸", bg=T["btn"], fg=T["btn_fg"],
                          font=("Consolas", 8), relief="flat", padx=4,
                          cursor="hand2", command=_tog).pack(side="left", padx=1)

            if not r.ok and r.fix_fn:
                _running = [False]
                def _do_fix(rr=r, btn_ref=[None], running=_running):
                    if running[0]:
                        return
                    running[0] = True
                    if btn_ref[0]:
                        btn_ref[0].configure(text="…", state="disabled")
                    def _bg():
                        try:
                            ok = rr.fix_fn(_flog)
                            def _done():
                                _flog(f"  {'✓ Fixed' if ok else '✗ Not fully fixed'}: {rr.name}")
                                rr.ok = ok
                                running[0] = False
                                if btn_ref[0]:
                                    lbl = "✓ Fixed" if ok else "✗ Retry"
                                    clr = T["ok"] if ok else T["err"]
                                    btn_ref[0].configure(
                                        text=lbl, bg=clr, state="normal")
                            root.after(0, _done)
                        except Exception as e:
                            root.after(0, lambda: _flog(f"  ✗ Exception: {e}"))
                            running[0] = False
                    threading.Thread(target=_bg, daemon=True).start()

                fix_btn = tk.Button(btns, text=r.fix_label[:22],
                                    bg=T["warn"], fg=T["bg"],
                                    font=("Consolas", 7, "bold"),
                                    relief="flat", padx=4, cursor="hand2",
                                    command=_do_fix)
                fix_btn.pack(side="left", padx=1)
                _do_fix.__defaults__ = (r, [fix_btn], [False])

        root.after(0, _ui)

    _busy = [False]

    def _do_run_checks():
        if _busy[0]:
            return
        _busy[0] = True
        _clear_stages()
        _check_results.clear()
        diag_status_var.set("Running checks…")
        _set_status("Running all checks…")

        fb = _sel_root[0]

        def _bg():
            def _log(msg):
                _flog(msg)
            results = run_all_checks(fb, log=_log)
            _check_results.extend(results)
            for r in results:
                _add_result_row(r)
            fails = sum(1 for r in results if not r.ok)
            msg = (f"All checks passed ({len(results)} total)"
                   if fails == 0 else
                   f"{fails} issue(s) found — use Fix buttons or 'Fix All'")
            root.after(0, lambda: diag_status_var.set(msg))
            root.after(0, lambda: _set_status(msg, T["ok"] if fails == 0 else T["warn"]))
            root.after(0, lambda: _busy.__setitem__(0, False))

        threading.Thread(target=_bg, daemon=True).start()

    def _do_fix_all():
        if not _check_results:
            _flog("  No results — run checks first.")
            return
        fixable = [r for r in _check_results if not r.ok and r.fix_fn]
        if not fixable:
            _flog("  Nothing to fix — all checks passed.")
            return
        _flog(f"Fix All: {len(fixable)} issue(s) to resolve…")

        def _bg():
            n = auto_fix_all(_check_results, log=_flog)
            root.after(0, lambda: _set_status(
                f"Fix All complete: {n}/{len(fixable)} resolved.",
                T["ok"] if n == len(fixable) else T["warn"]))

        threading.Thread(target=_bg, daemon=True).start()

    def _do_patch():
        fb = _sel_root[0]
        if not fb:
            _flog("  No install selected.")
            return
        _flog(f"Patching {fb.name} with latest scripts from USB…")
        def _bg():
            patched = patch_scripts(fb, log=_flog)
            root.after(0, lambda: _set_status(
                f"Patch complete: {len(patched)} file(s) deployed."))
        threading.Thread(target=_bg, daemon=True).start()

    _btn(tbr, "Run All Checks", T["accent"], _do_run_checks, side="left")
    _btn(tbr, "Fix All Problems", T["warn"], _do_fix_all, side="left")
    _btn(tbr, "Patch Scripts", T["btn"], _do_patch, side="left")

    # Auto-populate on load
    root.after(200, _do_scan)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — BOOTSTRAP
    # ══════════════════════════════════════════════════════════════════════════
    tab_boot = tk.Frame(nb, bg=T["bg"])
    nb.add(tab_boot, text="  Bootstrap  ")

    bh = tk.Frame(tab_boot, bg=T["hi"], pady=6)
    bh.pack(fill="x")
    tk.Label(bh, text="  CITL Bootstrap & Self-Heal — runs citl_bootstrap.py",
             fg=T["accent"], bg=T["hi"],
             font=("Consolas", 10, "bold")).pack(side="left", padx=8)

    boot_log = _make_log(tab_boot, height=28)
    boot_log.pack(fill="both", expand=True, padx=6, pady=4)

    bctrl = tk.Frame(tab_boot, bg=T["bg"])
    bctrl.pack(fill="x", padx=6, pady=(0, 4))

    _boot_running = [False]

    def _launch_bootstrap(extra_args=()):
        if _boot_running[0]:
            return
        _boot_running[0] = True
        _set_status("Running bootstrap…")
        _log_write(boot_log,
                   f"── Bootstrap started {datetime.now().strftime('%H:%M:%S')} ──")

        boot_py = USB_ROOT / "citl_bootstrap.py"
        if not boot_py.exists():
            _log_write(boot_log, f"  ERROR: {boot_py} not found on USB.")
            _boot_running[0] = False
            return

        cmd = [sys.executable, str(boot_py), "--cli"] + list(extra_args)

        def _bg():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    env={**os.environ, "PYTHONPATH":
                         f"{FA_DIR}:{os.environ.get('PYTHONPATH','')}"},
                )
                for line in proc.stdout:
                    _log_write(boot_log, line.rstrip())
                proc.wait()
                root.after(0, lambda: _set_status("Bootstrap finished."))
            except Exception as e:
                _log_write(boot_log, f"  ERROR: {e}")
            _boot_running[0] = False

        threading.Thread(target=_bg, daemon=True).start()

    _btn(bctrl, "Run Bootstrap Check", T["accent"],
         lambda: _launch_bootstrap(), side="left")
    _btn(bctrl, "Auto-Heal All",       T["warn"],
         lambda: _launch_bootstrap(["--auto-heal"]), side="left")
    _btn(bctrl, "Target: Factbook",    T["btn"],
         lambda: _launch_bootstrap(["--app", "factbook"]), side="left")
    _btn(bctrl, "Target: FLEX",        T["btn"],
         lambda: _launch_bootstrap(["--app", "flex"]), side="left")

    # ══════════════════════════════════════════════════════════════════════════

    # ======================================================================
    # TAB — SYNC & PATCHES  (beverage-named change detection)
    # ======================================================================
    tab_sync = tk.Frame(nb, bg=T["bg"])
    nb.add(tab_sync, text="  Sync & Patches  ")

    sh = tk.Frame(tab_sync, bg=T["hi"], pady=6)
    sh.pack(fill="x")
    tk.Label(sh,
             text="  CITL APP SYNC  —  Detect · Package · Apply repo changes to USB",
             fg=T["accent"], bg=T["hi"],
             font=("Consolas", 10, "bold")).pack(side="left", padx=8)
    tk.Label(sh, text="Beverage-coded patch payloads",
             fg=T["skip"], bg=T["hi"],
             font=("Consolas", 8)).pack(side="right", padx=8)

    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "citl_app_sync",
            str(USB_ROOT / "citl_app_sync.py"))
        if _spec and _spec.loader:
            _sync_mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_sync_mod)
            _sync_mod.run_sync_tab(tab_sync, T, root, _log_write)
        else:
            raise ImportError("spec loader not available")
    except Exception as _sync_exc:
        tk.Label(tab_sync,
                 text="Sync engine unavailable: "
                      + str(_sync_exc)
                      + "\n\nEnsure citl_app_sync.py is on the USB root.",
                 fg=T["warn"], bg=T["bg"],
                 font=("Consolas", 9), justify="left", padx=20, pady=20,
                 anchor="nw").pack(fill="both", expand=True)

    # TAB 3 — LAUNCH APPS
    # ══════════════════════════════════════════════════════════════════════════
    tab_launch = tk.Frame(nb, bg=T["bg"])
    nb.add(tab_launch, text="  Launch Apps  ")

    tk.Label(tab_launch,
             text="  Launch CITL Applications from USB",
             fg=T["accent"], bg=T["hi"],
             font=("Consolas", 10, "bold"), pady=6).pack(fill="x")

    launch_log = _make_log(tab_launch, height=14)
    launch_log.pack(fill="both", expand=True, padx=6, pady=4)

    def _llog(msg: str): _log_write(launch_log, msg)

    def _launch_app(script: Path, args=(), env_extra: dict = {}):
        if not script.exists():
            _llog(f"  ERROR: not found: {script}")
            return
        env = {
            **os.environ,
            "PYTHONPATH": f"{FA_DIR}:{os.environ.get('PYTHONPATH','')}",
            **env_extra,
        }
        _llog(f"Launching: {script.name}")
        try:
            subprocess.Popen(
                [sys.executable, str(script)] + list(args),
                env=env,
                cwd=str(script.parent),
            )
        except Exception as e:
            _llog(f"  ERROR: {e}")

    def _launch_shell(sh: Path):
        if not sh.exists():
            _llog(f"  ERROR: not found: {sh}")
            return
        _llog(f"Running: {sh.name}")
        try:
            subprocess.Popen(["bash", str(sh)], cwd=str(sh.parent))
        except Exception as e:
            _llog(f"  ERROR: {e}")

    apps_frame = tk.Frame(tab_launch, bg=T["bg"])
    apps_frame.pack(fill="x", padx=6)

    def _app_btn(label: str, color: str, fn, row: int, col: int):
        b = tk.Button(apps_frame, text=label,
                      bg=color, fg=T["bg"],
                      activebackground=T["status"], activeforeground=T["bg"],
                      relief="flat", padx=10, pady=12, cursor="hand2",
                      font=("Consolas", 9, "bold"), command=fn,
                      width=24)
        b.grid(row=row, column=col, padx=4, pady=4, sticky="ew")

    apps_frame.columnconfigure(0, weight=1)
    apps_frame.columnconfigure(1, weight=1)
    apps_frame.columnconfigure(2, weight=1)

    _fb_gui   = FA_DIR / "factbook_assistant_gui_ffmpeg_graceful_v2.py"
    _fb_gui2  = FA_DIR / "factbook_assistant_gui.py"
    _fb_sh    = USB_ROOT / "RUN_FACTBOOK.sh"
    _sync_sh  = USB_ROOT / "CITL App Sync.sh"
    _llm_sh   = USB_ROOT / "RUN_LLMOPS.sh"
    _repair_sh = USB_ROOT / "REPAIR_CITL_APPS.sh"
    _boot_py  = USB_ROOT / "citl_bootstrap.py"
    _diag_py  = FA_DIR / "citl_factbook_diagnostic.py"
    _repair_py = FA_DIR / "citl_repair_all.py"

    _app_btn("Factbook Assistant",
             T["accent"],
             lambda: (_launch_app(_fb_gui) if _fb_gui.exists()
                      else _launch_app(_fb_gui2)),
             0, 0)
    _app_btn("Run Factbook (Shell)",
             T["hi"],
             lambda: _launch_shell(_fb_sh),
             0, 1)
    _app_btn("CITL App Sync",
             T["btn"],
             lambda: _launch_shell(_sync_sh),
             0, 2)
    _app_btn("LLMOps Suite",
             T["btn"],
             lambda: _launch_shell(_llm_sh),
             1, 0)
    _app_btn("Factbook Diagnostic",
             T["warn"],
             lambda: _launch_app(_diag_py),
             1, 1)
    _app_btn("Repair All (Full GUI)",
             T["err"],
             lambda: _launch_app(_repair_py),
             1, 2)
    _app_btn("Bootstrap Self-Heal",
             T["accent"],
             lambda: _launch_app(_boot_py, ["--gui"]),
             2, 0)
    _app_btn("Open USB Root",
             T["skip"],
             lambda: subprocess.Popen(
                 ["explorer", str(USB_ROOT)] if IS_WIN
                 else ["xdg-open", str(USB_ROOT)]),
             2, 1)
    _app_btn("Open Terminal Here",
             T["skip"],
             lambda: subprocess.Popen(
                 ["cmd", "/k", f"cd /d {USB_ROOT}"] if IS_WIN else
                 ["bash", "-c",
                  f"cd {shlex.quote(str(USB_ROOT))} && "
                  "x-terminal-emulator || gnome-terminal || xterm"],
                 shell=False),
             2, 2)


    # ══════════════════════════════════════════════════════════════════════════
    # TAB — PORTABLE APP FIXER  (non-admin Windows engineering)
    # ══════════════════════════════════════════════════════════════════════════
    tab_portable = tk.Frame(nb, bg=T["bg"])
    nb.add(tab_portable, text="  Portable Fix  ")

    ph = tk.Frame(tab_portable, bg=T["hi"], pady=6)
    ph.pack(fill="x")
    tk.Label(ph,
             text="  PORTABLE APP FIXER  —  Non-Admin Windows Engineering",
             fg=T["accent"], bg=T["hi"],
             font=("Consolas", 10, "bold")).pack(side="left", padx=8)
    tk.Label(ph,
             text="Diagnose & repair portable CITL app folder",
             fg=T["skip"], bg=T["hi"],
             font=("Consolas", 8)).pack(side="right", padx=8)

    port_outer = tk.Frame(tab_portable, bg=T["bg"])
    port_outer.pack(fill="both", expand=True)

    port_left = tk.Frame(port_outer, bg=T["panel"], width=280)
    port_left.pack(side="left", fill="y", padx=(4, 0), pady=4)

    port_right = tk.Frame(port_outer, bg=T["bg"])
    port_right.pack(side="left", fill="both", expand=True, padx=4, pady=4)

    port_log = _make_log(port_right, height=32)
    port_log.pack(fill="both", expand=True)

    port_ctrl = tk.Frame(port_right, bg=T["bg"])
    port_ctrl.pack(fill="x", pady=(4, 0))

    def _plog(msg): _log_write(port_log, msg)

    _port_target = [USB_ROOT]

    tk.Label(port_left, text="Target Folder",
             fg=T["accent"], bg=T["panel"],
             font=("Consolas", 10, "bold")).pack(fill="x", padx=8, pady=(8, 2))

    port_path_var = tk.StringVar(value=str(USB_ROOT))
    port_path_lbl = tk.Label(port_left, textvariable=port_path_var,
                             fg=T["ok"], bg=T["panel"],
                             font=("Consolas", 7), wraplength=250,
                             justify="left", anchor="w")
    port_path_lbl.pack(fill="x", padx=8, pady=2)

    def _port_browse():
        d = filedialog.askdirectory(title="Select CITL portable app folder")
        if d:
            _port_target[0] = Path(d)
            port_path_var.set(str(_port_target[0]))

    tk.Button(port_left, text="Browse folder…",
              bg=T["btn"], fg=T["btn_fg"],
              font=("Consolas", 8, "bold"), relief="flat",
              padx=6, pady=4, cursor="hand2",
              command=_port_browse).pack(fill="x", padx=8, pady=2)

    tk.Label(port_left, text="Checks",
             fg=T["accent"], bg=T["panel"],
             font=("Consolas", 9, "bold")).pack(fill="x", padx=8, pady=(10, 2))

    for lbl in ["✓ Venv absolute paths", "✓ Config JSON paths",
                "✓ Batch/PS1 hardcoded paths", "✓ .lnk shortcut targets",
                "✓ Venv recreate if moved", "✓ pip -r requirements.txt",
                "✓ FFmpeg portable binary", "✓ DLL dependencies"]:
        tk.Label(port_left, text=f"  {lbl}",
                 fg=T["fg"], bg=T["panel"],
                 font=("Consolas", 7), anchor="w").pack(fill="x", padx=8)

    def _run_portable_diagnostics():
        target = _port_target[0]
        _plog(f"── Portable App Diagnostics: {target} ──────────────────────────")
        _plog(f"   Platform: {'Windows' if IS_WIN else 'Linux'}")

        # ── 1. Venv portability check ──────────────────────────────────────
        _plog("\n── [1/8] Python .venv portability ──────────────────────────────")
        venv_dir = target / ".venv"
        sub = "Scripts" if IS_WIN else "bin"
        if not venv_dir.is_dir():
            _plog("  WARN .venv not present — run 'Create .venv' to create one")
        else:
            cfg_file = venv_dir / "pyvenv.cfg"
            broken_abs = []
            if cfg_file.exists():
                cfg_txt = cfg_file.read_text(encoding="utf-8", errors="replace")
                for ln in cfg_txt.splitlines():
                    if "=" in ln:
                        k, _, v = ln.partition("=")
                        v = v.strip()
                        if v and not Path(v).exists() and (
                                (IS_WIN and re.match(r"[A-Z]:[/\]", v)) or
                                (not IS_WIN and v.startswith("/"))):
                            broken_abs.append(ln.strip())
            if broken_abs:
                _plog(f"  FAIL pyvenv.cfg has stale paths (venv was moved):")
                for ln in broken_abs:
                    _plog(f"       {ln}")
                _plog("  FIX  Use 'Recreate .venv' button below to rebuild in place.")
            else:
                _plog("  OK   pyvenv.cfg paths look valid")

            # Check activator scripts for stale VIRTUAL_ENV paths
            for act in (venv_dir / sub).glob("activate*"):
                try:
                    atxt = act.read_text(encoding="utf-8", errors="replace")
                    stale_found = False
                    for ln in atxt.splitlines():
                        if "VIRTUAL_ENV" not in ln:
                            continue
                        eq_idx = ln.find("=")
                        if eq_idx < 0:
                            continue
                        vpath = ln[eq_idx+1:].strip().strip(chr(34)).strip(chr(39))
                        if vpath and not Path(vpath).exists():
                            stale_found = True
                    if stale_found:
                        _plog(f"  WARN {act.name}: stale VIRTUAL_ENV path detected")
                except Exception:
                    pass

        # ── 2. Config JSON absolute paths ─────────────────────────────────
        _plog("\n── [2/8] Config JSON absolute paths ────────────────────────────")
        cfg_issues = []
        for search in [target, target / "factbook-assistant",
                       target / "factbook-assistant" / "data"]:
            if not search.is_dir():
                continue
            for jf in search.glob("*.json"):
                if jf.stat().st_size == 0:
                    continue
                try:
                    raw = jf.read_text(encoding="utf-8", errors="replace")
                    hits = re.findall(r'"([A-Z]:[/\\][^"]{3,})"', raw)
                    if hits:
                        cfg_issues.append((jf, hits))
                except Exception:
                    pass
        if cfg_issues:
            for jf, hits in cfg_issues:
                _plog(f"  FAIL {jf.name}: {len(hits)} Windows absolute path(s)")
                for h in hits[:3]:
                    _plog(f"       {h[:60]}")
        else:
            _plog("  OK   No hardcoded Windows paths in JSON configs")

        # ── 3. Batch / PS1 / Shell script absolute paths ──────────────────
        _plog("\n── [3/8] Launcher scripts (batch/ps1/sh) paths ─────────────────")
        script_issues = []
        for ext in ("*.cmd", "*.bat", "*.ps1", "*.sh"):
            for sf in target.glob(ext):
                try:
                    stxt = sf.read_text(encoding="utf-8", errors="replace")
                    # Detect C:bsolute\path patterns not using %~dp0
                    abs_hits = re.findall(r'[^%"](C:\\[A-Za-z\\]{4,})', stxt)
                    if abs_hits:
                        script_issues.append((sf, abs_hits))
                except Exception:
                    pass
        if script_issues:
            for sf, hits in script_issues:
                _plog(f"  WARN {sf.name}: possible hardcoded path(s) — verify manually")
        else:
            _plog("  OK   Launcher scripts look portable")

        # ── 4. Windows .lnk shortcuts ─────────────────────────────────────
        _plog("\n── [4/8] Windows shortcut (.lnk) targets ───────────────────────")
        if IS_WIN:
            lnk_count = len(list(target.glob("*.lnk")))
            if lnk_count:
                _plog(f"  INFO {lnk_count} .lnk file(s) found — shortcut targets "
                      f"may be absolute; re-create if the folder was moved")
            else:
                _plog("  OK   No .lnk shortcut files")
        else:
            _plog("  N/A  (Linux — no .lnk files)")

        # ── 5. pip freeze vs requirements ─────────────────────────────────
        _plog("\n── [5/8] pip requirements vs installed ─────────────────────────")
        req = next((target / f for f in ("requirements.txt", "requirements-base.txt")
                    if (target / f).exists()), None)
        if req:
            _plog(f"  INFO requirements file: {req.name}")
            _plog("  RUN  Use 'Reinstall requirements' button to sync packages")
        else:
            _plog("  WARN No requirements.txt found — cannot verify deps")

        # ── 6. FFmpeg portable binary ─────────────────────────────────────
        _plog("\n── [6/8] FFmpeg portable binary ────────────────────────────────")
        ffmp = (target / "bin" / ("ffmpeg.exe" if IS_WIN else "ffmpeg"))
        if ffmp.exists():
            _plog(f"  OK   Bundled FFmpeg: {ffmp}")
        elif shutil.which("ffmpeg"):
            _plog("  OK   FFmpeg on system PATH")
        else:
            _plog("  WARN FFmpeg not found — audio features limited")
            _plog("       Place ffmpeg.exe in .\\bin\ for portable use")

        # ── 7. Ollama portable ────────────────────────────────────────────
        _plog("\n── [7/8] Ollama availability ───────────────────────────────────")
        if shutil.which("ollama"):
            _plog("  OK   ollama on PATH")
        else:
            _plog("  WARN ollama not on PATH — LLM features unavailable")
            if IS_WIN:
                _plog("       Download: https://ollama.com/download/windows")

        # ── 8. Write permissions ──────────────────────────────────────────
        _plog("\n── [8/8] Folder write permissions ──────────────────────────────")
        test_f = target / ".citl_porttest"
        try:
            test_f.write_bytes(b"ok")
            test_f.unlink()
            _plog("  OK   Target folder is writable")
        except OSError as e:
            _plog(f"  FAIL Cannot write to folder: {e}")
            _plog("       Check UAC / NTFS permissions on this folder")

        _plog("\n── Portable diagnostics complete ───────────────────────────────")

    def _recreate_venv():
        target = _port_target[0]
        venv_path = target / ".venv"
        if venv_path.exists():
            _plog(f"  Removing stale .venv at {venv_path} …")
            try:
                shutil.rmtree(venv_path)
            except Exception as e:
                _plog(f"  ERROR removing .venv: {e}")
                return
        _plog("  Creating fresh .venv …")
        def _bg():
            ok, _ = _run([sys.executable, "-m", "venv", str(venv_path)],
                         timeout=120, log=_plog)
            if ok:
                _plog("  .venv created successfully.")
                req = next((target / f for f in
                            ("requirements.txt", "requirements-base.txt")
                            if (target / f).exists()), None)
                if req:
                    _plog(f"  Installing from {req.name} …")
                    sub = "Scripts" if IS_WIN else "bin"
                    pip = venv_path / sub / ("pip.exe" if IS_WIN else "pip")
                    _run([str(pip), "install", "--quiet", "-r", str(req)],
                         timeout=300, log=_plog)
                    _plog("  Requirements installed.")
            else:
                _plog("  FAILED to create .venv")
        threading.Thread(target=_bg, daemon=True).start()

    def _fix_json_paths():
        target = _port_target[0]
        fixed = 0
        for search in [target, target / "factbook-assistant",
                       target / "factbook-assistant" / "data"]:
            if not search.is_dir():
                continue
            for jf in search.glob("*.json"):
                if jf.stat().st_size == 0:
                    continue
                try:
                    raw = jf.read_text(encoding="utf-8")
                    data = json.loads(raw)
                    changed = False
                    for key in list(data.keys()):
                        if isinstance(data[key], str) and re.search(
                                r'[A-Z]:[/\\]', data[key]):
                            _plog(f"  Cleared Windows path in {jf.name}: {key}")
                            data[key] = ""
                            changed = True
                    if changed:
                        jf.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        fixed += 1
                except Exception as e:
                    _plog(f"  WARN {jf.name}: {e}")
        _plog(f"  Path fix complete: {fixed} file(s) updated")

    def _reinstall_reqs():
        target = _port_target[0]
        req = next((target / f for f in
                    ("requirements.txt", "requirements-base.txt")
                    if (target / f).exists()), None)
        if not req:
            _plog("  No requirements.txt found.")
            return
        def _bg():
            _plog(f"  pip install -r {req.name} …")
            ok, _ = _run([sys.executable, "-m", "pip", "install",
                          "--quiet", "-r", str(req)], timeout=300, log=_plog)
            _plog("  Done." if ok else "  FAILED.")
        threading.Thread(target=_bg, daemon=True).start()

    _btn(port_ctrl, "Run Portable Diagnostics", T["accent"],
         lambda: threading.Thread(target=_run_portable_diagnostics, daemon=True).start(),
         side="left")
    _btn(port_ctrl, "Recreate .venv", T["warn"], _recreate_venv, side="left")
    _btn(port_ctrl, "Fix JSON Paths",  T["btn"],  _fix_json_paths, side="left")
    _btn(port_ctrl, "Reinstall Requirements", T["btn"], _reinstall_reqs, side="left")

    root.after(500, lambda: threading.Thread(
        target=_run_portable_diagnostics, daemon=True).start())

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4 — FULL LOG
    # ══════════════════════════════════════════════════════════════════════════
    tab_log = tk.Frame(nb, bg=T["bg"])
    nb.add(tab_log, text="  Full Log  ")

    full_log = _make_log(tab_log, height=36)
    full_log.pack(fill="both", expand=True, padx=6, pady=4)

    log_ctrl = tk.Frame(tab_log, bg=T["bg"])
    log_ctrl.pack(fill="x", padx=6, pady=(0, 4))

    def _clear_log():
        full_log.configure(state="normal")
        full_log.delete("1.0", "end")
        full_log.configure(state="disabled")

    def _save_log():
        p = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*")],
            title="Save log",
            initialfile=f"citl_fixer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        )
        if p:
            try:
                full_log.configure(state="normal")
                Path(p).write_text(full_log.get("1.0", "end"), encoding="utf-8")
                full_log.configure(state="disabled")
                _set_status(f"Log saved: {p}")
            except Exception as e:
                _set_status(f"Save failed: {e}", T["err"])

    _btn(log_ctrl, "Clear Log", T["btn"], _clear_log, side="left")
    _btn(log_ctrl, "Save Log…", T["btn"], _save_log, side="left")

    # ── Wire full_log mirror now that full_log exists ──────────────────────────
    _full_log_mirror[0] = full_log

    root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def _entry_main() -> int:
    ap = argparse.ArgumentParser(
        description="CITL Fixer — USB Repair & Launch Station (Windows & Ubuntu)")
    ap.add_argument("--cli",  action="store_true", help="Terminal-only mode")
    ap.add_argument("--fix",  action="store_true", help="Auto-fix all issues (CLI)")
    ap.add_argument("--path", type=Path, default=None,
                    help="Factbook root to diagnose (skips auto-search)")
    ap.add_argument("--no-auto-update", action="store_true",
                    help="Skip auto patch cadence run on startup.")
    ap.add_argument("--force-auto-update", action="store_true",
                    help="Force patch cadence runner now, ignoring local throttle.")
    ap.add_argument("--clone-usb-target", default="",
                    help="Clone latest current CITL repo snapshot to a replacement USB target path (or 'auto').")
    ap.add_argument("--clone-usb-source", default="auto",
                    help="Optional source path for --clone-usb-target (default: auto).")
    args = ap.parse_args()

    try:
        if IS_WIN and not args.no_auto_update:
            _maybe_run_windows_auto_patch(log=print, force=bool(args.force_auto_update))

        if str(args.clone_usb_target or "").strip():
            return _run_usb_clone_from_fixer(
                str(args.clone_usb_target),
                source_arg=str(args.clone_usb_source or "auto"),
                log=print,
            )

        if args.cli or args.fix:
            run_cli(auto_fix=args.fix)
        else:
            run_gui()
        return 0
    except Exception:
        crash_log = _write_crash_log()
        print(f"[FATAL] CITL Fixer crashed. Crash log: {crash_log}")
        try:
            print("[FATAL] Attempting CLI fallback diagnostics...")
            run_cli(auto_fix=False)
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(_entry_main())
