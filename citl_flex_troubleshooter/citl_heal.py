"""
citl_heal.py  —  CITL Universal Diagnostic & Self-Heal Engine
═══════════════════════════════════════════════════════════════
Covers every failure mode across Factbook, FLEX Troubleshooter,
and all other CITL apps deployed on USB or local installs.

Each check returns a DiagnosticResult with:
  • status  — "ok" | "warn" | "error"
  • message — plain-English description
  • actions — list of HealAction (label + callable that fixes it)

Usage
-----
    from citl_heal import run_full_diagnostic
    results = run_full_diagnostic()

    # Or per-category:
    from citl_heal import check_ollama_layer, check_python_deps
    results = check_ollama_layer() + check_python_deps()

Embed the GUI panel with citl_heal_panel.py.
"""
from __future__ import annotations

import importlib
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# ── Paths ─────────────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
_DATA_DIR   = HERE / "data"
_LIB_RAW    = _DATA_DIR / "library_raw"
_IDX_DIR    = _DATA_DIR / "indexes"
_FLEX_DIR   = HERE.parent / "citl_flex_troubleshooter"
_FLEX_DATA  = _FLEX_DIR / "data"
_ROOT       = HERE.parent           # repo root
_SCRIPTS    = _ROOT / "scripts"
_DIST       = _ROOT / "dist"

# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class HealAction:
    """A single button / action the user (or the system) can take to fix an issue."""
    label:       str                    # button text, e.g. "Start Ollama"
    description: str                    # tooltip / log prefix
    run_fn:      Callable[[Callable[[str], None]], None]  # fn(log_cb) — writes progress to log_cb
    is_async:    bool = True            # run in background thread?


@dataclass
class DiagnosticResult:
    """One diagnostic check result."""
    category: str                       # e.g. "Ollama", "Python", "Index"
    name:     str                       # short name, e.g. "Ollama running"
    status:   str                       # "ok" | "warn" | "error"
    message:  str                       # human-readable detail
    actions:  List[HealAction] = field(default_factory=list)
    detail:   str = ""                  # extra technical detail (shown expanded)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _run_cmd(cmd: List[str], log_cb: Callable[[str], None],
             timeout: int = 120, shell: bool = False) -> bool:
    """Run a subprocess, streaming lines to log_cb.  Returns True on success."""
    log_cb(f"$ {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd, shell=shell,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        for line in proc.stdout:
            log_cb(line.rstrip())
        proc.wait(timeout=timeout)
        ok = proc.returncode == 0
        log_cb(f"[exit {proc.returncode}]")
        return ok
    except FileNotFoundError:
        log_cb(f"ERROR: command not found: {cmd[0]}")
        return False
    except subprocess.TimeoutExpired:
        proc.kill()
        log_cb("ERROR: command timed out")
        return False
    except Exception as e:
        log_cb(f"ERROR: {e}")
        return False


def _pip_install(pkg: str, log_cb: Callable[[str], None]) -> bool:
    return _run_cmd([sys.executable, "-m", "pip", "install", "--quiet", pkg], log_cb)


def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _check_ollama_running(host: str = None, timeout: float = 4.0) -> Tuple[bool, List[str]]:
    host = (host or _ollama_host()).rstrip("/")
    try:
        req = urllib.request.Request(host + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        models = [m["name"] for m in data.get("models", []) if isinstance(m, dict)]
        return True, models
    except Exception:
        return False, []


def _python_version_ok() -> Tuple[bool, str]:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 9)
    return ok, f"{v.major}.{v.minor}.{v.micro}"


def _import_ok(pkg: str) -> bool:
    try:
        importlib.import_module(pkg)
        return True
    except ImportError:
        return False


def _count_all_chunks(idx_dir: Path = None) -> int:
    d = idx_dir or _IDX_DIR
    if not d.is_dir():
        return 0
    total = 0
    for f in d.glob("*.jsonl"):
        if f.name.startswith("_"):
            continue
        try:
            total += sum(1 for line in f.open(encoding="utf-8", errors="ignore")
                         if line.strip() and not line.strip().startswith("//"))
        except Exception:
            pass
    return total


# ═════════════════════════════════════════════════════════════════════════════
# CHECK FUNCTIONS  —  each returns List[DiagnosticResult]
# ═════════════════════════════════════════════════════════════════════════════

# ── 1. Python version ─────────────────────────────────────────────────────────

def check_python_version() -> List[DiagnosticResult]:
    ok, ver = _python_version_ok()
    if ok:
        return [DiagnosticResult("Python", "Python version", "ok",
                                 f"Python {ver} — OK")]
    return [DiagnosticResult("Python", "Python version", "error",
                             f"Python {ver} detected — CITL apps require Python 3.9+.",
                             detail="Upgrade Python from https://www.python.org/downloads/",
                             actions=[HealAction(
                                 "Open Python Download Page",
                                 "Opening python.org in browser",
                                 lambda log: _open_url("https://www.python.org/downloads/", log),
                                 is_async=False,
                             )])]


# ── 2. Python dependencies ────────────────────────────────────────────────────

_DEPS: List[Tuple[str, str, str]] = [
    # (import_name, pip_name, severity)
    ("numpy",        "numpy",               "error"),
    ("requests",     "requests",            "error"),
    ("docx",         "python-docx",         "warn"),
    ("faster_whisper","faster-whisper",     "warn"),
    ("sounddevice",  "sounddevice",         "warn"),
    ("PIL",          "Pillow",              "warn"),
    ("docx2txt",     "docx2txt",            "warn"),
]


def check_python_deps() -> List[DiagnosticResult]:
    results = []
    for imp_name, pip_name, severity in _DEPS:
        if _import_ok(imp_name):
            results.append(DiagnosticResult("Python", f"Package: {pip_name}",
                                            "ok", f"{pip_name} installed"))
        else:
            _n = pip_name  # capture for closure
            results.append(DiagnosticResult(
                "Python", f"Package: {pip_name}", severity,
                f"{pip_name} is NOT installed — some features unavailable.",
                detail=f"Fix: pip install {pip_name}",
                actions=[HealAction(
                    f"Install {pip_name}",
                    f"pip install {pip_name}",
                    lambda log, p=_n: _pip_install(p, log),
                )],
            ))
    return results


# ── 3. tkinter ────────────────────────────────────────────────────────────────

def check_tkinter() -> List[DiagnosticResult]:
    try:
        import tkinter  # noqa: F401
        return [DiagnosticResult("Python", "tkinter", "ok", "tkinter available")]
    except ImportError:
        actions = []
        if platform.system() == "Linux":
            actions.append(HealAction(
                "Install tkinter (apt)",
                "sudo apt install python3-tk",
                lambda log: _run_cmd(
                    ["sudo", "apt-get", "install", "-y", "python3-tk"], log),
            ))
        return [DiagnosticResult(
            "Python", "tkinter", "error",
            "tkinter not available — GUI cannot start.",
            detail="On Ubuntu/Debian: sudo apt install python3-tk\n"
                   "On macOS: reinstall Python from python.org (homebrew Python omits tkinter)",
            actions=actions,
        )]


# ── 4. Ollama layer ───────────────────────────────────────────────────────────

_LLM_PREFERRED  = ["mistral:7b-instruct", "mistral", "llama3", "phi3", "gemma",
                   "olmo2", "olmo"]
_EMB_PREFERRED  = ["nomic-embed-text", "mxbai-embed-large"]
_MM_PREFERRED   = ["molmo"]  # AllenAI multimodal / vision models


def check_ollama_layer() -> List[DiagnosticResult]:
    results: List[DiagnosticResult] = []
    host = _ollama_host()

    # 4a. Is Ollama reachable?
    ollama_up, models = _check_ollama_running(host)
    if not ollama_up:
        results.append(DiagnosticResult(
            "Ollama", "Ollama running", "error",
            f"Ollama is NOT running at {host}.",
            detail="Start Ollama with: ollama serve\n"
                   "Or check OLLAMA_HOST env var if using a remote instance.",
            actions=[
                HealAction("Start Ollama", "ollama serve",
                           lambda log: _start_ollama(log)),
                HealAction("Check OLLAMA_HOST", "Print current OLLAMA_HOST setting",
                           lambda log: log(f"OLLAMA_HOST = {os.environ.get('OLLAMA_HOST','(not set — using 127.0.0.1:11434)')}"),
                           is_async=False),
                HealAction("Run Bootstrap Script", "Run install_citl_apps_portable to reinstall Ollama",
                           lambda log: _run_bootstrap(log)),
            ],
        ))
        # Can't check models if Ollama is down
        results.append(DiagnosticResult("Ollama", "Models installed", "warn",
                                        "Cannot check models — Ollama is offline."))
        return results

    results.append(DiagnosticResult(
        "Ollama", "Ollama running", "ok",
        f"Ollama running at {host}  ({len(models)} model(s) installed)",
    ))

    # 4b. LLM model
    has_llm = any(any(p in m for p in _LLM_PREFERRED) for m in models)
    if not has_llm and models:
        # Something is installed; might still work
        results.append(DiagnosticResult(
            "Ollama", "LLM model", "warn",
            f"No preferred LLM found. Installed: {', '.join(models[:4])}.\n"
            "CITL apps work best with mistral:7b-instruct.",
            actions=[HealAction(
                "Pull mistral:7b-instruct",
                "ollama pull mistral:7b-instruct",
                lambda log: _run_cmd(["ollama", "pull", "mistral:7b-instruct"], log, timeout=600),
            )],
        ))
    elif not models:
        results.append(DiagnosticResult(
            "Ollama", "LLM model", "error",
            "No LLM models installed. App cannot answer questions.",
            detail="Run: ollama pull mistral:7b-instruct  OR  ollama pull olmo2:7b",
            actions=[
                HealAction(
                    "Pull mistral:7b-instruct",
                    "ollama pull mistral:7b-instruct",
                    lambda log: _run_cmd(["ollama", "pull", "mistral:7b-instruct"],
                                         log, timeout=600),
                ),
                HealAction(
                    "Pull OLMo2 7B (AllenAI)",
                    "ollama pull olmo2:7b",
                    lambda log: _run_cmd(["ollama", "pull", "olmo2:7b"],
                                         log, timeout=7200),
                ),
            ],
        ))
    else:
        results.append(DiagnosticResult(
            "Ollama", "LLM model", "ok",
            f"LLM available: {models[0]}" + (f"  (+{len(models)-1} more)" if len(models) > 1 else ""),
        ))

    # 4c. Embed model
    has_emb = any(any(e in m for e in _EMB_PREFERRED) for m in models)
    if not has_emb:
        results.append(DiagnosticResult(
            "Ollama", "Embed model", "warn",
            "Embedding model (nomic-embed-text) not found — vector search disabled.\n"
            "Keyword search will be used as fallback.",
            detail="Run: ollama pull nomic-embed-text",
            actions=[HealAction(
                "Pull nomic-embed-text",
                "ollama pull nomic-embed-text",
                lambda log: _run_cmd(["ollama", "pull", "nomic-embed-text"], log, timeout=600),
            )],
        ))
    else:
        results.append(DiagnosticResult("Ollama", "Embed model", "ok",
                                        "Embedding model available"))

    # 4c-2. AllenAI multimodal (informational — not required for RAG)
    has_mm = any(any(p in m for p in _MM_PREFERRED) for m in models)
    if not has_mm:
        results.append(DiagnosticResult(
            "Ollama", "AllenAI Vision (Molmo)", "warn",
            "No AllenAI Molmo vision model installed — multimodal queries unavailable.",
            detail="Optional: ollama pull molmo7b-d-0924  or  ollama pull molmo7b-o-0924",
            actions=[
                HealAction("Pull Molmo 7B-D (Vision)",
                           "ollama pull molmo7b-d-0924",
                           lambda log: _run_cmd(["ollama", "pull", "molmo7b-d-0924"],
                                                log, timeout=7200)),
                HealAction("Pull OLMo2 7B (LLM)",
                           "ollama pull olmo2:7b",
                           lambda log: _run_cmd(["ollama", "pull", "olmo2:7b"],
                                                log, timeout=7200)),
            ],
        ))
    else:
        results.append(DiagnosticResult("Ollama", "AllenAI Vision (Molmo)", "ok",
                                        "Molmo multimodal model available"))

    # 4d. Port 11434 sanity (only if local)
    if "127.0.0.1" in host or "localhost" in host:
        import socket
        try:
            s = socket.create_connection(("127.0.0.1", 11434), timeout=2)
            s.close()
            results.append(DiagnosticResult("Ollama", "Port 11434", "ok",
                                            "Port 11434 is open"))
        except OSError:
            results.append(DiagnosticResult(
                "Ollama", "Port 11434", "error",
                "Port 11434 is not accepting connections — Ollama may have crashed or not started.",
                actions=[HealAction("Start Ollama", "ollama serve",
                                    lambda log: _start_ollama(log))],
            ))

    return results


# ── 5. Index / corpus layer ───────────────────────────────────────────────────

def check_index_layer() -> List[DiagnosticResult]:
    results: List[DiagnosticResult] = []

    # 5a. library_raw directory
    if not _LIB_RAW.is_dir():
        results.append(DiagnosticResult(
            "Index", "library_raw directory", "error",
            f"Source documents directory missing: {_LIB_RAW}",
            detail="Create the directory and add PDF/DOCX/TXT course documents.",
            actions=[HealAction(
                "Create library_raw/",
                f"mkdir {_LIB_RAW}",
                lambda log, p=_LIB_RAW: (_mkdir_safe(p, log)),
                is_async=False,
            )],
        ))
    else:
        docs = (list(_LIB_RAW.glob("*.pdf")) + list(_LIB_RAW.glob("*.txt")) +
                list(_LIB_RAW.glob("*.docx")) + list(_LIB_RAW.glob("*.md")))
        if not docs:
            results.append(DiagnosticResult(
                "Index", "Source documents", "warn",
                f"library_raw/ exists but is empty. No documents to index.\n"
                f"Path: {_LIB_RAW}",
                detail="Add PDF, TXT, DOCX, or MD course files to this folder, then rebuild the index.",
            ))
        else:
            results.append(DiagnosticResult(
                "Index", "Source documents", "ok",
                f"{len(docs)} source document(s) in library_raw/",
            ))

    # 5b. Index directory + JSONL chunks
    chunk_count = _count_all_chunks(_IDX_DIR)
    if chunk_count < 10:
        results.append(DiagnosticResult(
            "Index", "JSONL index chunks", "error",
            f"Index has only {chunk_count} chunks — too few for reliable search. "
            "Needs rebuild.",
            detail="Go to Library/Models tab → Rebuild Index.\n"
                   "Or click 'Rebuild Index' below.",
            actions=[HealAction(
                "Rebuild Index Now",
                "Running citl_auto_index rebuild…",
                lambda log: _rebuild_index(log, force=True),
            )],
        ))
    else:
        jsonl_count = len(list(_IDX_DIR.glob("*.jsonl"))) if _IDX_DIR.is_dir() else 0
        results.append(DiagnosticResult(
            "Index", "JSONL index chunks", "ok",
            f"Index has {chunk_count:,} chunks across {jsonl_count} file(s)",
        ))

    # 5c. Embedding JSON
    emb_json = HERE / "factbook_embeddings.json"
    if not emb_json.exists():
        results.append(DiagnosticResult(
            "Index", "Embedding JSON", "warn",
            "factbook_embeddings.json not found — vector search unavailable.\n"
            "Keyword search will be used instead.",
            detail="Run 'Build Embedding Index' from the Library/Models tab.",
            actions=[HealAction(
                "Build Embedding Index",
                "Running build_factbook_index.py…",
                lambda log: _build_embedding_index(log),
            )],
        ))
    else:
        try:
            data = json.loads(emb_json.read_text(encoding="utf-8"))
            n = len(data.get("chunks", data.get("embeddings", [])))
            if n < 10:
                results.append(DiagnosticResult(
                    "Index", "Embedding JSON", "warn",
                    f"factbook_embeddings.json has only {n} entries — may be corrupt or incomplete.",
                    actions=[HealAction(
                        "Rebuild Embedding Index",
                        "Running build_factbook_index.py…",
                        lambda log: _build_embedding_index(log),
                    )],
                ))
            else:
                results.append(DiagnosticResult(
                    "Index", "Embedding JSON", "ok",
                    f"Embedding index: {n:,} vectors",
                ))
        except Exception as e:
            results.append(DiagnosticResult(
                "Index", "Embedding JSON", "error",
                f"factbook_embeddings.json is corrupt: {e}",
                detail=f"Delete {emb_json} and rebuild.",
                actions=[
                    HealAction(
                        "Delete & Rebuild",
                        f"Deleting {emb_json.name} and rebuilding…",
                        lambda log, p=emb_json: _delete_and_rebuild_emb(p, log),
                    ),
                ],
            ))

    # 5d. Writable index dir check
    try:
        test_file = _IDX_DIR / ".write_test"
        _IDX_DIR.mkdir(parents=True, exist_ok=True)
        test_file.write_text("ok")
        test_file.unlink()
        results.append(DiagnosticResult("Index", "Index dir writable", "ok",
                                        f"Index directory is writable: {_IDX_DIR}"))
    except Exception as e:
        results.append(DiagnosticResult(
            "Index", "Index dir writable", "error",
            f"Index directory is NOT writable: {_IDX_DIR}\n"
            "This usually means the app is running from a read-only USB drive.\n"
            f"Error: {e}",
            detail="APPDATA fallback will be used for index writes.",
            actions=[HealAction(
                "Use APPDATA Fallback",
                "Switching index writes to APPDATA/CITL/indexes",
                lambda log: _set_appdata_fallback(log),
                is_async=False,
            )],
        ))

    return results


# ── 6. FLEX corpus layer ──────────────────────────────────────────────────────

def check_flex_corpus() -> List[DiagnosticResult]:
    results: List[DiagnosticResult] = []

    corpus = _FLEX_DIR / "flex_embeddings.json"
    if not _FLEX_DIR.is_dir():
        results.append(DiagnosticResult(
            "FLEX", "FLEX app directory", "warn",
            f"FLEX Troubleshooter directory not found: {_FLEX_DIR}\n"
            "FLEX checks skipped.",
        ))
        return results

    if not corpus.exists():
        results.append(DiagnosticResult(
            "FLEX", "FLEX corpus", "warn",
            "FLEX corpus (flex_embeddings.json) not built yet.\n"
            "Go to FLEX Index Builder tab and click 'Build / Rebuild Index'.",
            actions=[HealAction(
                "Build FLEX Corpus",
                "Running flex_builder.py…",
                lambda log: _run_cmd(
                    [sys.executable, str(_FLEX_DIR / "flex_builder.py")], log, timeout=300),
            )],
        ))
    else:
        try:
            data = json.loads(corpus.read_text(encoding="utf-8"))
            n = len(data.get("chunks", []))
            if n < 5:
                results.append(DiagnosticResult(
                    "FLEX", "FLEX corpus", "warn",
                    f"FLEX corpus has only {n} chunks — rebuild recommended.",
                    actions=[HealAction(
                        "Rebuild FLEX Corpus",
                        "Running flex_builder.py…",
                        lambda log: _run_cmd(
                            [sys.executable, str(_FLEX_DIR / "flex_builder.py")], log, timeout=300),
                    )],
                ))
            else:
                results.append(DiagnosticResult(
                    "FLEX", "FLEX corpus", "ok",
                    f"FLEX corpus: {n:,} chunks",
                ))
        except Exception as e:
            results.append(DiagnosticResult(
                "FLEX", "FLEX corpus", "error",
                f"FLEX corpus is corrupt: {e}",
                actions=[HealAction(
                    "Delete & Rebuild FLEX Corpus",
                    "Deleting corrupt corpus and rebuilding…",
                    lambda log, p=corpus: _delete_and_rebuild_flex(p, log),
                )],
            ))

    return results


# ── 7. File system checks ─────────────────────────────────────────────────────

def check_filesystem() -> List[DiagnosticResult]:
    results: List[DiagnosticResult] = []

    # 7a. Disk space (warn if < 2GB free on the drive hosting the app)
    try:
        usage = shutil.disk_usage(str(HERE))
        free_gb = usage.free / 1e9
        if free_gb < 0.5:
            results.append(DiagnosticResult(
                "Filesystem", "Disk space", "error",
                f"CRITICAL: Only {free_gb:.1f} GB free on app drive.\n"
                "Models and indexes may fail to write.",
            ))
        elif free_gb < 2.0:
            results.append(DiagnosticResult(
                "Filesystem", "Disk space", "warn",
                f"Low disk space: {free_gb:.1f} GB free. "
                "Consider freeing space before building indexes.",
            ))
        else:
            results.append(DiagnosticResult(
                "Filesystem", "Disk space", "ok",
                f"Disk space OK: {free_gb:.1f} GB free",
            ))
    except Exception as e:
        results.append(DiagnosticResult("Filesystem", "Disk space", "warn",
                                        f"Could not check disk space: {e}"))

    # 7b. Config file
    config_path = HERE / "citl_config.json"
    if config_path.exists():
        try:
            json.loads(config_path.read_text(encoding="utf-8"))
            results.append(DiagnosticResult("Filesystem", "Config file", "ok",
                                            "citl_config.json is valid JSON"))
        except json.JSONDecodeError as e:
            results.append(DiagnosticResult(
                "Filesystem", "Config file", "error",
                f"citl_config.json is corrupt (JSON parse error): {e}",
                detail="The config will be reset to defaults.",
                actions=[HealAction(
                    "Reset Config",
                    "Deleting corrupt config — app will regenerate defaults on next launch",
                    lambda log, p=config_path: _reset_config(p, log),
                    is_async=False,
                )],
            ))
    # Missing config is OK — apps recreate it

    # 7c. Key app directories exist
    for label, path in [
        ("data/",           _DATA_DIR),
        ("data/library_raw/", _LIB_RAW),
        ("data/indexes/",   _IDX_DIR),
    ]:
        if path.is_dir():
            results.append(DiagnosticResult("Filesystem", f"Dir: {label}", "ok",
                                            f"{label} exists"))
        else:
            results.append(DiagnosticResult(
                "Filesystem", f"Dir: {label}", "warn",
                f"Directory missing: {path}",
                actions=[HealAction(
                    f"Create {label}",
                    f"mkdir {path}",
                    lambda log, p=path: _mkdir_safe(p, log),
                    is_async=False,
                )],
            ))

    return results


# ── 8. FFmpeg check ───────────────────────────────────────────────────────────

def check_ffmpeg() -> List[DiagnosticResult]:
    # Check system PATH first
    if shutil.which("ffmpeg"):
        try:
            result = subprocess.run(["ffmpeg", "-version"],
                                    capture_output=True, text=True, timeout=5)
            ver_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
            return [DiagnosticResult("Media", "FFmpeg", "ok",
                                     f"FFmpeg on PATH: {ver_line[:60]}")]
        except Exception:
            pass

    # Check bundled ffmpeg in app dirs
    for candidate in [HERE / "bin" / "ffmpeg.exe",
                      HERE / "ffmpeg.exe",
                      _ROOT / "bin" / "ffmpeg.exe"]:
        if candidate.exists():
            return [DiagnosticResult("Media", "FFmpeg", "ok",
                                     f"Bundled FFmpeg found: {candidate}")]

    actions = []
    if platform.system() == "Windows":
        actions.append(HealAction(
            "Install FFmpeg (winget)",
            "winget install Gyan.FFmpeg",
            lambda log: _run_cmd(["winget", "install", "Gyan.FFmpeg",
                                  "--accept-package-agreements",
                                  "--accept-source-agreements"], log, timeout=300),
        ))
    elif platform.system() == "Linux":
        actions.append(HealAction(
            "Install FFmpeg (apt)",
            "sudo apt install ffmpeg",
            lambda log: _run_cmd(["sudo", "apt-get", "install", "-y", "ffmpeg"], log),
        ))
    elif platform.system() == "Darwin":
        actions.append(HealAction(
            "Install FFmpeg (brew)",
            "brew install ffmpeg",
            lambda log: _run_cmd(["brew", "install", "ffmpeg"], log, timeout=300),
        ))

    return [DiagnosticResult(
        "Media", "FFmpeg", "warn",
        "FFmpeg not found on PATH or in app directories.\n"
        "Audio recording and video capture features will be unavailable.",
        detail="Install FFmpeg or place ffmpeg.exe in the app's bin/ folder.",
        actions=actions,
    )]


# ── 9. Audio devices ─────────────────────────────────────────────────────────

def check_audio_devices() -> List[DiagnosticResult]:
    if not _import_ok("sounddevice"):
        return [DiagnosticResult(
            "Media", "Audio devices", "warn",
            "sounddevice not installed — cannot check audio devices.",
            actions=[HealAction(
                "Install sounddevice",
                "pip install sounddevice",
                lambda log: _pip_install("sounddevice", log),
            )],
        )]
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devs = [d for d in devices if d.get("max_input_channels", 0) > 0]
        if not input_devs:
            return [DiagnosticResult(
                "Media", "Audio devices", "warn",
                "No audio input devices found. Voice recording will not work.\n"
                "Check that a microphone is connected.",
            )]
        names = ", ".join(d["name"][:30] for d in input_devs[:3])
        return [DiagnosticResult(
            "Media", "Audio devices", "ok",
            f"{len(input_devs)} input device(s): {names}",
        )]
    except Exception as e:
        return [DiagnosticResult(
            "Media", "Audio devices", "warn",
            f"Could not query audio devices: {e}",
        )]


# ── 10. EXE / launcher check ──────────────────────────────────────────────────

def check_launchers() -> List[DiagnosticResult]:
    results: List[DiagnosticResult] = []
    launchers = [
        ("CITL-Factbook-Assistant.exe",      _DIST / "CITL-Factbook-Assistant.exe"),
        ("CITL-FLEX-Troubleshooter.exe",     _DIST / "CITL-FLEX-Troubleshooter.exe"),
        ("RUN_CITL_FLEX.sh",                 _ROOT / "RUN_CITL_FLEX.sh"),
        ("RUN_CITL_FLEX_WINDOWS.cmd",        _ROOT / "RUN_CITL_FLEX_WINDOWS.cmd"),
    ]
    for name, path in launchers:
        if path.exists():
            results.append(DiagnosticResult("Launchers", name, "ok",
                                            f"{name} present"))
        else:
            actions = []
            if name.endswith(".exe"):
                actions.append(HealAction(
                    f"Build {name}",
                    f"Running PyInstaller to build {name}…",
                    lambda log, n=name: _build_exe(n, log),
                ))
            results.append(DiagnosticResult(
                "Launchers", name, "warn",
                f"{name} not found at {path}.\n"
                "App can still run via Python — EXE is optional.",
                actions=actions,
            ))
    return results


# ── 11. Network / Ollama host reachability ────────────────────────────────────

def check_network() -> List[DiagnosticResult]:
    results: List[DiagnosticResult] = []
    host = _ollama_host()

    import socket
    import urllib.parse
    parsed = urllib.parse.urlparse(host)
    hostname = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434

    try:
        s = socket.create_connection((hostname, port), timeout=3)
        s.close()
        results.append(DiagnosticResult(
            "Network", f"Ollama host {hostname}:{port}", "ok",
            f"TCP connection to {hostname}:{port} succeeded",
        ))
    except OSError as e:
        actions = []
        if hostname in ("127.0.0.1", "localhost"):
            actions.append(HealAction(
                "Start Ollama", "ollama serve",
                lambda log: _start_ollama(log),
            ))
        else:
            actions.append(HealAction(
                "Reset to localhost",
                "Set OLLAMA_HOST to http://127.0.0.1:11434",
                lambda log: _reset_ollama_host(log),
                is_async=False,
            ))
        results.append(DiagnosticResult(
            "Network", f"Ollama host {hostname}:{port}", "error",
            f"Cannot reach Ollama at {hostname}:{port}: {e}",
            detail=f"Check OLLAMA_HOST env var (currently: {host})",
            actions=actions,
        ))

    return results


# ═════════════════════════════════════════════════════════════════════════════
# HEAL FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

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


def _kill_hung_ollama(log: Callable[[str], None]) -> None:
    if platform.system() != "Windows":
        return
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ollama.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=5)
        if "ollama.exe" in r.stdout:
            log("Killing existing ollama.exe for clean restart…")
            subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"],
                           capture_output=True, timeout=5)
            time.sleep(1)
    except Exception:
        pass


def _start_ollama(log: Callable[[str], None]) -> None:
    log("Attempting to start Ollama…")
    exe = _find_ollama_exe()
    if not exe:
        log("ERROR: ollama executable not found on PATH or in AppData\\Programs\\Ollama.")
        log("Install from https://ollama.com/download")
        return
    log(f"Found: {exe}")
    _kill_hung_ollama(log)
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
        log("Ollama launched. Waiting up to 30 s for API…")
        import socket as _sock
        for i in range(30):
            time.sleep(1)
            try:
                s = _sock.create_connection(("127.0.0.1", 11434), timeout=1)
                s.close()
                log(f"Ollama is online after {i+1}s. Re-run diagnostics.")
                return
            except Exception:
                pass
        log("ERROR: Ollama launched but did not respond within 30 s.")
        log("Open a terminal and run  ollama serve  to see the error output.")
    except Exception as e:
        log(f"ERROR launching Ollama: {e}")


def _run_bootstrap(log: Callable[[str], None]) -> None:
    """Run the CITL portable install bootstrap script."""
    log("Looking for bootstrap script…")
    candidates = [
        _ROOT / "scripts" / "windows" / "install_citl_apps_portable.ps1",
        _ROOT / "INSTALL_CITL_APPS_PORTABLE.cmd",
        _ROOT / "bootstrap.sh",
    ]
    for c in candidates:
        if c.exists():
            log(f"Found: {c}")
            if c.suffix == ".ps1":
                _run_cmd(["powershell", "-ExecutionPolicy", "Bypass",
                          "-File", str(c)], log, timeout=300)
            elif c.suffix == ".cmd":
                _run_cmd([str(c)], log, timeout=300, shell=True)
            else:
                _run_cmd(["bash", str(c)], log, timeout=300)
            return
    log("ERROR: Bootstrap script not found.")
    log(f"Expected one of:\n" + "\n".join(str(c) for c in candidates))


def _rebuild_index(log: Callable[[str], None], force: bool = True) -> None:
    log("Rebuilding keyword index from library_raw/…")
    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        from citl_auto_index import auto_index_library, LIB_RAW, IDX_DIR
        # Try writable dir
        try:
            _IDX_DIR.mkdir(parents=True, exist_ok=True)
            idx_dir = _IDX_DIR
        except Exception:
            appdata = Path(os.environ.get("APPDATA", Path.home())) / "CITL" / "indexes"
            appdata.mkdir(parents=True, exist_ok=True)
            idx_dir = appdata
            log(f"Using APPDATA fallback: {idx_dir}")
        results = auto_index_library(lib_dir=LIB_RAW, idx_dir=idx_dir, force=force)
        total = sum(results.values()) if results else 0
        log(f"Done. {total:,} chunks indexed across {len(results)} document(s).")
    except Exception as e:
        log(f"ERROR: {e}")


def _build_embedding_index(log: Callable[[str], None]) -> None:
    log("Building embedding index (requires Ollama + nomic-embed-text)…")
    script = HERE / "build_factbook_index.py"
    if not script.exists():
        log(f"ERROR: {script} not found.")
        return
    _run_cmd([sys.executable, str(script)], log, timeout=600)


def _delete_and_rebuild_emb(path: Path, log: Callable[[str], None]) -> None:
    log(f"Deleting {path.name}…")
    try:
        path.unlink()
        log("Deleted.")
    except Exception as e:
        log(f"ERROR deleting: {e}")
        return
    _build_embedding_index(log)


def _delete_and_rebuild_flex(path: Path, log: Callable[[str], None]) -> None:
    log(f"Deleting {path.name}…")
    try:
        path.unlink()
        log("Deleted.")
    except Exception as e:
        log(f"ERROR deleting: {e}")
        return
    script = _FLEX_DIR / "flex_builder.py"
    if not script.exists():
        log(f"ERROR: flex_builder.py not found at {script}")
        return
    _run_cmd([sys.executable, str(script)], log, timeout=300)


def _mkdir_safe(path: Path, log: Callable[[str], None]) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        log(f"Created: {path}")
    except Exception as e:
        log(f"ERROR: Could not create {path}: {e}")


def _reset_config(path: Path, log: Callable[[str], None]) -> None:
    try:
        path.unlink()
        log(f"Deleted {path.name}. App will regenerate defaults on next launch.")
    except Exception as e:
        log(f"ERROR: {e}")


def _set_appdata_fallback(log: Callable[[str], None]) -> None:
    appdata = Path(os.environ.get("APPDATA", Path.home())) / "CITL" / "indexes"
    try:
        appdata.mkdir(parents=True, exist_ok=True)
        log(f"APPDATA fallback created: {appdata}")
        log("Index writes will use this directory when the app folder is read-only.")
    except Exception as e:
        log(f"ERROR: {e}")


def _build_exe(name: str, log: Callable[[str], None]) -> None:
    script_map = {
        "CITL-Factbook-Assistant.exe": HERE / "citl_gui_entry.py",
        "CITL-FLEX-Troubleshooter.exe": _FLEX_DIR / "flex_troubleshooter_gui.py",
    }
    entry = script_map.get(name)
    if not entry or not entry.exists():
        # Search sibling paths before giving up
        for alt in ["flex_troubleshooter_gui.py", "flex_assistant_gui.py",
                    "citl_gui_entry.py", "factbook_assistant_gui_entry.py"]:
            for search_dir in [_FLEX_DIR, HERE, _ROOT]:
                candidate = search_dir / alt
                if candidate.exists() and (
                    ("FLEX" in name and "flex" in alt.lower()) or
                    ("Factbook" in name and ("factbook" in alt.lower() or "gui_entry" in alt))
                ):
                    entry = candidate
                    log(f"Using entry script: {entry}")
                    break
            if entry and entry.exists():
                break
    if not entry or not entry.exists():
        log(f"ERROR: Entry script for {name} not found.")
        log(f"  Searched: {HERE}, {_FLEX_DIR}")
        return
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        log("PyInstaller not found. Installing…")
        if not _pip_install("pyinstaller", log):
            return
    _run_cmd([
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--noconsole",
        "--hidden-import=wave",
        "--hidden-import=audioop",
        "--hidden-import=colorsys",
        "--name", name.replace(".exe", ""),
        str(entry),
    ], log, timeout=300)


def _reset_ollama_host(log: Callable[[str], None]) -> None:
    os.environ["OLLAMA_HOST"] = "http://127.0.0.1:11434"
    log("OLLAMA_HOST reset to http://127.0.0.1:11434 (for this session).")
    log("To make permanent: set OLLAMA_HOST in your system environment variables.")


def _open_url(url: str, log: Callable[[str], None]) -> None:
    import webbrowser
    webbrowser.open(url)
    log(f"Opened: {url}")


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def run_full_diagnostic() -> List[DiagnosticResult]:
    """Run all checks and return combined results."""
    results: List[DiagnosticResult] = []
    checks = [
        check_python_version,
        check_tkinter,
        check_python_deps,
        check_network,
        check_ollama_layer,
        check_index_layer,
        check_flex_corpus,
        check_filesystem,
        check_ffmpeg,
        check_audio_devices,
        check_launchers,
    ]
    for fn in checks:
        try:
            results.extend(fn())
        except Exception as e:
            results.append(DiagnosticResult(
                "Internal", fn.__name__, "warn",
                f"Check '{fn.__name__}' threw an unexpected error: {e}",
            ))
    return results


def run_quick_diagnostic() -> List[DiagnosticResult]:
    """Run only the critical-path checks (fast, for startup banner)."""
    results: List[DiagnosticResult] = []
    for fn in [check_python_version, check_network,
               check_ollama_layer, check_index_layer]:
        try:
            results.extend(fn())
        except Exception:
            pass
    return results


def summary(results: List[DiagnosticResult]) -> str:
    """Return a short human-readable summary string."""
    counts = {"ok": 0, "warn": 0, "error": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    errors = [r for r in results if r.status == "error"]
    warns  = [r for r in results if r.status == "warn"]
    parts  = []
    if errors:
        parts.append(f"{counts['error']} error(s): " +
                     ", ".join(r.name for r in errors[:3]))
    if warns:
        parts.append(f"{counts['warn']} warning(s)")
    if not parts:
        parts.append(f"All {counts['ok']} checks passed")
    return "  |  ".join(parts)
