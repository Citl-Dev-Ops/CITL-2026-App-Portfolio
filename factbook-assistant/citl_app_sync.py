#!/usr/bin/env python3
"""
Cross-platform CITL app sync utility.

Purpose:
- Detect USB/external copies of CITL repositories with similar layout.
- Sync this repo's app files to the selected target copy.
- Provide a small GUI utility that runs on Ubuntu and Windows.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]
LogFn = Optional[Callable[[str], None]]
APP_SYNC_NAME = "CITL App Sync Utility"
APP_SYNC_VERSION = "v1.6.3"
SYNC_LAUNCHER_WINDOWS = "RUN_APP_SYNC_WINDOWS.cmd"
SYNC_LAUNCHER_UBUNTU = "RUN_APP_SYNC_UBUNTU.sh"
SYNC_DUPLICATE_WINDOWS = "COPY_THIS_USB_TO_NEXT_WINDOWS.cmd"
SYNC_DUPLICATE_UBUNTU = "COPY_THIS_USB_TO_NEXT_UBUNTU.sh"
SYNC_LAUNCHER_README = "OPEN_SYNC_UTILITY_README.txt"
STATE_SCHEMA_VERSION = 1
STATE_FILE_NAME = "citl_app_sync_state.json"
UPDATE_AVAILABLE_EPSILON_SEC = 2.0
MODEL_SYNC_WARN_BYTES = 8 * 1024 * 1024 * 1024  # 8 GiB

REPO_MARKERS: Tuple[str, ...] = (
    "factbook-assistant/factbook_assistant_gui.py",
    "factbook_assistant_gui.py",
    "RUN_FACTBOOK.sh",
    "Run-CITL.ps1",
    "run_citl_factbook_gui_ffmpeg.ps1",
)

# ── CITL app registry ─────────────────────────────────────────────────────────
# "Factbook" is the umbrella name for the main desktop LLM utility.
# It encompasses: Study/Library Q&A, Transcription, Translation, TTS, and App Sync.
# Other distinct CITL apps (each may live in their own repo) are listed below it.
CITL_APPS: Tuple[dict, ...] = (
    {
        # ── UMBRELLA: everything that ships as the "Factbook" desktop app ──────
        "name": "Factbook",
        "description": (
            "Main CITL desktop LLM utility — Study & Library Q&A, "
            "Transcription, Translation, TTS, and corpus management. "
            "All components ship together as 'Factbook'."
        ),
        "icon": "📚",
        "key_files": [
            "factbook-assistant/factbook_assistant_gui.py",
            "factbook-assistant/citl_factbook_query.py",
            "factbook-assistant/citl_auto_index.py",
            "factbook-assistant/citl_text_extract.py",
            "factbook-assistant/citl_translation.py",
            "factbook-assistant/citl_audio_ffmpeg_graceful_v2.py",
            "factbook-assistant/citl_theme.py",
            "factbook-assistant/parsers.py",
            "factbook-assistant/citl_screen_recorder.py",
            "factbook-assistant/citl_doc_composer.py",
            "factbook-assistant/citl_doc_theme.py",
            "factbook-assistant/citl_doc_templates.py",
            "RUN_FACTBOOK_WINDOWS.cmd",
            "RUN_FACTBOOK.sh",
            "scripts/windows/run.ps1",
            "Run-CITL.ps1",
            "scripts/windows/run_llmops.ps1",
            "scripts/windows/record_demo.ps1",
        ],
        "version_file": "FACTBOOK_VERSION.txt",
        "launcher_win": "RUN_FACTBOOK_WINDOWS.cmd",
        "launcher_nix": "RUN_FACTBOOK.sh",
        "repo_marker": "factbook-assistant/factbook_assistant_gui.py",
    },
    {
        # ── App Sync ─────────────────────────────────────────────────────────
        "name": "CITL App Sync",
        "description": (
            "Cross-platform USB and phone sync dashboard. "
            "Keeps all CITL app copies aligned across Windows and Ubuntu. "
            "Auto-ports Ubuntu requirements on every sync."
        ),
        "icon": "🔄",
        "key_files": [
            "factbook-assistant/citl_app_sync.py",
            "RUN_APP_SYNC_WINDOWS.cmd",
            "RUN_APP_SYNC_UBUNTU.sh",
            "RUN_APP_SYNC.sh",
            "Run-CITL-App-Sync.ps1",
            "requirements-windows.txt",
            "requirements-linux.txt",
            "scripts/windows/setup.ps1",
            "scripts/linux/setup.sh",
            "SYNC_CITL_APPS_TO_USB_WINDOWS.cmd",
            "SYNC_CITL_APPS_TO_USB_UBUNTU.sh",
            "scripts/windows/sync_usb_apps.ps1",
            "scripts/windows/build_all_citl_exes.ps1",
            "BUILD_ALL_CITL_EXES_WINDOWS.cmd",
            "OPEN_SYNC_UTILITY_README.txt",
        ],
        "version_file": None,
        "launcher_win": "RUN_APP_SYNC_WINDOWS.cmd",
        "launcher_nix": "RUN_APP_SYNC_UBUNTU.sh",
        "repo_marker": "factbook-assistant/citl_app_sync.py",
    },
    {
        # ── LLM Studio / Bot Maker ───────────────────────────────────────────
        "name": "CITL LLM Studio",
        "description": (
            "Ollama model configuration and bot-building studio. "
            "Create, test, and export custom Modelfiles and chat personas. "
            "Also runs as 'Bot Maker' in the CITL Utilities launcher."
        ),
        "icon": "🤖",
        "key_files": [
            "factbook-assistant/citl_modelfile.py",
            "CITL-LLM-Studio-Kit/app/llm_studio_gui.py",
        ],
        "version_file": None,
        "launcher_win": None,
        "launcher_nix": None,
        "repo_marker": "CITL-LLM-Studio-Kit/app/llm_studio_gui.py",
    },
    {
        # ── Academic Advisor ─────────────────────────────────────────────────
        # FastAPI backend (uvicorn :8000) + React/Vite frontend (:5173)
        # Backed by Ollama qwen2.5:7b — advises on college course schedules,
        # degree audits, and CTCLink/SBCTC data.
        # Repo: C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS\2026 ACADEMIC ADVISOR
        "name": "CITL Academic Advisor",
        "description": (
            "AI degree-audit and advising assistant. "
            "FastAPI backend + React UI, powered by Ollama qwen2.5. "
            "Parses class schedules, audits transcripts, and answers "
            "advising questions from CTCLink/SBCTC data."
        ),
        "icon": "🎓",
        "key_files": [
            "api/app.py",
            "api/Modelfile",
            "scripts/Run-CITLAdvisor.ps1",
            "advisor-ui/src",
            "requirements.txt",
        ],
        "version_file": None,
        "launcher_win": "scripts/Run-CITLAdvisor.ps1",
        "launcher_nix": None,   # no Linux launcher yet
        "repo_marker": "api/app.py",
        "repo_path": r"C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS\2026 ACADEMIC ADVISOR",
        "repo_path_env": "CITL_ACADEMIC_ADVISOR_REPO",
    },
    {
        # ── CITL Toolkit (device/AV management) ──────────────────────────────
        "name": "CITL Toolkit",
        "description": (
            "Classroom AV and device management suite — audio checks, "
            "camera visibility, display profiles, Zoom updater, "
            "and software layer triage. Runs on Windows without install."
        ),
        "icon": "🖥️",
        "key_files": [
            "CITL_Toolkit/CITL_Launcher.ps1",
            "CITL_Toolkit/CITL_DeviceUpdater_GUI.ps1",
            "CITL_Toolkit/CITL_DisplayProfile_GUI.ps1",
        ],
        "version_file": None,
        "launcher_win": "CITL_Toolkit/CITL_Launcher.ps1",
        "launcher_nix": None,
        "repo_marker": "CITL_Toolkit/CITL_Launcher.ps1",
    },
    {
        # ── CITL LLMOps Presentation Suite ────────────────────────────────────
        "name": "LLMOps Suite",
        "description": (
            "Showcase, installer, and walkthrough for the full CITL app ecosystem. "
            "Explains LLM technology, career readiness, and human-in-the-loop "
            "operations for each app. Maroon + gray theme. "
            "Windows 10/11 and Ubuntu 24.04 LTS."
        ),
        "icon": "🎯",
        "key_files": [
            "factbook-assistant/citl_llmops_suite.py",
            "RUN_LLMOPS_WINDOWS.cmd",
            "RUN_LLMOPS.sh",
            "scripts/windows/run_llmops.ps1",
            "scripts/windows/build_llmops_exe.ps1",
            "scripts/windows/build_all_citl_exes.ps1",
            "BUILD_LLMOPS_EXE_WINDOWS.cmd",
            "BUILD_ALL_CITL_EXES_WINDOWS.cmd",
            "LLMOPS_SUITE_README.txt",
        ],
        "version_file": None,
        "launcher_win": "RUN_LLMOPS_WINDOWS.cmd",
        "launcher_nix": "RUN_LLMOPS.sh",
        "repo_marker": "factbook-assistant/citl_llmops_suite.py",
    },
)


def _read_version_file(repo: Path, rel_path: Optional[str]) -> str:
    """Return first non-empty line of a version file, or '' if absent."""
    if not rel_path:
        return ""
    try:
        return (repo / rel_path).read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return ""


def _bump_version_file(repo: Path, rel_path: Optional[str]) -> bool:
    """
    Increment the patch/build number in a version file if it contains a
    semantic-ish version string (e.g. 'v2.0', 'v2.0.1', 'CITL FACTBOOK v2.0').
    Returns True on success.
    """
    if not rel_path:
        return False
    vpath = repo / rel_path
    try:
        text = vpath.read_text(encoding="utf-8")
    except Exception:
        return False
    # Match patterns like v2.0 or v2.0.1 anywhere in the text
    m = re.search(r"(v\d+\.\d+)(?:\.(\d+))?", text)
    if not m:
        return False
    old_str = m.group(0)
    major_minor = m.group(1)
    patch = int(m.group(2) or "0") + 1
    new_str = f"{major_minor}.{patch}"
    new_text = text.replace(old_str, new_str, 1)
    # Update the baseline date line if present
    today = datetime.utcnow().strftime("%Y-%m-%d")
    new_text = re.sub(r"Baseline date:\s*\d{4}-\d{2}-\d{2}", f"Baseline date: {today}", new_text)
    try:
        vpath.write_text(new_text, encoding="utf-8")
        return True
    except Exception:
        return False


DEFAULT_EXCLUDES: Tuple[str, ...] = (
    ".git/",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".cache/",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tmp",
    "*.bak",
    "dist/",
    "build/",
    "node_modules/",
    "data/citl/",
    "data/indexes/",
    "models/",
    "ollama/",
    "*.wav",
    "*.mp3",
    "*.mp4",
)


@dataclass(frozen=True)
class SyncTarget:
    path: Path
    score: int
    has_git: bool
    markers: Tuple[str, ...]
    root: Path
    remembered: bool = False


@dataclass
class SyncResult:
    copied: int = 0
    skipped: int = 0
    errors: int = 0
    used_rsync: bool = False
    elapsed_sec: float = 0.0


@dataclass(frozen=True)
class SourceDetection:
    path: Path
    reason: str
    freshness_ts: float


@dataclass
class RepoComparison:
    source_avg_ts: float
    target_avg_ts: float
    source_newer: int
    target_newer: int
    source_only: int
    target_only: int
    common_files: int
    source_file_count: int
    target_file_count: int
    recommendation: str
    summary: str
    newer_source_files: List[str] = None   # files updated on source since last sync
    new_source_files: List[str] = None     # files only on source (not yet synced)

    def __post_init__(self):
        if self.newer_source_files is None:
            self.newer_source_files = []
        if self.new_source_files is None:
            self.new_source_files = []


@dataclass(frozen=True)
class PhoneDevice:
    serial: str
    state: str
    meta: str


@dataclass(frozen=True)
class TargetStatus:
    target: SyncTarget
    freshness_ts: float
    writable: bool
    write_detail: str
    update_available: bool
    root_label: str
    comparison: RepoComparison


def _freshness_score(values: Iterable[float], sample_limit: int = 250) -> float:
    seq = sorted((float(v) for v in values if v and v > 0), reverse=True)
    if not seq:
        return 0.0
    sample = seq[: min(sample_limit, len(seq))]
    return sum(sample) / float(len(sample))


def _tracked_repo_mtimes(repo: PathLike, excludes: Sequence[str]) -> Dict[str, float]:
    base = Path(repo).expanduser().resolve()
    out: Dict[str, float] = {}
    if not base.exists() or not base.is_dir():
        return out

    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        rel_root = root_path.relative_to(base)
        rel_root_posix = "" if str(rel_root) == "." else rel_root.as_posix()

        kept_dirs: List[str] = []
        for d in dirs:
            rel_dir = "/".join(x for x in (rel_root_posix, d) if x)
            if _is_excluded(rel_dir, excludes, is_dir=True):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for name in files:
            rel_file = "/".join(x for x in (rel_root_posix, name) if x)
            if _is_excluded(rel_file, excludes, is_dir=False):
                continue
            path = root_path / name
            try:
                out[rel_file] = path.stat().st_mtime
            except OSError:
                continue
    return out


def compare_repo_freshness(
    source_repo: PathLike,
    target_repo: PathLike,
    include_data: bool = False,
    include_models: bool = False,
) -> RepoComparison:
    excludes = _build_excludes(include_data=include_data, include_models=include_models)
    source_map = _tracked_repo_mtimes(source_repo, excludes)
    target_map = _tracked_repo_mtimes(target_repo, excludes)

    source_keys = set(source_map)
    target_keys = set(target_map)
    common = source_keys & target_keys

    source_newer = 0
    target_newer = 0
    newer_source_files: List[str] = []
    for rel in common:
        delta = source_map[rel] - target_map[rel]
        if delta > UPDATE_AVAILABLE_EPSILON_SEC:
            source_newer += 1
            newer_source_files.append((source_map[rel], rel))
        elif delta < -UPDATE_AVAILABLE_EPSILON_SEC:
            target_newer += 1

    # Sort newest-first; keep display names only
    newer_source_files.sort(key=lambda x: -x[0])
    newer_source_files = [r for _, r in newer_source_files[:12]]

    source_only_set = source_keys - target_keys
    new_source_files = sorted(source_only_set, key=lambda r: -source_map.get(r, 0))[:12]
    source_only = len(source_only_set)
    target_only = len(target_keys - source_keys)
    source_avg_ts = _freshness_score(source_map.values())
    target_avg_ts = _freshness_score(target_map.values())

    if not source_map or not target_map:
        recommendation = "review"
    elif source_newer == 0 and target_newer == 0 and source_only == 0 and target_only == 0:
        recommendation = "current"
    else:
        source_edge = source_newer + source_only + max(0.0, (source_avg_ts - target_avg_ts) / 43200.0)
        target_edge = target_newer + target_only + max(0.0, (target_avg_ts - source_avg_ts) / 43200.0)
        if source_edge >= max(3.0, target_edge * 1.35):
            recommendation = "push_source_to_target"
        elif target_edge >= max(3.0, source_edge * 1.35):
            recommendation = "pull_target_to_source"
        else:
            recommendation = "review"

    summary = (
        f"source newer files={source_newer}, target newer files={target_newer}, "
        f"source only={source_only}, target only={target_only}, "
        f"source average freshness={_fmt_ts(source_avg_ts)}, "
        f"target average freshness={_fmt_ts(target_avg_ts)}"
    )
    return RepoComparison(
        source_avg_ts=source_avg_ts,
        target_avg_ts=target_avg_ts,
        source_newer=source_newer,
        target_newer=target_newer,
        source_only=source_only,
        target_only=target_only,
        common_files=len(common),
        source_file_count=len(source_map),
        target_file_count=len(target_map),
        recommendation=recommendation,
        summary=summary,
        newer_source_files=newer_source_files,
        new_source_files=new_source_files,
    )


def adb_devices() -> List[PhoneDevice]:
    try:
        proc = subprocess.run(
            ["adb", "devices", "-l"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            check=False,
            timeout=8.0,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []
    rows: List[PhoneDevice] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        serial = parts[0]
        state = parts[1] if len(parts) > 1 else "unknown"
        meta = " ".join(parts[2:]) if len(parts) > 2 else ""
        rows.append(PhoneDevice(serial=serial, state=state, meta=meta))
    return rows


def connected_phone_devices() -> List[PhoneDevice]:
    return [item for item in adb_devices() if item.state == "device"]


def _safe_archive_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (text or "repo").strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "repo"


def create_repo_zip_archive(
    source_repo: PathLike,
    archive_path: PathLike,
    include_data: bool = False,
    include_models: bool = False,
    log_fn: LogFn = None,
) -> Dict[str, object]:
    src = Path(source_repo).expanduser().resolve()
    dst = Path(archive_path).expanduser().resolve()
    excludes = _build_excludes(include_data=include_data, include_models=include_models)
    start = time.time()
    file_count = 0
    byte_count = 0

    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src):
            root_path = Path(root)
            rel_root = root_path.relative_to(src)
            rel_root_posix = "" if str(rel_root) == "." else rel_root.as_posix()

            kept_dirs: List[str] = []
            for d in dirs:
                rel_dir = "/".join(x for x in (rel_root_posix, d) if x)
                if _is_excluded(rel_dir, excludes, is_dir=True):
                    continue
                kept_dirs.append(d)
            dirs[:] = kept_dirs

            for name in files:
                rel_file = "/".join(x for x in (rel_root_posix, name) if x)
                if _is_excluded(rel_file, excludes, is_dir=False):
                    continue
                path = root_path / name
                try:
                    zf.write(path, arcname=rel_file)
                    file_count += 1
                    byte_count += path.stat().st_size
                except OSError as exc:
                    _safe_log(log_fn, f"[PHONE][WARN] skipped {rel_file}: {exc}\n")

    return {
        "archive_path": dst,
        "file_count": file_count,
        "byte_count": byte_count,
        "elapsed_sec": time.time() - start,
    }


def push_repo_archive_to_phone(
    source_repo: PathLike,
    serial: str,
    include_data: bool = False,
    include_models: bool = False,
    log_fn: LogFn = None,
) -> Dict[str, object]:
    src = Path(source_repo).expanduser().resolve()
    temp_root = Path(tempfile.mkdtemp(prefix="citl_phone_bundle_"))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"{_safe_archive_name(src.name)}_{stamp}.zip"
    archive_path = temp_root / archive_name
    remote_path = f"/sdcard/Download/{archive_name}"

    try:
        info = create_repo_zip_archive(
            src,
            archive_path,
            include_data=include_data,
            include_models=include_models,
            log_fn=log_fn,
        )
        _safe_log(log_fn, f"[PHONE] pushing {archive_path} to {serial}:{remote_path}\n")
        proc = subprocess.run(
            ["adb", "-s", serial, "push", str(archive_path), remote_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=900.0,
        )
        if proc.stdout:
            _safe_log(log_fn, proc.stdout)
        if proc.returncode != 0:
            raise RuntimeError(f"adb push failed with exit code {proc.returncode}")
        info["remote_path"] = remote_path
        info["serial"] = serial
        return info
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return "unknown"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "unknown"


def _safe_log(log_fn: LogFn, message: str) -> None:
    if log_fn:
        log_fn(message)


def _fmt_bytes(size: int) -> str:
    try:
        n = float(size)
    except Exception:
        return "unknown size"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while n >= 1024.0 and idx < len(units) - 1:
        n /= 1024.0
        idx += 1
    return f"{n:.1f} {units[idx]}"


def _dir_size_bytes(path: PathLike) -> int:
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        return 0
    total = 0
    for base, _dirs, files in os.walk(root):
        base_path = Path(base)
        for name in files:
            fp = base_path / name
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def candidate_ollama_model_dirs(repo_root: PathLike) -> List[Path]:
    repo = Path(repo_root).expanduser()
    candidates: List[Path] = []
    env_models = (os.environ.get("OLLAMA_MODELS") or "").strip()
    if env_models:
        candidates.append(Path(env_models))
    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE") or str(Path.home())
        localapp = os.environ.get("LOCALAPPDATA") or ""
        candidates.extend(
            [
                Path(userprofile) / ".ollama" / "models",
                Path(localapp) / "Ollama" / "models" if localapp else Path(""),
            ]
        )
    else:
        candidates.append(Path.home() / ".ollama" / "models")

    candidates.extend(
        [
            repo / "ollama" / "models",
            repo / "ollama",
            repo / "models",
        ]
    )

    out: List[Path] = []
    seen: set = set()
    for p in candidates:
        if not str(p):
            continue
        try:
            rp = p.expanduser().resolve()
        except Exception:
            rp = p.expanduser()
        key = str(rp).lower()
        if key in seen:
            continue
        seen.add(key)
        if rp.exists() and rp.is_dir():
            out.append(rp)
    return out


def recommended_ollama_model_target_dir(target_repo: PathLike) -> Path:
    target = Path(target_repo).expanduser()
    try:
        target = target.resolve()
    except Exception:
        pass
    root = _guess_usb_root(target)
    if root != target:
        return root / "CITL_OLLAMA_MODELS"
    return target / "ollama" / "models"


def sync_external_model_store(
    source_models_dir: PathLike,
    target_models_dir: PathLike,
    log_fn: LogFn = None,
) -> Dict[str, object]:
    src = Path(source_models_dir).expanduser().resolve()
    dst = Path(target_models_dir).expanduser().resolve()
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Model source directory not found: {src}")
    if src == dst:
        _safe_log(log_fn, f"[MODEL] source and target are the same path: {src}\n")
        return {
            "copied": 0,
            "skipped": 0,
            "errors": 0,
            "bytes_copied": 0,
            "elapsed_sec": 0.0,
            "source": src,
            "target": dst,
        }

    start = time.time()
    copied = 0
    skipped = 0
    errors = 0
    bytes_copied = 0
    dst.mkdir(parents=True, exist_ok=True)

    _safe_log(log_fn, f"[MODEL] syncing Ollama model store\n")
    _safe_log(log_fn, f"[MODEL] source={src}\n")
    _safe_log(log_fn, f"[MODEL] target={dst}\n")

    for root, _dirs, files in os.walk(src):
        root_path = Path(root)
        rel_root = root_path.relative_to(src)
        out_dir = dst / rel_root
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            sp = root_path / name
            dp = out_dir / name
            try:
                if _needs_copy(sp, dp):
                    shutil.copy2(str(sp), str(dp))
                    copied += 1
                    try:
                        bytes_copied += sp.stat().st_size
                    except OSError:
                        pass
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                _safe_log(log_fn, f"[MODEL][ERR] {sp} -> {dp}: {exc}\n")

    elapsed = time.time() - start
    _safe_log(
        log_fn,
        f"[MODEL][DONE] copied={copied} skipped={skipped} errors={errors} "
        f"bytes_copied={bytes_copied} ({_fmt_bytes(bytes_copied)}) elapsed={elapsed:.1f}s\n",
    )
    return {
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
        "bytes_copied": bytes_copied,
        "elapsed_sec": elapsed,
        "source": src,
        "target": dst,
    }


def _state_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "CITL"


def _state_path() -> Path:
    return _state_dir() / STATE_FILE_NAME


def _load_state() -> Dict[str, object]:
    data: Dict[str, object] = {
        "version": STATE_SCHEMA_VERSION,
        "remembered_targets": {},
        "last_selected_target": "",
    }
    path = _state_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return data
    if not isinstance(raw, dict):
        return data
    remembered = raw.get("remembered_targets")
    if isinstance(remembered, dict):
        data["remembered_targets"] = remembered
    last_selected = raw.get("last_selected_target")
    if isinstance(last_selected, str):
        data["last_selected_target"] = last_selected
    return data


def _save_state(data: Dict[str, object]) -> None:
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_SCHEMA_VERSION,
        "remembered_targets": data.get("remembered_targets") or {},
        "last_selected_target": data.get("last_selected_target") or "",
    }
    _state_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _existing_paths(paths: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    seen: set = set()
    for p in paths:
        try:
            rp = p.expanduser().resolve()
        except Exception:
            rp = p.expanduser()
        key = str(rp)
        if key in seen:
            continue
        seen.add(key)
        try:
            exists = rp.exists()
        except OSError:
            continue
        except Exception:
            continue
        if exists:
            out.append(rp)
    return out


def _is_external_mount_path(path: Path) -> bool:
    low = str(path).lower()
    if os.name == "nt":
        return False
    # WSL-mounted Windows fixed drives (/mnt/c, /mnt/d, ...) are not external media.
    parts = path.parts
    if len(parts) >= 3 and parts[1].lower() == "mnt":
        letter = parts[2].lower()
        if len(letter) == 1 and letter.isalpha():
            return False
    prefixes = ("/media/", "/run/media/", "/mnt/", "/volumes/")
    return any(low.startswith(p) for p in prefixes)


def _has_repo_marker(path: Path) -> bool:
    if not path.is_dir():
        return False
    for rel in REPO_MARKERS:
        if (path / rel).exists():
            return True
    return False


def _normalize_repo_path(raw: str) -> Optional[Path]:
    val = (raw or "").strip().strip("\"'").strip()
    if not val:
        return None
    val = os.path.expandvars(os.path.expanduser(val))
    p = Path(val)
    try:
        return p.resolve()
    except Exception:
        return p


def _extract_run_citl_local_paths(script_path: Path) -> List[Path]:
    out: List[Path] = []
    if not script_path.exists():
        return out
    try:
        text = script_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return out

    # Matches lines such as: local a="$HOME/CITL_FACTBOOK_UBUNTU"
    for match in re.finditer(r'local\s+[a-zA-Z_]\w*\s*=\s*"([^"]+)"', text):
        p = _normalize_repo_path(match.group(1))
        if not p:
            continue
        if _is_external_mount_path(p):
            continue
        out.append(p)
    return _existing_paths(out)


def _candidate_local_repos(default_source: Path) -> List[Path]:
    home = Path.home()
    run_citl = home / ".local" / "bin" / "run-citl"

    seed: List[Path] = []
    seed.extend(_extract_run_citl_local_paths(run_citl))

    # Known local paths.
    seed.extend(
        [
            default_source,
            home / "CITL_FACTBOOK_UBUNTU",
            home / "CITL" / "CITL_FACTBOOK_UBUNTU",
            home / "CITL" / "CITL",
            home / "CITL" / "CITL - Desktop LLM EZ Install Kits",
        ]
    )

    # Shallow scan for similarly named repos.
    scan_roots = [home, home / "CITL"]
    for root in _existing_paths(scan_roots):
        try:
            entries = list(os.scandir(root))
        except Exception:
            continue
        for ent in entries:
            if not ent.is_dir(follow_symlinks=False):
                continue
            name = ent.name.lower()
            if "citl" in name or "factbook" in name:
                seed.append(Path(ent.path))
                # One more level.
                try:
                    sub = list(os.scandir(ent.path))
                except Exception:
                    sub = []
                for s in sub:
                    if s.is_dir(follow_symlinks=False):
                        sname = s.name.lower()
                        if "citl" in sname or "factbook" in sname:
                            seed.append(Path(s.path))

    uniq: List[Path] = []
    seen: set = set()
    for p in _existing_paths(seed):
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if _is_external_mount_path(p):
            continue
        if _has_repo_marker(p):
            uniq.append(p)
    return uniq


def _desktop_preferred_repo(candidates: Sequence[Path]) -> Optional[Path]:
    home = Path.home()
    run_citl = home / ".local" / "bin" / "run-citl"
    ordered = _extract_run_citl_local_paths(run_citl)
    cset = {str(p): p for p in candidates}
    for p in ordered:
        hit = cset.get(str(p))
        if hit is not None:
            return hit
    return None


def _repo_commit_timestamp(repo: Path) -> float:
    git_dir = repo / ".git"
    if not git_dir.exists():
        return 0.0
    try:
        p = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%ct"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return 0.0
    if p.returncode != 0:
        return 0.0
    try:
        return float((p.stdout or "").strip() or 0.0)
    except Exception:
        return 0.0


def _repo_file_timestamp(repo: Path) -> float:
    probe = [
        repo / "factbook-assistant" / "citl_app_sync.py",
        repo / "factbook-assistant" / "factbook_assistant_gui.py",
        repo / "factbook-assistant" / "build_corpus_index.py",
        repo / "RUN_FACTBOOK.sh",
        repo / "Run-CITL.ps1",
        repo / "factbook_assistant_gui.py",
    ]
    mts = [p.stat().st_mtime for p in probe if p.exists()]
    if mts:
        return max(mts)
    try:
        return repo.stat().st_mtime
    except Exception:
        return 0.0


def _repo_freshness(repo: Path) -> float:
    return max(_repo_commit_timestamp(repo), _repo_file_timestamp(repo))


def _windows_volume_identity(root: Path) -> Dict[str, str]:
    drive = str(root.drive or root.anchor or root)
    if drive and not drive.endswith("\\"):
        drive += "\\"
    info = {
        "key": f"winroot:{drive.lower()}",
        "root": drive or str(root),
        "label": "",
        "serial_hex": "",
    }
    if not drive:
        return info
    try:
        import ctypes

        volume_name = ctypes.create_unicode_buffer(261)
        fs_name = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint()
        max_component = ctypes.c_uint()
        flags = ctypes.c_uint()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive),
            volume_name,
            len(volume_name),
            ctypes.byref(serial),
            ctypes.byref(max_component),
            ctypes.byref(flags),
            fs_name,
            len(fs_name),
        )
        if ok:
            label = volume_name.value.strip()
            serial_hex = f"{serial.value:08X}" if serial.value else ""
            info["label"] = label
            info["serial_hex"] = serial_hex
            if serial_hex:
                info["key"] = f"winvol:{serial_hex.lower()}"
    except Exception:
        return info
    return info


def _root_identity(root: Path) -> Dict[str, str]:
    try:
        rp = root.expanduser().resolve()
    except Exception:
        rp = root.expanduser()
    if os.name == "nt":
        return _windows_volume_identity(rp)
    return {
        "key": f"path:{str(rp).lower()}",
        "root": str(rp),
        "label": rp.name,
        "serial_hex": "",
    }


def _root_label(root: Path) -> str:
    ident = _root_identity(root)
    parts = [ident.get("root", str(root))]
    label = ident.get("label", "")
    serial_hex = ident.get("serial_hex", "")
    if label:
        parts.append(label)
    if serial_hex:
        parts.append(f"serial {serial_hex}")
    return " | ".join(part for part in parts if part)


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        rp = path.expanduser().resolve()
    except Exception:
        rp = path.expanduser()
    try:
        rr = root.expanduser().resolve()
    except Exception:
        rr = root.expanduser()
    try:
        return rp.relative_to(rr).as_posix()
    except Exception:
        return ""


def _remember_target(target_repo: PathLike, root: Optional[Path] = None) -> None:
    target = Path(target_repo).expanduser()
    try:
        target = target.resolve()
    except Exception:
        pass

    remembered_root = (root or _guess_usb_root(target)).expanduser()
    try:
        remembered_root = remembered_root.resolve()
    except Exception:
        pass

    ident = _root_identity(remembered_root)
    entry = {
        "target_path": str(target),
        "relative_path": _safe_relative_path(target, remembered_root),
        "root": str(remembered_root),
        "label": ident.get("label", ""),
        "serial_hex": ident.get("serial_hex", ""),
        "saved_ts": time.time(),
        "saved_at": _fmt_ts(time.time()),
    }

    state = _load_state()
    remembered = dict(state.get("remembered_targets") or {})
    remembered[ident["key"]] = entry
    state["remembered_targets"] = remembered
    state["last_selected_target"] = str(target)
    _save_state(state)


def _last_selected_target() -> Optional[Path]:
    state = _load_state()
    raw = state.get("last_selected_target")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _normalize_repo_path(raw)


def _candidate_from_path(
    path: PathLike,
    source_name: str,
    root: Optional[Path] = None,
    remembered: bool = False,
) -> Optional[SyncTarget]:
    cand = Path(path).expanduser()
    try:
        cand = cand.resolve()
    except Exception:
        pass
    if not cand.exists() or not cand.is_dir():
        return None

    score, markers, has_git = _score_candidate(cand, source_name)
    if score < 5:
        return None

    base_root = root or _guess_usb_root(cand)
    return SyncTarget(
        path=cand,
        score=score + (1 if remembered else 0),
        has_git=has_git,
        markers=markers,
        root=base_root,
        remembered=remembered,
    )


def _remembered_target_candidates(roots: Sequence[Path]) -> List[Tuple[Path, Path]]:
    state = _load_state()
    remembered = state.get("remembered_targets")
    if not isinstance(remembered, dict):
        return []

    out: List[Tuple[Path, Path]] = []
    for root in roots:
        ident = _root_identity(root)
        raw = remembered.get(ident["key"])
        if not isinstance(raw, dict):
            continue

        rel = raw.get("relative_path")
        candidate: Optional[Path] = None
        if isinstance(rel, str) and rel.strip():
            candidate = root / Path(rel)
        else:
            raw_path = raw.get("target_path")
            if isinstance(raw_path, str):
                candidate = _normalize_repo_path(raw_path)
        if candidate is None:
            continue

        try:
            candidate = candidate.resolve()
        except Exception:
            pass
        out.append((root, candidate))
    return out


def detect_source_repo(source_arg: str = "auto", default_source: Optional[Path] = None) -> SourceDetection:
    default_repo = (default_source or _default_source()).expanduser().resolve()
    raw = (source_arg or "").strip()
    if raw and raw.lower() not in ("auto", "detect", "local"):
        explicit = _normalize_repo_path(raw)
        if explicit is None or not explicit.exists():
            raise FileNotFoundError(f"Source repo not found: {raw}")
        if not _has_repo_marker(explicit):
            raise FileNotFoundError(f"Source path is not a CITL repo: {explicit}")
        ts = max(_repo_commit_timestamp(explicit), _repo_file_timestamp(explicit))
        return SourceDetection(path=explicit, reason="explicit --source", freshness_ts=ts)

    candidates = _candidate_local_repos(default_repo)
    if not candidates:
        ts = max(_repo_commit_timestamp(default_repo), _repo_file_timestamp(default_repo))
        return SourceDetection(path=default_repo, reason="fallback default source", freshness_ts=ts)

    preferred = _desktop_preferred_repo(candidates)
    if preferred is not None:
        ts = max(_repo_commit_timestamp(preferred), _repo_file_timestamp(preferred))
        return SourceDetection(path=preferred, reason="desktop launcher preferred local repo", freshness_ts=ts)

    ranked: List[Tuple[float, Path]] = []
    for repo in candidates:
        ts = max(_repo_commit_timestamp(repo), _repo_file_timestamp(repo))
        ranked.append((ts, repo))
    ranked.sort(key=lambda x: x[0], reverse=True)
    best_ts, best_repo = ranked[0]
    return SourceDetection(path=best_repo, reason="most recently updated local repo", freshness_ts=best_ts)


def _windows_drive_roots_by_type(allowed_types: Tuple[int, ...]) -> List[Path]:
    roots: List[Path] = []
    try:
        import ctypes
    except Exception:
        return roots

    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not (bitmask & (1 << i)):
            continue
        drive = f"{letter}:\\"
        try:
            dtype = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive))
        except Exception:
            continue
        if dtype not in allowed_types:
            continue
        roots.append(Path(drive))
    return roots


def _windows_drive_roots() -> List[Path]:
    # DRIVE_REMOVABLE=2, DRIVE_FIXED=3
    return _windows_drive_roots_by_type((2, 3))


def _windows_removable_roots() -> List[Path]:
    # DRIVE_REMOVABLE=2
    return _windows_drive_roots_by_type((2,))


def scan_roots() -> List[Path]:
    roots: List[Path] = []
    user = os.environ.get("USER", "").strip()

    if os.name == "nt":
        roots.extend(_windows_drive_roots())
    else:
        if user:
            roots.append(Path("/media") / user)
            roots.append(Path("/run/media") / user)
        roots.append(Path("/media"))
        roots.append(Path("/mnt"))
        roots.append(Path("/Volumes"))

    extra = os.environ.get("CITL_SYNC_SCAN_ROOTS", "").strip()
    if extra:
        for raw in extra.split(os.pathsep):
            raw = raw.strip()
            if raw:
                roots.append(Path(raw))
    return _existing_paths(roots)


def _iter_candidate_dirs(root: Path, max_depth: int = 3) -> Iterable[Path]:
    queue: List[Tuple[Path, int]] = [(root, 0)]
    seen: set = set()
    while queue:
        cur, depth = queue.pop(0)
        key = str(cur)
        if key in seen:
            continue
        seen.add(key)

        lower = cur.name.lower()
        if "citl" in lower or "factbook" in lower:
            yield cur

        # Common portable layout shortcuts.
        quick = [
            cur / "CITL",
            cur / "CITL_FACTBOOK_UBUNTU",
            cur / "PORTABLE_APPS" / "CITL",
        ]
        for p in quick:
            try:
                if p.is_dir():
                    yield p
            except Exception:
                continue

        if depth >= max_depth:
            continue
        try:
            entries = list(os.scandir(cur))
        except Exception:
            continue

        for ent in entries:
            if not ent.is_dir(follow_symlinks=False):
                continue
            nxt = Path(ent.path)
            name = ent.name.lower()
            if depth == 0 or "citl" in name or "factbook" in name or "portable" in name:
                queue.append((nxt, depth + 1))
            elif name in ("apps", "repos"):
                queue.append((nxt, depth + 1))


def _score_candidate(path: Path, source_name: str) -> Tuple[int, Tuple[str, ...], bool]:
    hits: List[str] = []
    for rel in REPO_MARKERS:
        if (path / rel).exists():
            hits.append(rel)

    has_gui = any("factbook_assistant_gui.py" in h for h in hits)
    if not has_gui:
        return 0, tuple(), False

    has_git = (path / ".git").exists()
    pname = path.name.lower()
    score = len(hits) * 2
    if has_git:
        score += 2
    if "citl" in pname:
        score += 2
    if "factbook" in pname:
        score += 2
    if source_name and source_name.lower().replace("-", "_") in pname.replace("-", "_"):
        score += 1
    if "portable_apps" in str(path).lower():
        score += 1
    return score, tuple(hits), has_git


def _discover_sync_targets_from_roots(
    source_repo: PathLike,
    roots: Sequence[Path],
    max_depth: int = 3,
) -> List[SyncTarget]:
    src = Path(source_repo).expanduser().resolve()
    src_name = src.name
    best: Dict[str, SyncTarget] = {}
    checked: set = set()

    def maybe_add(item: SyncTarget) -> None:
        key = str(item.path)
        cur = best.get(key)
        if cur is None:
            best[key] = item
            return
        if item.remembered and not cur.remembered:
            best[key] = item
            return
        if item.score > cur.score:
            best[key] = item

    for root in roots:
        for cand in _iter_candidate_dirs(root, max_depth=max_depth):
            try:
                rp = cand.resolve()
            except Exception:
                rp = cand
            key = str(rp)
            if key in checked:
                continue
            checked.add(key)

            if rp == src:
                continue
            if src in rp.parents:
                continue

            score, markers, has_git = _score_candidate(rp, src_name)
            if score < 5:
                continue

            maybe_add(
                SyncTarget(
                    path=rp,
                    score=score,
                    has_git=has_git,
                    markers=markers,
                    root=root,
                )
            )

    for root, remembered_path in _remembered_target_candidates(roots):
        try:
            rp = remembered_path.resolve()
        except Exception:
            rp = remembered_path
        if rp == src:
            continue
        if src in rp.parents:
            continue
        item = _candidate_from_path(rp, src_name, root=root, remembered=True)
        if item is not None:
            maybe_add(item)

    out = list(best.values())
    out.sort(
        key=lambda t: (
            0 if t.remembered else 1,
            -t.score,
            0 if t.has_git else 1,
            str(t.path).lower(),
        )
    )
    return out


def discover_sync_targets(source_repo: PathLike, max_depth: int = 3) -> List[SyncTarget]:
    src = Path(source_repo).expanduser().resolve()
    roots = scan_roots()
    if os.name == "nt":
        src_drive = (src.drive or src.anchor or "").lower()
        other_roots = [
            root for root in roots if (root.drive or root.anchor or "").lower() != src_drive
        ]
        if other_roots:
            roots = other_roots
    return _discover_sync_targets_from_roots(src, roots, max_depth=max_depth)


def _resolve_candidate_repo_path(raw: str, source_repo: Path) -> Optional[Path]:
    val = (raw or "").strip()
    if not val:
        return None
    val = os.path.expandvars(os.path.expanduser(val))
    p = Path(val)
    if not p.is_absolute():
        p = source_repo / p
    try:
        return p.resolve()
    except Exception:
        return p


def resolve_app_source_root(app: dict, source_repo: PathLike) -> Path:
    """
    Resolve the best source root for an app:
    1) env var override (repo_path_env)
    2) explicit repo_path
    3) fallback to main source repo
    """
    src = Path(source_repo).expanduser()
    try:
        src = src.resolve()
    except Exception:
        pass

    marker = str(app.get("repo_marker") or "").strip()
    env_key = str(app.get("repo_path_env") or "").strip()
    candidates: List[str] = []

    if env_key:
        env_val = (os.environ.get(env_key) or "").strip()
        if env_val:
            candidates.append(env_val)

    repo_path = app.get("repo_path")
    if isinstance(repo_path, str) and repo_path.strip():
        candidates.append(repo_path)

    for raw in candidates:
        p = _resolve_candidate_repo_path(raw, src)
        if p is None or not p.exists():
            continue
        if marker and not (p / marker).exists():
            continue
        return p

    if marker and (src / marker).exists():
        return src
    return src


def sync_registered_app_key_files(
    source_repo: PathLike,
    target_repo: PathLike,
    log_fn: LogFn = None,
) -> Dict[str, Dict[str, int]]:
    """
    Sync key_files for every app entry in CITL_APPS.
    This captures files from app-specific repos when repo_path/repo_path_env is set.
    """
    src = Path(source_repo).expanduser().resolve()
    dst = Path(target_repo).expanduser().resolve()
    summary: Dict[str, Dict[str, int]] = {}

    def _copy_one(src_path: Path, dst_path: Path) -> Tuple[int, int]:
        copied = 0
        skipped = 0
        if src_path.is_dir():
            for root, _dirs, files in os.walk(src_path):
                root_path = Path(root)
                rel_root = root_path.relative_to(src_path)
                out_dir = dst_path / rel_root
                out_dir.mkdir(parents=True, exist_ok=True)
                for name in files:
                    s = root_path / name
                    d = out_dir / name
                    if _needs_copy(s, d):
                        shutil.copy2(s, d)
                        copied += 1
                    else:
                        skipped += 1
            return copied, skipped

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if _needs_copy(src_path, dst_path):
            shutil.copy2(src_path, dst_path)
            copied += 1
        else:
            skipped += 1
        return copied, skipped

    for app in CITL_APPS:
        app_name = str(app.get("name") or "Unnamed App")
        key_files = app.get("key_files") or []
        if not key_files:
            continue
        app_src = resolve_app_source_root(app, src)
        copied = 0
        skipped = 0
        missing = 0
        errors = 0

        _safe_log(log_fn, f"[APP-SYNC] {app_name}: source={app_src}\n")
        for rel in key_files:
            src_p = app_src / rel
            dst_p = dst / rel
            if not src_p.exists():
                missing += 1
                _safe_log(log_fn, f"[APP-SYNC][MISS] {app_name}: {src_p}\n")
                continue
            try:
                c, s = _copy_one(src_p, dst_p)
                copied += c
                skipped += s
            except Exception as e:
                errors += 1
                _safe_log(log_fn, f"[APP-SYNC][ERR] {app_name}: {src_p} -> {dst_p} ({e})\n")

        summary[app_name] = {
            "copied": copied,
            "skipped": skipped,
            "missing": missing,
            "errors": errors,
        }
        _safe_log(
            log_fn,
            f"[APP-SYNC] {app_name}: copied={copied} skipped={skipped} missing={missing} errors={errors}\n",
        )

    return summary


def _select_best_usb_target_for_push(
    source_repo: Path,
    include_data: bool = False,
    include_models: bool = False,
) -> Optional[Tuple[SyncTarget, RepoComparison]]:
    src = Path(source_repo).expanduser().resolve()
    targets: List[SyncTarget] = []

    if os.name == "nt":
        removable_roots = _windows_removable_roots()
        src_drive = (src.drive or src.anchor or "").lower()
        removable_roots = [
            root for root in removable_roots if (root.drive or root.anchor or "").lower() != src_drive
        ]
        if removable_roots:
            targets = _discover_sync_targets_from_roots(src, removable_roots, max_depth=3)

    if not targets:
        targets = discover_sync_targets(src)
    if not targets:
        return None

    priority = {
        "push_source_to_target": 0,
        "current": 1,
        "review": 2,
        "pull_target_to_source": 3,
    }
    ranked: List[Tuple[int, int, int, str, SyncTarget, RepoComparison]] = []
    for t in targets:
        comp = compare_repo_freshness(
            src,
            t.path,
            include_data=include_data,
            include_models=include_models,
        )
        ranked.append(
            (
                priority.get(comp.recommendation, 9),
                0 if t.remembered else 1,
                -t.score,
                str(t.path).lower(),
                t,
                comp,
            )
        )
    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    best = ranked[0]
    return best[4], best[5]


def _resolve_phone_serial(phone_arg: str = "auto") -> Tuple[Optional[str], str]:
    devices = connected_phone_devices()
    if not devices:
        return None, "No Android phone detected over ADB."

    raw = (phone_arg or "auto").strip()
    if not raw or raw.lower() in ("auto", "first"):
        dev = devices[0]
        return dev.serial, f"Auto-selected phone: {dev.serial}"

    for dev in devices:
        if dev.serial == raw:
            return dev.serial, f"Using requested phone: {dev.serial}"
    return None, f"Requested phone serial not found: {raw}"


def _push_repo_copy_to_phone(
    repo_path: PathLike,
    phone_arg: str = "auto",
    include_data: bool = False,
    include_models: bool = False,
) -> int:
    serial, note = _resolve_phone_serial(phone_arg)
    if not serial:
        print(f"[PHONE][ERROR] {note}")
        return 1

    repo = Path(repo_path).expanduser().resolve()
    print(f"[PHONE] {note}")
    print(f"[PHONE] exporting repo copy: {repo}")
    try:
        result = push_repo_archive_to_phone(
            repo,
            serial,
            include_data=include_data,
            include_models=include_models,
            log_fn=lambda s: print(s, end=""),
        )
    except Exception as e:
        print(f"[PHONE][ERROR] export failed: {e}")
        return 1

    print(
        f"[PHONE][DONE] files={result['file_count']} bytes={result['byte_count']} "
        f"remote={result['remote_path']} elapsed={result['elapsed_sec']:.1f}s"
    )
    return 0


def _run_sync_best_usb(args: argparse.Namespace, source: SourceDetection) -> int:
    print(f"[SOURCE] {source.path} ({source.reason})")
    model_source_arg = (getattr(args, "ollama_model_source", "") or "").strip()
    model_target_arg = (getattr(args, "ollama_model_target", "") or "").strip()
    if bool(args.include_models) and (not model_source_arg or not model_target_arg):
        print(
            "[WARN] --include-models set without both --ollama-model-source and "
            "--ollama-model-target; external Ollama model store copy will be skipped "
            "(repo-local models/ollama folders still sync)."
        )
    explicit_target_arg = (getattr(args, "target_path", "") or "").strip()
    target_path: Optional[Path] = None
    if explicit_target_arg:
        target_path = _normalize_repo_path(explicit_target_arg)
        if target_path is None:
            print(f"[ERROR] Invalid --target-path: {explicit_target_arg}")
            return 2
        try:
            target_path = target_path.resolve()
        except Exception:
            pass
        if not target_path.exists():
            try:
                target_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"[ERROR] Could not create --target-path {target_path}: {e}")
                return 2
        comparison = compare_repo_freshness(
            source.path,
            target_path,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )
        print(f"[TARGET] {target_path} (explicit --target-path)")
    else:
        chosen = _select_best_usb_target_for_push(
            source.path,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )
        if chosen is None:
            print("[ERROR] No compatible USB/external CITL target was detected.")
            return 2
        target, comparison = chosen
        target_path = target.path
        print(f"[TARGET] {target_path}")

    assert target_path is not None
    print(f"[TARGET] recommendation={comparison.recommendation} ({comparison.summary})")
    if comparison.recommendation == "pull_target_to_source":
        print(
            "[WARN] Selected target appears newer than this PC copy; "
            "continuing with PC -> USB push because --sync-best-usb was requested."
        )

    total_errors = 0
    if bool(getattr(args, "full_repo_sync", False)):
        result = sync_repo(
            source.path,
            target_path,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
            model_source_dir=(model_source_arg or None),
            model_target_dir=(model_target_arg or None),
            log_fn=lambda s: print(s, end=""),
        )
        mode = "rsync" if result.used_rsync else "python-copy"
        print(
            f"[DONE] repo-sync mode={mode} copied={result.copied} skipped={result.skipped} "
            f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s"
        )
        total_errors += int(result.errors)
    else:
        install_sync_launchers(target_path, log_fn=lambda s: print(s, end=""))
        print("[DONE] full repo sync skipped (app key-file update mode).")

    if not bool(getattr(args, "no_app_key_sync", False)):
        app_summary = sync_registered_app_key_files(
            source.path,
            target_path,
            log_fn=lambda s: print(s, end=""),
        )
        total_copied = sum(v.get("copied", 0) for v in app_summary.values())
        total_missing = sum(v.get("missing", 0) for v in app_summary.values())
        app_errors = sum(v.get("errors", 0) for v in app_summary.values())
        total_errors += app_errors
        print(
            f"[DONE] app-key-sync apps={len(app_summary)} copied={total_copied} "
            f"missing={total_missing} errors={app_errors}"
        )

    try:
        port_to_ubuntu(target_path, log_fn=lambda s: print(s, end=""))
    except Exception as e:
        total_errors += 1
        print(f"[WARN] Ubuntu port step failed on target: {e}")

    if bool(getattr(args, "push_target_to_phone", False)):
        total_errors += _push_repo_copy_to_phone(
            target_path,
            phone_arg=str(getattr(args, "phone_serial", "auto") or "auto"),
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )

    return 0 if total_errors == 0 else 1


def _path_root_key(path: PathLike) -> str:
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except Exception:
        pass
    if os.name == "nt":
        return (p.drive or p.anchor or str(p)).lower().rstrip("\\/")
    root = _guess_usb_root(p)
    try:
        root = root.resolve()
    except Exception:
        pass
    return str(root).lower().rstrip("/")


def _is_removable_source_repo(path: PathLike) -> bool:
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except Exception:
        pass

    if os.name == "nt":
        drive = (p.drive or p.anchor or "").lower()
        if not drive:
            return False
        removable = {(r.drive or r.anchor or "").lower() for r in _windows_removable_roots()}
        return drive in removable

    return _is_external_mount_path(p)


def _discover_duplicate_targets(source_repo: PathLike) -> List[SyncTarget]:
    src = Path(source_repo).expanduser().resolve()
    if os.name == "nt":
        removable = _windows_removable_roots()
        if removable:
            return _discover_sync_targets_from_roots(src, removable, max_depth=3)
    return discover_sync_targets(src)


def _pick_duplicate_target(
    from_path: Path,
    candidates: Sequence[SyncTarget],
    include_data: bool = False,
    include_models: bool = False,
) -> Optional[Tuple[Path, RepoComparison]]:
    if not candidates:
        return None

    priority = {
        "push_source_to_target": 0,
        "current": 1,
        "review": 2,
        "pull_target_to_source": 3,
    }
    from_root = _path_root_key(from_path)
    ranked: List[Tuple[int, int, int, int, float, str, Path, RepoComparison]] = []
    for t in candidates:
        comp = compare_repo_freshness(
            from_path,
            t.path,
            include_data=include_data,
            include_models=include_models,
        )
        same_root = 1 if _path_root_key(t.path) == from_root else 0
        freshness = _repo_freshness(t.path)
        ranked.append(
            (
                same_root,
                priority.get(comp.recommendation, 9),
                0 if t.remembered else 1,
                -t.score,
                -freshness,
                str(t.path).lower(),
                t.path,
                comp,
            )
        )

    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4], x[5]))
    best = ranked[0]
    return best[6], best[7]


def _run_duplicate_usb(args: argparse.Namespace, source: SourceDetection) -> int:
    print(f"[SOURCE] {source.path} ({source.reason})")
    source_repo = Path(source.path).expanduser().resolve()
    targets = _discover_duplicate_targets(source_repo)
    by_path = {str(t.path): t for t in targets}
    from_arg = (getattr(args, "duplicate_from", "") or "").strip()
    to_arg = (getattr(args, "duplicate_to", "") or "").strip()
    from_path = _normalize_repo_path(from_arg) if from_arg else None
    to_path = _normalize_repo_path(to_arg) if to_arg else None

    if from_path is not None:
        if from_path != source_repo and str(from_path) not in by_path:
            print(f"[ERROR] --duplicate-from not detected as a target: {from_path}")
            return 2
        if not _has_repo_marker(from_path):
            print(f"[ERROR] --duplicate-from is not a CITL repo: {from_path}")
            return 2
    if to_path and str(to_path) not in by_path:
        print(f"[ERROR] --duplicate-to not detected as a target: {to_path}")
        return 2

    if from_path is None:
        if _is_removable_source_repo(source_repo) and _has_repo_marker(source_repo):
            from_path = source_repo
            print(f"[DUPLICATE] auto-source=this USB ({from_path})")
        else:
            if not targets:
                print("[ERROR] No external CITL targets were detected for duplication.")
                return 2
            ranked = sorted(targets, key=lambda t: (_repo_freshness(t.path), t.score), reverse=True)
            from_path = ranked[0].path
            print(f"[DUPLICATE] auto-source=best detected target ({from_path})")

    assert from_path is not None

    if to_path is None:
        candidates = [t for t in targets if t.path != from_path]
        picked = _pick_duplicate_target(
            from_path,
            candidates,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )
        if picked is None:
            print(
                "[ERROR] Need at least one additional USB/external CITL target to duplicate to. "
                "Connect another CITL USB and try again."
            )
            return 2
        to_path, auto_comp = picked
        print(f"[DUPLICATE] auto-target=next detected target ({to_path})")
    else:
        auto_comp = compare_repo_freshness(
            from_path,
            to_path,
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )

    if from_path == to_path:
        print("[ERROR] Source and destination USB paths are the same.")
        return 2

    if _path_root_key(from_path) == _path_root_key(to_path):
        print("[WARN] Source and destination appear to be on the same drive root; continuing anyway.")

    model_source_arg = (getattr(args, "ollama_model_source", "") or "").strip()
    model_target_arg = (getattr(args, "ollama_model_target", "") or "").strip()
    if bool(args.include_models) and (not model_source_arg or not model_target_arg):
        print(
            "[WARN] --include-models set without both --ollama-model-source and "
            "--ollama-model-target; external Ollama model store copy will be skipped "
            "(repo-local models/ollama folders still sync)."
        )

    print(f"[DUPLICATE] from={from_path}")
    print(f"[DUPLICATE] to={to_path}")
    print(f"[DUPLICATE] recommendation={auto_comp.recommendation} ({auto_comp.summary})")

    result = sync_repo(
        from_path,
        to_path,
        include_data=bool(args.include_data),
        include_models=bool(args.include_models),
        model_source_dir=(model_source_arg or None),
        model_target_dir=(model_target_arg or None),
        log_fn=lambda s: print(s, end=""),
    )
    mode = "rsync" if result.used_rsync else "python-copy"
    print(
        f"[DONE] USB duplicate mode={mode} copied={result.copied} skipped={result.skipped} "
        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s"
    )

    if not bool(getattr(args, "no_app_key_sync", False)):
        app_summary = sync_registered_app_key_files(
            source.path,
            to_path,
            log_fn=lambda s: print(s, end=""),
        )
        total_copied = sum(v.get("copied", 0) for v in app_summary.values())
        total_missing = sum(v.get("missing", 0) for v in app_summary.values())
        app_errors = sum(v.get("errors", 0) for v in app_summary.values())
        print(
            f"[DONE] app-key-overlay apps={len(app_summary)} copied={total_copied} "
            f"missing={total_missing} errors={app_errors}"
        )
        total_errors = int(result.errors) + int(app_errors)
    else:
        total_errors = int(result.errors)

    try:
        port_to_ubuntu(to_path, log_fn=lambda s: print(s, end=""))
    except Exception as e:
        total_errors += 1
        print(f"[WARN] Ubuntu port step failed on duplicate target: {e}")

    if bool(getattr(args, "push_target_to_phone", False)):
        total_errors += _push_repo_copy_to_phone(
            to_path,
            phone_arg=str(getattr(args, "phone_serial", "auto") or "auto"),
            include_data=bool(args.include_data),
            include_models=bool(args.include_models),
        )

    return 0 if total_errors == 0 else 1


# ── GitHub / git automation ───────────────────────────────────────────────────

def _git_run(repo: Path, *args: str, timeout: int = 30) -> Tuple[int, str, str]:
    """Run a git command in `repo`. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", "git not found in PATH"
    except subprocess.TimeoutExpired:
        return -1, "", f"git command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def _find_git_root(path: Path) -> Optional[Path]:
    """Walk up from `path` to find the .git directory root."""
    p = path.resolve()
    for candidate in [p] + list(p.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def git_status_for_repo(repo: Path) -> Dict[str, object]:
    """
    Return a status dict for a git repo:
      branch, remote_url, ahead, behind, dirty, last_commit, last_author, error
    """
    root = _find_git_root(repo)
    if root is None:
        return {"error": "Not a git repo", "branch": "—", "ahead": 0, "behind": 0,
                "dirty": False, "last_commit": "", "last_author": "", "remote_url": ""}

    # Branch
    rc, branch, _ = _git_run(root, "rev-parse", "--abbrev-ref", "HEAD")
    branch = branch if rc == 0 else "unknown"

    # Remote URL
    rc, remote_url, _ = _git_run(root, "remote", "get-url", "origin")
    remote_url = remote_url if rc == 0 else ""

    # Fetch (non-blocking remote check — use cached FETCH_HEAD if offline)
    _git_run(root, "fetch", "--quiet", timeout=12)

    # Ahead / behind
    rc, ab, _ = _git_run(root, "rev-list", "--left-right", "--count",
                          f"HEAD...origin/{branch}")
    ahead = behind = 0
    if rc == 0 and ab:
        parts = ab.split()
        if len(parts) == 2:
            try:
                ahead, behind = int(parts[0]), int(parts[1])
            except ValueError:
                pass

    # Dirty working tree
    rc, diff_out, _ = _git_run(root, "status", "--porcelain")
    dirty = bool(diff_out.strip()) if rc == 0 else False

    # Last commit
    rc, log_line, _ = _git_run(root, "log", "-1", "--pretty=%h %s (%an, %ar)")
    last_commit = log_line if rc == 0 else ""
    rc, last_author, _ = _git_run(root, "log", "-1", "--pretty=%an <%ae>")
    last_author = last_author if rc == 0 else ""

    return {
        "root": root,
        "branch": branch,
        "remote_url": remote_url,
        "ahead": ahead,
        "behind": behind,
        "dirty": dirty,
        "last_commit": last_commit,
        "last_author": last_author,
        "error": None,
    }


def git_backup_repo(repo: Path, backup_dir: Optional[Path] = None) -> Path:
    """
    Create a timestamped zip backup of the repo (excluding .git, venv, __pycache__).
    Returns the path to the backup zip.
    """
    root = _find_git_root(repo) or repo.resolve()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", root.name)
    bdir = backup_dir or (root.parent / ".citl_git_backups")
    bdir.mkdir(parents=True, exist_ok=True)
    zip_path = bdir / f"{safe_name}_{ts}.zip"

    skip_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules",
                 "dist", "build", ".pytest_cache", ".mypy_cache"}
    skip_exts = {".pyc", ".pyo", ".log", ".tmp"}

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fname in filenames:
                if any(fname.endswith(e) for e in skip_exts):
                    continue
                full = Path(dirpath) / fname
                try:
                    arcname = full.relative_to(root)
                    zf.write(str(full), str(arcname))
                except Exception:
                    pass

    return zip_path


def git_commit_and_push(
    repo: Path,
    message: str = "",
    log_fn: LogFn = None,
) -> Tuple[bool, str]:
    """
    Stage all changes, commit (if dirty), and push to origin.
    Returns (success, summary_message).
    Raises nothing — all errors are returned in the message.
    """
    root = _find_git_root(repo)
    if root is None:
        return False, "Not a git repo — cannot push."

    status = git_status_for_repo(root)
    if status.get("error"):
        return False, str(status["error"])

    # Backup first
    try:
        bzip = git_backup_repo(root)
        _safe_log(log_fn, f"[GIT] Backup created: {bzip}\n")
    except Exception as e:
        _safe_log(log_fn, f"[GIT] Backup warning: {e}\n")

    branch = status["branch"]
    lines: List[str] = []

    if status["dirty"]:
        commit_msg = message or (
            f"CITL App Sync auto-commit {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
        )
        rc, out, err = _git_run(root, "add", "-A")
        lines.append(f"git add: rc={rc}")
        if err:
            lines.append(err)

        rc, out, err = _git_run(root, "commit", "-m", commit_msg)
        lines.append(f"git commit: rc={rc} — {out or err}")
        if rc != 0:
            return False, "\n".join(lines)
    else:
        lines.append("Working tree clean — no new commit needed.")

    # Refresh remote refs, then determine ahead/behind.
    _git_run(root, "fetch", "--quiet", timeout=20)
    rc_ab, ab, _ = _git_run(root, "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}")
    ahead = behind = 0
    if rc_ab == 0 and ab:
        parts = ab.split()
        if len(parts) == 2:
            try:
                ahead = int(parts[0])
                behind = int(parts[1])
            except ValueError:
                pass

    # If behind/diverged, attempt rebase first so push can succeed.
    if behind > 0:
        lines.append(f"Local branch is behind remote by {behind}; attempting pull --rebase first.")
        rc, out, err = _git_run(root, "pull", "--rebase", "--autostash", "origin", branch, timeout=180)
        lines.append(f"git pull --rebase origin {branch}: rc={rc}")
        if out:
            lines.append(out)
        if err:
            lines.append(err)
        if rc != 0:
            lines.append(
                "Rebase/pull failed before push. Resolve conflicts in this repo, then retry push."
            )
            return False, "\n".join(lines)

        rc_ab, ab, _ = _git_run(root, "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}")
        ahead = behind = 0
        if rc_ab == 0 and ab:
            parts = ab.split()
            if len(parts) == 2:
                try:
                    ahead = int(parts[0])
                    behind = int(parts[1])
                except ValueError:
                    pass

    if not status["dirty"] and ahead == 0:
        lines.append("Already up to date with remote — nothing to push.")
        return True, "\n".join(lines)

    rc, out, err = _git_run(root, "push", "origin", branch, timeout=90)
    lines.append(f"git push origin {branch}: rc={rc}")
    if out:
        lines.append(out)
    if err:
        lines.append(err)
        # Surface auth errors clearly
        if any(k in err.lower() for k in ("authentication", "credential", "permission denied",
                                           "could not read", "403", "401", "token")):
            lines.append(
                "\n[AUTH HELP] Push requires GitHub authentication.\n"
                "Options:\n"
                "  1. Run in terminal: git config --global credential.helper manager\n"
                "  2. Use a Personal Access Token (PAT) as your password.\n"
                "  3. Set up an SSH key: ssh-keygen then add ~/.ssh/id_ed25519.pub to GitHub.\n"
                "  4. Run: gh auth login  (if GitHub CLI is installed)"
            )

    success = rc == 0
    return success, "\n".join(lines)


def git_pull_repo(
    repo: Path,
    log_fn: LogFn = None,
) -> Tuple[bool, str]:
    """
    Backup then pull from origin.
    Returns (success, summary_message).
    """
    root = _find_git_root(repo)
    if root is None:
        return False, "Not a git repo — cannot pull."

    # Backup first
    try:
        bzip = git_backup_repo(root)
        _safe_log(log_fn, f"[GIT] Backup created before pull: {bzip}\n")
    except Exception as e:
        _safe_log(log_fn, f"[GIT] Backup warning: {e}\n")

    status = git_status_for_repo(root)
    branch = status.get("branch", "main")

    rc, out, err = _git_run(root, "pull", "--rebase", "--autostash", "origin", branch, timeout=180)
    lines: List[str] = [f"git pull --rebase origin {branch}: rc={rc}"]
    if out:
        lines.append(out)
    if err:
        lines.append(err)
    if rc != 0:
        lines.append("Pull failed. If there are conflicts, resolve them and run pull again.")

    return rc == 0, "\n".join(lines)


def git_status_all_apps(source_repo: Path) -> Dict[str, Dict]:
    """
    Return git status for every app in CITL_APPS that has a git repo.
    Keys are app names.
    """
    results: Dict[str, Dict] = {}
    for app in CITL_APPS:
        root = resolve_app_source_root(app, source_repo)
        results[app["name"]] = git_status_for_repo(root)
    return results


# ── Ubuntu port automation ────────────────────────────────────────────────────
# Windows-only pip packages that must never appear in requirements-linux.txt
_WINDOWS_ONLY_PKGS: frozenset = frozenset({
    "pywin32", "pypiwin32", "winsound", "comtypes", "pywintypes",
    "winreg", "winshell", "pywinpty", "pyreadline3",
})

# Linux system packages needed for CITL on Ubuntu (auto-installed by setup.sh)
_UBUNTU_APT_DEPS: Tuple[str, ...] = (
    "python3-venv", "python3-tk", "python3-dev",
    "ffmpeg", "libportaudio2", "portaudio19-dev",
    "alsa-utils", "pulseaudio-utils", "build-essential",
    "git", "python3-gi",
)

# Linux-only pip packages to always ensure are in requirements-linux.txt
_LINUX_EXTRA_PKGS: Tuple[str, ...] = ("sounddevice",)


def _parse_requirements(path: Path) -> List[str]:
    """Return non-empty, non-comment lines from a requirements file."""
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def _pkg_name(req_line: str) -> str:
    """Extract the package name from a requirement line (strips version specifiers)."""
    return re.split(r"[>=<!;\[@\s]", req_line.strip())[0].lower().replace("-", "_")


def sync_requirements_linux(repo: Path) -> Tuple[bool, str]:
    """
    Derive requirements-linux.txt from requirements-windows.txt:
      - Strip Windows-only packages
      - Preserve all -r include lines
      - Ensure Linux-extra packages are present
      - Write only if content changed
    Returns (changed: bool, report: str).
    """
    win_req = repo / "requirements-windows.txt"
    lin_req = repo / "requirements-linux.txt"

    if not win_req.exists():
        return False, "requirements-windows.txt not found; skipping Linux requirements sync."

    win_lines = _parse_requirements(win_req)
    existing_linux = _parse_requirements(lin_req)
    existing_names = {_pkg_name(l) for l in existing_linux if not l.startswith("-r")}

    new_lines: List[str] = []
    removed: List[str] = []
    for line in win_lines:
        if line.startswith("-r"):
            # Replace -r requirements-windows.txt with -r requirements-linux.txt if present
            ref = line[2:].strip()
            if "windows" in ref.lower():
                ref = ref.lower().replace("windows", "linux")
            # Only include if the referenced file exists or it's not the windows req itself
            if ref != "requirements-windows.txt":
                new_lines.append(f"-r {ref}")
            continue
        pname = _pkg_name(line)
        if pname in _WINDOWS_ONLY_PKGS:
            removed.append(line)
            continue
        new_lines.append(line)

    added: List[str] = []
    present_names = {_pkg_name(l) for l in new_lines}
    for extra in _LINUX_EXTRA_PKGS:
        if extra.replace("-", "_") not in present_names:
            new_lines.append(extra)
            added.append(extra)

    new_content = "\n".join(new_lines) + "\n"
    old_content = lin_req.read_text(encoding="utf-8") if lin_req.exists() else ""

    if new_content == old_content:
        return False, "requirements-linux.txt already up to date."

    try:
        lin_req.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return False, f"Could not write requirements-linux.txt: {e}"

    parts = []
    if removed:
        parts.append(f"removed Windows-only: {', '.join(removed)}")
    if added:
        parts.append(f"added Linux extras: {', '.join(added)}")
    return True, f"Updated requirements-linux.txt — {'; '.join(parts) if parts else 'content changed'}."


def _render_setup_sh(repo: Path) -> str:
    """
    Generate scripts/linux/setup.sh content that mirrors scripts/windows/setup.ps1
    in terms of which requirements files it installs.
    """
    req_file = "requirements-linux.txt"
    apt_deps = " \\\n      ".join(_UBUNTU_APT_DEPS)
    return f"""#!/usr/bin/env bash
# Auto-generated by CITL App Sync — mirrors scripts/windows/setup.ps1
# Do not edit manually; changes are overwritten on next sync.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/../.." && pwd)"
echo "== CITL Setup (Ubuntu 24.04 LTS / Linux) =="
echo "Repo: $REPO_DIR"

# ── System deps (Ubuntu 24.04 LTS) ────────────────────────────────────────────
if command -v apt-get >/dev/null 2>&1; then
  SUDO=""
  command -v sudo >/dev/null 2>&1 && SUDO="sudo"
  ${{SUDO}} apt-get update -y
  ${{SUDO}} apt-get install -y \\
      {apt_deps}
fi

# ── Python venv ────────────────────────────────────────────────────────────────
cd "$REPO_DIR"
if [[ ! -d ".venv" ]]; then
  echo "Creating venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -U pip wheel setuptools

# ── Python deps ────────────────────────────────────────────────────────────────
if [[ -f "$REPO_DIR/{req_file}" ]]; then
  pip install -r "$REPO_DIR/{req_file}"
elif [[ -f "$REPO_DIR/requirements.txt" ]]; then
  pip install -r "$REPO_DIR/requirements.txt"
else
  echo "WARN: No requirements file found at $REPO_DIR/{req_file}"
fi

# ── Ubuntu port sync (keeps Linux files in step with Windows changes) ──────────
if python -c "import citl_app_sync" 2>/dev/null; then
  python -c "from citl_app_sync import port_to_ubuntu; from pathlib import Path; r=port_to_ubuntu(Path('$REPO_DIR')); [print(k+': '+v) for k,v in r.items()]" || true
fi

echo "Setup complete. Run: scripts/linux/run.sh"
"""


def sync_linux_setup_script(repo: Path) -> Tuple[bool, str]:
    """
    Regenerate scripts/linux/setup.sh to match what Windows setup.ps1 does,
    keeping apt deps and pip requirements in sync.
    """
    target = repo / "scripts" / "linux" / "setup.sh"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"Cannot create scripts/linux/: {e}"

    new_content = _render_setup_sh(repo)
    old_content = target.read_text(encoding="utf-8") if target.exists() else ""

    # Only regenerate if the file is auto-generated (has our marker) or missing
    if old_content and "Auto-generated by CITL App Sync" not in old_content:
        return False, "scripts/linux/setup.sh exists with custom content; skipping auto-regeneration."

    if new_content == old_content:
        return False, "scripts/linux/setup.sh already up to date."

    try:
        target.write_text(new_content, encoding="utf-8")
        # Make executable on non-Windows hosts
        if os.name != "nt":
            target.chmod(0o755)
    except Exception as e:
        return False, f"Could not write scripts/linux/setup.sh: {e}"

    return True, "Regenerated scripts/linux/setup.sh."


def sync_ubuntu_launchers(repo: Path) -> Tuple[bool, str]:
    """
    Ensure all root-level .sh launchers exist and reference correct paths.
    Regenerates any that are missing or have our auto-generated marker.
    """
    launchers = {
        "RUN_FACTBOOK.sh": (
            "#!/usr/bin/env bash\n"
            "# Auto-generated by CITL App Sync\n"
            'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'VENV="$DIR/.venv"\n'
            'if [[ ! -d "$VENV" ]]; then bash "$DIR/scripts/linux/setup.sh"; fi\n'
            'source "$VENV/bin/activate"\n'
            'GUI="$DIR/factbook-assistant/factbook_assistant_gui.py"\n'
            '[[ -f "$GUI" ]] || GUI="$DIR/factbook_assistant_gui.py"\n'
            'exec python "$GUI"\n'
        ),
        "RUN_APP_SYNC.sh": (
            "#!/usr/bin/env bash\n"
            "# Auto-generated by CITL App Sync\n"
            'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'VENV="$DIR/.venv"\n'
            'if [[ ! -d "$VENV" ]]; then bash "$DIR/scripts/linux/setup.sh"; fi\n'
            'source "$VENV/bin/activate"\n'
            'exec python "$DIR/factbook-assistant/citl_app_sync.py" "$@"\n'
        ),
        "RUN_APP_SYNC_UBUNTU.sh": (
            "#!/usr/bin/env bash\n"
            "# Auto-generated by CITL App Sync\n"
            'exec bash "$(dirname "${BASH_SOURCE[0]}")/RUN_APP_SYNC.sh" "$@"\n'
        ),
        "RUN_LLMOPS.sh": (
            "#!/usr/bin/env bash\n"
            "# Auto-generated by CITL App Sync\n"
            'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'VENV="$DIR/.venv"\n'
            'if [[ ! -d "$VENV" ]]; then bash "$DIR/scripts/linux/setup.sh"; fi\n'
            'source "$VENV/bin/activate"\n'
            'SCRIPT1="$DIR/factbook-assistant/citl_llmops_suite.py"\n'
            'SCRIPT2="$DIR/citl_llmops_suite.py"\n'
            'SCRIPT=""\n'
            'if [[ -f "$SCRIPT1" ]]; then SCRIPT="$SCRIPT1"; elif [[ -f "$SCRIPT2" ]]; then SCRIPT="$SCRIPT2"; fi\n'
            'if [[ -z "$SCRIPT" ]]; then echo "ERROR: LLMOps suite not found"; exit 1; fi\n'
            'if command -v python3 >/dev/null 2>&1; then exec python3 "$SCRIPT"; else exec python "$SCRIPT"; fi\n'
        ),
    }

    updated: List[str] = []
    skipped: List[str] = []
    for name, content in launchers.items():
        path = repo / name
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if old and "Auto-generated by CITL App Sync" not in old:
            skipped.append(name)
            continue
        if old == content:
            continue
        try:
            path.write_text(content, encoding="utf-8")
            if os.name != "nt":
                path.chmod(0o755)
            updated.append(name)
        except Exception:
            pass

    msg_parts = []
    if updated:
        msg_parts.append(f"Updated launchers: {', '.join(updated)}")
    if skipped:
        msg_parts.append(f"Skipped (custom content): {', '.join(skipped)}")
    changed = bool(updated)
    return changed, " | ".join(msg_parts) if msg_parts else "Launchers already up to date."


def _slugify_name(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "app").strip().lower()).strip("-")
    return slug or "app"


def _bootstrap_entry_rel(app: dict) -> str:
    rel = str(app.get("repo_marker") or "").strip()
    if rel:
        return rel.replace("\\", "/")
    keys = app.get("key_files") or []
    for item in keys:
        if str(item).strip():
            return str(item).replace("\\", "/")
    return ""


def _render_bootstrap_cmd(entry_rel: str, app_name: str) -> str:
    entry_win = entry_rel.replace("/", "\\")
    ext = Path(entry_rel).suffix.lower()
    base = (
        "@echo off\n"
        "setlocal\n"
        'set "HERE=%~dp0\\..\\.."\n'
        f'set "TARGET=%HERE%\\{entry_win}"\n'
        'if not exist "%TARGET%" (\n'
        f'  echo {app_name}: entry not found: %TARGET%\n'
        "  pause\n"
        "  exit /b 1\n"
        ")\n"
    )
    if ext in (".cmd", ".bat", ".exe"):
        run = '"%TARGET%" %*\n'
    elif ext == ".ps1":
        run = 'powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%" %*\n'
    elif ext == ".py":
        run = (
            'if exist "%HERE%\\.venv\\Scripts\\python.exe" (\n'
            '  "%HERE%\\.venv\\Scripts\\python.exe" "%TARGET%" %*\n'
            ") else (\n"
            "  where py >nul 2>&1\n"
            "  if %ERRORLEVEL%==0 (\n"
            "    py -3 \"%TARGET%\" %*\n"
            "  ) else (\n"
            "    python \"%TARGET%\" %*\n"
            "  )\n"
            ")\n"
        )
    else:
        run = 'powershell -NoProfile -Command "Start-Process \\"%HERE%\\""\n'
    return base + run + "exit /b %ERRORLEVEL%\n"


def _render_bootstrap_sh(entry_rel: str, app_name: str) -> str:
    ext = Path(entry_rel).suffix.lower()
    base = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"\n'
        f'TARGET="$HERE/{entry_rel}"\n'
        'if [[ ! -e "$TARGET" ]]; then\n'
        f'  echo "{app_name}: entry not found: $TARGET"\n'
        "  exit 1\n"
        "fi\n"
    )
    if ext == ".sh":
        run = 'exec bash "$TARGET" "$@"\n'
    elif ext == ".py":
        run = (
            'if [[ -x "$HERE/.venv/bin/python3" ]]; then\n'
            '  exec "$HERE/.venv/bin/python3" "$TARGET" "$@"\n'
            "fi\n"
            'if command -v python3 >/dev/null 2>&1; then exec python3 "$TARGET" "$@"; fi\n'
            'exec python "$TARGET" "$@"\n'
        )
    else:
        run = (
            f'echo "{app_name}: no Ubuntu-native launcher for {entry_rel}"\n'
            "echo \"Use this as a placeholder and run the Windows launcher on Windows hosts.\"\n"
            "exit 2\n"
        )
    return base + run


def sync_device_agnostic_bootstraps(repo: Path) -> Tuple[bool, str]:
    """
    Generate fallback launchers for apps missing an explicit Windows or Ubuntu launcher.
    This keeps USB copies runnable even when app-specific wrappers are absent.
    """
    win_dir = repo / "bootstrap" / "windows"
    nix_dir = repo / "bootstrap" / "linux"
    win_dir.mkdir(parents=True, exist_ok=True)
    nix_dir.mkdir(parents=True, exist_ok=True)

    updated: List[str] = []
    skipped: List[str] = []

    for app in CITL_APPS:
        app_name = str(app.get("name") or "App")
        slug = _slugify_name(app_name)
        entry_rel = _bootstrap_entry_rel(app)
        if not entry_rel:
            skipped.append(f"{app_name}(no-entry)")
            continue

        win_launcher = str(app.get("launcher_win") or "").strip()
        win_missing = not win_launcher or not (repo / win_launcher).exists()
        if win_missing:
            out = win_dir / f"Run-{slug}.cmd"
            content = _render_bootstrap_cmd(entry_rel, app_name)
            old = out.read_text(encoding="utf-8") if out.exists() else ""
            if old != content:
                out.write_text(content, encoding="utf-8")
                updated.append(out.as_posix())

        nix_launcher = str(app.get("launcher_nix") or "").strip()
        nix_missing = not nix_launcher or not (repo / nix_launcher).exists()
        if nix_missing:
            out = nix_dir / f"run-{slug}.sh"
            content = _render_bootstrap_sh(entry_rel, app_name)
            old = out.read_text(encoding="utf-8") if out.exists() else ""
            if old != content:
                out.write_text(content, encoding="utf-8")
                if os.name != "nt":
                    out.chmod(0o755)
                updated.append(out.as_posix())

    readme = repo / "bootstrap" / "README.txt"
    readme_text = (
        "CITL device-agnostic bootstrap launchers\n"
        "======================================\n\n"
        "These fallback scripts are auto-generated by CITL App Sync.\n"
        "They exist for apps that do not yet ship native launchers on both Windows and Ubuntu.\n\n"
        "Windows fallback folder: bootstrap/windows\n"
        "Ubuntu fallback folder:  bootstrap/linux\n"
    )
    old_readme = readme.read_text(encoding="utf-8") if readme.exists() else ""
    if old_readme != readme_text:
        readme.write_text(readme_text, encoding="utf-8")
        updated.append(readme.as_posix())

    if updated:
        return True, f"Generated/updated {len(updated)} bootstrap file(s)."
    if skipped:
        return False, "No bootstrap updates needed."
    return False, "Bootstrap launchers already up to date."


def port_to_ubuntu(repo: Path, log_fn: LogFn = None) -> Dict[str, str]:
    """
    Run all Ubuntu porting checks on `repo` and return a dict of
    {component: status_message}.  Writes files only when changes are needed.
    """
    results: Dict[str, str] = {}
    checks = [
        ("requirements-linux.txt", sync_requirements_linux),
        ("scripts/linux/setup.sh", sync_linux_setup_script),
        ("Ubuntu launchers", sync_ubuntu_launchers),
        ("Device-agnostic bootstraps", sync_device_agnostic_bootstraps),
    ]
    for label, fn in checks:
        try:
            changed, msg = fn(repo)
            status = f"{'UPDATED' if changed else 'OK'}: {msg}"
        except Exception as e:
            status = f"ERROR: {e}"
        results[label] = status
        _safe_log(log_fn, f"[UBUNTU-PORT] {label}: {status}\n")
    return results


def _build_excludes(include_data: bool, include_models: bool) -> List[str]:
    excludes = list(DEFAULT_EXCLUDES)
    if include_data:
        excludes = [p for p in excludes if not p.startswith("data/")]
    if include_models:
        excludes = [p for p in excludes if p not in ("models/", "ollama/")]
    return excludes


def _is_excluded(rel_posix: str, excludes: Sequence[str], is_dir: bool = False) -> bool:
    rel = rel_posix.strip("/")
    if not rel:
        return False
    for pattern in excludes:
        pat = pattern.strip()
        if not pat:
            continue
        if pat.endswith("/"):
            base = pat[:-1].strip("/")
            if rel == base or rel.startswith(base + "/"):
                return True
            continue
        if fnmatch.fnmatch(rel, pat):
            return True
        if is_dir and fnmatch.fnmatch(rel + "/", pat):
            return True
    return False


def _needs_copy(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    try:
        ss = src.stat()
        ds = dst.stat()
    except Exception:
        return True
    if ss.st_size != ds.st_size:
        return True
    # mtime granularity can differ across filesystems, use 2s tolerance.
    if abs(ss.st_mtime - ds.st_mtime) > 2.0:
        return True
    return False


def _guess_usb_root(target_repo: Path) -> Path:
    target = target_repo.expanduser().resolve()
    if os.name == "nt":
        drive = target.drive or target.anchor
        if drive:
            return Path(drive + "\\")
        return target

    user = os.environ.get("USER", "").strip()
    roots: List[Path] = []
    if user:
        roots.append(Path("/media") / user)
        roots.append(Path("/run/media") / user)
    roots.extend(
        [
            Path("/mnt"),
            Path("/Volumes"),
            Path("/media"),
            Path("/run/media"),
        ]
    )

    for base in roots:
        try:
            if target == base:
                return target
            if base in target.parents:
                rel = target.relative_to(base)
                if rel.parts:
                    return base / rel.parts[0]
        except Exception:
            continue
    return target


def _render_sync_launcher_sh() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""

pick() {
  local p="$1"
  if [ -f "$p/RUN_APP_SYNC.sh" ]; then
    TARGET="$p"
    return 0
  fi
  return 1
}

pick "$ROOT" || true
pick "$ROOT/CITL_FACTBOOK_UBUNTU" || true
pick "$ROOT/CITL" || true
pick "$ROOT/PORTABLE_APPS/CITL" || true

if [ -z "$TARGET" ]; then
  for d in "$ROOT"/*; do
    [ -d "$d" ] || continue
    if pick "$d"; then
      break
    fi
  done
fi

if [ -z "$TARGET" ]; then
  echo "Could not find RUN_APP_SYNC.sh under: $ROOT"
  exit 1
fi

exec bash "$TARGET/RUN_APP_SYNC.sh" "$@"
"""


def _render_duplicate_launcher_sh() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""

pick() {
  local p="$1"
  if [ -f "$p/RUN_APP_SYNC.sh" ]; then
    TARGET="$p"
    return 0
  fi
  return 1
}

pick "$ROOT" || true
pick "$ROOT/CITL_FACTBOOK_UBUNTU" || true
pick "$ROOT/CITL" || true
pick "$ROOT/PORTABLE_APPS/CITL" || true

if [ -z "$TARGET" ]; then
  for d in "$ROOT"/*; do
    [ -d "$d" ] || continue
    if pick "$d"; then
      break
    fi
  done
fi

if [ -z "$TARGET" ]; then
  echo "Could not find RUN_APP_SYNC.sh under: $ROOT"
  exit 1
fi

exec bash "$TARGET/RUN_APP_SYNC.sh" --source "$TARGET" --duplicate-usb --duplicate-from "$TARGET" "$@"
"""


def _render_sync_launcher_cmd() -> str:
    return r"""@echo off
setlocal enableextensions
set "ROOT=%~dp0"
set "TARGET="

if exist "%ROOT%Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%"
if not defined TARGET if exist "%ROOT%CITL_FACTBOOK_UBUNTU\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL_FACTBOOK_UBUNTU\"
if not defined TARGET if exist "%ROOT%CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL\"
if not defined TARGET if exist "%ROOT%PORTABLE_APPS\CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%PORTABLE_APPS\CITL\"

if not defined TARGET (
  for /d %%D in ("%ROOT%*") do (
    if exist "%%~fD\Run-CITL-App-Sync.ps1" (
      set "TARGET=%%~fD\"
      goto :found
    )
  )
)

:found
if not defined TARGET (
  echo Could not find Run-CITL-App-Sync.ps1 under %ROOT%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%Run-CITL-App-Sync.ps1" %*
exit /b %ERRORLEVEL%
"""


def _render_duplicate_launcher_cmd() -> str:
    return r"""@echo off
setlocal enableextensions
set "ROOT=%~dp0"
set "TARGET="

if exist "%ROOT%Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%"
if not defined TARGET if exist "%ROOT%CITL_FACTBOOK_UBUNTU\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL_FACTBOOK_UBUNTU\"
if not defined TARGET if exist "%ROOT%CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%CITL\"
if not defined TARGET if exist "%ROOT%PORTABLE_APPS\CITL\Run-CITL-App-Sync.ps1" set "TARGET=%ROOT%PORTABLE_APPS\CITL\"

if not defined TARGET (
  for /d %%D in ("%ROOT%*") do (
    if exist "%%~fD\Run-CITL-App-Sync.ps1" (
      set "TARGET=%%~fD\"
      goto :found
    )
  )
)

:found
if not defined TARGET (
  echo Could not find Run-CITL-App-Sync.ps1 under %ROOT%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%Run-CITL-App-Sync.ps1" --source "%TARGET%" --duplicate-usb --duplicate-from "%TARGET%" %*
exit /b %ERRORLEVEL%
"""


def _render_sync_launcher_readme() -> str:
    return (
        "CITL Sync Utility Launchers\n"
        "===========================\n\n"
        "Ubuntu launcher: RUN_APP_SYNC_UBUNTU.sh\n"
        "Windows launcher: RUN_APP_SYNC_WINDOWS.cmd\n\n"
        "Self-duplicate launchers (USB -> next USB):\n"
        "  Ubuntu: COPY_THIS_USB_TO_NEXT_UBUNTU.sh\n"
        "  Windows: COPY_THIS_USB_TO_NEXT_WINDOWS.cmd\n\n"
        "These launchers search this USB drive for the CITL repo and then open the\n"
        "cross-platform sync utility.\n\n"
        "Default sync behavior is time-considerate: full repo delta copy while excluding\n"
        "large model/data/media folders unless explicitly requested.\n\n"
        "Headless options:\n"
        "  --sync-best-usb                 Auto-pick best USB target and sync PC -> USB\n"
        "  --duplicate-usb                 Duplicate one USB copy to another\n"
        "  --duplicate-from <path>         Source USB path for duplicate mode\n"
        "  --duplicate-to <path>           Destination USB path for duplicate mode\n"
        "  --include-models                Include repo models/ollama folders\n"
        "  --ollama-model-source <path>    Optional external Ollama model source directory\n"
        "  --ollama-model-target <path>    Optional external Ollama model target directory\n"
    )


def _write_launcher(path: Path, text: str, make_executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if make_executable and os.name != "nt":
        try:
            mode = path.stat().st_mode
            path.chmod(mode | 0o111)
        except Exception:
            # FAT/EXFAT mounts may not support chmod semantics.
            pass


def install_sync_launchers(target_repo: PathLike, log_fn: LogFn = None) -> List[Path]:
    target = Path(target_repo).expanduser().resolve()
    usb_root = _guess_usb_root(target)
    locations: List[Path] = [target]

    if os.name == "nt":
        drive = target.drive or target.anchor
        dtype = 0
        if drive:
            if not str(drive).endswith("\\"):
                drive = str(drive) + "\\"
            try:
                import ctypes

                dtype = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(str(drive)))
            except Exception:
                dtype = 0
        if dtype == 2 and usb_root != target:
            locations.insert(0, usb_root)
    else:
        if _is_external_mount_path(target):
            locations = [usb_root]
            if usb_root != target:
                locations.append(target)
        else:
            locations = [target]

    written: List[Path] = []
    for loc in locations:
        sh_path = loc / SYNC_LAUNCHER_UBUNTU
        cmd_path = loc / SYNC_LAUNCHER_WINDOWS
        dup_sh_path = loc / SYNC_DUPLICATE_UBUNTU
        dup_cmd_path = loc / SYNC_DUPLICATE_WINDOWS
        readme_path = loc / SYNC_LAUNCHER_README

        _write_launcher(sh_path, _render_sync_launcher_sh(), make_executable=True)
        _write_launcher(cmd_path, _render_sync_launcher_cmd(), make_executable=False)
        _write_launcher(dup_sh_path, _render_duplicate_launcher_sh(), make_executable=True)
        _write_launcher(dup_cmd_path, _render_duplicate_launcher_cmd(), make_executable=False)
        _write_launcher(readme_path, _render_sync_launcher_readme(), make_executable=False)

        written.extend([sh_path, cmd_path, dup_sh_path, dup_cmd_path, readme_path])
        _safe_log(log_fn, f"[LAUNCHER] wrote {sh_path}\n")
        _safe_log(log_fn, f"[LAUNCHER] wrote {cmd_path}\n")
        _safe_log(log_fn, f"[LAUNCHER] wrote {dup_sh_path}\n")
        _safe_log(log_fn, f"[LAUNCHER] wrote {dup_cmd_path}\n")
        _safe_log(log_fn, f"[LAUNCHER] wrote {readme_path}\n")

    return written


def audit_docs_bundle(source_repo: PathLike, target_repo: PathLike, log_fn: LogFn = None) -> Dict[str, int]:
    src = Path(source_repo).expanduser().resolve()
    dst = Path(target_repo).expanduser().resolve()
    src_docs = src / "docs"
    dst_docs = dst / "docs"

    if not src_docs.is_dir():
        _safe_log(log_fn, "[DOCS] source docs/ missing; audit skipped.\n")
        return {"audited": 0, "missing": 0, "mismatched": 0}

    src_files: List[Path] = []
    for p in src_docs.rglob("*"):
        if p.is_file():
            src_files.append(p)
    src_files.sort(key=lambda p: str(p.relative_to(src_docs)).lower())

    missing: List[str] = []
    mismatched: List[str] = []
    for sf in src_files:
        rel = sf.relative_to(src_docs)
        tf = dst_docs / rel
        rels = rel.as_posix()
        if not tf.exists():
            missing.append(rels)
            continue
        try:
            if sf.stat().st_size != tf.stat().st_size:
                mismatched.append(rels)
        except Exception:
            mismatched.append(rels)

    audited = len(src_files)
    _safe_log(
        log_fn,
        f"[DOCS] audited={audited} missing={len(missing)} mismatched={len(mismatched)}\n",
    )
    if missing:
        for item in missing[:12]:
            _safe_log(log_fn, f"[DOCS][MISSING] {item}\n")
        if len(missing) > 12:
            _safe_log(log_fn, f"[DOCS][MISSING] ... and {len(missing) - 12} more\n")
    if mismatched:
        for item in mismatched[:12]:
            _safe_log(log_fn, f"[DOCS][MISMATCH] {item}\n")
        if len(mismatched) > 12:
            _safe_log(log_fn, f"[DOCS][MISMATCH] ... and {len(mismatched) - 12} more\n")
    return {"audited": audited, "missing": len(missing), "mismatched": len(mismatched)}


def _sync_with_copy(
    source_repo: Path,
    target_repo: Path,
    excludes: Sequence[str],
    log_fn: LogFn,
) -> SyncResult:
    result = SyncResult()
    start = time.time()
    source_repo = source_repo.resolve()
    target_repo.mkdir(parents=True, exist_ok=True)

    scanned = 0
    for root, dirs, files in os.walk(source_repo):
        root_path = Path(root)
        rel_root = root_path.relative_to(source_repo)
        rel_root_posix = "" if str(rel_root) == "." else rel_root.as_posix()

        kept_dirs: List[str] = []
        for d in dirs:
            rel_dir = "/".join(x for x in (rel_root_posix, d) if x)
            if _is_excluded(rel_dir, excludes, is_dir=True):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for f in files:
            scanned += 1
            rel_file = "/".join(x for x in (rel_root_posix, f) if x)
            if _is_excluded(rel_file, excludes, is_dir=False):
                result.skipped += 1
                continue

            src_file = root_path / f
            dst_file = target_repo / rel_file
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                if _needs_copy(src_file, dst_file):
                    shutil.copy2(src_file, dst_file)
                    result.copied += 1
                else:
                    result.skipped += 1
            except Exception as e:
                result.errors += 1
                _safe_log(log_fn, f"[ERROR] {rel_file}: {e}\n")

            if scanned % 300 == 0:
                _safe_log(
                    log_fn,
                    f"[PROGRESS] scanned={scanned} copied={result.copied} skipped={result.skipped} errors={result.errors}\n",
                )

    result.elapsed_sec = time.time() - start
    return result


def _sync_with_rsync(
    source_repo: Path,
    target_repo: Path,
    excludes: Sequence[str],
    log_fn: LogFn,
) -> SyncResult:
    start = time.time()
    cmd: List[str] = ["rsync", "-a", "--human-readable"]
    for pat in excludes:
        cmd.extend(["--exclude", pat])
    cmd.extend([str(source_repo) + "/", str(target_repo) + "/"])

    _safe_log(log_fn, f"[CMD] {' '.join(cmd)}\n")
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    assert p.stdout is not None
    for line in p.stdout:
        if line:
            _safe_log(log_fn, line)
    rc = p.wait()
    if rc != 0:
        raise RuntimeError(f"rsync failed with exit code {rc}")
    return SyncResult(used_rsync=True, elapsed_sec=time.time() - start)


def sync_repo(
    source_repo: PathLike,
    target_repo: PathLike,
    include_data: bool = False,
    include_models: bool = False,
    model_source_dir: Optional[PathLike] = None,
    model_target_dir: Optional[PathLike] = None,
    log_fn: LogFn = None,
) -> SyncResult:
    src = Path(source_repo).expanduser().resolve()
    dst = Path(target_repo).expanduser().resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"Source repo not found: {src}")
    dst.mkdir(parents=True, exist_ok=True)

    excludes = _build_excludes(include_data=include_data, include_models=include_models)
    _safe_log(log_fn, f"[SYNC] source={src}\n")
    _safe_log(log_fn, f"[SYNC] target={dst}\n")
    _safe_log(log_fn, f"[SYNC] exclude_count={len(excludes)}\n")

    result: SyncResult
    if os.name != "nt" and shutil.which("rsync"):
        try:
            result = _sync_with_rsync(src, dst, excludes, log_fn)
        except Exception as e:
            _safe_log(log_fn, f"[WARN] rsync fallback to Python copy: {e}\n")
            result = _sync_with_copy(src, dst, excludes, log_fn)
    else:
        result = _sync_with_copy(src, dst, excludes, log_fn)

    try:
        install_sync_launchers(dst, log_fn=log_fn)
    except Exception as e:
        _safe_log(log_fn, f"[WARN] launcher install failed: {e}\n")
    try:
        audit_docs_bundle(src, dst, log_fn=log_fn)
    except Exception as e:
        _safe_log(log_fn, f"[WARN] docs audit failed: {e}\n")

    # Always port Ubuntu components in BOTH source and destination repos
    # so the USB copy is immediately ready for Ubuntu installation.
    for label, target_repo in (("source", src), ("target", dst)):
        try:
            port_to_ubuntu(target_repo, log_fn=log_fn)
        except Exception as e:
            _safe_log(log_fn, f"[WARN] Ubuntu port ({label}) failed: {e}\n")

    if include_models and model_source_dir and model_target_dir:
        try:
            sync_external_model_store(
                model_source_dir,
                model_target_dir,
                log_fn=log_fn,
            )
        except Exception as e:
            _safe_log(log_fn, f"[WARN] external model sync failed: {e}\n")

    return result


def open_in_file_manager(path: PathLike) -> None:
    p = Path(path).expanduser()
    if os.name == "nt":
        os.startfile(str(p))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
        return
    subprocess.Popen(["xdg-open", str(p)])


class SyncGUI:
    def __init__(self, source_repo: PathLike, source_reason: str = "", source_freshness_ts: float = 0.0):
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext

        self.tk = tk
        self.messagebox = messagebox
        self.scrolledtext = scrolledtext
        self.filedialog = filedialog

        self.colors = {
            "bg": "#07101c",
            "panel": "#101c31",
            "panel_alt": "#162744",
            "card": "#12203a",
            "card_selected": "#264779",
            "border": "#33527f",
            "text": "#f3f8ff",
            "muted": "#9eb4d5",
            "accent": "#60dbff",
            "accent_active": "#8ce7ff",
            "button": "#29466f",
            "button_active": "#3b6297",
            "good": "#84f6a0",
            "warn": "#ffd369",
            "danger": "#ff8b8b",
        }

        self.source_repo = Path(source_repo).expanduser().resolve()
        self.source_reason = (source_reason or "").strip()
        self.source_freshness_ts = float(source_freshness_ts or 0.0)
        self.targets: List[SyncTarget] = []
        self.target_status: Dict[str, TargetStatus] = {}
        self.devices: List[PhoneDevice] = []
        self._busy = False
        self._tile_columns = 0

        self.root = tk.Tk()
        self.root.title(f"{APP_SYNC_NAME} {APP_SYNC_VERSION}")
        self.root.geometry("1440x940")
        self.root.minsize(1080, 760)
        self.root.configure(bg=self.colors["bg"])
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Scrollable outer layout so the full dashboard is reachable on smaller screens.
        self.main_canvas = tk.Canvas(self.root, bg=self.colors["bg"], highlightthickness=0, bd=0)
        self.main_scroll = tk.Scrollbar(self.root, orient="vertical", command=self.main_canvas.yview)
        self.main_canvas.configure(yscrollcommand=self.main_scroll.set)
        self.main_canvas.grid(row=0, column=0, sticky="nsew")
        self.main_scroll.grid(row=0, column=1, sticky="ns")

        self.main_frame = tk.Frame(self.main_canvas, bg=self.colors["bg"])
        self.main_window = self.main_canvas.create_window((0, 0), window=self.main_frame, anchor="nw")
        self.main_frame.bind("<Configure>", self._sync_main_scrollregion)
        self.main_canvas.bind("<Configure>", self._on_main_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_main_mousewheel)
        self.root.bind_all("<Button-4>", self._on_main_mousewheel)
        self.root.bind_all("<Button-5>", self._on_main_mousewheel)

        self.status_var = tk.StringVar(value="Ready.")
        self.target_var = tk.StringVar(value="")
        self.device_var = tk.StringVar(value="")
        self.include_data_var = tk.BooleanVar(value=False)
        self.include_models_var = tk.BooleanVar(value=False)
        self.header_var = tk.StringVar(value=f"{APP_SYNC_NAME} {APP_SYNC_VERSION}")
        self.source_path_var = tk.StringVar(value=str(self.source_repo))
        self.source_meta_var = tk.StringVar(value="")
        self.targets_meta_var = tk.StringVar(value="Targets detected: scanning...")
        self.phone_var = tk.StringVar(value="Phone: scanning for ADB devices...")
        self.guide_var = tk.StringVar(value="Guide: scanning devices and repo copies...")
        self.health_var = tk.StringVar(value="Health: not checked yet.")
        self.detail_title_var = tk.StringVar(value="No target selected")
        self.detail_status_var = tk.StringVar(value="Insert or refresh a USB/external repo to begin.")
        self.detail_reason_var = tk.StringVar(value="No sync recommendation yet.")
        self.detail_path_var = tk.StringVar(value="Select a repo tile on the left.")
        self.detail_root_var = tk.StringVar(value="-")
        self.detail_freshness_var = tk.StringVar(value="-")
        self.detail_compare_var = tk.StringVar(value="-")
        self.detail_write_var = tk.StringVar(value="-")
        self.detail_memory_var = tk.StringVar(value="-")
        self.detail_device_var = tk.StringVar(value="No phone selected")

        self._git_statuses: Dict[str, Dict] = {}   # populated by _refresh_git_statuses
        self._git_accounts: List[Dict[str, str]] = []
        self._build_ui()
        self.refresh_targets()
        # Fetch git statuses in background at startup
        self.root.after(1500, self._refresh_git_statuses)

    def _panel(self, parent, bg: str):
        return self.tk.Frame(
            parent,
            bg=bg,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            bd=0,
        )

    def _make_label(
        self,
        parent,
        *,
        text: str = "",
        textvariable=None,
        bg: Optional[str] = None,
        fg: Optional[str] = None,
        font: Optional[Tuple[str, int, str]] = None,
        wraplength: int = 0,
        anchor: str = "w",
        justify: str = "left",
        padx: int = 0,
        pady: int = 0,
    ):
        return self.tk.Label(
            parent,
            text=text,
            textvariable=textvariable,
            bg=bg or self.colors["panel"],
            fg=fg or self.colors["text"],
            font=font or ("Segoe UI", 11, "normal"),
            wraplength=wraplength,
            anchor=anchor,
            justify=justify,
            padx=padx,
            pady=pady,
        )

    def _make_button(self, parent, text: str, command, *, accent: bool = False, state: str = "normal"):
        bg = self.colors["accent"] if accent else self.colors["button"]
        fg = self.colors["bg"] if accent else self.colors["text"]
        active_bg = self.colors["accent_active"] if accent else self.colors["button_active"]
        btn = self.tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            disabledforeground=self.colors["muted"],
            relief="flat",
            bd=0,
            padx=16,
            pady=14,
            cursor="hand2",
            font=("Segoe UI Semibold", 12),
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            wraplength=220,
            justify="center",
        )
        btn.configure(state=state)
        return btn

    def _sync_main_scrollregion(self, _event=None) -> None:
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _on_main_canvas_configure(self, event) -> None:
        self.main_canvas.itemconfigure(self.main_window, width=event.width)

    def _is_descendant_widget(self, widget, ancestor) -> bool:
        cur = widget
        while cur is not None:
            if cur == ancestor:
                return True
            cur = getattr(cur, "master", None)
        return False

    def _on_main_mousewheel(self, event) -> None:
        # Allow text and entry controls to keep their own native scroll behavior.
        try:
            klass = str(event.widget.winfo_class()).lower()
        except Exception:
            klass = ""
        if klass in ("text", "entry", "spinbox", "listbox"):
            return

        delta_units = 0
        if getattr(event, "num", None) == 4:
            delta_units = -1
        elif getattr(event, "num", None) == 5:
            delta_units = 1
        else:
            delta = int(getattr(event, "delta", 0) or 0)
            if delta != 0:
                delta_units = -1 if delta > 0 else 1

        if delta_units:
            target_canvas = self.main_canvas
            if (
                getattr(self, "tiles_canvas", None) is not None
                and (
                    event.widget == self.tiles_canvas
                    or (
                        getattr(self, "tiles_inner", None) is not None
                        and self._is_descendant_widget(event.widget, self.tiles_inner)
                    )
                )
            ):
                target_canvas = self.tiles_canvas
            target_canvas.yview_scroll(delta_units, "units")

    def _device_label(self, device: PhoneDevice) -> str:
        meta = (device.meta or "").strip()
        return f"{device.serial}  {meta}".strip()

    def _update_source_meta(self) -> None:
        reason = self.source_reason or "manual/default source"
        fresh = _fmt_ts(self.source_freshness_ts)
        self.source_meta_var.set(f"Selection: {reason}\nFreshness: {fresh}")

    def _target_write_check(self, target: Path) -> Tuple[bool, str]:
        probe = target / ".citl_sync_write_test.tmp"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True, "writable"
        except Exception as e:
            return False, str(e)

    def _recommendation_label(self, comparison: RepoComparison) -> str:
        mapping = {
            "push_source_to_target": "PUSH PC -> USB",
            "pull_target_to_source": "PULL USB -> PC",
            "current": "ALREADY ALIGNED",
            "review": "REVIEW BEFORE SYNC",
        }
        return mapping.get(comparison.recommendation, "REVIEW BEFORE SYNC")

    def _recommendation_color(self, comparison: RepoComparison) -> str:
        if comparison.recommendation == "push_source_to_target":
            return self.colors["good"]
        if comparison.recommendation == "current":
            return self.colors["accent"]
        if comparison.recommendation == "pull_target_to_source":
            return self.colors["warn"]
        return self.colors["danger"]

    def _recommendation_priority(self, comparison: RepoComparison) -> Tuple[int, int, int]:
        order = {
            "push_source_to_target": 0,
            "current": 1,
            "review": 2,
            "pull_target_to_source": 3,
        }
        return (
            order.get(comparison.recommendation, 9),
            -comparison.source_newer + comparison.target_newer,
            -comparison.source_only + comparison.target_only,
        )

    def _build_ui(self) -> None:
        self._update_source_meta()
        page = self.main_frame
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=3)
        page.grid_rowconfigure(6, weight=1)

        header = self.tk.Frame(page, bg=self.colors["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 10))
        header.grid_columnconfigure(0, weight=1)
        self._make_label(
            header,
            textvariable=self.header_var,
            bg=self.colors["bg"],
            font=("Segoe UI Semibold", 24, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self._make_label(
            header,
            text="Accessible USB and phone sync dashboard for CITL repo copies",
            bg=self.colors["bg"],
            fg=self.colors["muted"],
            font=("Segoe UI", 13, "normal"),
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))


        top = self.tk.Frame(page, bg=self.colors["bg"])
        top.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 12))
        top.grid_columnconfigure(0, weight=3)
        top.grid_columnconfigure(1, weight=4)

        source_card = self._panel(top, self.colors["panel"])
        source_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        source_card.grid_columnconfigure(0, weight=1)
        self._make_label(
            source_card,
            text="Local Source Repo",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))
        self._make_label(
            source_card,
            textvariable=self.source_path_var,
            bg=self.colors["panel"],
            font=("Consolas", 11, "normal"),
            wraplength=560,
        ).grid(row=1, column=0, sticky="w", padx=16)
        self._make_label(
            source_card,
            textvariable=self.source_meta_var,
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            wraplength=560,
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(10, 12))

        options = self.tk.Frame(source_card, bg=self.colors["panel"])
        options.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 16))
        data_cb = self.tk.Checkbutton(
            options,
            text="Include data and indexes",
            variable=self.include_data_var,
            command=self.refresh_targets,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            selectcolor=self.colors["button"],
            activebackground=self.colors["panel"],
            activeforeground=self.colors["text"],
            highlightthickness=0,
            font=("Segoe UI", 11),
        )
        data_cb.grid(row=0, column=0, sticky="w")
        model_cb = self.tk.Checkbutton(
            options,
            text="Include models and ollama",
            variable=self.include_models_var,
            command=self.refresh_targets,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            selectcolor=self.colors["button"],
            activebackground=self.colors["panel"],
            activeforeground=self.colors["text"],
            highlightthickness=0,
            font=("Segoe UI", 11),
        )
        model_cb.grid(row=1, column=0, sticky="w", pady=(8, 0))

        actions_card = self._panel(top, self.colors["panel_alt"])
        actions_card.grid(row=0, column=1, sticky="nsew")
        actions_card.grid_columnconfigure(0, weight=1)
        self._make_label(
            actions_card,
            text="Guided Sync Actions",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))
        self._make_label(
            actions_card,
            textvariable=self.targets_meta_var,
            bg=self.colors["panel_alt"],
            wraplength=720,
            font=("Segoe UI Semibold", 12, "bold"),
        ).grid(row=1, column=0, sticky="w", padx=16)
        self._make_label(
            actions_card,
            textvariable=self.phone_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            wraplength=720,
            font=("Segoe UI", 11, "normal"),
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(6, 0))
        self.guide_label = self._make_label(
            actions_card,
            textvariable=self.guide_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["good"],
            wraplength=720,
            font=("Segoe UI Semibold", 12, "bold"),
        )
        self.guide_label.grid(row=3, column=0, sticky="w", padx=16, pady=(8, 0))
        self._make_label(
            actions_card,
            textvariable=self.health_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            wraplength=720,
            font=("Segoe UI", 11, "normal"),
        ).grid(row=4, column=0, sticky="w", padx=16, pady=(8, 0))

        device_card = self.tk.Frame(actions_card, bg=self.colors["panel_alt"])
        device_card.grid(row=5, column=0, sticky="ew", padx=16, pady=(14, 8))
        device_card.grid_columnconfigure(0, weight=1)
        self._make_label(
            device_card,
            text="Connected Phones",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.device_button_frame = self.tk.Frame(device_card, bg=self.colors["panel_alt"])
        self.device_button_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        action_grid = self.tk.Frame(actions_card, bg=self.colors["panel_alt"])
        action_grid.grid(row=6, column=0, sticky="ew", padx=16, pady=(10, 16))
        for col in range(3):
            action_grid.grid_columnconfigure(col, weight=1)
        self.refresh_btn = self._make_button(action_grid, "1. Refresh USB + Phone", self.refresh_targets)
        self.refresh_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 10))
        self.pick_btn = self._make_button(action_grid, "2. Auto Pick Best Match", self.on_auto_pick_best)
        self.pick_btn.grid(row=0, column=1, sticky="ew", padx=8, pady=(0, 10))
        self.open_source_btn = self._make_button(action_grid, "Open Local Source", self.on_open_source)
        self.open_source_btn.grid(row=0, column=2, sticky="ew", padx=(8, 0), pady=(0, 10))
        self.push_btn = self._make_button(action_grid, "3. Push PC -> USB", self.on_push_to_target, accent=True, state="disabled")
        self.push_btn.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 10))
        self.pull_btn = self._make_button(action_grid, "4. Pull USB -> PC", self.on_pull_from_target, state="disabled")
        self.pull_btn.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 10))
        self.phone_btn = self._make_button(action_grid, "5. Send Selected USB -> Phone", self.on_send_target_to_phone, state="disabled")
        self.phone_btn.grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=(0, 10))
        self.open_target_btn = self._make_button(action_grid, "Open Selected Target", self.on_open_target, state="disabled")
        self.open_target_btn.grid(row=2, column=0, sticky="ew", padx=(0, 8))
        self.remember_btn = self._make_button(action_grid, "Remember Selected Folder", self.on_remember_target, state="disabled")
        self.remember_btn.grid(row=2, column=1, sticky="ew", padx=8)
        self.close_btn = self._make_button(action_grid, "Close", self.root.destroy)
        self.close_btn.grid(row=2, column=2, sticky="ew", padx=(8, 0))
        self.duplicate_btn = self._make_button(
            action_grid,
            "6. Duplicate Selected USB -> Backup USB",
            self.on_duplicate_usb,
            state="disabled",
        )
        self.duplicate_btn.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        body = self.tk.Frame(page, bg=self.colors["bg"])
        body.grid(row=2, column=0, sticky="nsew", padx=22, pady=(0, 12))
        body.grid_columnconfigure(0, weight=4)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(0, weight=1)

        tiles_panel = self._panel(body, self.colors["panel"])
        tiles_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        tiles_panel.grid_columnconfigure(0, weight=1)
        tiles_panel.grid_rowconfigure(1, weight=1)
        self._make_label(
            tiles_panel,
            text="Detected CITL Repo Copies",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        tile_wrap = self.tk.Frame(tiles_panel, bg=self.colors["panel"])
        tile_wrap.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tile_wrap.grid_columnconfigure(0, weight=1)
        tile_wrap.grid_rowconfigure(0, weight=1)

        self.tiles_canvas = self.tk.Canvas(tile_wrap, bg=self.colors["panel"], highlightthickness=0, bd=0)
        tile_scroll = self.tk.Scrollbar(tile_wrap, orient="vertical", command=self.tiles_canvas.yview)
        self.tiles_canvas.configure(yscrollcommand=tile_scroll.set)
        self.tiles_canvas.grid(row=0, column=0, sticky="nsew")
        tile_scroll.grid(row=0, column=1, sticky="ns")

        self.tiles_inner = self.tk.Frame(self.tiles_canvas, bg=self.colors["panel"])
        self.tiles_window = self.tiles_canvas.create_window((0, 0), window=self.tiles_inner, anchor="nw")
        self.tiles_inner.bind(
            "<Configure>",
            lambda _event: self.tiles_canvas.configure(scrollregion=self.tiles_canvas.bbox("all")),
        )
        self.tiles_canvas.bind("<Configure>", self._on_tiles_canvas_configure)

        detail_panel = self._panel(body, self.colors["panel_alt"])
        detail_panel.grid(row=0, column=1, sticky="nsew")
        detail_panel.grid_columnconfigure(0, weight=1)
        self._make_label(
            detail_panel,
            text="Selected Copy Details",
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))
        self._make_label(
            detail_panel,
            textvariable=self.detail_title_var,
            bg=self.colors["panel_alt"],
            font=("Segoe UI Semibold", 18, "bold"),
            wraplength=520,
        ).grid(row=1, column=0, sticky="w", padx=16)
        self.detail_status_label = self._make_label(
            detail_panel,
            textvariable=self.detail_status_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 16, "bold"),
            wraplength=520,
        )
        self.detail_status_label.grid(row=2, column=0, sticky="w", padx=16, pady=(8, 2))
        self.detail_reason_label = self._make_label(
            detail_panel,
            textvariable=self.detail_reason_var,
            bg=self.colors["panel_alt"],
            fg=self.colors["muted"],
            font=("Segoe UI", 11, "normal"),
            wraplength=520,
        )
        self.detail_reason_label.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 12))

        detail_fields = self.tk.Frame(detail_panel, bg=self.colors["panel_alt"])
        detail_fields.grid(row=4, column=0, sticky="ew", padx=16)
        detail_fields.grid_columnconfigure(0, weight=1)
        rows = [
            ("Target Path", self.detail_path_var, ("Consolas", 11, "normal")),
            ("Detected Unit", self.detail_root_var, ("Consolas", 11, "normal")),
            ("Average Comparison", self.detail_compare_var, ("Segoe UI", 11, "normal")),
            ("Target Freshness", self.detail_freshness_var, ("Segoe UI", 11, "normal")),
            ("Access", self.detail_write_var, ("Segoe UI", 11, "normal")),
            ("Memory", self.detail_memory_var, ("Segoe UI", 11, "normal")),
            ("Selected Phone", self.detail_device_var, ("Segoe UI", 11, "normal")),
        ]
        for idx, (title, var, font) in enumerate(rows):
            self._make_label(
                detail_fields,
                text=title,
                bg=self.colors["panel_alt"],
                fg=self.colors["muted"],
                font=("Segoe UI Semibold", 10, "bold"),
            ).grid(row=idx * 2, column=0, sticky="w", pady=(0 if idx == 0 else 10, 2))
            self._make_label(
                detail_fields,
                textvariable=var,
                bg=self.colors["panel_alt"],
                wraplength=520,
                font=font,
            ).grid(row=idx * 2 + 1, column=0, sticky="w")

        # ── GitHub Sync Panel (row 3) ──────────────────────────────────────────
        page.grid_rowconfigure(3, weight=0)
        gh_panel = self._panel(page, self.colors["panel"])
        gh_panel.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 8))
        gh_panel.grid_columnconfigure(0, weight=1)

        gh_header = self.tk.Frame(gh_panel, bg=self.colors["panel"])
        gh_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        gh_header.grid_columnconfigure(0, weight=1)
        self._make_label(
            gh_header,
            text="GitHub Sync",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self.gh_user_var = self.tk.StringVar(value="Detecting git identity...")
        self._make_label(
            gh_header,
            textvariable=self.gh_user_var,
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Consolas", 10),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Git auth status indicator
        self.gh_auth_var = self.tk.StringVar(value="")
        self._make_label(
            gh_header,
            textvariable=self.gh_auth_var,
            bg=self.colors["panel"],
            fg=self.colors["warn"],
            font=("Segoe UI", 9),
        ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        gh_btns = self.tk.Frame(gh_header, bg=self.colors["panel"])
        gh_btns.grid(row=0, column=1, rowspan=3, sticky="e")
        self._make_button(gh_btns, "Refresh Git Status", self._refresh_git_statuses).grid(
            row=0, column=0, padx=(0, 6))
        self._make_button(gh_btns, "Push All Updated", self.on_git_push_all, accent=True).grid(
            row=0, column=1, padx=(0, 6))
        self._make_button(gh_btns, "Pull All Newer", self.on_git_pull_all_newer).grid(
            row=0, column=2, padx=(0, 6))
        self._make_button(gh_btns, "Check Git Auth", self._check_git_auth).grid(
            row=0, column=3, padx=(0, 6))
        self._make_button(gh_btns, "Open GitHub.com", self._open_github_web).grid(
            row=0, column=4)

        self.gh_apps_frame = self.tk.Frame(gh_panel, bg=self.colors["panel"])
        self.gh_apps_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 14))
        self._make_label(
            self.gh_apps_frame,
            text="Click 'Refresh Git Status' to load remote state.",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, sticky="w", padx=8)

        # ── CITL App Overview (row 4) ──────────────────────────────────────────
        page.grid_rowconfigure(4, weight=0)
        apps_panel = self._panel(page, self.colors["panel"])
        apps_panel.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 12))
        apps_panel.grid_columnconfigure(0, weight=1)
        self._make_label(
            apps_panel,
            text="CITL Apps Overview",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
        self.apps_frame = self.tk.Frame(apps_panel, bg=self.colors["panel"])
        self.apps_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 14))
        self._render_apps_overview()

        status_bar = self.tk.Label(
            page,
            textvariable=self.status_var,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            anchor="w",
            padx=18,
            pady=10,
            font=("Segoe UI", 11),
        )
        status_bar.grid(row=5, column=0, sticky="ew")

        log_panel = self._panel(page, self.colors["panel"])
        log_panel.grid(row=6, column=0, sticky="nsew", padx=22, pady=(0, 18))
        log_panel.grid_columnconfigure(0, weight=1)
        log_panel.grid_rowconfigure(1, weight=1)
        self._make_label(
            log_panel,
            text="Activity Log",
            bg=self.colors["panel"],
            fg=self.colors["accent"],
            font=("Segoe UI Semibold", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))
        self.log = self.scrolledtext.ScrolledText(
            log_panel,
            wrap="word",
            state="disabled",
            bg=self.colors["card"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            relief="flat",
            bd=0,
            font=("Consolas", 10),
            padx=12,
            pady=12,
        )
        self.log.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        self._append(f"{APP_SYNC_NAME} {APP_SYNC_VERSION}\n")
        self._append("This dashboard now guides USB discovery, safe sync direction, and optional phone export.\n")
        self._append("Green recommendation means the PC source is newer and pushing to USB is the safe default.\n")
        self._append("Yellow recommendation means the USB copy appears newer and pulling back to the PC may be safer.\n")
        self._append("Red recommendation means both sides differ enough that you should review before syncing.\n")
        self._append(f"[SOURCE] {self.source_reason or 'manual/default source'}: {self.source_repo}\n")
        self._append(f"[SOURCE_FRESHNESS] {_fmt_ts(self.source_freshness_ts)}\n\n")


    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _selected_target(self) -> Optional[Path]:
        raw = self.target_var.get().strip()
        if not raw:
            return None
        return _normalize_repo_path(raw)

    def _selected_status(self) -> Optional[TargetStatus]:
        target = self._selected_target()
        if target is None:
            return None
        return self.target_status.get(str(target))

    def _selected_device(self) -> Optional[PhoneDevice]:
        raw = self.device_var.get().strip()
        if not raw:
            return None
        for device in self.devices:
            if device.serial == raw:
                return device
        return None

    def _build_target_statuses(self, targets: List[SyncTarget]) -> Dict[str, TargetStatus]:
        status: Dict[str, TargetStatus] = {}
        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        for target in targets:
            freshness_ts = _repo_freshness(target.path)
            writable, detail = self._target_write_check(target.path)
            comparison = compare_repo_freshness(
                self.source_repo,
                target.path,
                include_data=include_data,
                include_models=include_models,
            )
            status[str(target.path)] = TargetStatus(
                target=target,
                freshness_ts=freshness_ts,
                writable=writable,
                write_detail=detail,
                update_available=(comparison.recommendation == "push_source_to_target"),
                root_label=_root_label(target.root),
                comparison=comparison,
            )
        return status

    def _pick_preferred_target(self, targets: List[SyncTarget], statuses: Dict[str, TargetStatus]) -> Tuple[Optional[Path], str]:
        current = self._selected_target()
        if current is not None:
            for target in targets:
                if target.path == current:
                    return target.path, "kept current selection"

        last_selected = _last_selected_target()
        if last_selected is not None:
            for target in targets:
                if target.path == last_selected:
                    return target.path, "re-used last selected target"

        ranked: List[Tuple[Tuple[int, int, int], Path, bool]] = []
        for target in targets:
            snap = statuses.get(str(target.path))
            if snap is None:
                continue
            ranked.append((self._recommendation_priority(snap.comparison), target.path, target.remembered))
        if ranked:
            ranked.sort(key=lambda item: (0 if item[2] else 1, item[0], str(item[1]).lower()))
            best = ranked[0][1]
            return best, "selected safest available match"
        return None, ""

    def _mark_target_remembered(self, target_path: Path) -> None:
        updated: List[SyncTarget] = []
        changed = False
        for target in self.targets:
            if target.path == target_path and not target.remembered:
                updated.append(
                    SyncTarget(
                        path=target.path,
                        score=target.score,
                        has_git=target.has_git,
                        markers=target.markers,
                        root=target.root,
                        remembered=True,
                    )
                )
                changed = True
            else:
                updated.append(target)
        if changed:
            self.targets = updated
            self.target_status = self._build_target_statuses(self.targets)

    def _select_target(self, target_path: Path, *, remember: bool = True, log_selection: bool = False) -> None:
        try:
            rp = target_path.expanduser().resolve()
        except Exception:
            rp = target_path.expanduser()
        self.target_var.set(str(rp))
        if remember:
            try:
                _remember_target(rp)
                self._mark_target_remembered(rp)
            except Exception as e:
                self._append(f"[WARN] could not remember target folder: {e}\n")
        self._render_tiles()
        self._update_detail_panel()
        self._update_health_banner(log=log_selection)
        self._refresh_guidance()
        self._update_action_states()
        self._set_status(f"Selected target: {rp}")

    def _select_device(self, serial: str) -> None:
        self.device_var.set(serial)
        self._render_device_buttons()
        self._update_detail_panel()
        self._refresh_guidance()
        self._update_action_states()

    def _update_action_states(self) -> None:
        has_target = self._selected_target() is not None
        has_device = self._selected_device() is not None
        can_duplicate = has_target and len(self.targets) >= 2
        normal = "disabled" if self._busy else "normal"
        self.refresh_btn.configure(state=normal)
        self.pick_btn.configure(state=normal if (self.targets and not self._busy) else "disabled")
        self.push_btn.configure(state=normal if (has_target and not self._busy) else "disabled")
        self.pull_btn.configure(state=normal if (has_target and not self._busy) else "disabled")
        self.phone_btn.configure(state=normal if (has_target and has_device and not self._busy) else "disabled")
        self.open_target_btn.configure(state=normal if (has_target and not self._busy) else "disabled")
        self.remember_btn.configure(state=normal if (has_target and not self._busy) else "disabled")
        self.duplicate_btn.configure(state=normal if (can_duplicate and not self._busy) else "disabled")

    def _bind_tile_select(self, widget, target_path: Path) -> None:
        widget.bind("<Button-1>", lambda _event, p=target_path: self._select_target(p))

    def _on_tiles_canvas_configure(self, event) -> None:
        self.tiles_canvas.itemconfigure(self.tiles_window, width=event.width)
        columns = 1 if event.width < 980 else 2
        if columns != self._tile_columns:
            self._tile_columns = columns
            self._render_tiles()

    def _render_device_buttons(self) -> None:
        for child in self.device_button_frame.winfo_children():
            child.destroy()
        if not self.devices:
            self._make_label(
                self.device_button_frame,
                text="No Android phone detected over ADB. USB sync still works.",
                bg=self.colors["panel_alt"],
                fg=self.colors["muted"],
                wraplength=700,
            ).grid(row=0, column=0, sticky="w")
            return
        selected = self.device_var.get().strip()
        for idx, device in enumerate(self.devices):
            btn = self._make_button(
                self.device_button_frame,
                self._device_label(device),
                lambda s=device.serial: self._select_device(s),
                accent=(device.serial == selected),
            )
            btn.grid(row=idx, column=0, sticky="ew", pady=(0 if idx == 0 else 8, 0))

    def _app_source_root(self, app: dict) -> Path:
        """Return the source root for an app — its own repo_path if set, else the CITL source repo."""
        return resolve_app_source_root(app, self.source_repo)

    # ── GitHub sync methods ───────────────────────────────────────────────────

    def _git_repo_root_for_app(self, app: dict) -> Optional[Path]:
        src = self._app_source_root(app)
        return _find_git_root(src)

    def _refresh_git_statuses(self) -> None:
        """Fetch git status for all apps in a background thread, then re-render."""
        self._set_status("Fetching git status from GitHub...")
        self._append("\n[GITHUB] Refresh Git Status requested.\n")

        def worker():
            statuses: Dict[str, Dict] = {}
            accounts: List[Dict[str, str]] = []
            user_name, user_email = "", ""

            try:
                rc, u, _ = _git_run(self.source_repo, "config", "user.name")
                if rc == 0:
                    user_name = u
                rc, e, _ = _git_run(self.source_repo, "config", "user.email")
                if rc == 0:
                    user_email = e
            except Exception:
                pass

            try:
                accounts = self._detect_git_accounts()
            except Exception as e:
                self.root.after(0, lambda t=str(e): self._append(f"[GIT][WARN] account scan failed: {t}\n"))

            for app in CITL_APPS:
                self.root.after(0, lambda n=app["name"]: self._append(f"[GITHUB] checking {n}...\n"))
                try:
                    root = self._git_repo_root_for_app(app)
                    if root:
                        statuses[app["name"]] = git_status_for_repo(root)
                    else:
                        statuses[app["name"]] = {"error": "No git repo found"}
                except Exception as e:
                    statuses[app["name"]] = {"error": f"Status failed: {e}"}

            self.root.after(0, lambda: self._apply_git_statuses(statuses, user_name, user_email, accounts))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_git_statuses(
        self,
        statuses: Dict[str, Dict],
        user_name: str,
        user_email: str,
        accounts: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        self._git_statuses = statuses
        self._git_accounts = list(accounts or [])

        if self._git_accounts:
            if len(self._git_accounts) == 1:
                a = self._git_accounts[0]
                self.gh_user_var.set(f"Logged in as: {a['name']} <{a['email']}>")
                self.gh_auth_var.set("")
            else:
                first = self._git_accounts[0]
                self.gh_user_var.set(
                    f"Logged in as: {first['name']} <{first['email']}> (+{len(self._git_accounts) - 1} more)"
                )
                self.gh_auth_var.set(
                    "Multiple Git identities detected. Click 'Check Git Auth' to choose repo-local identity."
                )
        elif user_name:
            self.gh_user_var.set(f"Logged in as: {user_name} <{user_email}>")
            self.gh_auth_var.set("")
        else:
            self.gh_user_var.set("Logged in as: (no git identity detected)")

        self._render_github_panel()
        self._set_status("Git status refreshed.")

    def _render_github_panel(self) -> None:
        """Render one column per CITL app showing git branch, ahead/behind, dirty state."""
        for w in self.gh_apps_frame.winfo_children():
            w.destroy()

        if not self._git_statuses:
            self._make_label(
                self.gh_apps_frame,
                text="Click 'Refresh Git Status' to load.",
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                font=("Segoe UI", 10),
            ).grid(row=0, column=0, sticky="w", padx=8)
            return

        cols = len(CITL_APPS)
        for c in range(cols):
            self.gh_apps_frame.grid_columnconfigure(c, weight=1, uniform="ghcol")

        for idx, app in enumerate(CITL_APPS):
            st = self._git_statuses.get(app["name"]) or {}
            err = st.get("error")
            bg = self.colors["card"]

            frame = self.tk.Frame(
                self.gh_apps_frame,
                bg=bg,
                highlightthickness=1,
                highlightbackground=self.colors["border"],
                padx=12, pady=10,
            )
            frame.grid(row=0, column=idx, sticky="nsew", padx=6, pady=4)
            frame.grid_columnconfigure(0, weight=1)

            # App name
            self._make_label(frame,
                text=f"{app['icon']} {app['name']}",
                bg=bg, fg=self.colors["accent"],
                font=("Segoe UI Semibold", 11, "bold"), wraplength=210,
            ).grid(row=0, column=0, sticky="w")

            if err:
                self._make_label(frame, text=err, bg=bg, fg=self.colors["danger"],
                    font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(4, 0))
                continue

            branch = st.get("branch", "?")
            ahead  = int(st.get("ahead", 0))
            behind = int(st.get("behind", 0))
            dirty  = bool(st.get("dirty", False))
            last   = st.get("last_commit", "")
            remote_url = st.get("remote_url", "")

            # Remote URL (shortened)
            short_url = re.sub(r"https://github\.com/", "github: ", remote_url)
            self._make_label(frame, text=short_url, bg=bg, fg=self.colors["muted"],
                font=("Consolas", 8), wraplength=210,
            ).grid(row=1, column=0, sticky="w", pady=(3, 0))

            # Branch + sync state
            if ahead > 0 and behind == 0:
                sync_text = f"branch:{branch}  AHEAD {ahead}  ← push needed"
                sync_color = self.colors["warn"]
            elif behind > 0 and ahead == 0:
                sync_text = f"branch:{branch}  BEHIND {behind}  ← pull available"
                sync_color = self.colors["accent"]
            elif ahead > 0 and behind > 0:
                sync_text = f"branch:{branch}  DIVERGED +{ahead}/-{behind}  ← review"
                sync_color = self.colors["danger"]
            else:
                sync_text = f"branch:{branch}  Up to date"
                sync_color = self.colors["good"]

            if dirty:
                sync_text += "  [uncommitted changes]"

            self._make_label(frame, text=sync_text, bg=bg, fg=sync_color,
                font=("Segoe UI Semibold", 10, "bold"), wraplength=210,
            ).grid(row=2, column=0, sticky="w", pady=(6, 0))

            # Last commit
            if last:
                self._make_label(frame, text=last, bg=bg, fg=self.colors["muted"],
                    font=("Consolas", 8), wraplength=210,
                ).grid(row=3, column=0, sticky="w", pady=(4, 0))

            # Push / Pull buttons
            btn_row = self.tk.Frame(frame, bg=bg)
            btn_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))

            can_push = dirty or ahead > 0
            can_pull = behind > 0

            push_btn = self.tk.Button(btn_row,
                text="Push to GitHub",
                command=lambda a=app: self._on_git_push_app(a),
                bg=self.colors["warn"] if can_push else self.colors["button"],
                fg=self.colors["bg"] if can_push else self.colors["muted"],
                activebackground=self.colors["accent_active"],
                activeforeground=self.colors["bg"],
                relief="flat", bd=0, padx=8, pady=5,
                cursor="hand2", font=("Segoe UI Semibold", 10),
            )
            push_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            btn_row.grid_columnconfigure(0, weight=1)

            pull_btn = self.tk.Button(btn_row,
                text="Pull from GitHub",
                command=lambda a=app: self._on_git_pull_app(a),
                bg=self.colors["accent"] if can_pull else self.colors["button"],
                fg=self.colors["bg"] if can_pull else self.colors["muted"],
                activebackground=self.colors["accent_active"],
                activeforeground=self.colors["bg"],
                relief="flat", bd=0, padx=8, pady=5,
                cursor="hand2", font=("Segoe UI Semibold", 10),
            )
            pull_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))
            btn_row.grid_columnconfigure(1, weight=1)

    def _detect_git_accounts(self) -> List[Dict[str, str]]:
        """
        Scan the device for git identities already configured.
        Returns a list of dicts: [{name, email, source}, ...]
        Sources checked (in order): local repo config, global config, gh CLI, SSH config.
        Deduplicates by email when possible.
        """
        accounts: List[Dict[str, str]] = []
        seen_keys: set = set()

        def _add(name: str, email: str, source: str) -> None:
            e = (email or "").strip().lower()
            n = (name or "").strip()
            if not n and not e:
                return
            if not e and n:
                e = f"{n.lower()}@users.noreply.github.com"
            key = e or f"{source}:{n.lower()}"
            if key in seen_keys:
                return
            seen_keys.add(key)
            accounts.append({"name": n or e.split("@")[0], "email": e, "source": source})

        def _owner_from_remote(remote_url: str) -> str:
            raw = (remote_url or "").strip()
            if not raw:
                return ""
            m = re.search(r"github\.com[:/]+([^/]+)/", raw, re.IGNORECASE)
            if m:
                return m.group(1).strip()
            return ""

        # 1. Repo-local config (highest priority)
        rc, n, _ = _git_run(self.source_repo, "config", "--local", "user.name")
        rc2, e, _ = _git_run(self.source_repo, "config", "--local", "user.email")
        if rc == 0 and rc2 == 0 and e.strip():
            _add(n, e, "repo-local")

        # 1b. Repo-local config from all app repos (can differ per app/repo)
        for app in CITL_APPS:
            root = self._git_repo_root_for_app(app)
            if not root:
                continue
            rc, n, _ = _git_run(root, "config", "--local", "user.name")
            rc2, e, _ = _git_run(root, "config", "--local", "user.email")
            if rc == 0 and rc2 == 0 and (n.strip() or e.strip()):
                _add(n, e, f"repo-local:{app['name']}")
            rc3, remote_url, _ = _git_run(root, "remote", "get-url", "origin")
            if rc3 == 0 and remote_url.strip():
                owner = _owner_from_remote(remote_url)
                if owner:
                    _add(owner, f"{owner}@users.noreply.github.com", f"origin-owner:{app['name']}")

        # 2. Global git config
        rc, n, _ = _git_run(self.source_repo, "config", "--global", "user.name")
        rc2, e, _ = _git_run(self.source_repo, "config", "--global", "user.email")
        if rc == 0 and rc2 == 0 and e.strip():
            _add(n, e, "git-global")

        # 3. GitHub CLI identities
        try:
            result = subprocess.run(
                ["gh", "auth", "status", "-h", "github.com"],
                capture_output=True, text=True, timeout=6,
            )
            combined = (result.stdout or "") + (result.stderr or "")
            for m in re.finditer(r"Logged in to github\.com.*?as\s+([^\s]+)", combined, re.IGNORECASE):
                gh_user = m.group(1).strip()
                _add(gh_user, f"{gh_user}@users.noreply.github.com", "gh-cli")
            for m in re.finditer(r"github\.com\s+account\s+([^\s]+)", combined, re.IGNORECASE):
                gh_user = m.group(1).strip()
                _add(gh_user, f"{gh_user}@users.noreply.github.com", "gh-cli")
        except Exception:
            pass

        # 4. Windows Credential Manager entries for github.com
        if os.name == "nt":
            try:
                cred = subprocess.run(
                    ["cmdkey", "/list"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                ctext = (cred.stdout or "") + (cred.stderr or "")
                for m in re.finditer(r"git:https://([^@\s]+)@github\.com", ctext, re.IGNORECASE):
                    user = m.group(1).strip()
                    _add(user, f"{user}@users.noreply.github.com", "win-credential-manager")
            except Exception:
                pass

        # 5. Multiple identities in SSH config (~/.ssh/config  Host github-*)
        ssh_conf = Path.home() / ".ssh" / "config"
        if ssh_conf.exists():
            try:
                txt = ssh_conf.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r"Host\s+(github[^\n]+)", txt, re.IGNORECASE):
                    host_alias = m.group(1).strip()
                    if host_alias.lower() != "github.com":
                        # Extract identity comment if present
                        block_start = m.start()
                        block = txt[block_start:block_start + 300]
                        id_m = re.search(r"IdentityFile\s+(\S+)", block, re.IGNORECASE)
                        if id_m:
                            key_path = Path(id_m.group(1).replace("~", str(Path.home())))
                            pub = key_path.with_suffix(".pub")
                            if pub.exists():
                                pub_text = pub.read_text(encoding="utf-8", errors="ignore").strip()
                                comment = pub_text.split()[-1] if pub_text.split() else ""
                                if "@" in comment:
                                    _add(host_alias, comment, f"ssh-config({host_alias})")
            except Exception:
                pass

        # 6. SSH public key comments often include account email.
        ssh_dir = Path.home() / ".ssh"
        if ssh_dir.exists():
            try:
                for pub in ssh_dir.glob("*.pub"):
                    try:
                        text = pub.read_text(encoding="utf-8", errors="ignore").strip()
                    except Exception:
                        continue
                    parts = text.split()
                    if not parts:
                        continue
                    comment = parts[-1]
                    if "@" in comment:
                        _add(pub.stem, comment, f"ssh-key:{pub.name}")
            except Exception:
                pass

        return accounts

    def _check_git_auth(self) -> None:
        """Detect all git accounts on this device; if multiple, offer account selection."""
        self._set_status("Detecting git accounts...")
        self._append("\n[GITHUB] Check Git Auth requested.\n")

        def worker():
            accounts = self._detect_git_accounts()

            if not accounts:
                self.root.after(0, lambda: (
                    self.gh_auth_var.set("No git account detected on this device"),
                    self._set_status("No git identity found."),
                    self._append("\n[GIT] No git user.name/email configured on this device.\n"
                                 "Run: git config --global user.name 'Your Name'\n"
                                 "     git config --global user.email 'you@example.com'\n"),
                ))
                return

            if len(accounts) == 1:
                a = accounts[0]
                label = f"{a['name']} <{a['email']}> [{a['source']}]"
                self.root.after(0, lambda: (
                    self.gh_user_var.set(f"Account: {label}"),
                    self.gh_auth_var.set(""),
                    self._set_status(f"Using: {label}"),
                    self._append(f"\n[GIT] Active account: {label}\n"),
                ))
            else:
                # Multiple accounts — let user pick
                self.root.after(0, lambda: self._prompt_account_selection(accounts))

        threading.Thread(target=worker, daemon=True).start()

    def _prompt_account_selection(self, accounts: List[Dict[str, str]]) -> None:
        """Show a simple dialog to pick which git identity to use for this repo."""
        import tkinter as _tk

        dlg = _tk.Toplevel(self.root)
        dlg.title("Select GitHub Account")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(bg=self.colors["bg"])

        _tk.Label(dlg, text="Multiple git accounts detected.\nSelect which to use for this repo:",
                  bg=self.colors["bg"], fg=self.colors["text"],
                  font=("Segoe UI", 11), justify="left").pack(padx=20, pady=(16, 8))

        choice_var = _tk.StringVar()
        options = [f"{a['name']} <{a['email']}> [{a['source']}]" for a in accounts]
        choice_var.set(options[0])

        for opt in options:
            _tk.Radiobutton(
                dlg, text=opt, variable=choice_var, value=opt,
                bg=self.colors["bg"], fg=self.colors["text"],
                selectcolor=self.colors["card"],
                activebackground=self.colors["bg"],
                font=("Segoe UI", 10),
            ).pack(anchor="w", padx=24, pady=2)

        def _apply_identity(name: str, email: str, chosen_label: str) -> None:
            # Write repo-local config across all detected app repos so Push/Pull uses
            # the selected identity consistently.
            roots: Dict[str, Path] = {}
            src_root = _find_git_root(self.source_repo)
            if src_root:
                roots[str(src_root)] = src_root
            for app in CITL_APPS:
                r = self._git_repo_root_for_app(app)
                if r:
                    roots[str(r)] = r
            for r in roots.values():
                _git_run(r, "config", "--local", "user.name", name)
                _git_run(r, "config", "--local", "user.email", email)
            self.gh_user_var.set(f"Account: {chosen_label}")
            self.gh_auth_var.set("")
            self._set_status(f"Account set to: {name} <{email}> across {len(roots)} repo(s)")
            self._append(
                f"\n[GIT] Account set (repo-local across {len(roots)} repos): {chosen_label}\n"
            )
            dlg.destroy()

        def _apply():
            chosen = choice_var.get()
            idx = options.index(chosen)
            a = accounts[idx]
            _apply_identity(a["name"], a["email"], chosen)

        def _manual():
            from tkinter import simpledialog

            name = simpledialog.askstring("Manual Git Name", "Enter git user.name:", parent=dlg)
            if name is None:
                return
            name = name.strip()
            if not name:
                self.messagebox.showerror("Invalid name", "git user.name cannot be blank.", parent=dlg)
                return

            email = simpledialog.askstring("Manual Git Email", "Enter git user.email:", parent=dlg)
            if email is None:
                return
            email = email.strip().lower()
            if "@" not in email:
                self.messagebox.showerror("Invalid email", "Enter a valid email address.", parent=dlg)
                return

            label = f"{name} <{email}> [manual]"
            _apply_identity(name, email, label)

        btn_row = _tk.Frame(dlg, bg=self.colors["bg"])
        btn_row.pack(pady=(12, 16))
        self._make_button(btn_row, "Use This Account", _apply, accent=True).pack(side="left", padx=8)
        self._make_button(btn_row, "Use Manual...", _manual).pack(side="left", padx=8)
        self._make_button(btn_row, "Cancel", dlg.destroy).pack(side="left")

    def _open_github_web(self) -> None:
        """Open the GitHub remote URL in the default browser."""
        rc, url, _ = _git_run(self.source_repo, "remote", "get-url", "origin")
        if rc == 0 and url:
            web_url = url.strip()
            if web_url.startswith("git@"):
                # Convert SSH to HTTPS
                web_url = re.sub(r"^git@github\.com:", "https://github.com/", web_url)
                web_url = re.sub(r"\.git$", "", web_url)
            elif web_url.endswith(".git"):
                web_url = web_url[:-4]
            import webbrowser
            webbrowser.open(web_url)
        else:
            self.messagebox.showinfo("No remote", "No 'origin' remote URL configured for this repo.")

    def _on_git_push_app(self, app: dict) -> None:
        root = self._git_repo_root_for_app(app)
        if root is None:
            self.messagebox.showerror("No git repo", f"{app['name']}: no git repo found.")
            return
        self._begin_busy(f"Pushing {app['name']} to GitHub...")
        self._append(f"\n[GITHUB] Pushing {app['name']} ({root})...\n")

        def worker():
            ok, msg = git_commit_and_push(
                root,
                log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
            )
            self.root.after(0, lambda: self._append(
                f"[GITHUB] {'OK' if ok else 'FAILED'}: {msg}\n"
            ))
            self.root.after(0, lambda: self._set_status(
                f"{app['name']} push {'complete' if ok else 'failed'}."
            ))
            self.root.after(0, self._refresh_git_statuses)
            self.root.after(0, self._end_busy)

        threading.Thread(target=worker, daemon=True).start()

    def _on_git_pull_app(self, app: dict) -> None:
        root = self._git_repo_root_for_app(app)
        if root is None:
            self.messagebox.showerror("No git repo", f"{app['name']}: no git repo found.")
            return
        st = self._git_statuses.get(app["name"]) or {}
        if int(st.get("behind", 0)) == 0 and not self.messagebox.askyesno(
            "Confirm pull",
            f"{app['name']} is not behind the remote.\nPull anyway?"
        ):
            return
        self._begin_busy(f"Pulling {app['name']} from GitHub...")
        self._append(f"\n[GITHUB] Pulling {app['name']} ({root})...\n")

        def worker():
            ok, msg = git_pull_repo(
                root,
                log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
            )
            self.root.after(0, lambda: self._append(
                f"[GITHUB] {'OK' if ok else 'FAILED'}: {msg}\n"
            ))
            self.root.after(0, lambda: self._set_status(
                f"{app['name']} pull {'complete' if ok else 'failed'}."
            ))
            self.root.after(0, self._refresh_git_statuses)
            self.root.after(0, self._end_busy)

        threading.Thread(target=worker, daemon=True).start()

    def on_git_push_all(self) -> None:
        """Push all apps that are dirty or ahead of remote."""
        self._append("\n[GITHUB] Push All Updated requested.\n")
        to_push = [
            app for app in CITL_APPS
            if (self._git_statuses.get(app["name"]) or {}).get("dirty")
            or int((self._git_statuses.get(app["name"]) or {}).get("ahead", 0)) > 0
        ]
        if not to_push:
            self.messagebox.showinfo(
                "Nothing to push",
                "All repos are up to date with GitHub. No push needed."
            )
            return

        names = "\n".join(f"  • {a['name']}" for a in to_push)
        if not self.messagebox.askyesno(
            "Push All",
            f"Push {len(to_push)} repo(s) to GitHub?\n\n{names}\n\n"
            "A backup zip will be created for each before pushing."
        ):
            return

        self._begin_busy(f"Pushing {len(to_push)} repos to GitHub...")

        def worker():
            for app in to_push:
                root = self._git_repo_root_for_app(app)
                if root is None:
                    self.root.after(0, lambda n=app["name"]: self._append(
                        f"[GITHUB] Skipping {n}: no git repo\n"
                    ))
                    continue
                self.root.after(0, lambda n=app["name"]: self._append(
                    f"\n[GITHUB] Pushing {n}...\n"
                ))
                ok, msg = git_commit_and_push(
                    root,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda n=app["name"], o=ok, m=msg: self._append(
                    f"[GITHUB] {n}: {'OK' if o else 'FAILED'} — {m}\n"
                ))

            self.root.after(0, self._refresh_git_statuses)
            self.root.after(0, self._end_busy)
            self.root.after(0, lambda: self._set_status("Push all complete."))

        threading.Thread(target=worker, daemon=True).start()

    def on_git_pull_all_newer(self) -> None:
        """Pull all apps where remote has newer commits."""
        self._append("\n[GITHUB] Pull All Newer requested.\n")
        to_pull = [
            app for app in CITL_APPS
            if int((self._git_statuses.get(app["name"]) or {}).get("behind", 0)) > 0
        ]
        if not to_pull:
            self.messagebox.showinfo(
                "Already up to date",
                "No repos are behind their remote. Nothing to pull."
            )
            return

        names = "\n".join(f"  • {a['name']}" for a in to_pull)
        if not self.messagebox.askyesno(
            "Pull All Newer",
            f"Pull {len(to_pull)} repo(s) that are behind GitHub?\n\n{names}\n\n"
            "A backup zip will be created for each before pulling."
        ):
            return

        self._begin_busy(f"Pulling {len(to_pull)} repos from GitHub...")

        def worker():
            for app in to_pull:
                root = self._git_repo_root_for_app(app)
                if root is None:
                    continue
                self.root.after(0, lambda n=app["name"]: self._append(
                    f"\n[GITHUB] Pulling {n}...\n"
                ))
                ok, msg = git_pull_repo(
                    root,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                self.root.after(0, lambda n=app["name"], o=ok, m=msg: self._append(
                    f"[GITHUB] {n}: {'OK' if o else 'FAILED'} — {m}\n"
                ))

            self.root.after(0, self._refresh_git_statuses)
            self.root.after(0, self._end_busy)
            self.root.after(0, lambda: self._set_status("Pull all newer complete."))

        threading.Thread(target=worker, daemon=True).start()

    def _app_usb_comparison(self, app: dict) -> Tuple[str, str]:
        """
        Compare key app files between source repo and primary USB target.
        Returns (status_text, color).
        """
        target = self._selected_target() or (self.targets[0].path if self.targets else None)
        src_root = self._app_source_root(app)

        if target is None:
            return "No USB target detected", self.colors["muted"]

        # Apps with their own separate repo that isn't synced to USB yet
        if src_root != self.source_repo and not (target / app.get("repo_marker", "NOMATCH")).exists():
            return f"Separate repo — not in USB copy ({src_root.name})", self.colors["muted"]

        key_files = app.get("key_files") or []
        newer_on_pc = 0
        newer_on_usb = 0
        missing_on_usb = 0
        for rel in key_files:
            src_p = src_root / rel
            dst_p = target / rel
            if not src_p.exists():
                continue
            if not dst_p.exists():
                missing_on_usb += 1
                continue
            try:
                delta = src_p.stat().st_mtime - dst_p.stat().st_mtime
                if delta > UPDATE_AVAILABLE_EPSILON_SEC:
                    newer_on_pc += 1
                elif delta < -UPDATE_AVAILABLE_EPSILON_SEC:
                    newer_on_usb += 1
            except Exception:
                pass

        if missing_on_usb > 0 or newer_on_pc > 0:
            parts = []
            if newer_on_pc:
                parts.append(f"{newer_on_pc} file(s) newer on PC")
            if missing_on_usb:
                parts.append(f"{missing_on_usb} file(s) not on USB")
            return f"USB needs update: {', '.join(parts)}", self.colors["warn"]
        if newer_on_usb > 0:
            return f"USB is ahead ({newer_on_usb} file(s))", self.colors["accent"]
        if key_files:
            return "USB in sync", self.colors["good"]
        return "No key files tracked", self.colors["muted"]

    def _on_sync_app_files(self, app: dict) -> None:
        """Sync only the key files for a specific app to the primary USB target."""
        target = self._selected_target() or (self.targets[0].path if self.targets else None)
        if target is None:
            self.messagebox.showinfo("No Target", "No USB target detected. Refresh first.")
            return

        key_files = app.get("key_files") or []
        if not key_files:
            self.messagebox.showinfo("Nothing to sync", f"{app['name']} has no tracked key files.")
            return

        app_name = app["name"]
        src_root = self._app_source_root(app)
        self._append(f"\n[APP-SYNC] Syncing {app_name} from {src_root.name} to {target}\n")

        def worker() -> None:
            copied = 0
            errors = 0
            for rel in key_files:
                src_p = src_root / rel
                dst_p = target / rel
                if not src_p.exists():
                    continue
                try:
                    dst_p.parent.mkdir(parents=True, exist_ok=True)
                    if _needs_copy(src_p, dst_p):
                        shutil.copy2(str(src_p), str(dst_p))
                        copied += 1
                        self.root.after(0, lambda r=rel: self._append(f"  copied: {r}\n"))
                except Exception as e:
                    errors += 1
                    self.root.after(0, lambda r=rel, ex=e: self._append(f"  error: {r} — {ex}\n"))

            # Also run Ubuntu port on target after app-level sync
            try:
                port_to_ubuntu(target)
            except Exception:
                pass

            self.root.after(0, lambda: self._append(
                f"[APP-SYNC] {app_name} done — copied={copied} errors={errors}\n"
            ))
            self.root.after(0, self._render_apps_overview)

        threading.Thread(target=worker, daemon=True).start()

    def _render_apps_overview(self) -> None:
        """Render one card per CITL app showing version, USB sync status, and per-app sync button."""
        for w in self.apps_frame.winfo_children():
            w.destroy()

        cols = max(len(CITL_APPS), 1)
        for col in range(cols):
            self.apps_frame.grid_columnconfigure(col, weight=1, uniform="apptile")

        for idx, app in enumerate(CITL_APPS):
            usb_status, usb_color = self._app_usb_comparison(app)
            needs_sync = "needs update" in usb_status or "not on USB" in usb_status

            card_bg = self.colors["card"]
            border_color = self.colors["warn"] if needs_sync else self.colors["border"]
            card = self.tk.Frame(
                self.apps_frame,
                bg=card_bg,
                highlightthickness=2 if needs_sync else 1,
                highlightbackground=border_color,
                bd=0,
                padx=14,
                pady=12,
            )
            card.grid(row=0, column=idx, sticky="nsew", padx=6, pady=4)
            card.grid_columnconfigure(0, weight=1)

            # Icon + name
            self._make_label(
                card,
                text=f"{app['icon']}  {app['name']}",
                bg=card_bg,
                fg=self.colors["accent"],
                font=("Segoe UI Semibold", 12, "bold"),
                wraplength=250,
            ).grid(row=0, column=0, sticky="w")

            # Description
            self._make_label(
                card,
                text=app["description"],
                bg=card_bg,
                fg=self.colors["muted"],
                font=("Segoe UI", 9, "normal"),
                wraplength=250,
            ).grid(row=1, column=0, sticky="w", pady=(4, 0))

            # Version (source)
            src_root = self._app_source_root(app)
            ver = _read_version_file(src_root, app.get("version_file"))
            ver_text = f"v{ver}" if ver else "—"
            repo_label = f"  [{src_root.name}]" if src_root != self.source_repo else ""
            self._make_label(
                card,
                text=f"PC version: {ver_text}{repo_label}",
                bg=card_bg,
                fg=self.colors["text"],
                font=("Consolas", 10, "normal"),
            ).grid(row=2, column=0, sticky="w", pady=(8, 0))

            # Key files with mtime
            key_files = app.get("key_files") or []
            file_lines = []
            for rel in key_files[:3]:
                p = src_root / rel
                if p.exists():
                    try:
                        mtime = _fmt_ts(p.stat().st_mtime)
                    except Exception:
                        mtime = "?"
                    file_lines.append(f"  {Path(rel).name}  {mtime}")
                else:
                    file_lines.append(f"  {Path(rel).name}  [not in source]")
            if file_lines:
                self._make_label(
                    card,
                    text="\n".join(file_lines),
                    bg=card_bg,
                    fg=self.colors["muted"],
                    font=("Consolas", 9, "normal"),
                    wraplength=260,
                ).grid(row=3, column=0, sticky="w", pady=(4, 0))

            # USB sync status
            self._make_label(
                card,
                text=usb_status,
                bg=card_bg,
                fg=usb_color,
                font=("Segoe UI Semibold", 10, "bold"),
                wraplength=250,
            ).grid(row=4, column=0, sticky="w", pady=(8, 0))

            # Platform readiness (check against the app's own source root)
            slug = _slugify_name(app.get("name", "app"))
            fallback_win = self.source_repo / "bootstrap" / "windows" / f"Run-{slug}.cmd"
            fallback_nix = self.source_repo / "bootstrap" / "linux" / f"run-{slug}.sh"

            win_ok = None
            nix_ok = None
            parts = []
            if app.get("launcher_win"):
                win_ok = (src_root / app["launcher_win"]).exists() or fallback_win.exists()
                parts.append(f"Win {'OK' if win_ok else '!'}")
            else:
                win_ok = fallback_win.exists()
                parts.append(f"Win {'OK' if win_ok else '!'} (bootstrap)")
            if app.get("launcher_nix"):
                nix_ok = (src_root / app["launcher_nix"]).exists() or fallback_nix.exists()
                parts.append(f"Ubuntu {'OK' if nix_ok else '!'}")
            else:
                nix_ok = fallback_nix.exists()
                parts.append(f"Ubuntu {'OK' if nix_ok else '!'} (bootstrap)")
            if parts:
                all_ok = all(x for x in [win_ok, nix_ok] if x is not None)
                self._make_label(
                    card,
                    text="  ".join(parts),
                    bg=card_bg,
                    fg=self.colors["good"] if all_ok else self.colors["warn"],
                    font=("Segoe UI", 9, "normal"),
                ).grid(row=5, column=0, sticky="w", pady=(2, 0))

            # Per-app sync button
            if key_files:
                btn_text = "Sync This App to USB" if needs_sync else "Re-sync App to USB"
                btn_color = self.colors["warn"] if needs_sync else self.colors["button"]
                btn_fg = self.colors["bg"] if needs_sync else self.colors["text"]
                btn = self.tk.Button(
                    card,
                    text=btn_text,
                    command=lambda a=app: self._on_sync_app_files(a),
                    bg=btn_color,
                    fg=btn_fg,
                    activebackground=self.colors["accent_active"],
                    activeforeground=self.colors["bg"],
                    relief="flat",
                    bd=0,
                    padx=10,
                    pady=6,
                    cursor="hand2",
                    font=("Segoe UI Semibold", 10),
                    wraplength=220,
                )
                btn.grid(row=6, column=0, sticky="ew", pady=(10, 0))

    def _render_tiles(self) -> None:
        for child in self.tiles_inner.winfo_children():
            child.destroy()

        if not self.targets:
            self._make_label(
                self.tiles_inner,
                text="No compatible external repo was detected yet. Insert a known USB or external CITL copy and click Refresh USB + Phone.",
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                wraplength=860,
            ).grid(row=0, column=0, sticky="w", padx=14, pady=14)
            return

        cols = max(self._tile_columns, 1)
        for col in range(cols):
            self.tiles_inner.grid_columnconfigure(col, weight=1, uniform="tile")

        selected = str(self._selected_target() or "")
        for idx, target in enumerate(self.targets):
            snap = self.target_status.get(str(target.path))
            if snap is None:
                continue
            is_selected = selected == str(target.path)
            card_bg = self.colors["card_selected"] if is_selected else self.colors["card"]
            border = self.colors["accent"] if is_selected else self.colors["border"]
            rec_label = self._recommendation_label(snap.comparison)
            rec_color = self._recommendation_color(snap.comparison)
            memory_text = "LAST KNOWN FOLDER" if target.remembered else "NEW DETECTION"
            memory_color = self.colors["warn"] if target.remembered else self.colors["muted"]
            writable_text = "Writable" if snap.writable else "Read-only / blocked"
            writable_color = self.colors["good"] if snap.writable else self.colors["danger"]

            card = self.tk.Frame(
                self.tiles_inner,
                bg=card_bg,
                highlightthickness=2 if is_selected else 1,
                highlightbackground=border,
                highlightcolor=self.colors["accent"],
                bd=0,
                cursor="hand2",
                padx=14,
                pady=14,
            )
            row = idx // cols
            col = idx % cols
            card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)

            title = self._make_label(
                card,
                text=target.path.name or str(target.path),
                bg=card_bg,
                font=("Segoe UI Semibold", 14, "bold"),
                wraplength=420,
            )
            title.grid(row=0, column=0, sticky="w")
            status = self._make_label(
                card,
                text=rec_label,
                bg=card_bg,
                fg=rec_color,
                font=("Segoe UI Semibold", 11, "bold"),
            )
            status.grid(row=0, column=1, sticky="e")
            path_label = self._make_label(
                card,
                text=str(target.path),
                bg=card_bg,
                fg=self.colors["text"],
                font=("Consolas", 10, "normal"),
                wraplength=500,
            )
            path_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 4))
            root_label = self._make_label(
                card,
                text=f"Unit: {snap.root_label}",
                bg=card_bg,
                fg=self.colors["muted"],
                font=("Segoe UI", 10, "normal"),
                wraplength=500,
            )
            root_label.grid(row=2, column=0, columnspan=2, sticky="w")
            # Changed-files summary
            changed_lines = []
            if snap.comparison.newer_source_files:
                changed_lines.append("Updated: " + ", ".join(
                    Path(f).name for f in snap.comparison.newer_source_files[:5]
                ))
            if snap.comparison.new_source_files:
                changed_lines.append("New: " + ", ".join(
                    Path(f).name for f in snap.comparison.new_source_files[:3]
                ))
            if not changed_lines:
                changed_lines.append(
                    f"Newer on source: {snap.comparison.source_newer}  "
                    f"Newer on target: {snap.comparison.target_newer}  "
                    f"Source only: {snap.comparison.source_only}"
                )
            compare_label = self._make_label(
                card,
                text="\n".join(changed_lines),
                bg=card_bg,
                fg=self.colors["warn"] if snap.comparison.newer_source_files or snap.comparison.new_source_files else self.colors["muted"],
                font=("Segoe UI", 10, "normal"),
                wraplength=500,
            )
            compare_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
            avg_label = self._make_label(
                card,
                text=(
                    f"Average freshness: PC {_fmt_ts(snap.comparison.source_avg_ts)} | "
                    f"copy {_fmt_ts(snap.comparison.target_avg_ts)}"
                ),
                bg=card_bg,
                fg=self.colors["muted"],
                font=("Segoe UI", 10, "normal"),
                wraplength=500,
            )
            avg_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
            footer_left = self._make_label(
                card,
                text=memory_text,
                bg=card_bg,
                fg=memory_color,
                font=("Segoe UI Semibold", 10, "bold"),
            )
            footer_left.grid(row=5, column=0, sticky="w", pady=(12, 0))
            footer_right = self._make_label(
                card,
                text=writable_text,
                bg=card_bg,
                fg=writable_color,
                font=("Segoe UI Semibold", 10, "bold"),
            )
            footer_right.grid(row=5, column=1, sticky="e", pady=(12, 0))

            for widget in (card, title, status, path_label, root_label, compare_label, avg_label, footer_left, footer_right):
                self._bind_tile_select(widget, target.path)


    def _update_detail_panel(self) -> None:
        snap = self._selected_status()
        device = self._selected_device()
        self.detail_device_var.set(self._device_label(device) if device else "No phone selected")
        if snap is None:
            self.detail_title_var.set("No target selected")
            self.detail_status_var.set("Insert or refresh a USB or external repo to begin.")
            self.detail_status_label.configure(fg=self.colors["muted"])
            self.detail_reason_var.set("The utility will auto-pick the safest match once compatible copies are found.")
            self.detail_path_var.set("Select a repo tile on the left.")
            self.detail_root_var.set("-")
            self.detail_freshness_var.set("-")
            self.detail_compare_var.set("-")
            self.detail_write_var.set("-")
            self.detail_memory_var.set("-")
            self._update_action_states()
            return

        target = snap.target
        comparison = snap.comparison
        status_text = self._recommendation_label(comparison)
        status_color = self._recommendation_color(comparison)
        write_text = "Writable" if snap.writable else f"Not writable: {snap.write_detail}"
        memory_text = "Remembered for this detected unit" if target.remembered else "Seen in current scan only"

        self.detail_title_var.set(target.path.name or str(target.path))
        self.detail_status_var.set(status_text)
        self.detail_status_label.configure(fg=status_color)
        self.detail_reason_var.set(comparison.summary)
        self.detail_path_var.set(str(target.path))
        self.detail_root_var.set(snap.root_label)
        self.detail_freshness_var.set(_fmt_ts(snap.freshness_ts))
        self.detail_compare_var.set(
            f"PC newer files {comparison.source_newer}; copy newer files {comparison.target_newer}; "
            f"PC-only files {comparison.source_only}; copy-only files {comparison.target_only}; "
            f"shared tracked files {comparison.common_files}"
        )
        self.detail_write_var.set(write_text)
        self.detail_memory_var.set(memory_text)
        self._update_action_states()

    def _refresh_guidance(self) -> None:
        snap = self._selected_status()
        if snap is None:
            self.guide_var.set("Guide: click Refresh USB + Phone to auto-find repo copies and any connected Android device.")
            self.guide_label.configure(fg=self.colors["muted"])
            return
        comparison = snap.comparison
        if comparison.recommendation == "push_source_to_target":
            self.guide_var.set("Guide: the local PC copy looks newer on average. Push PC -> USB is the safe default.")
        elif comparison.recommendation == "pull_target_to_source":
            self.guide_var.set("Guide: the selected USB copy looks newer on average. Pull USB -> PC before pushing anything else.")
        elif comparison.recommendation == "current":
            self.guide_var.set("Guide: the selected copy appears aligned. No repo sync is needed unless you want a fresh export to phone.")
        else:
            self.guide_var.set("Guide: both sides have differences. Review the counts before pushing or pulling so you do not overwrite newer work.")
        if len(self.targets) >= 2:
            self.guide_var.set(self.guide_var.get() + " You can also duplicate the selected USB to another backup USB.")
        self.guide_label.configure(fg=self._recommendation_color(comparison))

    def _update_health_banner(self, *, log: bool = False) -> None:
        source_ok = _has_repo_marker(self.source_repo)
        snap = self._selected_status()
        device = self._selected_device()
        parts: List[str] = []
        parts.append("source=ok" if source_ok else "source=missing-markers")
        if snap is None:
            parts.append("target=not-selected")
            ok = source_ok
        else:
            parts.append(f"target={'writable' if snap.writable else 'not-writable'}")
            parts.append(f"recommendation={snap.comparison.recommendation}")
            ok = source_ok and snap.writable
        parts.append(f"targets_detected={len(self.targets)}")
        parts.append(f"phones_detected={len(self.devices)}")
        if device is not None:
            parts.append(f"selected_phone={device.serial}")
        msg = ("Health PASS: " if ok else "Health WARN: ") + ", ".join(parts)
        self.health_var.set(msg)
        if log:
            self._append(f"[HEALTH] {msg}\n")

    def refresh_targets(self) -> None:
        self._set_status("Scanning USB targets and ADB phones...")
        self._append("\n[SCAN] discovering candidate repo targets and phones...\n")

        def worker() -> None:
            # Always run Ubuntu port checks on source repo at scan time
            try:
                ubuntu_results = port_to_ubuntu(
                    self.source_repo,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
                any_updated = any("UPDATED" in v for v in ubuntu_results.values())
                if any_updated:
                    self.root.after(0, self._render_apps_overview)
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[WARN] Ubuntu port check: {e}\n"))

            try:
                targets = discover_sync_targets(self.source_repo)
                devices = connected_phone_devices()
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[ERROR] scan failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("Scan failed."))
                return
            self.root.after(0, lambda: self._apply_refresh(targets, devices))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_refresh(self, targets: List[SyncTarget], devices: List[PhoneDevice]) -> None:
        self.targets = targets
        self.devices = devices
        self.target_status = self._build_target_statuses(targets)
        preferred, reason = self._pick_preferred_target(targets, self.target_status)
        if devices:
            if self.device_var.get().strip() not in {item.serial for item in devices}:
                self.device_var.set(devices[0].serial)
            self.phone_var.set(f"Phone ready: {len(devices)} device(s) over ADB. Selected: {self._device_label(self._selected_device() or devices[0])}")
        else:
            self.device_var.set("")
            self.phone_var.set("Phone: no Android device detected over ADB. USB sync is still available.")

        updates = sum(1 for item in self.target_status.values() if item.comparison.recommendation == "push_source_to_target")
        pulls = sum(1 for item in self.target_status.values() if item.comparison.recommendation == "pull_target_to_source")
        reviews = sum(1 for item in self.target_status.values() if item.comparison.recommendation == "review")
        remembered = sum(1 for target in targets if target.remembered)
        if targets:
            self.targets_meta_var.set(
                f"Targets found: {len(targets)} | safe pushes: {updates} | safer pulls: {pulls} | review first: {reviews} | remembered folders: {remembered}"
            )
            self._append(
                f"[SCAN] found {len(targets)} target(s); push-safe={updates}; pull-safer={pulls}; review-first={reviews}; remembered={remembered}\n"
            )
            if preferred is not None:
                self.target_var.set(str(preferred))
                self._append(f"[SCAN] {reason}: {preferred}\n")
                self._set_status(f"Found {len(targets)} candidate target(s).")
            else:
                self.target_var.set("")
                self._set_status("Found targets, but no default selection was available.")
        else:
            self.target_var.set("")
            self.targets_meta_var.set("Targets found: 0")
            self._append("[SCAN] no compatible external CITL repo found.\n")
            self._set_status("No target found. Insert or mount a repo copy and click Refresh USB + Phone.")

        self._render_device_buttons()
        self._render_tiles()
        self._update_detail_panel()
        self._update_health_banner(log=True)
        self._refresh_guidance()
        self._update_action_states()

    def on_open_source(self) -> None:
        try:
            open_in_file_manager(self.source_repo)
        except Exception as e:
            self.messagebox.showerror("Open failed", str(e))

    def on_open_target(self) -> None:
        target = self._selected_target()
        if not target:
            self.messagebox.showinfo("No target", "Select a repo tile first.")
            return
        try:
            _remember_target(target)
            self._mark_target_remembered(target)
            open_in_file_manager(target)
            self._update_detail_panel()
            self._render_tiles()
        except Exception as e:
            self.messagebox.showerror("Open failed", str(e))

    def on_remember_target(self) -> None:
        target = self._selected_target()
        if not target:
            self.messagebox.showinfo("No target", "Select a repo tile first.")
            return
        try:
            _remember_target(target)
            self._mark_target_remembered(target)
        except Exception as e:
            self.messagebox.showerror("Remember failed", str(e))
            return
        self._append(f"[STATE] remembered target folder for auto-detection: {target}\n")
        self._update_detail_panel()
        self._render_tiles()
        self._set_status(f"Remembered target folder: {target}")

    def on_auto_pick_best(self) -> None:
        if not self.targets:
            self.messagebox.showinfo("No targets", "Refresh first so the utility can find USB copies.")
            return
        preferred, reason = self._pick_preferred_target(self.targets, self.target_status)
        if preferred is None:
            self.messagebox.showinfo("No recommendation", "No safe default target was available.")
            return
        self._select_target(preferred, log_selection=True)
        self._append(f"[GUIDE] auto-picked best target: {preferred} ({reason})\n")

    def on_health_check(self) -> None:
        self._update_health_banner(log=True)
        self._refresh_guidance()
        self._set_status("Health check complete.")


    def _choose_duplicate_destination(self, source_target: Path) -> Optional[Tuple[Path, RepoComparison]]:
        candidates = [t for t in self.targets if t.path != source_target]
        if not candidates:
            return None
        picked = _pick_duplicate_target(
            source_target,
            candidates,
            include_data=bool(self.include_data_var.get()),
            include_models=bool(self.include_models_var.get()),
        )
        if picked is None:
            return None
        dest_target, comparison = picked
        self._append(f"[DUPLICATE] auto-picked destination: {dest_target}\n")
        return dest_target, comparison

    def _prepare_model_sync_plan(
        self,
        op_label: str,
        source_repo_for_models: Path,
        target_repo_for_models: Path,
    ) -> Optional[Tuple[bool, Optional[Path], Optional[Path]]]:
        include_models = bool(self.include_models_var.get())
        if not include_models:
            return (False, None, None)

        model_candidates = candidate_ollama_model_dirs(source_repo_for_models)
        default_source = model_candidates[0] if model_candidates else None
        default_target = recommended_ollama_model_target_dir(target_repo_for_models)

        detected_size = _dir_size_bytes(default_source) if default_source else 0
        size_msg = _fmt_bytes(detected_size) if detected_size > 0 else "unknown"
        warn = (
            f"{op_label} requested model sync.\n\n"
            "Model files can be very large (often 8 GB to 100+ GB).\n"
            "Please make sure you already pulled required models first, for example:\n"
            "  ollama pull qwen2.5:7b\n"
            "  ollama pull nomic-embed-text\n\n"
            "Continue with model transfer setup now?"
        )
        if not self.messagebox.askyesno("Model Sync Preflight", warn):
            if self.messagebox.askyesno(
                "Skip model files?",
                "Continue this sync WITHOUT copying model files?",
            ):
                return (False, None, None)
            return None

        source_dir: Optional[Path] = None
        if default_source:
            source_prompt = (
                "Use detected model source directory?\n\n"
                f"{default_source}\n\n"
                f"Approximate size: {size_msg}\n"
            )
            if detected_size >= MODEL_SYNC_WARN_BYTES:
                source_prompt += "\nWarning: this is a large transfer."
            if self.messagebox.askyesno("Model Source Directory", source_prompt):
                source_dir = default_source

        if source_dir is None:
            picked = self.filedialog.askdirectory(
                title="Select Ollama model source directory",
                initialdir=str(source_repo_for_models),
                mustexist=True,
            )
            if not picked:
                return None
            source_dir = Path(picked).expanduser()

        if not source_dir.exists() or not source_dir.is_dir():
            self.messagebox.showerror("Invalid model source", f"Directory not found:\n{source_dir}")
            return None

        target_choice = self.messagebox.askyesnocancel(
            "Model Target Directory",
            "Choose destination for model storage.\n\n"
            f"Recommended (keeps models out of repo and easier to manage size):\n{default_target}\n\n"
            "Yes = use recommended path\n"
            "No = pick a custom path\n"
            "Cancel = stop this sync",
        )
        if target_choice is None:
            return None
        if target_choice:
            target_dir = default_target
        else:
            picked_target = self.filedialog.askdirectory(
                title="Select destination model directory",
                initialdir=str(_guess_usb_root(target_repo_for_models)),
                mustexist=False,
            )
            if not picked_target:
                return None
            target_dir = Path(picked_target).expanduser()

        self._append(
            f"[MODEL] external model copy enabled\n"
            f"[MODEL] source={source_dir} ({_fmt_bytes(_dir_size_bytes(source_dir))})\n"
            f"[MODEL] target={target_dir}\n"
        )
        return (True, source_dir, target_dir)

    def _sync_app_key_overlay(self, target_repo: Path) -> Tuple[int, int, int]:
        summary = sync_registered_app_key_files(
            self.source_repo,
            target_repo,
            log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
        )
        total_copied = sum(v.get("copied", 0) for v in summary.values())
        total_missing = sum(v.get("missing", 0) for v in summary.values())
        total_errors = sum(v.get("errors", 0) for v in summary.values())
        self.root.after(
            0,
            lambda: self._append(
                f"[APP-SYNC][OVERLAY] apps={len(summary)} copied={total_copied} "
                f"missing={total_missing} errors={total_errors}\n"
            ),
        )
        return total_copied, total_missing, total_errors

    def _confirm_sync_direction(self, mode: str, snap: TargetStatus) -> bool:
        comparison = snap.comparison
        if mode == "push":
            title = "Confirm PC -> USB sync"
            if comparison.recommendation == "pull_target_to_source":
                return self.messagebox.askyesno(
                    title,
                    "Warning: this USB copy looks newer on average than the PC source.\n\n"
                    f"{comparison.summary}\n\n"
                    "Pushing now may overwrite newer USB work. Continue anyway?",
                )
            if comparison.recommendation == "review":
                return self.messagebox.askyesno(
                    title,
                    "Warning: both sides have mixed newer components.\n\n"
                    f"{comparison.summary}\n\n"
                    "Continue with PC -> USB push anyway?",
                )
            return self.messagebox.askyesno(
                title,
                f"Push the local PC source to this USB copy?\n\n{comparison.summary}",
            )

        title = "Confirm USB -> PC sync"
        if comparison.recommendation == "push_source_to_target":
            return self.messagebox.askyesno(
                title,
                "Warning: the PC source looks newer on average than the selected USB copy.\n\n"
                f"{comparison.summary}\n\n"
                "Pulling now may overwrite newer PC work. Continue anyway?",
            )
        if comparison.recommendation == "review":
            return self.messagebox.askyesno(
                title,
                "Warning: both sides have mixed newer components.\n\n"
                f"{comparison.summary}\n\n"
                "Continue with USB -> PC pull anyway?",
            )
        return self.messagebox.askyesno(
            title,
            f"Pull the selected USB copy back into the local PC source?\n\n{comparison.summary}",
        )

    def _begin_busy(self, label: str) -> None:
        self._busy = True
        self._set_status(label)
        self._update_action_states()

    def _finish_busy(self) -> None:
        self._busy = False
        self._update_action_states()

    # Alias used by GitHub worker threads
    _end_busy = _finish_busy

    def on_push_to_target(self) -> None:
        target = self._selected_target()
        snap = self._selected_status()
        if not target or snap is None:
            self.messagebox.showerror("No target", "Select a repo tile first.")
            return
        if not self._confirm_sync_direction("push", snap):
            return

        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        model_plan = self._prepare_model_sync_plan(
            "PC -> USB push",
            self.source_repo,
            target,
        )
        if model_plan is None:
            return
        include_models_effective, model_source_dir, model_target_dir = model_plan
        try:
            _remember_target(target)
            self._mark_target_remembered(target)
        except Exception as e:
            self._append(f"[WARN] could not persist target memory before push: {e}\n")

        self._begin_busy("Syncing PC source to selected USB copy...")
        self._append("\n[SYNC] starting PC -> USB push...\n")

        def worker() -> None:
            try:
                result = sync_repo(
                    self.source_repo,
                    target,
                    include_data=include_data,
                    include_models=include_models_effective,
                    model_source_dir=model_source_dir,
                    model_target_dir=model_target_dir,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[ERROR] push failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("PC -> USB push failed."))
            else:
                mode = "rsync" if result.used_rsync else "python-copy"
                self.root.after(
                    0,
                    lambda: self._append(
                        f"[DONE] PC -> USB mode={mode} copied={result.copied} skipped={result.skipped} "
                        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s\n"
                    ),
                )
                # Auto-bump version numbers in source repo after successful push
                if result.errors == 0:
                    self._sync_app_key_overlay(target)
                    bumped = []
                    for app in CITL_APPS:
                        vf = app.get("version_file")
                        if vf and _bump_version_file(self.source_repo, vf):
                            bumped.append(vf)
                    if bumped:
                        self.root.after(0, lambda b=bumped: self._append(
                            f"[VERSION] auto-bumped patch in: {', '.join(b)}\n"
                        ))
                        self.root.after(0, self._render_apps_overview)
                self.root.after(0, lambda: self._set_status("PC -> USB push complete. Refreshing analysis..."))
            finally:
                self.root.after(0, self._after_sync_action)

        threading.Thread(target=worker, daemon=True).start()

    def on_pull_from_target(self) -> None:
        target = self._selected_target()
        snap = self._selected_status()
        if not target or snap is None:
            self.messagebox.showerror("No target", "Select a repo tile first.")
            return
        if not self._confirm_sync_direction("pull", snap):
            return

        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        model_plan = self._prepare_model_sync_plan(
            "USB -> PC pull",
            target,
            self.source_repo,
        )
        if model_plan is None:
            return
        include_models_effective, model_source_dir, model_target_dir = model_plan
        self._begin_busy("Syncing selected USB copy back to local PC source...")
        self._append("\n[SYNC] starting USB -> PC pull...\n")

        def worker() -> None:
            try:
                result = sync_repo(
                    target,
                    self.source_repo,
                    include_data=include_data,
                    include_models=include_models_effective,
                    model_source_dir=model_source_dir,
                    model_target_dir=model_target_dir,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[ERROR] pull failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("USB -> PC pull failed."))
            else:
                mode = "rsync" if result.used_rsync else "python-copy"
                self.root.after(
                    0,
                    lambda: self._append(
                        f"[DONE] USB -> PC mode={mode} copied={result.copied} skipped={result.skipped} "
                        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s\n"
                    ),
                )
                self.root.after(0, lambda: self._set_status("USB -> PC pull complete. Refreshing analysis..."))
            finally:
                self.root.after(0, self._after_sync_action)

        threading.Thread(target=worker, daemon=True).start()

    def on_duplicate_usb(self) -> None:
        self._append("\n[SYNC] duplicate button pressed.\n")
        source_target = self._selected_target()
        if source_target is None:
            self.messagebox.showerror("No target", "Select the USB copy you want to duplicate from.")
            return
        picked = self._choose_duplicate_destination(source_target)
        if picked is None:
            self.messagebox.showerror(
                "No destination",
                "No backup USB destination was detected. Connect another CITL USB and refresh.",
            )
            return
        dest_target, comparison = picked
        if source_target == dest_target:
            self.messagebox.showerror("Invalid destination", "Source and destination USB paths are the same.")
            return

        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        if not self.messagebox.askyesno(
            "Confirm USB duplication",
            "Duplicate selected USB copy to backup USB?\n\n"
            f"From:\n{source_target}\n\n"
            f"To:\n{dest_target}\n\n"
            f"{comparison.summary}",
        ):
            return

        model_plan = self._prepare_model_sync_plan(
            "USB -> USB duplicate",
            source_target,
            dest_target,
        )
        if model_plan is None:
            return
        include_models_effective, model_source_dir, model_target_dir = model_plan

        self._begin_busy("Duplicating selected USB copy to backup USB...")
        self._append("\n[SYNC] starting USB -> USB duplicate...\n")

        def worker() -> None:
            try:
                result = sync_repo(
                    source_target,
                    dest_target,
                    include_data=include_data,
                    include_models=include_models_effective,
                    model_source_dir=model_source_dir,
                    model_target_dir=model_target_dir,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[ERROR] duplicate failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("USB duplicate failed."))
            else:
                mode = "rsync" if result.used_rsync else "python-copy"
                self.root.after(
                    0,
                    lambda: self._append(
                        f"[DONE] USB duplicate mode={mode} copied={result.copied} skipped={result.skipped} "
                        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s\n"
                    ),
                )
                if result.errors == 0:
                    self._sync_app_key_overlay(dest_target)
                self.root.after(0, lambda: self._set_status("USB duplicate complete. Refreshing analysis..."))
            finally:
                self.root.after(0, self._after_sync_action)

        threading.Thread(target=worker, daemon=True).start()

    def on_send_target_to_phone(self) -> None:
        target = self._selected_target()
        device = self._selected_device()
        if target is None:
            self.messagebox.showerror("No target", "Select the USB copy you want to send to the phone.")
            return
        if device is None:
            self.messagebox.showerror("No phone", "No Android phone is selected. Connect one over ADB first.")
            return

        include_data = bool(self.include_data_var.get())
        include_models = bool(self.include_models_var.get())
        if not self.messagebox.askyesno(
            "Confirm USB -> phone export",
            "Create a ZIP bundle from the selected repo copy and push it to the phone's Downloads folder?\n\n"
            f"Selected copy:\n{target}\n\n"
            f"Phone:\n{self._device_label(device)}\n\n"
            f"Include data/indexes: {'yes' if include_data else 'no'}\n"
            f"Include models/ollama: {'yes' if include_models else 'no'}\n",
        ):
            return

        self._begin_busy("Building ZIP and sending selected copy to phone...")
        self._append("\n[PHONE] starting USB -> phone export...\n")

        def worker() -> None:
            try:
                result = push_repo_archive_to_phone(
                    target,
                    device.serial,
                    include_data=include_data,
                    include_models=include_models,
                    log_fn=lambda s: self.root.after(0, lambda t=s: self._append(t)),
                )
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[ERROR] phone export failed: {e}\n"))
                self.root.after(0, lambda: self._set_status("USB -> phone export failed."))
            else:
                self.root.after(
                    0,
                    lambda: self._append(
                        f"[DONE] phone export files={result['file_count']} bytes={result['byte_count']} "
                        f"elapsed={result['elapsed_sec']:.1f}s remote={result['remote_path']} serial={result['serial']}\n"
                    ),
                )
                self.root.after(0, lambda: self._set_status("USB -> phone export complete."))
            finally:
                self.root.after(0, self._after_phone_action)

        threading.Thread(target=worker, daemon=True).start()

    def _after_sync_action(self) -> None:
        self._finish_busy()
        self.refresh_targets()

    def _after_phone_action(self) -> None:
        self._finish_busy()
        self.refresh_targets()

    def on_sync(self) -> None:
        self.on_push_to_target()

    def run(self) -> None:
        self.root.mainloop()


def launch_sync_gui(source_repo: PathLike, source_reason: str = "", source_freshness_ts: float = 0.0) -> None:
    gui = SyncGUI(
        source_repo=source_repo,
        source_reason=source_reason,
        source_freshness_ts=source_freshness_ts,
    )
    gui.run()


def _print_detect_json(source: SourceDetection) -> int:
    targets = discover_sync_targets(source.path)
    payload = {
        "app": {
            "name": APP_SYNC_NAME,
            "version": APP_SYNC_VERSION,
        },
        "source": {
            "path": str(source.path),
            "reason": source.reason,
            "freshness_ts": source.freshness_ts,
            "freshness_local": _fmt_ts(source.freshness_ts),
        },
        "targets": [
            {
                "path": str(t.path),
                "score": t.score,
                "has_git": t.has_git,
                "markers": list(t.markers),
                "root": str(t.root),
                "root_label": _root_label(t.root),
                "remembered": t.remembered,
                "freshness_ts": _repo_freshness(t.path),
                "freshness_local": _fmt_ts(_repo_freshness(t.path)),
                "comparison": {
                    "recommendation": compare_repo_freshness(source.path, t.path).recommendation,
                    "summary": compare_repo_freshness(source.path, t.path).summary,
                    "source_newer": compare_repo_freshness(source.path, t.path).source_newer,
                    "target_newer": compare_repo_freshness(source.path, t.path).target_newer,
                    "source_only": compare_repo_freshness(source.path, t.path).source_only,
                    "target_only": compare_repo_freshness(source.path, t.path).target_only,
                },
            }
            for t in targets
        ],
        "phones": [
            {
                "serial": item.serial,
                "state": item.state,
                "meta": item.meta,
            }
            for item in connected_phone_devices()
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


def _run_headless_sync(args: argparse.Namespace, source: SourceDetection) -> int:
    print(f"[SOURCE] {source.path} ({source.reason})")
    model_source_arg = (getattr(args, "ollama_model_source", "") or "").strip()
    model_target_arg = (getattr(args, "ollama_model_target", "") or "").strip()
    if bool(args.include_models) and (not model_source_arg or not model_target_arg):
        print(
            "[WARN] --include-models set without both --ollama-model-source and "
            "--ollama-model-target; external Ollama model store copy will be skipped "
            "(repo-local models/ollama folders still sync)."
        )
    result = sync_repo(
        source.path,
        args.sync,
        include_data=bool(args.include_data),
        include_models=bool(args.include_models),
        model_source_dir=(model_source_arg or None),
        model_target_dir=(model_target_arg or None),
        log_fn=lambda s: print(s, end=""),
    )
    mode = "rsync" if result.used_rsync else "python-copy"
    print(
        f"[DONE] mode={mode} copied={result.copied} skipped={result.skipped} "
        f"errors={result.errors} elapsed={result.elapsed_sec:.1f}s"
    )
    return 0


def _default_source() -> Path:
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller EXE.  Honour CITL_REPO env if set; otherwise
        # walk up 3 levels from EXE: dist/AppName/App.exe -> CITL/
        env_repo = os.environ.get("CITL_REPO", "").strip()
        if env_repo and Path(env_repo).is_dir():
            return Path(env_repo)
        return Path(sys.executable).parent.parent.parent
    return Path(__file__).resolve().parent.parent


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CITL App Sync Utility")
    ap.add_argument("--version", action="store_true", help="Print CITL App Sync version and exit")
    ap.add_argument(
        "--source",
        default="auto",
        help="Source repo path or 'auto' (desktop local repo first, else most recently updated local repo)",
    )
    ap.add_argument("--detect-json", action="store_true", help="Print detected targets as JSON and exit")
    ap.add_argument("--sync", default="", help="Sync source repo to this target path (headless)")
    ap.add_argument(
        "--sync-best-usb",
        action="store_true",
        help="Auto-detect the best USB target and push PC app files to it (headless)",
    )
    ap.add_argument(
        "--target-path",
        default="",
        help="Explicit target repo path for --sync-best-usb (bypasses auto target selection)",
    )
    ap.add_argument(
        "--duplicate-usb",
        action="store_true",
        help="Duplicate one USB CITL repo copy to another USB target (headless)",
    )
    ap.add_argument("--duplicate-from", default="", help="Source USB repo path for --duplicate-usb")
    ap.add_argument("--duplicate-to", default="", help="Destination USB repo path for --duplicate-usb")
    ap.add_argument("--include-data", action="store_true", help="Include data/ and index folders in sync")
    ap.add_argument("--include-models", action="store_true", help="Include models/ and ollama/ in sync")
    ap.add_argument("--ollama-model-source", default="", help="Optional external Ollama model source directory")
    ap.add_argument("--ollama-model-target", default="", help="Optional external Ollama model target directory")
    ap.add_argument(
        "--no-app-key-sync",
        action="store_true",
        help="With --sync-best-usb, skip per-app key-file sync pass",
    )
    ap.add_argument(
        "--full-repo-sync",
        action="store_true",
        help="With --sync-best-usb, also perform full repo copy (slower)",
    )
    ap.add_argument(
        "--push-target-to-phone",
        action="store_true",
        help="After sync/duplicate, zip selected target and push it to phone Downloads via ADB",
    )
    ap.add_argument(
        "--phone-serial",
        default="auto",
        help="ADB phone serial to use with --push-target-to-phone (default: auto)",
    )
    args = ap.parse_args(argv)

    if args.version:
        print(f"{APP_SYNC_NAME} {APP_SYNC_VERSION}")
        return 0

    source = detect_source_repo(args.source, default_source=_default_source())

    if args.detect_json:
        return _print_detect_json(source)
    if args.duplicate_usb:
        return _run_duplicate_usb(args, source)
    if args.sync_best_usb:
        return _run_sync_best_usb(args, source)
    if args.sync:
        return _run_headless_sync(args, source)

    launch_sync_gui(source.path, source.reason, source.freshness_ts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



