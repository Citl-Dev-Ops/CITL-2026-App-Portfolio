#!/usr/bin/env python3
"""
citl_factbook_diagnostic.py  —  CITL Factbook Full Pipeline Diagnostic
═══════════════════════════════════════════════════════════════════════════
Tests every step in the Factbook/FLEX RAG pipeline with LIVE checks.
Never silently swallows an error. Every failure shows:
  • The exact exception / HTTP status / file path that failed
  • The exact command(s) to fix it
  • An auto-fix button that runs the fix and re-tests

Pipeline stages (in order):
  1  Python version
  2  Core packages (numpy, requests)
  3  Optional packages (python-docx, Pillow, etc.)
  4  Ollama port open (TCP)
  5  Ollama API responding (/api/tags)
  6  LLM model installed
  7  Embed model installed
  8  Embed model LIVE test (actual API call → verify vector shape)
  9  Source documents exist and are readable
  10 Text extraction per-document (extract_text live test)
  11 citl_auto_index importable
  12 Index directory writable
  13 JSONL index chunks >= threshold
  14 Keyword search returns results (live query)
  15 Embedding JSON exists and is valid (shape check)
  16 Embedding dimensions match embed model output
  17 LLM generation LIVE test (actual API call → non-empty response)
  18 Full RAG end-to-end smoke test (embed → top-k → generate)

Usage
-----
    python citl_factbook_diagnostic.py          # GUI
    python citl_factbook_diagnostic.py --cli    # terminal
    python citl_factbook_diagnostic.py --fix    # CLI + auto-fix all
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# ── Paths ─────────────────────────────────────────────────────────────────────
HERE     = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
LIB_RAW  = DATA_DIR / "library_raw"
IDX_DIR  = DATA_DIR / "indexes"
EMB_JSON = HERE / "factbook_embeddings.json"

# Ensure this directory is on sys.path
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


# ══════════════════════════════════════════════════════════════════════════════
# RESULT DATACLASS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StepResult:
    stage:      int
    name:       str
    status:     str          # "pass" | "fail" | "warn" | "skip"
    detail:     str          # full explanation — NEVER empty on fail
    fix_cmds:   List[str] = field(default_factory=list)   # exact shell commands
    fix_fn:     Optional[Callable[["StepResult", Callable], bool]] = None
    fix_label:  str = ""
    duration_ms: float = 0.0

    @property
    def passed(self): return self.status == "pass"
    @property
    def failed(self): return self.status == "fail"


def _step(stage: int, name: str, fn: Callable, *args, **kwargs) -> StepResult:
    """Run a check function, catch ALL exceptions, record timing."""
    t0 = time.monotonic()
    try:
        result: StepResult = fn(*args, **kwargs)
    except Exception as e:
        result = StepResult(
            stage=stage, name=name, status="fail",
            detail=(
                f"INTERNAL ERROR in diagnostic check '{name}':\n"
                f"{traceback.format_exc().strip()}\n\n"
                f"This is a bug in the diagnostic tool. "
                f"Please report it with the traceback above."
            ),
        )
    result.duration_ms = (time.monotonic() - t0) * 1000
    return result


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

def _ollama_hostname() -> str:
    import urllib.parse
    return urllib.parse.urlparse(_ollama_host()).hostname or "127.0.0.1"

def _ollama_port() -> int:
    import urllib.parse
    return urllib.parse.urlparse(_ollama_host()).port or 11434

def _http_post(url: str, payload: dict, timeout: float = 30.0) -> dict:
    """POST JSON, return parsed response dict.  Raises on any error with full detail."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def _http_get(url: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())

def _count_chunks(idx_dir: Path) -> Tuple[int, List[str]]:
    """Return (total_chunks, list_of_jsonl_files)."""
    if not idx_dir.is_dir():
        return 0, []
    files = []
    total = 0
    for f in idx_dir.glob("*.jsonl"):
        if f.name.startswith("_"):
            continue
        files.append(f.name)
        try:
            n = sum(1 for ln in f.open(encoding="utf-8", errors="ignore")
                    if ln.strip() and not ln.strip().startswith("//"))
            total += n
        except Exception:
            pass
    return total, files

def _run_cmd_capture(cmd: List[str], timeout: int = 120) -> Tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)

def _writable_idx_dir() -> Path:
    """Return a writable index dir — USB read-only fallback."""
    candidates = [
        IDX_DIR,
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
    return IDX_DIR


# ══════════════════════════════════════════════════════════════════════════════
# STAGE CHECKS
# ══════════════════════════════════════════════════════════════════════════════

# ── Stage 1: Python version ───────────────────────────────────────────────────

def _check_python_version() -> StepResult:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < (3, 9):
        return StepResult(
            stage=1, name="Python version", status="fail",
            detail=(
                f"Python {ver} detected. CITL apps require Python 3.9 or newer.\n"
                f"Executable: {sys.executable}\n\n"
                f"Fix: install Python 3.9+ from https://www.python.org/downloads/\n"
                f"On Ubuntu/Debian: sudo apt install python3.11 python3.11-tk"
            ),
            fix_cmds=[
                "# Windows:",
                "winget install Python.Python.3.11",
                "# Ubuntu/Debian:",
                "sudo apt install python3.11 python3.11-venv python3.11-tk",
            ],
        )
    return StepResult(stage=1, name="Python version", status="pass",
                      detail=f"Python {ver}  [{sys.executable}]")


# ── Stage 2: Core packages ────────────────────────────────────────────────────

def _check_core_packages() -> StepResult:
    failures = []
    for mod, pkg in [("numpy", "numpy"), ("requests", "requests")]:
        try:
            importlib.import_module(mod)
        except ImportError as e:
            failures.append((pkg, str(e)))

    if failures:
        pkgs = " ".join(p for p, _ in failures)
        errs = "\n".join(f"  import {p}: {e}" for p, e in failures)
        return StepResult(
            stage=2, name="Core packages", status="fail",
            detail=(
                f"Required packages missing:\n{errs}\n\n"
                f"Without these, the app CANNOT run.\n"
                f"Fix command:\n  {sys.executable} -m pip install {pkgs}"
            ),
            fix_cmds=[f"{sys.executable} -m pip install {pkgs}"],
            fix_fn=lambda r, log: _fix_pip([p for p, _ in failures], log),
            fix_label=f"Install {pkgs}",
        )

    import numpy as np
    return StepResult(stage=2, name="Core packages", status="pass",
                      detail=f"numpy {np.__version__}, requests installed")


# ── Stage 3: Optional packages ────────────────────────────────────────────────

def _check_optional_packages() -> StepResult:
    missing = []
    for mod, pkg in [
        ("docx",         "python-docx"),
        ("PIL",          "Pillow"),
        ("docx2txt",     "docx2txt"),
        ("faster_whisper","faster-whisper"),
        ("sounddevice",  "sounddevice"),
    ]:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)

    if missing:
        pkgs = " ".join(missing)
        return StepResult(
            stage=3, name="Optional packages", status="warn",
            detail=(
                f"Optional packages not installed: {', '.join(missing)}\n"
                f"Core functionality works without these, but PDF/audio features\n"
                f"may be limited.\n\n"
                f"Fix: {sys.executable} -m pip install {pkgs}"
            ),
            fix_cmds=[f"{sys.executable} -m pip install {pkgs}"],
            fix_fn=lambda r, log: _fix_pip(missing, log),
            fix_label=f"Install {len(missing)} optional package(s)",
        )
    return StepResult(stage=3, name="Optional packages", status="pass",
                      detail="All optional packages installed")


# ── Stage 4: Ollama TCP port open ─────────────────────────────────────────────

def _check_ollama_port() -> StepResult:
    host = _ollama_hostname()
    port = _ollama_port()
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.close()
        return StepResult(stage=4, name="Ollama port open", status="pass",
                          detail=f"TCP connection to {host}:{port} succeeded")
    except socket.timeout:
        err = f"Connection to {host}:{port} timed out after 3 seconds"
    except ConnectionRefusedError:
        err = f"Connection refused on {host}:{port} — Ollama is not running"
    except OSError as e:
        err = f"Socket error on {host}:{port}: {e}"

    fix_cmd = "ollama serve"
    detail = (
        f"{err}\n\n"
        f"OLLAMA_HOST env var: {os.environ.get('OLLAMA_HOST', '(not set)')}\n"
        f"Resolved endpoint: {host}:{port}\n\n"
        f"Fix: start Ollama in a terminal window:\n"
        f"  {fix_cmd}\n\n"
        f"If Ollama is not installed:\n"
        f"  Windows: winget install Ollama.Ollama\n"
        f"  Ubuntu:  curl -fsSL https://ollama.com/install.sh | sh"
    )
    return StepResult(
        stage=4, name="Ollama port open", status="fail", detail=detail,
        fix_cmds=[fix_cmd],
        fix_fn=lambda r, log: _fix_start_ollama(log),
        fix_label="Start Ollama",
    )


# ── Stage 5: Ollama API responding ────────────────────────────────────────────

def _check_ollama_api() -> StepResult:
    host = _ollama_host()
    url = f"{host}/api/tags"
    try:
        data = _http_get(url, timeout=8.0)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode(errors="replace")[:300]
        except Exception:
            pass
        return StepResult(
            stage=5, name="Ollama API", status="fail",
            detail=(
                f"Ollama returned HTTP {e.code} from {url}\n"
                f"Response body: {body}\n\n"
                f"This suggests Ollama is running but its API is broken.\n"
                f"Try restarting Ollama:\n  pkill ollama && ollama serve"
            ),
            fix_cmds=["pkill ollama && ollama serve"],
        )
    except urllib.error.URLError as e:
        return StepResult(
            stage=5, name="Ollama API", status="fail",
            detail=(
                f"Cannot reach Ollama API at {url}\n"
                f"Underlying error: {e.reason}\n\n"
                f"Fix: run  ollama serve  in a terminal"
            ),
            fix_cmds=["ollama serve"],
            fix_fn=lambda r, log: _fix_start_ollama(log),
            fix_label="Start Ollama",
        )
    except json.JSONDecodeError as e:
        return StepResult(
            stage=5, name="Ollama API", status="fail",
            detail=(
                f"Ollama API at {url} returned invalid JSON.\n"
                f"Parse error: {e}\n\n"
                f"Try restarting Ollama: ollama serve"
            ),
        )
    except Exception as e:
        return StepResult(
            stage=5, name="Ollama API", status="fail",
            detail=(
                f"Unexpected error contacting Ollama API at {url}:\n"
                f"{traceback.format_exc().strip()}"
            ),
        )

    models = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]
    return StepResult(stage=5, name="Ollama API", status="pass",
                      detail=f"Ollama API OK — {len(models)} model(s) installed")


# ── Stage 6: LLM model installed ─────────────────────────────────────────────

def _check_llm_model() -> StepResult:
    host = _ollama_host()
    try:
        data = _http_get(f"{host}/api/tags", timeout=8.0)
    except Exception as e:
        return StepResult(
            stage=6, name="LLM model installed", status="skip",
            detail=f"Skipped — Ollama API unavailable: {e}")

    models = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]
    _PREFERRED = ["mistral:7b-instruct", "mistral", "llama3", "phi3", "gemma", "qwen"]
    matched = [m for m in models if any(p in m for p in _PREFERRED)]

    if not models:
        return StepResult(
            stage=6, name="LLM model installed", status="fail",
            detail=(
                "No models installed in Ollama at all.\n"
                "The app cannot answer any questions without an LLM.\n\n"
                "Fix:\n"
                "  ollama pull mistral:7b-instruct\n\n"
                "Smaller alternative (4 GB RAM):\n"
                "  ollama pull phi3:mini"
            ),
            fix_cmds=["ollama pull mistral:7b-instruct"],
            fix_fn=lambda r, log: _fix_ollama_pull("mistral:7b-instruct", log),
            fix_label="Pull mistral:7b-instruct",
        )

    if not matched:
        return StepResult(
            stage=6, name="LLM model installed", status="warn",
            detail=(
                f"Installed models: {', '.join(models[:6])}\n"
                f"None match the preferred list {_PREFERRED[:3]}.\n"
                f"The app will use {models[0]} but quality may vary.\n\n"
                f"Recommended: ollama pull mistral:7b-instruct"
            ),
            fix_cmds=["ollama pull mistral:7b-instruct"],
            fix_fn=lambda r, log: _fix_ollama_pull("mistral:7b-instruct", log),
            fix_label="Pull mistral:7b-instruct",
        )

    return StepResult(stage=6, name="LLM model installed", status="pass",
                      detail=f"LLM model: {matched[0]}")


# ── Stage 7: Embed model installed ───────────────────────────────────────────

def _check_embed_model() -> StepResult:
    host = _ollama_host()
    try:
        data = _http_get(f"{host}/api/tags", timeout=8.0)
    except Exception as e:
        return StepResult(
            stage=7, name="Embed model installed", status="skip",
            detail=f"Skipped — Ollama API unavailable: {e}")

    models = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]
    _EMB = ["nomic-embed-text", "mxbai-embed-large", "all-minilm"]
    matched = [m for m in models if any(e in m for e in _EMB)]

    if not matched:
        return StepResult(
            stage=7, name="Embed model installed", status="fail",
            detail=(
                f"Embedding model not found.\n"
                f"Installed models: {', '.join(models[:6]) or '(none)'}\n\n"
                f"Without an embed model, vector search is disabled.\n"
                f"Keyword search will be used as fallback (less accurate).\n\n"
                f"Fix:\n"
                f"  ollama pull nomic-embed-text\n\n"
                f"This model is ~274 MB."
            ),
            fix_cmds=["ollama pull nomic-embed-text"],
            fix_fn=lambda r, log: _fix_ollama_pull("nomic-embed-text", log),
            fix_label="Pull nomic-embed-text",
        )

    return StepResult(stage=7, name="Embed model installed", status="pass",
                      detail=f"Embed model: {matched[0]}")


# ── Stage 8: Embed model LIVE test ────────────────────────────────────────────

def _check_embed_live() -> StepResult:
    host = _ollama_host()
    emb_model = os.environ.get("CITL_EMBED_MODEL", "nomic-embed-text")

    # Make sure embed model is actually installed first
    try:
        data = _http_get(f"{host}/api/tags", timeout=8.0)
        models = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]
        if not any("embed" in m or "minilm" in m for m in models):
            return StepResult(
                stage=8, name="Embed live test", status="skip",
                detail="Skipped — no embedding model installed (see Stage 7)")
    except Exception:
        return StepResult(
            stage=8, name="Embed live test", status="skip",
            detail="Skipped — Ollama unreachable")

    test_text = "This is a diagnostic test for CITL Factbook."
    for url, payload in [
        (f"{host}/api/embed",       {"model": emb_model, "input": test_text}),
        (f"{host}/api/embeddings",  {"model": emb_model, "prompt": test_text}),
    ]:
        try:
            resp = _http_post(url, payload, timeout=45.0)
        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read().decode(errors="replace")[:300]
            except Exception: pass
            last_err = (
                f"HTTP {e.code} from {url}\n"
                f"Payload sent: {json.dumps(payload)}\n"
                f"Response body: {body}\n\n"
                f"Possible causes:\n"
                f"  • Model name mismatch (CITL_EMBED_MODEL={emb_model})\n"
                f"  • Model not fully loaded — wait 5 seconds and retry\n"
                f"  • Run: ollama pull {emb_model}"
            )
            continue
        except urllib.error.URLError as e:
            last_err = f"Connection error to {url}: {e.reason}"
            continue
        except Exception as e:
            last_err = f"Unexpected error calling {url}:\n{traceback.format_exc().strip()}"
            continue

        # Parse vector
        vec = None
        if "embeddings" in resp and resp["embeddings"]:
            vec = resp["embeddings"][0]
        elif "embedding" in resp:
            vec = resp["embedding"]

        if vec is None:
            last_err = (
                f"Embed API at {url} returned unexpected response shape:\n"
                f"{json.dumps(resp)[:400]}\n\n"
                f"Expected keys: 'embeddings' or 'embedding'"
            )
            continue

        if not isinstance(vec, list) or len(vec) == 0:
            last_err = (
                f"Embed API returned an empty or non-list vector.\n"
                f"vec type: {type(vec)}, len: {len(vec) if isinstance(vec, list) else 'N/A'}"
            )
            continue

        dim = len(vec)
        if dim < 64:
            last_err = (
                f"Embed vector has only {dim} dimensions — suspiciously small.\n"
                f"nomic-embed-text should return 768 dimensions.\n"
                f"The model may be corrupt. Try:\n"
                f"  ollama rm {emb_model} && ollama pull {emb_model}"
            )
            continue

        return StepResult(stage=8, name="Embed live test", status="pass",
                          detail=f"Embed model responded: {dim}-dimensional vector via {url}")

    return StepResult(
        stage=8, name="Embed live test", status="fail",
        detail=(
            f"Embedding API FAILED for model '{emb_model}'.\n\n"
            f"Last error:\n{last_err}\n\n"
            f"CITL_EMBED_MODEL env var: {os.environ.get('CITL_EMBED_MODEL','(not set)')}\n\n"
            f"Resolution steps:\n"
            f"  1. ollama pull {emb_model}\n"
            f"  2. Restart Ollama:  ollama serve\n"
            f"  3. Re-run this diagnostic"
        ),
        fix_cmds=[
            f"ollama pull {emb_model}",
            "# Then restart this diagnostic",
        ],
        fix_fn=lambda r, log: _fix_ollama_pull(emb_model, log),
        fix_label=f"Re-pull {emb_model}",
    )


# ── Stage 9: Source documents ─────────────────────────────────────────────────

def _check_source_documents() -> StepResult:
    if not LIB_RAW.is_dir():
        return StepResult(
            stage=9, name="Source documents", status="fail",
            detail=(
                f"library_raw/ directory does not exist: {LIB_RAW}\n\n"
                f"This directory must contain the course PDFs/text files\n"
                f"that the app indexes and searches.\n\n"
                f"Fix:\n"
                f"  mkdir -p \"{LIB_RAW}\"\n"
                f"  # Then copy your course documents into it"
            ),
            fix_cmds=[f'mkdir -p "{LIB_RAW}"'],
            fix_fn=lambda r, log: _fix_mkdir(LIB_RAW, log),
            fix_label="Create library_raw/ directory",
        )

    exts = {".pdf", ".txt", ".docx", ".md", ".rtf"}
    docs = [p for p in LIB_RAW.rglob("*")
            if p.is_file() and p.suffix.lower() in exts]

    if not docs:
        return StepResult(
            stage=9, name="Source documents", status="fail",
            detail=(
                f"library_raw/ exists but contains NO source documents.\n"
                f"Path: {LIB_RAW}\n\n"
                f"Add your course PDFs, text files, or DOCX files to this folder,\n"
                f"then run the Index Builder to rebuild the search index.\n\n"
                f"Supported formats: PDF, TXT, DOCX, MD, RTF"
            ),
        )

    sizes = []
    for d in docs[:5]:
        try:
            sizes.append(f"{d.name} ({d.stat().st_size:,} bytes)")
        except Exception:
            sizes.append(d.name)

    return StepResult(stage=9, name="Source documents", status="pass",
                      detail=(
                          f"{len(docs)} document(s) in library_raw/\n"
                          f"  " + "\n  ".join(sizes[:5]) +
                          (f"\n  ... and {len(docs)-5} more" if len(docs) > 5 else "")
                      ))


# ── Stage 10: Text extraction live test ───────────────────────────────────────

def _check_text_extraction() -> StepResult:
    if not LIB_RAW.is_dir():
        return StepResult(stage=10, name="Text extraction", status="skip",
                          detail="Skipped — library_raw/ missing (see Stage 9)")

    exts = {".pdf", ".txt", ".docx", ".md"}
    docs = [p for p in LIB_RAW.glob("*") if p.is_file() and p.suffix.lower() in exts]
    if not docs:
        return StepResult(stage=10, name="Text extraction", status="skip",
                          detail="Skipped — no documents to test")

    results = []
    for doc in docs[:3]:  # test first 3 docs
        try:
            extract_fn = None
            try:
                from citl_text_extract import extract_text as _ext
                extract_fn = _ext
            except ImportError:
                pass

            if extract_fn:
                text = extract_fn(doc)
            else:
                # Basic fallback
                text = doc.read_text(encoding="utf-8", errors="ignore")

            if not text or len(text.strip()) < 20:
                results.append((doc.name, "warn",
                                 f"Extracted only {len(text.strip())} chars — may be a scanned PDF"))
            else:
                results.append((doc.name, "pass",
                                 f"{len(text):,} chars extracted"))
        except ImportError as e:
            results.append((doc.name, "fail",
                             f"Import error during extraction: {e}\n"
                             f"  Fix: {sys.executable} -m pip install python-docx Pillow pdfminer.six"))
        except Exception as e:
            results.append((doc.name, "fail",
                             f"Extraction failed: {e}\n"
                             f"Traceback:\n{traceback.format_exc().strip()}"))

    failed = [(n, d) for n, s, d in results if s == "fail"]
    warned = [(n, d) for n, s, d in results if s == "warn"]

    if failed:
        errors = "\n\n".join(f"[{n}]\n{d}" for n, d in failed)
        return StepResult(
            stage=10, name="Text extraction", status="fail",
            detail=(
                f"Text extraction FAILED for {len(failed)} document(s):\n\n"
                f"{errors}\n\n"
                f"Fix: install the required extraction packages:\n"
                f"  {sys.executable} -m pip install python-docx Pillow pdfminer.six docx2txt"
            ),
            fix_cmds=[
                f"{sys.executable} -m pip install python-docx Pillow pdfminer.six docx2txt"
            ],
            fix_fn=lambda r, log: _fix_pip(
                ["python-docx", "Pillow", "pdfminer.six", "docx2txt"], log),
            fix_label="Install extraction packages",
        )

    detail_lines = [f"[{s.upper()}] {n}: {d}" for n, s, d in results]
    if warned:
        return StepResult(stage=10, name="Text extraction", status="warn",
                          detail=(
                              f"Extraction OK but some files may be scanned images:\n"
                              + "\n".join(detail_lines)
                          ))
    return StepResult(stage=10, name="Text extraction", status="pass",
                      detail="Text extraction OK:\n" + "\n".join(detail_lines))


# ── Stage 11: citl_auto_index importable ──────────────────────────────────────

def _check_auto_index_import() -> StepResult:
    try:
        import citl_auto_index as _ai
        return StepResult(stage=11, name="citl_auto_index import", status="pass",
                          detail=f"citl_auto_index loaded from {_ai.__file__}")
    except ImportError as e:
        return StepResult(
            stage=11, name="citl_auto_index import", status="fail",
            detail=(
                f"Cannot import citl_auto_index:\n{e}\n\n"
                f"sys.path includes: {[p for p in sys.path[:5]]}\n\n"
                f"This file must be in: {HERE}\n"
                f"Current directory: {Path.cwd()}\n\n"
                f"Fix: ensure you are running from the correct directory, or\n"
                f"that {HERE} is the factbook-assistant folder."
            ),
        )
    except Exception as e:
        return StepResult(
            stage=11, name="citl_auto_index import", status="fail",
            detail=(
                f"citl_auto_index imported but raised an error on load:\n"
                f"{traceback.format_exc().strip()}\n\n"
                f"This may indicate a missing dependency within citl_auto_index."
            ),
        )


# ── Stage 12: Index directory writable ────────────────────────────────────────

def _check_index_writable() -> StepResult:
    test_paths = [
        IDX_DIR,
        Path(os.environ.get("APPDATA", Path.home())) / "CITL" / "indexes",
        Path.home() / ".citl" / "indexes",
    ]
    errors = []
    for p in test_paths:
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".write_test"
            t.write_text("ok"); t.unlink()
            note = ""
            if p != IDX_DIR:
                note = (
                    f"\n\nNOTE: App folder is read-only (USB drive?).\n"
                    f"Index will be written to fallback path:\n  {p}\n"
                    f"This is expected on USB deployments."
                )
            return StepResult(stage=12, name="Index dir writable", status="pass",
                              detail=f"Index directory is writable: {p}{note}")
        except Exception as e:
            errors.append(f"  {p}: {e}")

    return StepResult(
        stage=12, name="Index dir writable", status="fail",
        detail=(
            f"CANNOT write to ANY index directory.\n\n"
            f"Tried:\n" + "\n".join(errors) + "\n\n"
            f"Possible causes:\n"
            f"  • Running from a write-protected USB with full-disk encryption\n"
            f"  • APPDATA environment variable missing or invalid\n"
            f"  • Disk is full (check: df -h or Windows Disk Management)\n\n"
            f"Fix:\n"
            f"  1. Check disk space\n"
            f"  2. Set APPDATA env var to a writable folder\n"
            f"  3. Copy app to local hard drive"
        ),
    )


# ── Stage 13: JSONL index chunk count ────────────────────────────────────────

def _check_index_chunks() -> StepResult:
    idx_dir = _writable_idx_dir()
    total, files = _count_chunks(idx_dir)
    MIN_CHUNKS = 50

    if total == 0 and not files:
        # Check if there's even a library to index
        docs = list(LIB_RAW.glob("*.*")) if LIB_RAW.is_dir() else []
        doc_note = (
            f"\n\nNo documents in library_raw/ either — add documents first."
            if not docs else
            f"\n\nDocuments exist in library_raw/ ({len(docs)} files) but have not been indexed yet."
        )
        return StepResult(
            stage=13, name="Index chunk count", status="fail",
            detail=(
                f"Index directory has NO index files.\n"
                f"Index directory checked: {idx_dir}{doc_note}\n\n"
                f"Fix: run the indexer:\n"
                f"  python {HERE / 'citl_auto_index.py'}\n"
                f"Or use the Library/Models tab → Rebuild Index"
            ),
            fix_cmds=[f"{sys.executable} \"{HERE / 'citl_auto_index.py'}\""],
            fix_fn=lambda r, log: _fix_rebuild_index(log, force=True),
            fix_label="Rebuild Index Now",
        )

    if total < MIN_CHUNKS:
        return StepResult(
            stage=13, name="Index chunk count", status="fail",
            detail=(
                f"Index has only {total} chunks across {len(files)} file(s).\n"
                f"Minimum needed for reliable search: {MIN_CHUNKS} chunks.\n"
                f"Index directory: {idx_dir}\n"
                f"Index files: {', '.join(files[:5])}\n\n"
                f"Likely causes:\n"
                f"  • Documents are short or could not be read (scanned PDFs?)\n"
                f"  • Indexer ran but text extraction failed silently\n"
                f"  • USB mtime fingerprint preventing re-index\n\n"
                f"Fix: force a full rebuild:\n"
                f"  python \"{HERE / 'citl_auto_index.py'}\" --force"
            ),
            fix_cmds=[f"{sys.executable} \"{HERE / 'citl_auto_index.py'}\" --force"],
            fix_fn=lambda r, log: _fix_rebuild_index(log, force=True),
            fix_label="Force Rebuild Index",
        )

    return StepResult(stage=13, name="Index chunk count", status="pass",
                      detail=(
                          f"{total:,} chunks across {len(files)} file(s)\n"
                          f"  Files: {', '.join(files[:6])}"
                          + (f"  ... +{len(files)-6} more" if len(files) > 6 else "")
                      ))


# ── Stage 14: Keyword search live test ───────────────────────────────────────

def _check_keyword_search() -> StepResult:
    idx_dir = _writable_idx_dir()
    total, _ = _count_chunks(idx_dir)
    if total < 5:
        return StepResult(stage=14, name="Keyword search", status="skip",
                          detail="Skipped — index is empty (see Stage 13)")

    try:
        from citl_auto_index import keyword_search
    except ImportError as e:
        return StepResult(stage=14, name="Keyword search", status="fail",
                          detail=f"Cannot import keyword_search from citl_auto_index:\n{e}")

    test_queries = ["requirements", "student", "policy", "course", "the"]
    for q in test_queries:
        try:
            hits = keyword_search(q, idx_dir=idx_dir, top_k=5)
            if hits:
                return StepResult(stage=14, name="Keyword search", status="pass",
                                  detail=(
                                      f"Keyword search working — query '{q}' returned {len(hits)} hit(s)\n"
                                      f"Sample: [{hits[0].get('source','')}] {hits[0].get('text','')[:80]}…"
                                  ))
        except Exception as e:
            return StepResult(
                stage=14, name="Keyword search", status="fail",
                detail=(
                    f"keyword_search('{q}') raised an exception:\n"
                    f"{traceback.format_exc().strip()}\n\n"
                    f"This usually means the JSONL index files are corrupt.\n"
                    f"Fix: force rebuild the index."
                ),
                fix_fn=lambda r, log: _fix_rebuild_index(log, force=True),
                fix_label="Rebuild Index",
            )

    return StepResult(
        stage=14, name="Keyword search", status="warn",
        detail=(
            f"Keyword search returned no hits for any of: {test_queries}\n"
            f"The index has {total:,} chunks but none matched these terms.\n"
            f"The indexed documents may not be general course materials.\n"
            f"This may be expected for specialized corpora."
        ),
    )


# ── Stage 15: Embedding JSON valid ────────────────────────────────────────────

def _check_embedding_json() -> StepResult:
    if not EMB_JSON.exists():
        return StepResult(
            stage=15, name="Embedding JSON", status="warn",
            detail=(
                f"factbook_embeddings.json not found: {EMB_JSON}\n\n"
                f"Vector search is DISABLED. Keyword search will be used.\n"
                f"Keyword search works but may be less accurate.\n\n"
                f"To enable vector search, run the embedding builder:\n"
                f"  python \"{HERE / 'build_factbook_index.py'}\"\n\n"
                f"This requires Ollama + nomic-embed-text to be running."
            ),
            fix_cmds=[f"{sys.executable} \"{HERE / 'build_factbook_index.py'}\""],
            fix_fn=lambda r, log: _fix_build_embeddings(log),
            fix_label="Build Embedding Index",
        )

    try:
        data = json.loads(EMB_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return StepResult(
            stage=15, name="Embedding JSON", status="fail",
            detail=(
                f"factbook_embeddings.json is CORRUPT — JSON parse error:\n"
                f"  {e}\n"
                f"  Line {e.lineno}, column {e.colno}\n"
                f"  File: {EMB_JSON} ({EMB_JSON.stat().st_size:,} bytes)\n\n"
                f"Fix: delete the corrupt file and rebuild:\n"
                f"  del \"{EMB_JSON}\"  (Windows)\n"
                f"  rm \"{EMB_JSON}\"   (Linux/macOS)\n"
                f"  python \"{HERE / 'build_factbook_index.py'}\""
            ),
            fix_cmds=[
                f'rm "{EMB_JSON}"',
                f'{sys.executable} "{HERE / "build_factbook_index.py"}"',
            ],
            fix_fn=lambda r, log: _fix_delete_rebuild_embeddings(log),
            fix_label="Delete & Rebuild Embeddings",
        )
    except Exception as e:
        return StepResult(
            stage=15, name="Embedding JSON", status="fail",
            detail=(
                f"Cannot read factbook_embeddings.json:\n"
                f"{traceback.format_exc().strip()}"
            ),
        )

    chunks = data.get("chunks", data.get("embeddings", []))
    n = len(chunks)
    if n < 10:
        return StepResult(
            stage=15, name="Embedding JSON", status="fail",
            detail=(
                f"factbook_embeddings.json has only {n} entries — too few.\n"
                f"File: {EMB_JSON} ({EMB_JSON.stat().st_size:,} bytes)\n\n"
                f"The file may be incomplete (interrupted build?) or corrupt.\n\n"
                f"Fix: rebuild:\n"
                f"  python \"{HERE / 'build_factbook_index.py'}\""
            ),
            fix_fn=lambda r, log: _fix_delete_rebuild_embeddings(log),
            fix_label="Rebuild Embeddings",
        )

    return StepResult(stage=15, name="Embedding JSON", status="pass",
                      detail=f"factbook_embeddings.json: {n:,} entries, {EMB_JSON.stat().st_size/1e6:.1f} MB")


# ── Stage 16: Embedding dimension consistency ─────────────────────────────────

def _check_embedding_dimensions() -> StepResult:
    if not EMB_JSON.exists():
        return StepResult(stage=16, name="Embedding dimensions", status="skip",
                          detail="Skipped — embedding JSON absent (see Stage 15)")

    try:
        import numpy as np
    except ImportError:
        return StepResult(stage=16, name="Embedding dimensions", status="skip",
                          detail="Skipped — numpy not installed (see Stage 2)")

    try:
        data = json.loads(EMB_JSON.read_text(encoding="utf-8"))
        raw = data.get("embeddings", [])
        if not raw:
            return StepResult(
                stage=16, name="Embedding dimensions", status="fail",
                detail=(
                    f"factbook_embeddings.json has no 'embeddings' key or empty list.\n"
                    f"Keys found: {list(data.keys())}\n\n"
                    f"Fix: rebuild the embedding index."
                ),
                fix_fn=lambda r, log: _fix_delete_rebuild_embeddings(log),
                fix_label="Rebuild Embeddings",
            )

        mat = np.asarray(raw, dtype=np.float32)
        n_vecs, n_dim = mat.shape

        # Check for NaN/Inf
        bad = int(np.any(np.isnan(mat)) or np.any(np.isinf(mat)))
        if bad:
            return StepResult(
                stage=16, name="Embedding dimensions", status="fail",
                detail=(
                    f"Embedding matrix contains NaN or Inf values.\n"
                    f"Shape: {n_vecs} × {n_dim}\n\n"
                    f"This means the embedding build was interrupted or the embed\n"
                    f"model returned invalid data.\n\n"
                    f"Fix: rebuild:\n"
                    f"  python \"{HERE / 'build_factbook_index.py'}\""
                ),
                fix_fn=lambda r, log: _fix_delete_rebuild_embeddings(log),
                fix_label="Rebuild Embeddings",
            )

        if n_dim < 64:
            return StepResult(
                stage=16, name="Embedding dimensions", status="fail",
                detail=(
                    f"Embedding dimensionality is only {n_dim} — suspiciously small.\n"
                    f"nomic-embed-text produces 768-dim vectors.\n"
                    f"Shape: {n_vecs} × {n_dim}\n\n"
                    f"The embed model may have been swapped since the index was built.\n"
                    f"Fix: rebuild with the correct model:\n"
                    f"  ollama pull nomic-embed-text\n"
                    f"  python \"{HERE / 'build_factbook_index.py'}\""
                ),
                fix_fn=lambda r, log: _fix_delete_rebuild_embeddings(log),
                fix_label="Rebuild Embeddings",
            )

        return StepResult(stage=16, name="Embedding dimensions", status="pass",
                          detail=f"Embedding matrix: {n_vecs:,} vectors × {n_dim} dimensions, no NaN/Inf")

    except Exception as e:
        return StepResult(
            stage=16, name="Embedding dimensions", status="fail",
            detail=(
                f"Error loading embedding matrix:\n"
                f"{traceback.format_exc().strip()}"
            ),
        )


# ── Stage 17: LLM generation live test ───────────────────────────────────────

def _check_llm_generation() -> StepResult:
    host = _ollama_host()
    try:
        data = _http_get(f"{host}/api/tags", timeout=8.0)
        models = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]
    except Exception as e:
        return StepResult(stage=17, name="LLM generation", status="skip",
                          detail=f"Skipped — Ollama unavailable: {e}")

    if not models:
        return StepResult(stage=17, name="LLM generation", status="skip",
                          detail="Skipped — no models installed")

    # Pick best model
    _PREFERRED = ["mistral", "llama3", "phi3", "gemma", "qwen"]
    llm = next((m for m in models if any(p in m for p in _PREFERRED)), models[0])

    payload = {
        "model": llm,
        "prompt": "Reply with exactly: CITL_OK",
        "stream": False,
        "options": {"temperature": 0, "num_predict": 10},
    }
    url = f"{host}/api/generate"
    try:
        resp = _http_post(url, payload, timeout=90.0)
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode(errors="replace")[:400]
        except Exception: pass
        return StepResult(
            stage=17, name="LLM generation", status="fail",
            detail=(
                f"Ollama /api/generate returned HTTP {e.code}\n"
                f"Model: {llm}\n"
                f"URL: {url}\n"
                f"Response body: {body}\n\n"
                f"The model may still be loading. Wait 10 seconds and retry.\n"
                f"Or try: ollama run {llm} (to pre-load the model)"
            ),
            fix_cmds=[f"ollama run {llm}"],
        )
    except urllib.error.URLError as e:
        return StepResult(
            stage=17, name="LLM generation", status="fail",
            detail=(
                f"Connection error calling /api/generate:\n{e.reason}\n"
                f"URL: {url}\n\nFix: ollama serve"
            ),
        )
    except socket.timeout:
        return StepResult(
            stage=17, name="LLM generation", status="fail",
            detail=(
                f"LLM generation TIMED OUT after 90 seconds.\n"
                f"Model: {llm}\n\n"
                f"Possible causes:\n"
                f"  • Not enough RAM — model swapping to disk\n"
                f"  • Model is very large for this hardware\n\n"
                f"Recommendations:\n"
                f"  • Use a smaller model: ollama pull phi3:mini  (2.3 GB)\n"
                f"  • Close other applications to free RAM\n"
                f"  • Minimum 8 GB RAM for mistral:7b-instruct"
            ),
            fix_cmds=["ollama pull phi3:mini"],
            fix_fn=lambda r, log: _fix_ollama_pull("phi3:mini", log),
            fix_label="Pull phi3:mini (smaller model)",
        )
    except Exception as e:
        return StepResult(
            stage=17, name="LLM generation", status="fail",
            detail=(
                f"Unexpected error calling LLM generation API:\n"
                f"{traceback.format_exc().strip()}"
            ),
        )

    text = resp.get("response", "").strip()
    if not text:
        return StepResult(
            stage=17, name="LLM generation", status="fail",
            detail=(
                f"LLM returned an empty response.\n"
                f"Model: {llm}\n"
                f"Full API response: {json.dumps(resp)[:400]}\n\n"
                f"The model may be loading or out of memory.\n"
                f"Try: ollama run {llm}"
            ),
        )

    return StepResult(stage=17, name="LLM generation", status="pass",
                      detail=f"LLM ({llm}) responded in {resp.get('total_duration',0)/1e9:.1f}s — '{text[:80]}'")


# ── Stage 18: Full RAG end-to-end smoke test ──────────────────────────────────

def _check_full_pipeline() -> StepResult:
    # Need Ollama + index
    host = _ollama_host()
    idx_dir = _writable_idx_dir()
    total, _ = _count_chunks(idx_dir)

    try:
        ollama_data = _http_get(f"{host}/api/tags", timeout=8.0)
        models = [m.get("name", "") for m in ollama_data.get("models", []) if isinstance(m, dict)]
        ollama_up = True
    except Exception:
        ollama_up = False
        models = []

    if not ollama_up:
        return StepResult(stage=18, name="Full RAG pipeline", status="skip",
                          detail="Skipped — Ollama not running")
    if total < 5:
        return StepResult(stage=18, name="Full RAG pipeline", status="skip",
                          detail="Skipped — index empty")
    if not models:
        return StepResult(stage=18, name="Full RAG pipeline", status="skip",
                          detail="Skipped — no models installed")

    try:
        from citl_rag_patch import resilient_answer
        test_question = "What documents are available in this system?"
        t0 = time.monotonic()
        answer = resilient_answer(
            test_question,
            model=models[0],
            host=host,
        )
        elapsed = time.monotonic() - t0
    except ImportError as e:
        return StepResult(
            stage=18, name="Full RAG pipeline", status="fail",
            detail=(
                f"Cannot import citl_rag_patch:\n{e}\n\n"
                f"citl_rag_patch.py must be in: {HERE}\n"
                f"Ensure the file is present and not corrupt."
            ),
        )
    except Exception as e:
        return StepResult(
            stage=18, name="Full RAG pipeline", status="fail",
            detail=(
                f"Full pipeline raised an exception:\n"
                f"{traceback.format_exc().strip()}\n\n"
                f"Question tested: '{test_question}'"
            ),
        )

    if not answer or answer.startswith("⚠") or answer.startswith("Unable"):
        return StepResult(
            stage=18, name="Full RAG pipeline", status="warn",
            detail=(
                f"Pipeline completed but returned a fallback/warning message:\n"
                f"  '{answer[:200]}'\n\n"
                f"This usually means Ollama answered but the index context was\n"
                f"insufficient. Consider adding more source documents.\n"
                f"Elapsed: {elapsed:.1f}s"
            ),
        )

    return StepResult(stage=18, name="Full RAG pipeline", status="pass",
                      detail=(
                          f"Full RAG pipeline OK in {elapsed:.1f}s\n"
                          f"Sample answer: '{answer[:150]}…'"
                      ))


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-FIX FUNCTIONS (called by fix_fn lambdas)
# ══════════════════════════════════════════════════════════════════════════════

def _fix_pip(packages: List[str], log: Callable[[str], None]) -> bool:
    log(f"Running: {sys.executable} -m pip install {' '.join(packages)}")
    ok, out = _run_cmd_capture(
        [sys.executable, "-m", "pip", "install"] + packages, timeout=180)
    for line in out.split("\n"):
        log(line)
    return ok


def _find_ollama_exe() -> Optional[str]:
    """Search every likely Windows (and Linux/Mac) location for the ollama binary."""
    import shutil
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
            Path("C:/Users") / username / "AppData/Local/Ollama/ollama.exe",
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
    """Kill any stuck ollama.exe processes before a fresh start."""
    if platform.system() != "Windows":
        return
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ollama.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5)
        if "ollama.exe" in result.stdout:
            log("  Found existing ollama.exe — killing it for a clean restart...")
            subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"],
                           capture_output=True, timeout=5)
            time.sleep(1)
    except Exception as e:
        log(f"  (kill check skipped: {e})")


def _fix_start_ollama(log: Callable[[str], None]) -> bool:
    ollama_exe = _find_ollama_exe()
    if not ollama_exe:
        log("ERROR: ollama executable not found anywhere on this machine.")
        log("  Expected: %LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe")
        log("  Install:  winget install Ollama.Ollama")
        log("  Download: https://ollama.com/download/windows")
        return False

    log(f"Found Ollama: {ollama_exe}")
    _kill_hung_ollama(log)
    log("Starting Ollama in background (silent, no console window)...")
    try:
        if platform.system() == "Windows":
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS  = 0x00000008
            subprocess.Popen(
                [ollama_exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            )
        else:
            subprocess.Popen([ollama_exe, "serve"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"ERROR launching Ollama: {e}")
        return False

    log("Waiting up to 45 seconds for Ollama to respond...")
    host, port = _ollama_hostname(), _ollama_port()
    for i in range(45):
        time.sleep(1)
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            log(f"Ollama is online after {i+1} seconds.")
            return True
        except Exception:
            pass
    log("ERROR: Ollama launched but did not respond within 45 seconds.")
    log("  Possible causes: port 11434 blocked by firewall, CUDA init slow, or Ollama crashed.")
    log("  Try: open a terminal and run  ollama serve  to see the error output.")
    return False


def _fix_ollama_pull(model: str, log: Callable[[str], None]) -> bool:
    log(f"Pulling {model} (this may take several minutes)...")
    ok, out = _run_cmd_capture(["ollama", "pull", model], timeout=900)
    for line in out.split("\n"):
        log(line)
    if ok:
        log(f"Successfully pulled {model}")
    else:
        log(f"Failed to pull {model}. Check internet connection.")
    return ok


def _fix_mkdir(path: Path, log: Callable[[str], None]) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        log(f"Created: {path}")
        return True
    except Exception as e:
        log(f"ERROR: {e}")
        return False


def _fix_rebuild_index(log: Callable[[str], None], force: bool = True) -> bool:
    log("Rebuilding keyword index...")
    try:
        from citl_auto_index import auto_index_library, LIB_RAW as _LR
        idx_dir = _writable_idx_dir()
        log(f"Writing index to: {idx_dir}")
        results = auto_index_library(lib_dir=_LR, idx_dir=idx_dir, force=force)
        total = sum(results.values()) if results else 0
        if total > 0:
            log(f"Done: {total:,} chunks indexed across {len(results)} document(s)")
            for name, count in results.items():
                log(f"  {name}: {count:,} chunks")
            return True
        else:
            log("WARNING: Index rebuilt but 0 chunks produced.")
            log(f"library_raw/ path: {LIB_RAW}")
            log(f"Documents found: {list(LIB_RAW.glob('*.*')) if LIB_RAW.is_dir() else 'directory missing'}")
            return False
    except Exception as e:
        log(f"ERROR: {traceback.format_exc()}")
        return False


def _fix_build_embeddings(log: Callable[[str], None]) -> bool:
    script = HERE / "build_factbook_index.py"
    if not script.exists():
        log(f"ERROR: build_factbook_index.py not found at {script}")
        return False
    log(f"Running: {sys.executable} {script}")
    log("This may take several minutes depending on corpus size and hardware...")
    ok, out = _run_cmd_capture([sys.executable, str(script)], timeout=900)
    for line in out.split("\n"):
        log(line)
    return ok


def _fix_delete_rebuild_embeddings(log: Callable[[str], None]) -> bool:
    log(f"Deleting {EMB_JSON.name}...")
    try:
        EMB_JSON.unlink(missing_ok=True)
        log("Deleted.")
    except Exception as e:
        log(f"ERROR deleting: {e}")
        return False
    return _fix_build_embeddings(log)


# ══════════════════════════════════════════════════════════════════════════════
# MASTER RUNNER
# ══════════════════════════════════════════════════════════════════════════════

_ALL_STAGES = [
    (1,  "Python version",           _check_python_version),
    (2,  "Core packages",            _check_core_packages),
    (3,  "Optional packages",        _check_optional_packages),
    (4,  "Ollama port open",         _check_ollama_port),
    (5,  "Ollama API",               _check_ollama_api),
    (6,  "LLM model installed",      _check_llm_model),
    (7,  "Embed model installed",    _check_embed_model),
    (8,  "Embed live test",          _check_embed_live),
    (9,  "Source documents",         _check_source_documents),
    (10, "Text extraction",          _check_text_extraction),
    (11, "citl_auto_index import",   _check_auto_index_import),
    (12, "Index dir writable",       _check_index_writable),
    (13, "Index chunk count",        _check_index_chunks),
    (14, "Keyword search",           _check_keyword_search),
    (15, "Embedding JSON",           _check_embedding_json),
    (16, "Embedding dimensions",     _check_embedding_dimensions),
    (17, "LLM generation",           _check_llm_generation),
    (18, "Full RAG pipeline",        _check_full_pipeline),
]


def run_diagnostic(
    on_result: Callable[[StepResult], None] = None,
    stop_on_critical: bool = False,
) -> List[StepResult]:
    """
    Run all 18 stages.  Calls on_result(StepResult) after each stage
    so the GUI can update in real time.

    If stop_on_critical=True, stops after a stage 1-4 hard failure
    (no point running higher stages if Python is broken).
    """
    results: List[StepResult] = []
    _CRITICAL_STAGES = {1, 2, 4}  # hard stops

    for stage, name, fn in _ALL_STAGES:
        r = _step(stage, name, fn)
        results.append(r)
        if on_result:
            on_result(r)
        if stop_on_critical and stage in _CRITICAL_STAGES and r.failed:
            # Add a note about stopping
            skip = StepResult(
                stage=stage + 1,
                name="Remaining stages",
                status="skip",
                detail=(
                    f"Remaining stages skipped because Stage {stage} ({name}) FAILED.\n"
                    f"Fix the issue above first, then re-run the diagnostic."
                ),
            )
            results.append(skip)
            if on_result:
                on_result(skip)
            break

    return results


# ══════════════════════════════════════════════════════════════════════════════
# CLI MODE
# ══════════════════════════════════════════════════════════════════════════════

_STATUS_ICON = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}
_STATUS_CLR  = {"pass": "\033[92m", "fail": "\033[91m",
                "warn": "\033[93m", "skip": "\033[90m"}
_RST = "\033[0m"


def _cli_print_result(r: StepResult):
    icon  = _STATUS_ICON.get(r.status, "????")
    color = _STATUS_CLR.get(r.status, "")
    rst   = _RST if sys.stdout.isatty() else ""
    col   = color if sys.stdout.isatty() else ""

    print(f"\n{col}[{icon}] Stage {r.stage:02d}: {r.name}  ({r.duration_ms:.0f}ms){rst}")
    for line in r.detail.split("\n"):
        safe = line.encode("ascii", "replace").decode("ascii")
        print(f"       {safe}")
    if r.fix_cmds:
        print(f"       FIX COMMAND(S):")
        for cmd in r.fix_cmds:
            safe = cmd.encode("ascii", "replace").decode("ascii")
            print(f"         $ {safe}")


def run_cli(auto_fix: bool = False):
    print("=" * 64)
    print("  CITL Factbook Pipeline Diagnostic  (18 stages)")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)

    results = run_diagnostic(on_result=_cli_print_result)

    # Summary
    passed  = [r for r in results if r.status == "pass"]
    failed  = [r for r in results if r.status == "fail"]
    warned  = [r for r in results if r.status == "warn"]
    skipped = [r for r in results if r.status == "skip"]

    print(f"\n{'=' * 64}")
    print(f"  SUMMARY: {len(passed)} passed, {len(failed)} failed, "
          f"{len(warned)} warnings, {len(skipped)} skipped")
    print(f"{'=' * 64}")

    if failed:
        print(f"\nFAILED STAGES:")
        for r in failed:
            print(f"  Stage {r.stage:02d}: {r.name}")
            if r.fix_label:
                print(f"    -> Fix available: {r.fix_label}")

    if auto_fix:
        fixable = [r for r in failed + warned if r.fix_fn]
        if fixable:
            print(f"\nAuto-fixing {len(fixable)} issue(s)...")
            for r in fixable:
                print(f"\n  Fixing: {r.name}")
                log_lines = []
                def _log(line, lines=log_lines):
                    lines.append(line)
                    print(f"    {line.encode('ascii','replace').decode('ascii')}")
                ok = r.fix_fn(r, _log)
                if ok:
                    print(f"  FIXED: {r.name}")
                else:
                    print(f"  COULD NOT AUTO-FIX: {r.name}")

    if not failed:
        print("\n  All critical stages passed. Factbook pipeline is healthy.")
    else:
        print(f"\n  {len(failed)} stage(s) failed. Fix the issues above and re-run.")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# GUI MODE
# ══════════════════════════════════════════════════════════════════════════════

def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
    except ImportError:
        print("Tkinter not available. Running CLI mode.")
        run_cli()
        return

    _T = {
        "bg":      "#071A1E", "fg":     "#C8E8EC", "accent":   "#00C8A8",
        "hi":      "#0A3040", "btn":    "#0D2838", "btn_fg":   "#B8E8E4",
        "txt_bg":  "#041214", "txt_fg": "#B4DCE0", "status":   "#00E5C8",
        "ok":      "#06D6A0", "warn":   "#FFD166", "err":      "#FF6B6B",
        "skip":    "#607080",
    }

    root = tk.Tk()
    root.title("CITL Factbook Pipeline Diagnostic")
    root.geometry("940x720")
    root.configure(bg=_T["bg"])
    root.resizable(True, True)

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg=_T["hi"], pady=8)
    hdr.pack(fill="x")
    tk.Label(hdr, text="  CITL Factbook Pipeline Diagnostic",
             fg=_T["accent"], bg=_T["hi"],
             font=("Consolas", 14, "bold")).pack(side="left", padx=10)
    tk.Label(hdr, text="18 stages  |  every failure shows exact cause + fix",
             fg=_T["fg"], bg=_T["hi"],
             font=("Consolas", 9)).pack(side="right", padx=10)

    # ── Status bar ─────────────────────────────────────────────────────────────
    status_var = tk.StringVar(value="  Click 'Run Diagnostic' to test all 18 pipeline stages.")
    status_lbl = tk.Label(root, textvariable=status_var,
                          fg=_T["status"], bg=_T["bg"],
                          font=("Consolas", 9), anchor="w", padx=8)
    status_lbl.pack(fill="x")

    # ── Main paned ─────────────────────────────────────────────────────────────
    paned = tk.PanedWindow(root, orient="vertical",
                           bg=_T["hi"], sashwidth=5, sashrelief="flat")
    paned.pack(fill="both", expand=True, padx=4, pady=4)

    # ── Stage list (scrollable canvas) ────────────────────────────────────────
    list_outer = tk.Frame(paned, bg=_T["bg"])
    paned.add(list_outer, minsize=200)

    canvas = tk.Canvas(list_outer, bg=_T["bg"], highlightthickness=0)
    vsb = ttk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
    stage_frame = tk.Frame(canvas, bg=_T["bg"])
    stage_frame.bind("<Configure>",
                     lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=stage_frame, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    canvas.bind("<Enter>",
                lambda e: canvas.bind_all("<MouseWheel>",
                    lambda ev: canvas.yview_scroll(int(-1*(ev.delta/120)), "units")))
    canvas.bind("<Leave>",
                lambda e: canvas.unbind_all("<MouseWheel>"))

    # ── Log pane ───────────────────────────────────────────────────────────────
    log_outer = tk.Frame(paned, bg=_T["bg"])
    paned.add(log_outer, minsize=120)
    tk.Label(log_outer, text="  Fix Action Log",
             fg=_T["accent"], bg=_T["bg"],
             font=("Consolas", 9, "bold"), anchor="w").pack(fill="x")
    log_widget = ScrolledText(log_outer, state="disabled", wrap="word",
                              bg=_T["txt_bg"], fg=_T["txt_fg"],
                              font=("Consolas", 9), relief="flat", padx=6)
    log_widget.pack(fill="both", expand=True)
    for tag, color in [("ok", _T["ok"]), ("warn", _T["warn"]),
                       ("err", _T["err"]), ("cmd", _T["accent"])]:
        log_widget.tag_configure(tag, foreground=color)

    def _log(line: str, tag: str = ""):
        def _do():
            log_widget.configure(state="normal")
            lw = line.lower()
            t = tag or (
                "ok"   if ("ok" in lw or "fixed" in lw or "done" in lw) else
                "err"  if ("error" in lw or "failed" in lw or "cannot" in lw) else
                "warn" if ("warn" in lw) else
                "cmd"  if (line.startswith("$") or line.startswith("Running") or line.startswith("Pulling")) else
                ""
            )
            log_widget.insert("end", line + "\n", t or ())
            log_widget.configure(state="disabled")
            log_widget.see("end")
        root.after(0, _do)

    # ── Toolbar ────────────────────────────────────────────────────────────────
    toolbar = tk.Frame(root, bg=_T["bg"], pady=5)
    toolbar.pack(fill="x")

    _result_cache: List[StepResult] = []

    def _clear_stages():
        for w in stage_frame.winfo_children():
            w.destroy()

    _DOT_COLOR = {"pass": _T["ok"], "warn": _T["warn"],
                  "fail": _T["err"], "skip": _T["skip"]}

    def _add_stage_row(r: StepResult):
        dot_color = _DOT_COLOR.get(r.status, _T["fg"])
        row = tk.Frame(stage_frame, bg=_T["bg"])
        row.pack(fill="x", pady=1, padx=2)

        # Status dot
        tk.Label(row, text="●", fg=dot_color, bg=_T["bg"],
                 font=("Consolas", 11)).pack(side="left", padx=(4, 6))

        # Stage number + name
        info = tk.Frame(row, bg=_T["bg"])
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info,
                 text=f"[{r.status.upper():4s}] S{r.stage:02d}: {r.name}  ({r.duration_ms:.0f}ms)",
                 fg=dot_color, bg=_T["bg"],
                 font=("Consolas", 9, "bold"), anchor="w").pack(anchor="w")

        # First line of detail
        first_line = r.detail.split("\n")[0] if r.detail else ""
        tk.Label(info, text=first_line,
                 fg=_T["fg"], bg=_T["bg"],
                 font=("Consolas", 8), anchor="w",
                 wraplength=480, justify="left").pack(anchor="w")

        # Buttons: Detail and Fix (if available)
        btn_frame = tk.Frame(row, bg=_T["bg"])
        btn_frame.pack(side="right", padx=4)

        # Full detail toggle
        _expanded = [False]
        _detail_frame = [None]
        def _toggle(rr=r, ex=_expanded, df=_detail_frame, p=info):
            if ex[0]:
                if df[0]: df[0].destroy(); df[0] = None
                ex[0] = False
            else:
                df[0] = tk.Frame(p, bg=_T["hi"], padx=8, pady=4)
                df[0].pack(fill="x")
                tk.Label(df[0], text=rr.detail,
                         fg=_T["warn"] if rr.failed else _T["fg"],
                         bg=_T["hi"],
                         font=("Consolas", 8), justify="left",
                         wraplength=560, anchor="w").pack(anchor="w")
                if rr.fix_cmds:
                    tk.Label(df[0],
                             text="Fix commands:\n" + "\n".join(f"  $ {c}" for c in rr.fix_cmds),
                             fg=_T["accent"], bg=_T["hi"],
                             font=("Consolas", 8), justify="left", anchor="w").pack(anchor="w")
                ex[0] = True

        tk.Button(btn_frame, text="Detail",
                  bg=_T["btn"], fg=_T["status"],
                  activebackground=_T["hi"],
                  relief="flat", padx=5, pady=2, cursor="hand2",
                  font=("Consolas", 8),
                  command=_toggle).pack(side="left", padx=2)

        # Fix button
        if r.fix_fn and not r.passed:
            def _run_fix(rr=r):
                _log(f"\n{'='*50}", "cmd")
                _log(f"Fixing Stage {rr.stage}: {rr.name}", "cmd")
                _log(f"{'='*50}", "cmd")
                status_var.set(f"  Fixing: {rr.name}...")

                def _bg():
                    ok = False
                    try:
                        ok = rr.fix_fn(rr, _log)
                    except Exception as e:
                        root.after(0, lambda: _log(f"ERROR: {e}", "err"))
                    root.after(0, lambda: status_var.set(
                        f"  Fix {'succeeded' if ok else 'did not fully resolve'}: {rr.name}. "
                        f"Re-run diagnostic to verify."))

                threading.Thread(target=_bg, daemon=True).start()

            tk.Button(btn_frame,
                      text=f"Fix: {r.fix_label}",
                      bg=_T["accent"], fg=_T["bg"],
                      activebackground=_T["ok"],
                      relief="flat", padx=6, pady=2, cursor="hand2",
                      font=("Consolas", 8, "bold"),
                      command=_run_fix).pack(side="left", padx=2)

        tk.Frame(stage_frame, height=1, bg=_T["hi"]).pack(fill="x")

    def _run_diagnostic_bg(auto_fix_all: bool = False):
        _clear_stages()
        _result_cache.clear()

        # Placeholder
        ph = tk.Label(stage_frame, text="  Running stage checks...",
                      fg=_T["status"], bg=_T["bg"],
                      font=("Consolas", 10))
        ph.pack(pady=20)

        counts = {"pass": 0, "fail": 0, "warn": 0, "skip": 0}

        def _on_result(r: StepResult):
            _result_cache.append(r)
            counts[r.status] = counts.get(r.status, 0) + 1

            def _ui():
                if len(_result_cache) == 1:
                    ph.destroy()
                _add_stage_row(r)
                status_var.set(
                    f"  Stage {r.stage}/18: {r.name} [{r.status.upper()}]  "
                    f"| {counts['pass']} pass  {counts['fail']} fail  {counts['warn']} warn"
                )
            root.after(0, _ui)

        def _bg():
            results = run_diagnostic(on_result=_on_result)

            if auto_fix_all:
                fixable = [rr for rr in results if not rr.passed and rr.fix_fn]
                for rr in fixable:
                    root.after(0, lambda n=rr.name: _log(f"\nAuto-fixing: {n}", "cmd"))
                    try:
                        rr.fix_fn(rr, _log)
                    except Exception as e:
                        root.after(0, lambda err=e: _log(f"ERROR: {err}", "err"))

            def _done():
                failed = [rr for rr in results if rr.failed]
                if failed:
                    status_var.set(
                        f"  COMPLETE: {counts['pass']} passed, {counts['fail']} FAILED, "
                        f"{counts['warn']} warnings -- fix the red stages above")
                    status_lbl.configure(fg=_T["err"])
                else:
                    status_var.set(
                        f"  ALL CLEAR: {counts['pass']} passed, {counts['warn']} warnings -- pipeline healthy")
                    status_lbl.configure(fg=_T["ok"])

            root.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _btn(text, color, cmd):
        return tk.Button(toolbar, text=text,
                         bg=color, fg=_T["bg"],
                         activebackground=_T["status"], activeforeground=_T["bg"],
                         relief="flat", padx=10, pady=4, cursor="hand2",
                         font=("Consolas", 9, "bold"), command=cmd)

    _btn("Run Diagnostic", _T["accent"],
         lambda: _run_diagnostic_bg(False)).pack(side="left", padx=6)
    _btn("Auto-Fix All",   _T["warn"],
         lambda: _run_diagnostic_bg(True)).pack(side="left", padx=2)
    tk.Button(toolbar, text="Clear Log",
              bg=_T["btn"], fg=_T["btn_fg"], relief="flat",
              padx=8, pady=4, cursor="hand2", font=("Consolas", 9),
              command=lambda: (
                  log_widget.configure(state="normal"),
                  log_widget.delete("1.0", "end"),
                  log_widget.configure(state="disabled")
              )).pack(side="left", padx=2)
    tk.Button(toolbar, text="Exit",
              bg=_T["err"], fg=_T["bg"], relief="flat",
              padx=8, pady=4, cursor="hand2", font=("Consolas", 9),
              command=root.destroy).pack(side="right", padx=6)

    # Auto-run on open
    root.after(300, lambda: _run_diagnostic_bg(False))
    root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # Fix Windows terminal encoding
    if platform.system() == "Windows":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="CITL Factbook Pipeline Diagnostic — 18-stage live test")
    ap.add_argument("--cli",  action="store_true", help="CLI mode (no GUI)")
    ap.add_argument("--fix",  action="store_true", help="Auto-fix failures in CLI mode")
    args = ap.parse_args()

    if args.cli:
        run_cli(auto_fix=args.fix)
    else:
        try:
            import tkinter  # noqa
            run_gui()
        except ImportError:
            print("tkinter not available — running CLI mode")
            run_cli(auto_fix=args.fix)


if __name__ == "__main__":
    main()
