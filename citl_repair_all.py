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
import hashlib
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
from typing import Callable, Dict, List, Optional, Tuple

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

PATCH_LAUNCHERS = [
    REPO_ROOT / "DIAGNOSE_FACTBOOK.cmd",
    REPO_ROOT / "diagnose_factbook.sh",
    REPO_ROOT / "LAUNCH_FACTBOOK.cmd",
    REPO_ROOT / "launch_factbook.sh",
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
    ("Academic Advisor",        "academic_advisor_gui.py"),
    ("Academic Advisor",        "citl_academic_advisor.py"),
    ("Academic Advisor",        "academic_advisor"),
]


def _classify_citl_apps(path: Path) -> List[str]:
    """Return matched CITL app names present under this repo/path."""
    names: List[str] = []
    for app_name, marker in APP_MARKERS:
        try:
            if (path / marker).exists() and app_name not in names:
                names.append(app_name)
        except OSError:
            pass
    return names


def _guess_citl_apps_from_text(repo_path: str, repo_nickname: str = "") -> List[str]:
    """Fallback app classification when marker files are not available."""
    name_text = f"{repo_nickname} {Path(str(repo_path)).name}".lower()
    text = f"{name_text} {repo_path}".lower()
    out: List[str] = []
    if "factbook" in text:
        out.append("Factbook Assistant")
    if "flex" in text or "troubleshooter" in text:
        out.append("FLEX Troubleshooter")
    if "app_sync" in text or "app sync" in text:
        out.append("App Sync")
    if "academic" in text and "advisor" in text:
        out.append("Academic Advisor")
    if "citl" in name_text and not out:
        out.append("CITL App")
    return out


def _repo_apps(repo_root: Path, repo_nickname: str = "") -> List[str]:
    names = _classify_citl_apps(repo_root)
    if names:
        return names
    return _guess_citl_apps_from_text(_safe_resolve_str(repo_root), repo_nickname)


def _is_citl_repo_record(repo_path: str, repo_nickname: str = "") -> bool:
    try:
        if _is_citl_repo(Path(repo_path)):
            return True
    except Exception:
        pass
    return len(_guess_citl_apps_from_text(repo_path, repo_nickname)) > 0


def _is_citl_repo(path: Path) -> bool:
    """True if repo matches CITL markers or strong CITL naming hints."""
    if len(_classify_citl_apps(path)) > 0:
        return True
    return len(_guess_citl_apps_from_text(_safe_resolve_str(path), path.name)) > 0

# ══════════════════════════════════════════════════════════════════════════════
# FINDER
# ══════════════════════════════════════════════════════════════════════════════

def _home_drive() -> str:
    """Return the drive letter (Windows) or '/' (Linux) of THIS script."""
    if platform.system() == "Windows":
        return str(HERE.resolve()).split(":")[0].upper() + ":"
    return "/"


# Registry lives ON THE USB so it travels with the drive and accumulates
# knowledge from every machine this USB has been plugged into.
_REGISTRY_PATH = REPO_ROOT / "citl_device_registry.json"
_REGISTRY_LOCK = threading.RLock()
_MAX_MACHINE_EVENTS = 300
_MAX_REPO_APPLY_EVENTS = 50


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_resolve_str(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _machine_id() -> str:
    raw = "|".join([
        socket.gethostname(),
        os.environ.get("COMPUTERNAME", ""),
        os.environ.get("USERNAME") or os.environ.get("USER") or "",
        platform.system(),
        platform.release(),
        platform.machine(),
    ])
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:12]


def _machine_identity() -> dict:
    return {
        "machine_id": _machine_id(),
        "os": platform.system(),
        "platform": platform.platform(),
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
    }


def _preferred_machine_nickname(host: str) -> str:
    if host == socket.gethostname():
        for env_key in ("CITL_MACHINE_NICKNAME", "CITL_HOST_NICKNAME", "CITL_NICKNAME"):
            val = (os.environ.get(env_key) or "").strip()
            if val:
                return val
    return host.split(".")[0]


def _append_capped(seq: list, item: dict, limit: int) -> None:
    seq.append(item)
    if len(seq) > limit:
        del seq[:-limit]


def _load_registry() -> dict:
    """Load the full multi-device registry from the USB."""
    with _REGISTRY_LOCK:
        try:
            if _REGISTRY_PATH.exists():
                return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_registry(registry: dict) -> None:
    """Write the multi-device registry back to the USB."""
    with _REGISTRY_LOCK:
        try:
            _REGISTRY_PATH.write_text(
                json.dumps(registry, indent=2, default=str),
                encoding="utf-8")
        except Exception:
            pass


def _ensure_machine_entry(reg: dict, host: str) -> dict:
    entry = reg.setdefault(host, {})
    entry.setdefault("nickname", _preferred_machine_nickname(host))
    entry.setdefault("citl_paths", [])
    entry.setdefault("git_repos", [])
    entry.setdefault("pinned_repos", [])
    entry.setdefault("patch_apply", {})
    entry.setdefault("repo_builds", {})
    entry.setdefault("events", [])
    entry.setdefault("first_seen", _now_iso())
    entry.setdefault("last_seen", "")
    entry.setdefault("last_connected", "")
    entry.setdefault("last_scan", "")
    entry.setdefault("last_apply", "")
    entry.setdefault("updated", "")

    if host == socket.gethostname():
        ident = _machine_identity()
        entry["nickname"] = _preferred_machine_nickname(host)
        entry["machine_id"] = ident.get("machine_id", "")
        entry["os"] = ident.get("os", "")
        entry["platform"] = ident.get("platform", "")
        entry["user"] = ident.get("user", "")
    else:
        entry.setdefault("machine_id", "")
        entry.setdefault("os", "")
        entry.setdefault("platform", "")
        entry.setdefault("user", "")
    return entry


def _touch_machine(event: str, note: str = "") -> None:
    with _REGISTRY_LOCK:
        reg = _load_registry()
        host = socket.gethostname()
        entry = _ensure_machine_entry(reg, host)
        now = _now_iso()
        entry["last_seen"] = now
        entry["last_connected"] = now
        entry["updated"] = now
        rec = {"ts": now, "event": event}
        if note:
            rec["note"] = note
        _append_capped(entry.setdefault("events", []), rec, _MAX_MACHINE_EVENTS)
        _save_registry(reg)


def _git_head_info(repo_root: Path) -> dict:
    info = {
        "branch": "",
        "hash": "",
        "time": "",
        "subject": "",
        "author": "",
    }
    try:
        rb = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        if rb.returncode == 0:
            info["branch"] = rb.stdout.strip()
    except Exception:
        pass
    try:
        rl = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%H|%ai|%an|%s"],
            capture_output=True, text=True, timeout=6,
            encoding="utf-8", errors="replace",
        )
        if rl.returncode == 0 and rl.stdout.strip():
            h, ai, an, subj = (rl.stdout.strip().split("|", 3) + ["", "", "", ""])[:4]
            info["hash"] = h.strip()
            info["time"] = ai.strip()
            info["author"] = an.strip()
            info["subject"] = subj.strip()
    except Exception:
        pass
    return info


def _update_repo_build(entry: dict, repo_root: Path, source: str = "") -> None:
    repo_key = _safe_resolve_str(repo_root)
    now = _now_iso()
    builds = entry.setdefault("repo_builds", {})
    b = builds.setdefault(repo_key, {})
    b["path"] = repo_key
    b["repo_nickname"] = repo_root.name
    b["last_seen"] = now
    if source:
        b["source"] = source
    head = _git_head_info(repo_root)
    if head.get("branch"):
        b["branch"] = head["branch"]
    if head.get("hash"):
        b["last_head"] = head["hash"]
        b["last_head_time"] = head.get("time", "")
        b["last_head_subject"] = head.get("subject", "")
        b["last_head_author"] = head.get("author", "")


def _record_repo_scan(repos: List[Path], source: str = "scan") -> None:
    with _REGISTRY_LOCK:
        reg = _load_registry()
        host = socket.gethostname()
        entry = _ensure_machine_entry(reg, host)
        now = _now_iso()
        known = {_safe_resolve_str(Path(p)) for p in entry.get("git_repos", [])}
        known.update({_safe_resolve_str(Path(p)) for p in entry.get("pinned_repos", [])})
        for repo in repos:
            repo_key = _safe_resolve_str(repo)
            known.add(repo_key)
            _update_repo_build(entry, repo, source=source)
        entry["git_repos"] = sorted(known)
        entry["last_seen"] = now
        entry["last_connected"] = now
        entry["last_scan"] = now
        entry["updated"] = now
        _append_capped(entry.setdefault("events", []), {
            "ts": now,
            "event": "repo_scan",
            "source": source,
            "repo_count": len(repos),
        }, _MAX_MACHINE_EVENTS)
        _save_registry(reg)


def _pin_repo_path(repo_root: Path, note: str = "manual_select") -> None:
    """Persist a manually selected repo so future offline scans include it."""
    with _REGISTRY_LOCK:
        reg = _load_registry()
        host = socket.gethostname()
        entry = _ensure_machine_entry(reg, host)
        now = _now_iso()
        repo_key = _safe_resolve_str(repo_root)
        pins = {_safe_resolve_str(Path(p)) for p in entry.get("pinned_repos", [])}
        pins.add(repo_key)
        entry["pinned_repos"] = sorted(pins)
        repos = {_safe_resolve_str(Path(p)) for p in entry.get("git_repos", [])}
        repos.add(repo_key)
        entry["git_repos"] = sorted(repos)
        _update_repo_build(entry, repo_root, source="manual_pin")
        entry["last_seen"] = now
        entry["last_connected"] = now
        entry["updated"] = now
        _append_capped(entry.setdefault("events", []), {
            "ts": now,
            "event": "repo_pin",
            "repo": repo_key,
            "note": note,
        }, _MAX_MACHINE_EVENTS)
        _save_registry(reg)


def _load_device_memory() -> List[Path]:
    """Return all known CITL paths from ALL devices in the registry
    that are accessible on THIS machine right now."""
    reg = _load_registry()
    seen: set = set()
    out: List[Path] = []
    for _host, entry in reg.items():
        for ps in entry.get("citl_paths", []):
            p = Path(ps)
            try:
                if p.exists() and str(p.resolve()) not in seen:
                    seen.add(str(p.resolve()))
                    out.append(p)
            except OSError:
                pass
    return out


def _save_device_memory(paths: List[Path]) -> None:
    """Record found paths under THIS machine's hostname in the USB registry."""
    with _REGISTRY_LOCK:
        reg = _load_registry()
        host = socket.gethostname()
        entry = _ensure_machine_entry(reg, host)
        existing_strs = {e for e in entry.get("citl_paths", [])}
        new_strs = {_safe_resolve_str(p) for p in paths}
        combined = sorted(existing_strs | new_strs)
        now = _now_iso()
        entry["citl_paths"] = combined
        entry["last_seen"] = now
        entry["last_connected"] = now
        entry["updated"] = now
        _append_capped(entry.setdefault("events", []), {
            "ts": now,
            "event": "path_scan",
            "path_count": len(paths),
        }, _MAX_MACHINE_EVENTS)
        _save_registry(reg)


def _save_git_repos(repos: List[Path]) -> None:
    """Record known git repo paths under THIS machine's hostname."""
    _record_repo_scan(repos, source="find_git_repos")


def _patch_bundle_sources() -> List[Path]:
    """All files that make up the USB patch bundle."""
    out: List[Path] = []
    seen: set = set()
    for src in [Path(__file__).resolve(), *PATCH_SCRIPTS, *PATCH_LAUNCHERS]:
        try:
            key = str(src.resolve())
        except OSError:
            key = str(src)
        if key in seen:
            continue
        seen.add(key)
        out.append(src)
    return out


def _current_patch_signature() -> str:
    """Stable signature for the current USB patch payload."""
    h = hashlib.sha256()
    for src in sorted(_patch_bundle_sources(), key=lambda p: p.name.lower()):
        try:
            if not src.exists():
                continue
            st = src.stat()
            h.update(src.name.encode("utf-8", errors="replace"))
            h.update(str(st.st_size).encode("ascii", errors="ignore"))
            h.update(str(int(st.st_mtime)).encode("ascii", errors="ignore"))
        except OSError:
            continue
    return h.hexdigest()[:12]


def _record_patch_apply(repo_root: Path, copied_count: int) -> None:
    """Persist that THIS host has applied the current patch signature to repo_root."""
    with _REGISTRY_LOCK:
        reg = _load_registry()
        host = socket.gethostname()
        entry = _ensure_machine_entry(reg, host)
        apply_map = entry.setdefault("patch_apply", {})
        now = _now_iso()
        sig = _current_patch_signature()
        repo_key = _safe_resolve_str(repo_root)

        apply_map[repo_key] = {
            "signature": sig,
            "applied_at": now,
            "files_copied": int(copied_count),
            "repo_nickname": repo_root.name,
            "machine": host,
            "machine_id": entry.get("machine_id", ""),
            "status": "applied",
        }
        if repo_key not in entry["git_repos"]:
            entry["git_repos"].append(repo_key)
        _update_repo_build(entry, repo_root, source="apply")
        builds = entry.setdefault("repo_builds", {})
        b = builds.setdefault(repo_key, {})
        b["last_apply_signature"] = sig
        b["last_apply_at"] = now
        b["last_apply_files"] = int(copied_count)
        b["last_apply_status"] = "applied"
        _append_capped(
            b.setdefault("apply_history", []),
            {"ts": now, "signature": sig, "files_copied": int(copied_count), "status": "applied"},
            _MAX_REPO_APPLY_EVENTS,
        )

        entry["last_seen"] = now
        entry["last_connected"] = now
        entry["last_apply"] = now
        entry["updated"] = now
        _append_capped(entry.setdefault("events", []), {
            "ts": now,
            "event": "apply",
            "repo": repo_key,
            "signature": sig,
            "files_copied": int(copied_count),
        }, _MAX_MACHINE_EVENTS)
        _save_registry(reg)


def _patch_apply_rows(signature: str) -> List[dict]:
    """Flatten registry into rows for current patch signature coverage."""
    reg = _load_registry()
    rows: List[dict] = []
    for host, entry in reg.items():
        machine_id = str(entry.get("machine_id") or "")
        last_connected = str(entry.get("last_connected") or "")
        last_seen = str(entry.get("last_seen") or "")
        last_scan = str(entry.get("last_scan") or "")
        last_apply = str(entry.get("last_apply") or "")
        host_nickname = str(entry.get("nickname") or host.split(".")[0])
        apply_map = entry.get("patch_apply", {}) or {}
        builds = entry.get("repo_builds", {}) or {}
        repos = set(entry.get("git_repos", []) or [])
        repos.update(entry.get("pinned_repos", []) or [])
        repos.update(apply_map.keys())
        repos.update(builds.keys())
        for repo_s in sorted(repos):
            applied = False
            applied_at = ""
            files_copied = 0
            repo_nickname = Path(repo_s).name
            rec = apply_map.get(repo_s, {})
            b = builds.get(repo_s, {})
            if isinstance(b, dict):
                repo_nickname = str(b.get("repo_nickname") or repo_nickname)
            if isinstance(rec, dict):
                repo_nickname = str(rec.get("repo_nickname") or repo_nickname)
            if not _is_citl_repo_record(repo_s, repo_nickname):
                continue
            last_sig = ""
            if isinstance(rec, dict):
                last_sig = str(rec.get("signature") or "")
                applied_at = str(rec.get("applied_at") or applied_at)
                files_copied = int(rec.get("files_copied") or files_copied)
            if isinstance(b, dict):
                last_sig = str(last_sig or b.get("last_apply_signature") or "")
                applied_at = str(applied_at or b.get("last_apply_at") or "")
                files_copied = int(files_copied or b.get("last_apply_files") or 0)
            applied = bool(last_sig) and (last_sig == signature)
            rows.append({
                "host": host,
                "host_nickname": host_nickname,
                "machine_id": machine_id,
                "last_connected": last_connected,
                "last_seen": last_seen,
                "last_scan": last_scan,
                "last_apply": last_apply,
                "repo": repo_s,
                "repo_nickname": repo_nickname,
                "apps": _repo_apps(Path(repo_s), repo_nickname),
                "applied": applied,
                "applied_at": applied_at,
                "files_copied": files_copied,
                "last_signature": last_sig,
                "branch": str((b or {}).get("branch") if isinstance(b, dict) else ""),
                "head": str((b or {}).get("last_head") if isinstance(b, dict) else ""),
                "head_time": str((b or {}).get("last_head_time") if isinstance(b, dict) else ""),
            })
    return rows


def _machine_summary_rows(signature: str) -> List[dict]:
    reg = _load_registry()
    out: List[dict] = []
    for host, entry in reg.items():
        host_nickname = str(entry.get("nickname") or host.split(".")[0])
        machine_id = str(entry.get("machine_id") or "")
        apply_map = entry.get("patch_apply", {}) or {}
        builds = entry.get("repo_builds", {}) or {}
        repos = set(entry.get("git_repos", []) or [])
        repos.update(entry.get("pinned_repos", []) or [])
        repos.update(apply_map.keys())
        repos.update(builds.keys())
        citl_repos = []
        for repo_s in sorted(repos):
            repo_nickname = Path(repo_s).name
            b = builds.get(repo_s, {})
            if isinstance(b, dict):
                repo_nickname = str(b.get("repo_nickname") or repo_nickname)
            rec = apply_map.get(repo_s, {})
            if isinstance(rec, dict):
                repo_nickname = str(rec.get("repo_nickname") or repo_nickname)
            if _is_citl_repo_record(repo_s, repo_nickname):
                citl_repos.append(repo_s)
        repo_total = len(citl_repos)
        applied_count = 0
        for repo_s in citl_repos:
            rec = apply_map.get(repo_s, {})
            b = builds.get(repo_s, {})
            last_sig = ""
            if isinstance(rec, dict):
                last_sig = str(rec.get("signature") or "")
            if not last_sig and isinstance(b, dict):
                last_sig = str(b.get("last_apply_signature") or "")
            if last_sig and last_sig == signature:
                applied_count += 1
        out.append({
            "host": host,
            "host_nickname": host_nickname,
            "machine_id": machine_id,
            "repo_total": repo_total,
            "applied_count": applied_count,
            "pending_count": max(0, repo_total - applied_count),
            "last_connected": str(entry.get("last_connected") or ""),
            "last_seen": str(entry.get("last_seen") or ""),
            "last_scan": str(entry.get("last_scan") or ""),
            "last_apply": str(entry.get("last_apply") or ""),
            "os": str(entry.get("os") or ""),
            "platform": str(entry.get("platform") or ""),
            "user": str(entry.get("user") or ""),
            "updated": str(entry.get("updated") or ""),
        })
    return out


def _machine_recent_events(limit_per_host: int = 8) -> List[dict]:
    reg = _load_registry()
    out: List[dict] = []
    for host, entry in reg.items():
        host_nickname = str(entry.get("nickname") or host.split(".")[0])
        machine_id = str(entry.get("machine_id") or "")
        events = entry.get("events", [])
        if not isinstance(events, list):
            continue
        for ev in events[-max(1, limit_per_host):]:
            if not isinstance(ev, dict):
                continue
            repo_s = str(ev.get("repo") or "")
            if repo_s and not _is_citl_repo_record(repo_s):
                continue
            out.append({
                "host": host,
                "host_nickname": host_nickname,
                "machine_id": machine_id,
                "ts": str(ev.get("ts") or ""),
                "event": str(ev.get("event") or ""),
                "note": str(ev.get("note") or ""),
                "source": str(ev.get("source") or ""),
                "repo": repo_s,
                "signature": str(ev.get("signature") or ""),
                "repo_count": str(ev.get("repo_count") or ""),
                "path_count": str(ev.get("path_count") or ""),
                "files_copied": str(ev.get("files_copied") or ""),
            })
    out.sort(key=lambda r: (
        str(r.get("host_nickname", "")),
        str(r.get("ts", "")),
    ))
    return out


def _find_git_repos_on_machine() -> List[Path]:
    """Scan every drive for CITL git repos. Returns paths sorted newest-first."""
    import string
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    candidates: List[Path] = []

    # Previously known from registry
    reg = _load_registry()
    for _host, entry in reg.items():
        for ps in [*(entry.get("git_repos", []) or []),
                   *(entry.get("pinned_repos", []) or [])]:
            p = Path(ps)
            try:
                if p.is_dir():
                    candidates.insert(0, p)
            except OSError:
                pass

    # Known high-probability paths on every drive
    if platform.system() == "Windows":
        drives = []
        for l in string.ascii_uppercase:
            p = Path(f"{l}:/")
            try:
                if p.exists():
                    drives.append(p)
            except OSError:
                pass
    else:
        drives = [Path("/"), Path.home()]

    for drive in drives:
        for rel in [
            f"Users/{user}/CITL",
            f"Users/{user}/Documents/CITL",
            f"Users/{user}/Desktop/CITL",
            "00 HENOSIS CODING PROJECTS/CITL PROJECTS/2026 ACADEMIC ADVISOR",
            "00 HENOSIS CODING PROJECTS/- - CURRENT CONDITIONS PROMPT",
            "CITL", "citl",
        ]:
            p = drive / rel
            try:
                if p.is_dir():
                    candidates.append(p)
            except OSError:
                pass

    # Also walk one level under common project directories
    project_roots = []
    for drive in drives:
        for folder in ["Users", "00 HENOSIS CODING PROJECTS",
                       "Projects", "projects", "dev", "Dev"]:
            pr = drive / folder
            try:
                if pr.is_dir():
                    project_roots.append(pr)
            except OSError:
                pass
    for pr in project_roots:
        try:
            for child in pr.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    candidates.append(child)
        except OSError:
            pass

    # Filter to actual git repos, deduplicate, sort by newest commit
    seen: set = set()
    git_repos: List[Path] = []
    for p in candidates:
        try:
            k = str(p.resolve())
        except OSError:
            continue
        if k in seen:
            continue
        try:
            r = subprocess.run(
                ["git", "-C", str(p), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=4)
            if r.returncode == 0:
                real = Path(r.stdout.strip())
                rk = str(real.resolve())
                if rk not in seen:
                    if not _is_citl_repo(real):
                        continue
                    seen.add(rk)
                    seen.add(k)
                    git_repos.append(real)
        except Exception:
            pass

    _save_git_repos(git_repos)
    return git_repos


def _all_drives() -> List[Path]:
    """Return all mounted/available root paths."""
    drives: List[Path] = []
    if platform.system() == "Windows":
        import string
        for letter in string.ascii_uppercase:
            p = Path(f"{letter}:/")
            try:
                if p.exists():
                    drives.append(p)
            except OSError:
                pass
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


def _get_volume_label(drive_root: Path) -> str:
    """Get volume label for a drive (Windows); falls back to drive letter."""
    if platform.system() != "Windows":
        return str(drive_root)
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        ctypes.windll.kernel32.GetVolumeInformationW(
            str(drive_root).rstrip("/\\") + "\\", buf, 261,
            None, None, None, None, 0)
        label = buf.value.strip()
        return label if label else str(drive_root).rstrip("\\/")
    except Exception:
        return str(drive_root).rstrip("\\/")


def _patch_color(idx: int) -> str:
    """Return one of 300+ visually distinct hex colors by batch index."""
    import colorsys
    n = 300
    h = (idx % n) / n
    s = 0.78 if (idx // n) % 2 == 0 else 0.55
    v = 0.92 if (idx // n) % 2 == 0 else 0.78
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"


def _git_commits(repo_path: Path, max_count: int = 300) -> List[dict]:
    """Return git log for repo_path as list of dicts, newest first."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "log",
             f"--max-count={max_count}",
             "--format=%H|%ai|%an|%s",
             "--no-merges"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        commits = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                h, ai, an, subj = parts
                try:
                    dt = datetime.fromisoformat(ai.strip()[:19])
                except Exception:
                    dt = datetime.now()
                commits.append({"hash": h[:8], "dt": dt,
                                "author": an.strip(), "subject": subj.strip()})
        return commits
    except Exception:
        return []


def _group_by_48h(commits: List[dict]) -> List[List[dict]]:
    """Group commits into batches where consecutive batches are >48 hours apart."""
    if not commits:
        return []
    groups: List[List[dict]] = [[commits[0]]]
    for c in commits[1:]:
        gap = (groups[-1][-1]["dt"] - c["dt"]).total_seconds()
        if gap <= 48 * 3600:
            groups[-1].append(c)
        else:
            groups.append([c])
    return groups


def _quick_candidates() -> List[Path]:
    """High-probability locations checked in <1s.
    Searches THIS drive + C:\\Users\\<user>\\CITL + device memory.
    Deep search (all drives) is only triggered explicitly."""
    cands: List[Path] = []
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"

    # 1. Previously-seen paths from device memory (fastest)
    for p in _load_device_memory():
        if p.is_dir():
            cands.append(p)

    # 2. This script's own tree (USB root and ancestors)
    for anc in [HERE, REPO_ROOT, REPO_ROOT.parent, REPO_ROOT.parent.parent]:
        if anc.is_dir():
            cands.append(anc)

    # 3. Check EVERY available drive for C:\Users\<user>\CITL equivalent
    #    This ensures we find local CITL repos even when running from USB.
    if platform.system() == "Windows":
        import string
        for letter in string.ascii_uppercase:
            drive_root = Path(f"{letter}:/")
            try:
                if not drive_root.exists():
                    continue
            except OSError:
                continue
            for rel in [
                f"Users/{user}/CITL",
                "Users/Public/CITL",
                "CITL",
                "citl",
            ]:
                p = drive_root / rel
                try:
                    if p.is_dir():
                        cands.append(p)
                except OSError:
                    pass
    else:
        home_root = Path("/")
        for rel in [f"home/{user}/CITL", "opt/citl", "srv/citl"]:
            p = home_root / rel
            if p.is_dir():
                cands.append(p)

    # 4. CWD and its parent
    cwd = Path.cwd()
    for anc in [cwd, cwd.parent]:
        if anc.is_dir():
            cands.append(anc)

    # Deduplicate preserving order
    seen: set = set()
    out: List[Path] = []
    for c in cands:
        try:
            k = str(c.resolve())
        except OSError:
            continue
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def _is_factbook_root(path: Path) -> bool:
    """True if this directory contains a known CITL marker file.
    Matches the factbook-assistant/ subfolder, the repo root, or the
    citl_flex_troubleshooter/ subfolder — nothing else."""
    for _, marker in APP_MARKERS:
        try:
            if (path / marker).exists():
                return True
        except OSError:
            pass
    return False


def _dir_mtime(path: Path) -> float:
    """Most-recent mtime across key files in a candidate dir."""
    best = 0.0
    for _, marker in APP_MARKERS:
        f = path / marker
        try:
            if f.exists():
                best = max(best, f.stat().st_mtime)
        except OSError:
            pass
    return best


def quick_search(log: Callable[[str], None] = print) -> List[Path]:
    """Fast search: same-drive hot-spots + device memory. Returns results
    sorted by most-recently-modified first. Saves found paths to device memory
    so future runs start faster."""
    log("Quick search — checking this drive and previously-seen locations...")
    found: List[Path] = []
    seen: set = set()

    for cand in _quick_candidates():
        # Cand itself
        if _is_factbook_root(cand):
            try:
                k = str(cand.resolve())
            except OSError:
                continue
            if k not in seen:
                seen.add(k)
                found.append(cand)
                log(f"  Found: {cand}")
        # Immediate children only (no deep walk here)
        try:
            for child in cand.iterdir():
                if not child.is_dir():
                    continue
                if child.name in ("__pycache__", ".git", ".venv", "node_modules",
                                  "System Volume Information", "$Recycle.Bin"):
                    continue
                if _is_factbook_root(child):
                    try:
                        k = str(child.resolve())
                    except OSError:
                        continue
                    if k not in seen:
                        seen.add(k)
                        found.append(child)
                        log(f"  Found: {child}")
        except (PermissionError, OSError):
            pass

    ranked = sorted(found, key=lambda p: _dir_mtime(p), reverse=True)
    if ranked:
        _save_device_memory(ranked)          # remember for next run
    log(f"Quick search complete: {len(ranked)} instance(s) found.")
    return ranked


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

CAPTURE_BOOTSTRAP_REQUESTS_REL = Path("bootstrap") / "workstation_capture_requests.jsonl"
CAPTURE_ALWAYS_SKIP_PARTS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".cache",
    "node_modules", "dist", "build",
}
CAPTURE_ALWAYS_SKIP_SUFFIXES = (".pyc", ".pyo", ".tmp", ".log", ".bak")
CAPTURE_HEAVY_CATEGORY_PARTS = {
    "venv": {".venv", "venv"},
    "ollama": {"ollama", "blobs"},
    "models": {"models"},
}
CAPTURE_LARGE_FILE_WARN_BYTES = 512 * 1024 * 1024       # 512 MiB
CAPTURE_HUGE_FILE_CONFIRM_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
CAPTURE_HUGE_CATEGORY_CONFIRM_BYTES = 8 * 1024 * 1024 * 1024  # 8 GiB


def _fmt_bytes(n: int) -> str:
    x = float(max(0, int(n)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024.0 or unit == "TB":
            return f"{x:.1f} {unit}" if unit != "B" else f"{int(x)} B"
        x /= 1024.0
    return f"{int(n)} B"


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists() or not path.is_dir():
        return 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in CAPTURE_ALWAYS_SKIP_PARTS]
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


def _capture_heavy_category(rel_path: Path) -> Optional[str]:
    parts = {p.lower() for p in rel_path.parts}
    for cat, names in CAPTURE_HEAVY_CATEGORY_PARTS.items():
        if parts.intersection(names):
            return cat
    return None


def _capture_skip_reason(rel_path: Path) -> str:
    low_parts = [p.lower() for p in rel_path.parts]
    for p in low_parts:
        if p in CAPTURE_ALWAYS_SKIP_PARTS:
            return f"skip-part:{p}"
    low_name = rel_path.name.lower()
    for suf in CAPTURE_ALWAYS_SKIP_SUFFIXES:
        if low_name.endswith(suf):
            return f"skip-suffix:{suf}"
    return ""


def _git_status_changed_paths(repo_root: Path) -> List[Tuple[str, Path]]:
    """
    Return [(status, rel_path)] from `git status --porcelain -z`.
    Includes tracked modifications and untracked files.
    """
    out: List[Tuple[str, Path]] = []
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "-z", "--untracked-files=all"],
            capture_output=True, timeout=20,
        )
        if r.returncode != 0:
            return out
        items = [x for x in r.stdout.split(b"\x00") if x]
        i = 0
        while i < len(items):
            chunk = items[i]
            if len(chunk) < 4:
                i += 1
                continue
            status = chunk[:2].decode("utf-8", errors="replace")
            path_b = chunk[3:]
            path_s = path_b.decode("utf-8", errors="replace")
            rel = Path(path_s)
            # For rename/copy entries, porcelain -z emits an extra path token.
            if status and status[0] in ("R", "C") and (i + 1) < len(items):
                new_s = items[i + 1].decode("utf-8", errors="replace")
                rel = Path(new_s)
                i += 1
            out.append((status, rel))
            i += 1
    except Exception:
        return out
    return out


def _append_bootstrap_capture_request(repo_root: Path,
                                      kind: str,
                                      size_bytes: int,
                                      note: str = "") -> None:
    req_path = REPO_ROOT / CAPTURE_BOOTSTRAP_REQUESTS_REL
    req_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _now_iso(),
        "host": socket.gethostname(),
        "machine_id": _machine_id(),
        "repo": _safe_resolve_str(repo_root),
        "repo_name": repo_root.name,
        "kind": kind,
        "size_bytes": int(size_bytes),
        "size_human": _fmt_bytes(size_bytes),
        "action": "bootstrap_recommended",
        "note": note,
    }
    with req_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_capture_plan(repo_root: Path,
                        include_heavy: set,
                        include_large: bool,
                        include_huge: bool) -> dict:
    if not _is_citl_repo(repo_root):
        return {
            "repo": repo_root,
            "apps": [],
            "changed": [],
            "entries": [],
            "copy_count": 0,
            "copy_bytes": 0,
            "skipped_counts": {"non_citl_repo": 1},
            "skipped_bytes": {},
        }
    changed = _git_status_changed_paths(repo_root)
    entries: List[Tuple[Path, Path, int, str]] = []
    skipped_counts = {
        "deleted": 0,
        "always_skip": 0,
        "heavy": 0,
        "large": 0,
        "huge": 0,
        "up_to_date": 0,
    }
    skipped_bytes = {"heavy": 0, "large": 0, "huge": 0}

    for status, rel in changed:
        # Deletions are logged but not auto-deleted on USB.
        if "D" in status:
            skipped_counts["deleted"] += 1
            continue
        src = repo_root / rel
        if not src.exists() or not src.is_file():
            continue
        reason = _capture_skip_reason(rel)
        if reason:
            skipped_counts["always_skip"] += 1
            continue
        cat = _capture_heavy_category(rel)
        try:
            size = src.stat().st_size
        except OSError:
            continue
        if cat and cat not in include_heavy:
            skipped_counts["heavy"] += 1
            skipped_bytes["heavy"] += size
            continue
        if size >= CAPTURE_HUGE_FILE_CONFIRM_BYTES and not include_huge:
            skipped_counts["huge"] += 1
            skipped_bytes["huge"] += size
            continue
        if size >= CAPTURE_LARGE_FILE_WARN_BYTES and not include_large:
            skipped_counts["large"] += 1
            skipped_bytes["large"] += size
            continue

        dst = REPO_ROOT / rel
        try:
            if dst.exists() and _file_sha256(src) == _file_sha256(dst):
                skipped_counts["up_to_date"] += 1
                continue
        except Exception:
            pass
        entries.append((src, dst, size, status))

    return {
        "repo": repo_root,
        "apps": _repo_apps(repo_root, repo_root.name),
        "changed": changed,
        "entries": entries,
        "copy_count": len(entries),
        "copy_bytes": sum(e[2] for e in entries),
        "skipped_counts": skipped_counts,
        "skipped_bytes": skipped_bytes,
    }

def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _repo_patch_layout(repo_root: Path) -> List[Tuple[Path, Path]]:
    """
    Return (source, destination) pairs for this repo patch payload.
    Destination rule:
      - core scripts + this orchestrator -> repo/factbook-assistant when present
      - launchers -> repo root
    """
    this_file = Path(__file__).resolve()
    fa_dir = repo_root / "factbook-assistant"
    dest = fa_dir if fa_dir.is_dir() else repo_root
    pairs: List[Tuple[Path, Path]] = []
    pairs.append((this_file, dest / this_file.name))
    for src in PATCH_SCRIPTS:
        pairs.append((src, dest / src.name))
    for src in PATCH_LAUNCHERS:
        pairs.append((src, repo_root / src.name))

    # Deduplicate by destination, keep first source.
    out: List[Tuple[Path, Path]] = []
    seen_dst: set = set()
    for src, dst in pairs:
        k = _safe_resolve_str(dst)
        if k in seen_dst:
            continue
        seen_dst.add(k)
        out.append((src, dst))
    return out


def _repo_patch_gap(repo_root: Path) -> dict:
    """
    Offline patch gap report for one repo based on file hashes.
    """
    gap = {
        "repo": _safe_resolve_str(repo_root),
        "missing": [],
        "outdated": [],
        "up_to_date": [],
        "source_missing": [],
    }
    for src, dst in _repo_patch_layout(repo_root):
        if not src.exists():
            gap["source_missing"].append(src.name)
            continue
        if not dst.exists():
            gap["missing"].append(dst.name)
            continue
        try:
            if _file_sha256(src) == _file_sha256(dst):
                gap["up_to_date"].append(dst.name)
            else:
                gap["outdated"].append(dst.name)
        except Exception:
            gap["outdated"].append(dst.name)
    gap["missing_count"] = len(gap["missing"])
    gap["outdated_count"] = len(gap["outdated"])
    gap["up_to_date_count"] = len(gap["up_to_date"])
    gap["source_missing_count"] = len(gap["source_missing"])
    gap["needs_apply"] = (gap["missing_count"] + gap["outdated_count"]) > 0
    return gap


def _copy_if_needed(src: Path, dst: Path, log: Callable[[str], None]) -> bool:
    if not src.exists():
        log(f"  SKIP {src.name} - not found on this USB")
        return False
    try:
        if dst.exists():
            try:
                if _file_sha256(src) == _file_sha256(dst):
                    log(f"  Up-to-date: {dst}")
                    return False
            except Exception:
                pass
        dst.parent.mkdir(parents=True, exist_ok=True)
        existed = dst.exists()
        shutil.copy2(src, dst)
        action = "Patched" if existed else "Added"
        log(f"  {action}: {dst}")
        return True
    except Exception as e:
        log(f"  WARN: could not copy {src.name} -> {dst}: {e}")
        return False

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
    for launcher_src in PATCH_LAUNCHERS:
        if not launcher_src.exists():
            continue
        dst = target_root / launcher_src.name
        try:
            existed = dst.exists()
            if (not dst.exists()) or (dst.stat().st_mtime < launcher_src.stat().st_mtime):
                shutil.copy2(launcher_src, dst)
                action = "Added launcher" if not existed else "Patched launcher"
                log(f"  {action}: {dst.name}")
                patched.append(str(dst))
        except Exception as e:
            log(f"  WARN: {launcher_src.name}: {e}")

    log(f"Patch complete: {len(patched)} file(s) deployed to {dest}")
    return patched


def propagate_usb_bundle_to_repo(repo_root: Path,
                                 log: Callable[[str], None] = print) -> List[str]:
    """
    Sync THIS USB's latest repair files into one local repo.
    Returns list of files copied/updated.
    """
    patched: List[str] = []
    this_file = Path(__file__).resolve()

    try:
        if repo_root.resolve() == REPO_ROOT.resolve():
            log(f"  SKIP source USB repo: {repo_root}")
            return patched
    except OSError:
        pass

    fa_dir = repo_root / "factbook-assistant"
    dest = fa_dir if fa_dir.is_dir() else repo_root

    # Keep this orchestrator synced too.
    try:
        dst = dest / this_file.name
        if (not dst.exists()) or (dst.stat().st_mtime < this_file.stat().st_mtime):
            shutil.copy2(this_file, dst)
            patched.append(str(dst))
            log(f"  Patched: {dst}")
        else:
            log(f"  Up-to-date: {dst}")
    except Exception as e:
        log(f"  WARN: could not copy {this_file.name} -> {dest}: {e}")

    # Use existing patcher for the script + launcher bundle.
    patched.extend(patch_target(repo_root, log))
    try:
        _record_patch_apply(repo_root, len(patched))
    except Exception as e:
        log(f"  WARN: could not record apply state for {repo_root}: {e}")
    return patched


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC RUNNER (imports citl_factbook_diagnostic dynamically)
# ══════════════════════════════════════════════════════════════════════════════

def patch_target(target_root: Path, log: Callable[[str], None] = print) -> List[str]:
    """
    Copy the latest diagnostic / heal scripts from this USB into the target.
    Returns list of files successfully patched.
    """
    fa_dir = target_root / "factbook-assistant"
    dest = fa_dir if fa_dir.is_dir() else target_root
    patched: List[str] = []

    # patch_target applies PATCH_SCRIPTS + PATCH_LAUNCHERS only.
    this_name = Path(__file__).resolve().name
    for src, dst in _repo_patch_layout(target_root):
        if src.name == this_name:
            continue
        if _copy_if_needed(src, dst, log):
            patched.append(str(dst))

    log(f"Patch complete: {len(patched)} file(s) deployed to {dest}")
    return patched


def propagate_usb_bundle_to_repo(repo_root: Path,
                                 log: Callable[[str], None] = print) -> List[str]:
    """
    Sync THIS USB's latest repair files into one local repo.
    Returns list of files copied/updated.
    """
    patched: List[str] = []

    try:
        if repo_root.resolve() == REPO_ROOT.resolve():
            log(f"  SKIP source USB repo: {repo_root}")
            return patched
    except OSError:
        pass

    if not _is_citl_repo(repo_root):
        log(f"  SKIP non-CITL repo: {repo_root}")
        return patched

    gap = _repo_patch_gap(repo_root)
    log(
        f"  Gap: missing={gap['missing_count']} | outdated={gap['outdated_count']} "
        f"| current={gap['up_to_date_count']}"
    )

    # Apply the full payload (orchestrator + scripts + launchers).
    for src, dst in _repo_patch_layout(repo_root):
        if _copy_if_needed(src, dst, log):
            patched.append(str(dst))

    try:
        _record_patch_apply(repo_root, len(patched))
    except Exception as e:
        log(f"  WARN: could not record apply state for {repo_root}: {e}")
    return patched


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
        from tkinter import ttk, messagebox
        from tkinter.scrolledtext import ScrolledText
    except ImportError:
        print("Tkinter not available — run: sudo apt install python3-tk")
        run_cli(start_path=start_path)
        return

    _touch_machine("session_start", "gui")
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

    # Header row: device info
    ph = tk.Frame(patch_tab, bg=_T["hi"], pady=4)
    ph.pack(fill="x")
    _device_label_var = tk.StringVar(value=f"  Device: {socket.gethostname()}")
    tk.Label(ph, textvariable=_device_label_var,
             fg=_T["accent"], bg=_T["hi"],
             font=("Consolas", 9, "bold"), anchor="w", padx=8).pack(side="left")
    _drive_label_var = tk.StringVar(value="")
    tk.Label(ph, textvariable=_drive_label_var,
             fg=_T["warn"], bg=_T["hi"],
             font=("Consolas", 9), anchor="e", padx=8).pack(side="right")

    # Reload button
    ph2 = tk.Frame(patch_tab, bg=_T["bg"], pady=2)
    ph2.pack(fill="x", padx=4)

    matrix_wrap = tk.Frame(patch_tab, bg=_T["bg"])
    matrix_wrap.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    matrix_cols = (
        "status", "host", "machine", "app", "repo", "gap",
        "last_apply", "branch", "head", "path",
    )
    patch_matrix = ttk.Treeview(
        matrix_wrap,
        columns=matrix_cols,
        show="headings",
        selectmode="extended",
        height=14,
    )
    for key, title, width, anchor in [
        ("status", "Status", 94, "center"),
        ("host", "Host", 128, "w"),
        ("machine", "Machine ID", 108, "w"),
        ("app", "CITL App", 160, "w"),
        ("repo", "Repo", 168, "w"),
        ("gap", "Patch Gap", 116, "w"),
        ("last_apply", "Last Apply", 142, "w"),
        ("branch", "Branch", 88, "w"),
        ("head", "Head", 84, "w"),
        ("path", "Path", 360, "w"),
    ]:
        patch_matrix.heading(key, text=title)
        patch_matrix.column(key, width=width, minwidth=60, anchor=anchor, stretch=True)

    pm_v = ttk.Scrollbar(matrix_wrap, orient="vertical", command=patch_matrix.yview)
    pm_h = ttk.Scrollbar(matrix_wrap, orient="horizontal", command=patch_matrix.xview)
    patch_matrix.configure(yscrollcommand=pm_v.set, xscrollcommand=pm_h.set)
    patch_matrix.grid(row=0, column=0, sticky="nsew")
    pm_v.grid(row=0, column=1, sticky="ns")
    pm_h.grid(row=1, column=0, sticky="ew")
    matrix_wrap.grid_columnconfigure(0, weight=1)
    matrix_wrap.grid_rowconfigure(0, weight=1)

    patch_matrix.tag_configure("pending", foreground=_T["err"])
    patch_matrix.tag_configure("applied", foreground=_T["ok"])
    patch_matrix.tag_configure("partial", foreground=_T["warn"])
    patch_matrix.tag_configure("offline", foreground=_T["skip"])

    diag_wrap = tk.LabelFrame(
        patch_tab,
        text="Tertiary Diagnostic Log",
        fg=_T["skip"],
        bg=_T["bg"],
        padx=4,
        pady=4,
    )
    diag_wrap.pack(fill="x", padx=4, pady=(0, 4))

    patch_log = ScrolledText(diag_wrap, state="disabled",
                             bg=_T["txt_bg"], fg=_T["txt_fg"],
                             font=("Consolas", 9), relief="flat", padx=6, height=10)
    patch_log.pack(fill="x", expand=False)
    for _tname, _tcol in [
        ("header",  _T["accent"]),
        ("batch",   _T["warn"]),
        ("hash",    _T["skip"]),
        ("ok",      _T["ok"]),
        ("err",     _T["err"]),
        ("dim",     _T["skip"]),
    ]:
        patch_log.tag_configure(_tname, foreground=_tcol)

    _patch_row_meta: Dict[str, dict] = {}

    def _repo_key(host: str, repo_s: str) -> str:
        return f"{host.lower()}|{repo_s.lower()}"

    def _clear_matrix():
        for iid in patch_matrix.get_children():
            patch_matrix.delete(iid)
        _patch_row_meta.clear()

    def _insert_matrix_row(row: dict) -> None:
        local_actionable = bool(row.get("local_actionable"))
        status = str(row.get("status") or "PENDING")
        tag = (
            "applied" if status.startswith("APPLIED") else
            "pending" if status.startswith("PENDING") else
            "partial" if status.startswith("PARTIAL") else
            "offline"
        )
        iid = patch_matrix.insert(
            "",
            "end",
            values=(
                status,
                row.get("host_nickname", ""),
                row.get("machine_id", ""),
                row.get("apps_label", ""),
                row.get("repo_nickname", ""),
                row.get("gap_label", "-"),
                row.get("applied_at", ""),
                row.get("branch", "-"),
                row.get("head_short", "-"),
                row.get("repo", ""),
            ),
            tags=(tag,),
        )
        _patch_row_meta[iid] = {
            **row,
            "local_actionable": local_actionable,
        }

    def _selected_matrix_repos() -> List[Path]:
        seen: set = set()
        out: List[Path] = []
        for iid in patch_matrix.selection():
            meta = _patch_row_meta.get(iid, {})
            if not meta.get("local_actionable"):
                continue
            repo_s = str(meta.get("repo") or "")
            if not repo_s:
                continue
            key = repo_s.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(Path(repo_s))
        return out

    def _select_pending_rows():
        sel = patch_matrix.selection()
        if sel:
            patch_matrix.selection_remove(*sel)
        for iid, meta in _patch_row_meta.items():
            if str(meta.get("status", "")).startswith("PENDING"):
                patch_matrix.selection_add(iid)

    def _select_current_host_rows():
        sel = patch_matrix.selection()
        if sel:
            patch_matrix.selection_remove(*sel)
        cur_host = socket.gethostname().lower()
        for iid, meta in _patch_row_meta.items():
            if str(meta.get("host", "")).lower() == cur_host:
                patch_matrix.selection_add(iid)

    def _select_same_app_rows():
        focused = patch_matrix.focus()
        if not focused:
            return
        app_label = str(_patch_row_meta.get(focused, {}).get("apps_label") or "")
        if not app_label:
            return
        sel = patch_matrix.selection()
        if sel:
            patch_matrix.selection_remove(*sel)
        for iid, meta in _patch_row_meta.items():
            if str(meta.get("apps_label") or "") == app_label:
                patch_matrix.selection_add(iid)

    def _build_apply_plan(repo_root: Path) -> dict:
        entries: List[Tuple[Path, Path, int]] = []
        for src, dst in _repo_patch_layout(repo_root):
            if not src.exists():
                continue
            try:
                if dst.exists() and _file_sha256(src) == _file_sha256(dst):
                    continue
            except Exception:
                pass
            try:
                sz = src.stat().st_size
            except OSError:
                sz = 0
            entries.append((src, dst, sz))
        return {
            "repo": repo_root,
            "apps": _repo_apps(repo_root, repo_root.name),
            "entries": entries,
            "copy_count": len(entries),
            "copy_bytes": sum(x[2] for x in entries),
        }

    def _plog(line: str, tag: str = ""):
        def _d():
            patch_log.configure(state="normal")
            if not tag:
                low = line.lower()
                t = ("ok"  if any(w in low for w in ("patched", "added", "fixed", "complete")) else
                     "err" if any(w in low for w in ("error", "fail", "cannot")) else
                     "")
            else:
                t = tag
            patch_log.insert("end", line + "\n", t or ())
            patch_log.configure(state="disabled")
            patch_log.see("end")
        root.after(0, _d)

    def _load_patch_log(hint_path: Optional[Path] = None):
        """Populate Patch Log with git history from ALL git repos on this machine.
        Scans every drive for CITL git repos — not just the selected USB path."""
        patch_log.configure(state="normal")
        patch_log.delete("1.0", "end")
        patch_log.configure(state="disabled")
        _clear_matrix()
        _plog("Scanning all drives for CITL git repos...", "header")

        def _bg():
            git_repos = _find_git_repos_on_machine()

            # If hint_path given, make sure its git root is included first
            if hint_path:
                try:
                    r = subprocess.run(
                        ["git", "-C", str(hint_path), "rev-parse", "--show-toplevel"],
                        capture_output=True, text=True, timeout=5)
                    if r.returncode == 0:
                        hp = Path(r.stdout.strip())
                        if hp not in git_repos and _is_citl_repo(hp):
                            git_repos.insert(0, hp)
                except Exception:
                    pass

            if not git_repos:
                _plog("No git repos found on this machine.", "err")
                _plog("Ensure git is installed and CITL repos are checked out.", "dim")
                root.after(0, _clear_matrix)
                return

            _plog(f"Found {len(git_repos)} git repo(s) on {socket.gethostname()}", "ok")

            all_batch_idx = 0  # global color index across all repos
            for repo_idx, git_root in enumerate(git_repos):
                drive_root = (Path(str(git_root)[:3])
                              if platform.system() == "Windows" else Path("/"))
                label = _get_volume_label(drive_root)

                _plog("", "dim")
                _plog("=" * 64, "header")
                _plog(f"  REPO  : {git_root}", "header")
                _plog(f"  DRIVE : {drive_root}  [{label}]", "header")
                _plog(f"  HOST  : {socket.gethostname()}", "header")
                _plog("=" * 64, "header")

                if repo_idx == 0:
                    root.after(0, lambda lbl=label, dr=str(drive_root):
                        _drive_label_var.set(f"Drive: {dr}  [{lbl}]"))

                commits = _git_commits(git_root, max_count=120)
                if not commits:
                    _plog("  (no git history or git not in PATH)", "err")
                    continue

                groups = _group_by_48h(commits)
                _plog(f"  {len(commits)} commits  |  {len(groups)} patch batch(es)", "ok")
                try:
                    gap = _repo_patch_gap(git_root)
                    gap_tag = "ok" if not gap.get("needs_apply") else "batch"
                    _plog(
                        f"  PATCH GAP  | missing:{gap['missing_count']}  "
                        f"outdated:{gap['outdated_count']}  current:{gap['up_to_date_count']}",
                        gap_tag,
                    )
                    if gap.get("needs_apply"):
                        preview = [*gap.get("missing", []), *gap.get("outdated", [])][:6]
                        if preview:
                            _plog("  NEEDS UPDATE FILES: " + ", ".join(preview), "dim")
                except Exception as _gap_exc:
                    _plog(f"  PATCH GAP check failed: {_gap_exc}", "err")

                groups_to_show = groups[:4]
                for batch in groups_to_show:
                    color_hex = _patch_color(all_batch_idx)
                    date_range = (
                        f"{batch[-1]['dt'].strftime('%Y-%m-%d')} "
                        f"-> {batch[0]['dt'].strftime('%Y-%m-%d %H:%M')}"
                    )

                    def _insert_header(idx=all_batch_idx, dr=date_range,
                                       ch=color_hex, n=len(batch)):
                        patch_log.configure(state="normal")
                        patch_log.tag_configure(f"c{idx}", foreground=ch)
                        patch_log.insert(
                            "end",
                            f"\n  PATCH #{idx+1:03d}  [{dr}]  ({n} commit(s))\n",
                            f"c{idx}")
                        patch_log.configure(state="disabled")

                    root.after(0, _insert_header)
                    time.sleep(0.01)
                    all_batch_idx += 1

                    for c in batch[:4]:
                        _plog(
                            f"    [{c['hash']}] "
                            f"{c['dt'].strftime('%m-%d %H:%M')}  "
                            f"{c['subject'][:70]}",
                            "dim")
                if len(groups) > len(groups_to_show):
                    _plog(
                        f"    ... {len(groups) - len(groups_to_show)} older patch batch(es) hidden in tertiary log",
                        "dim",
                    )

            _plog("", "dim")
            _plog(f"-- Patch Log complete  |  {all_batch_idx} total batch(es) across "
                  f"{len(git_repos)} repo(s) --", "ok")

            sig = _current_patch_signature()
            machine_rows = _machine_summary_rows(sig)
            rows = _patch_apply_rows(sig)

            if machine_rows:
                machine_rows = sorted(machine_rows, key=lambda r: (
                    str(r.get("host_nickname", "")),
                    str(r.get("host", "")),
                ))
                _plog("", "dim")
                _plog("=" * 64, "header")
                _plog(f"  MACHINE STATUS  |  USB PATCH SIG: {sig}", "header")
                _plog("=" * 64, "header")
                for m in machine_rows:
                    applied_cnt = int(m.get("applied_count") or 0)
                    repo_total = int(m.get("repo_total") or 0)
                    pending_cnt = int(m.get("pending_count") or 0)
                    if repo_total == 0:
                        tag = "dim"
                        status = "NO-REPOS"
                    elif pending_cnt == 0:
                        tag = "ok"
                        status = "CURRENT"
                    elif applied_cnt > 0:
                        tag = "batch"
                        status = "PARTIAL"
                    else:
                        tag = "err"
                        status = "STALE"
                    _plog(
                        f"  {status:8} | host:{m.get('host_nickname')} ({m.get('host')}) "
                        f"| machine:{m.get('machine_id')} | repos:{applied_cnt}/{repo_total}",
                        tag,
                    )
                    _plog(
                        f"           last_connected:{m.get('last_connected','')} | "
                        f"last_scan:{m.get('last_scan','')} | last_apply:{m.get('last_apply','')}",
                        "dim",
                    )
                    _plog(
                        f"           user:{m.get('user','')} | os:{m.get('os','')} | "
                        f"updated:{m.get('updated','')}",
                        "dim",
                    )

            events = _machine_recent_events(limit_per_host=6)
            if events:
                _plog("", "dim")
                _plog("=" * 64, "header")
                _plog("  RECENT MACHINE HISTORY", "header")
                _plog("=" * 64, "header")
                for ev in events:
                    info = []
                    if ev.get("note"):
                        info.append(f"note:{ev.get('note')}")
                    if ev.get("source"):
                        info.append(f"source:{ev.get('source')}")
                    if ev.get("repo_count"):
                        info.append(f"repos:{ev.get('repo_count')}")
                    if ev.get("path_count"):
                        info.append(f"paths:{ev.get('path_count')}")
                    if ev.get("files_copied"):
                        info.append(f"files:{ev.get('files_copied')}")
                    if ev.get("signature"):
                        info.append(f"sig:{ev.get('signature')}")
                    if ev.get("repo"):
                        info.append(f"repo:{Path(str(ev.get('repo'))).name}")
                    detail = " | ".join(info) if info else "-"
                    _plog(
                        f"  {ev.get('ts')} | host:{ev.get('host_nickname')} ({ev.get('host')}) "
                        f"| machine:{ev.get('machine_id')} | event:{ev.get('event')} | {detail}",
                        "dim",
                    )

            if rows:
                rows = sorted(rows, key=lambda r: (
                    str(r.get("host_nickname", "")),
                    str(r.get("repo_nickname", "")),
                    str(r.get("repo", "")),
                ))
                applied_n = sum(1 for r in rows if r.get("applied"))
                pending_n = len(rows) - applied_n

                _plog("", "dim")
                _plog("=" * 64, "header")
                _plog("  APPLY COVERAGE BY REPO SLOT", "header")
                _plog(
                    f"  {applied_n}/{len(rows)} repo slot(s) applied  |  "
                    f"{pending_n} pending",
                    "ok" if pending_n == 0 else "batch",
                )
                _plog("=" * 64, "header")

                for row in rows:
                    host_nick = str(row.get("host_nickname", ""))
                    host_name = str(row.get("host", ""))
                    repo_nick = str(row.get("repo_nickname", ""))
                    repo_path = str(row.get("repo", ""))
                    branch = str(row.get("branch", "") or "-")
                    head = str(row.get("head", "") or "")
                    head_short = head[:8] if head else "-"
                    if row.get("applied"):
                        _plog(
                            f"  APPLIED  | host:{host_nick} ({host_name}) | repo:{repo_nick} "
                            f"| branch:{branch} | head:{head_short}",
                            "ok",
                        )
                        _plog(
                            f"            date:{row.get('applied_at', '')} | files:{row.get('files_copied', 0)} "
                            f"| machine:{row.get('machine_id', '')} | path:{repo_path}",
                            "dim",
                        )
                    else:
                        _plog(
                            f"  PENDING  | host:{host_nick} ({host_name}) | repo:{repo_nick} "
                            f"| branch:{branch} | head:{head_short}",
                            "err",
                        )
                        _plog(
                            f"            last_sig:{row.get('last_signature', '')} | "
                            f"last_apply:{row.get('applied_at', '')} | path:{repo_path}",
                            "dim",
                        )

            # Primary patch matrix: machine-coded + app-coded per repo row.
            current_host = socket.gethostname()
            current_host_nick = _preferred_machine_nickname(current_host)
            row_by_key: Dict[str, dict] = {}
            for row in rows:
                repo_s = str(row.get("repo") or "")
                if not repo_s:
                    continue
                row_by_key[_repo_key(str(row.get("host") or ""), repo_s)] = dict(row)

            for repo in git_repos:
                repo_s = _safe_resolve_str(repo)
                key = _repo_key(current_host, repo_s)
                if key not in row_by_key:
                    head = _git_head_info(repo)
                    row_by_key[key] = {
                        "host": current_host,
                        "host_nickname": current_host_nick,
                        "machine_id": _machine_id(),
                        "repo": repo_s,
                        "repo_nickname": repo.name,
                        "apps": _repo_apps(repo, repo.name),
                        "applied": False,
                        "applied_at": "",
                        "files_copied": 0,
                        "last_signature": "",
                        "branch": head.get("branch", ""),
                        "head": head.get("hash", ""),
                    }

            matrix_rows: List[dict] = []
            for _k, row in sorted(row_by_key.items(), key=lambda kv: (
                str(kv[1].get("host_nickname", "")),
                str(kv[1].get("repo_nickname", "")),
                str(kv[1].get("repo", "")),
            )):
                repo_s = str(row.get("repo") or "")
                host = str(row.get("host") or "")
                host_nick = str(row.get("host_nickname") or host.split(".")[0])
                repo_nick = str(row.get("repo_nickname") or Path(repo_s).name)
                repo_path = Path(repo_s) if repo_s else Path(".")
                apps = row.get("apps") or _repo_apps(repo_path, repo_nick)
                if not apps:
                    continue
                apps_label = " / ".join(apps)
                branch = str(row.get("branch") or "-")
                head = str(row.get("head") or "")
                head_short = head[:8] if head else "-"
                applied = bool(row.get("applied"))
                applied_at = str(row.get("applied_at") or "")
                local_actionable = False
                gap_label = "-"
                status = "PENDING*"

                if host.lower() == current_host.lower() and repo_s:
                    try:
                        local_actionable = repo_path.is_dir() and _is_citl_repo(repo_path)
                    except OSError:
                        local_actionable = False

                if local_actionable:
                    try:
                        gap = _repo_patch_gap(repo_path)
                        gap_label = (
                            f"m:{gap['missing_count']} o:{gap['outdated_count']} "
                            f"c:{gap['up_to_date_count']}"
                        )
                        if gap.get("needs_apply"):
                            status = "PENDING"
                        elif applied:
                            status = "APPLIED"
                        else:
                            status = "CURRENT"
                    except Exception:
                        status = "PARTIAL"
                        gap_label = "gap-check-failed"
                else:
                    status = "APPLIED*" if applied else "PENDING*"

                matrix_rows.append({
                    "status": status,
                    "host": host,
                    "host_nickname": host_nick,
                    "machine_id": str(row.get("machine_id") or ""),
                    "apps_label": apps_label,
                    "repo_nickname": repo_nick,
                    "repo": repo_s,
                    "gap_label": gap_label,
                    "applied_at": applied_at,
                    "branch": branch,
                    "head_short": head_short,
                    "local_actionable": local_actionable,
                })

            def _push_matrix():
                _clear_matrix()
                for mr in matrix_rows:
                    _insert_matrix_row(mr)
                _select_pending_rows()
            root.after(0, _push_matrix)

        threading.Thread(target=_bg, daemon=True).start()

    _apply_running = [False]
    _apply_btn_ref = [None]

    def _apply_selected_repos():
        if _apply_running[0]:
            _set_status("Apply already running...", _T["warn"])
            return

        repos = _selected_matrix_repos()
        if not repos:
            _set_status("Select one or more CITL rows in the patch matrix first.", _T["warn"])
            return

        plans = []
        skipped_non_citl = 0
        for repo in repos:
            try:
                if repo.resolve() == REPO_ROOT.resolve():
                    continue
            except OSError:
                pass
            if not _is_citl_repo(repo):
                skipped_non_citl += 1
                continue
            plan = _build_apply_plan(repo)
            if plan["copy_count"] > 0:
                plans.append(plan)

        if not plans:
            _set_status("Selected rows are already current for USB patch files.", _T["ok"])
            if skipped_non_citl > 0:
                _plog(f"Skipped {skipped_non_citl} non-CITL selection(s).", "dim")
            return

        total_files = sum(int(p["copy_count"]) for p in plans)
        total_bytes = sum(int(p["copy_bytes"]) for p in plans)
        preview_lines = []
        for p in plans[:12]:
            apps = " / ".join(p.get("apps") or ["CITL App"])
            preview_lines.append(
                f"- {p['repo'].name} | app:{apps} | files:{p['copy_count']} | size:{_fmt_bytes(p['copy_bytes'])}"
            )
        preview = "\n".join(preview_lines)
        if len(plans) > 12:
            preview += f"\n... plus {len(plans) - 12} more selected repo(s)"
        confirmed = messagebox.askyesno(
            "Apply selected CITL patches?",
            "Targeted USB -> workstation apply.\n\n"
            f"Selected repos: {len(plans)}\n"
            f"Files to copy: {total_files}\n"
            f"Total size: {_fmt_bytes(total_bytes)}\n\n"
            f"{preview}\n\n"
            "Proceed with these selected patch targets?",
        )
        if not confirmed:
            _set_status("Apply cancelled.")
            return

        _apply_running[0] = True
        if _apply_btn_ref[0] is not None:
            _apply_btn_ref[0].configure(state="disabled")
        sig = _current_patch_signature()
        _touch_machine("apply_start", f"signature={sig};selected={len(plans)}")
        _set_status(f"Applying USB patch to {len(plans)} selected CITL repo(s)...")
        _plog("", "dim")
        _plog("Applying USB latest files to selected CITL repos...", "header")
        _plog(f"USB patch signature: {sig}", "header")

        def _done(status_msg: str, color: str):
            _apply_running[0] = False
            if _apply_btn_ref[0] is not None:
                _apply_btn_ref[0].configure(state="normal")
            _set_status(status_msg, color)

        def _bg():
            synced = 0
            copied_files = 0
            copied_bytes = 0
            for idx, plan in enumerate(plans, start=1):
                repo = Path(plan["repo"])
                apps = " / ".join(plan.get("apps") or ["CITL App"])
                _plog(f"[{idx:02d}/{len(plans):02d}] APPLY {repo} | app:{apps}", "batch")
                patched = propagate_usb_bundle_to_repo(repo, _plog)
                synced += 1
                copied_files += len(patched)
                copied_bytes += int(plan.get("copy_bytes") or 0)

            _plog("", "dim")
            _plog(
                f"Apply complete: {copied_files} file(s), {_fmt_bytes(copied_bytes)} across {synced} selected repo(s).",
                "ok",
            )
            _touch_machine(
                "apply_complete",
                f"signature={sig};selected={len(plans)};synced={synced};files={copied_files};bytes={copied_bytes}",
            )
            root.after(0, lambda: _done(
                f"Apply complete - {synced} selected repo(s) processed.",
                _T["ok"]))
            root.after(200, lambda: _load_patch_log(_selected_path[0]))

        threading.Thread(target=_bg, daemon=True).start()

    _capture_running = [False]
    _capture_btn_ref = [None]

    def _capture_selected_updates_to_usb():
        if _capture_running[0]:
            _set_status("Capture already running...", _T["warn"])
            return

        repos = []
        for r in _selected_matrix_repos():
            try:
                if r.resolve() == REPO_ROOT.resolve():
                    continue
            except OSError:
                pass
            if _is_citl_repo(r):
                repos.append(r)
        if not repos:
            _set_status("Select one or more local CITL rows for reverse capture.", _T["warn"])
            _plog("No eligible local CITL rows selected for reverse capture.", "err")
            return

        preflight_lines = []
        candidate_repos: List[Path] = []
        for repo in repos:
            changed = _git_status_changed_paths(repo)
            if not changed:
                continue
            base_plan = _build_capture_plan(repo, include_heavy=set(), include_large=False, include_huge=False)
            apps = " / ".join(_repo_apps(repo, repo.name))
            preflight_lines.append(
                f"- {repo.name} | app:{apps} | changed:{len(changed)} | "
                f"default_copy:{base_plan['copy_count']} file(s) / {_fmt_bytes(base_plan['copy_bytes'])}"
            )
            candidate_repos.append(repo)

        if not candidate_repos:
            _set_status("No local git changes detected on selected rows.", _T["warn"])
            _plog("Selected CITL rows have no local git changes.", "dim")
            return

        preview = "\n".join(preflight_lines[:12])
        if len(preflight_lines) > 12:
            preview += f"\n... plus {len(preflight_lines) - 12} more repo(s)"
        if not messagebox.askyesno(
            "Capture selected workstation changes?",
            "Targeted workstation -> USB reverse capture.\n\n"
            f"Selected repos with changes: {len(candidate_repos)}\n\n"
            f"{preview}\n\n"
            "Proceed to per-repo safety prompts and capture planning?",
        ):
            _set_status("Reverse capture cancelled.")
            return

        _capture_running[0] = True
        if _capture_btn_ref[0] is not None:
            _capture_btn_ref[0].configure(state="disabled")

        _touch_machine("capture_start", f"repo_count={len(candidate_repos)}")
        _set_status("Preparing reverse capture from selected CITL repos...")
        _plog("", "dim")
        _plog("Preparing reverse capture from selected CITL repos...", "header")

        plans: List[dict] = []
        bootstrap_reqs = 0

        for repo in candidate_repos:
            changed = _git_status_changed_paths(repo)
            if not changed:
                _plog(f"[SKIP] {repo}  | no local git changes detected", "dim")
                continue

            apps = " / ".join(_repo_apps(repo, repo.name))
            _plog(f"[PLAN] {repo}  | app:{apps} | {len(changed)} changed path(s)", "batch")

            include_heavy: set = set()
            heavy_sizes: Dict[str, int] = {}
            for cat, names in CAPTURE_HEAVY_CATEGORY_PARTS.items():
                sz = 0
                for n in names:
                    p = repo / n
                    if p.exists() and p.is_dir():
                        sz += _dir_size_bytes(p)
                heavy_sizes[cat] = sz

            for cat, sz in heavy_sizes.items():
                if sz <= 0:
                    continue
                first = messagebox.askyesno(
                    f"Include {cat} assets?",
                    "Reverse capture detected heavy assets.\n\n"
                    f"Repo: {repo}\n"
                    f"App(s): {apps}\n"
                    f"Category: {cat}\n"
                    f"Approx size: {_fmt_bytes(sz)}\n\n"
                    "Recommended: No (skip heavy assets and use bootstrap).\n"
                    "Yes = include this category now\n"
                    "No = skip and log bootstrap request",
                )
                approved = bool(first)
                if approved and sz >= CAPTURE_HUGE_CATEGORY_CONFIRM_BYTES:
                    approved = messagebox.askyesno(
                        f"Confirm large {cat} capture",
                        f"{cat} is very large ({_fmt_bytes(sz)}).\n\n"
                        "This may be slow and consume significant USB space.\n"
                        "Proceed anyway?",
                    )
                if approved:
                    include_heavy.add(cat)
                    _plog(f"  include heavy category: {cat} ({_fmt_bytes(sz)})", "warn")
                else:
                    bootstrap_reqs += 1
                    _append_bootstrap_capture_request(
                        repo, cat, sz, note="skipped heavy category during reverse capture")
                    _plog(f"  bootstrap recommended for {cat} ({_fmt_bytes(sz)})", "dim")

            large_files = 0
            huge_files = 0
            large_bytes = 0
            huge_bytes = 0
            for _status, rel in changed:
                src = repo / rel
                if not src.exists() or not src.is_file():
                    continue
                if _capture_skip_reason(rel):
                    continue
                cat = _capture_heavy_category(rel)
                if cat and cat not in include_heavy:
                    continue
                try:
                    sz = src.stat().st_size
                except OSError:
                    continue
                if sz >= CAPTURE_LARGE_FILE_WARN_BYTES:
                    large_files += 1
                    large_bytes += sz
                if sz >= CAPTURE_HUGE_FILE_CONFIRM_BYTES:
                    huge_files += 1
                    huge_bytes += sz

            include_large = True
            include_huge = True
            if large_files > 0:
                include_large = messagebox.askyesno(
                    "Include large changed files?",
                    f"Repo: {repo}\n"
                    f"App(s): {apps}\n"
                    f"Large changed files: {large_files}\n"
                    f"Approx size: {_fmt_bytes(large_bytes)}\n\n"
                    "Recommended: No (skip large files and use bootstrap).\n"
                    "Yes = include large files now\n"
                    "No = skip large files",
                )
                if not include_large:
                    bootstrap_reqs += 1
                    _append_bootstrap_capture_request(
                        repo, "large_files", large_bytes,
                        note=f"skipped {large_files} large changed file(s)")
            if include_large and huge_files > 0:
                include_huge = messagebox.askyesno(
                    "Confirm huge file capture",
                    f"Repo: {repo}\n"
                    f"App(s): {apps}\n"
                    f"Huge changed files (>= {_fmt_bytes(CAPTURE_HUGE_FILE_CONFIRM_BYTES)}): {huge_files}\n"
                    f"Approx size: {_fmt_bytes(huge_bytes)}\n\n"
                    "Proceed with huge-file capture?",
                )
                if not include_huge:
                    bootstrap_reqs += 1
                    _append_bootstrap_capture_request(
                        repo, "huge_files", huge_bytes,
                        note=f"skipped {huge_files} huge changed file(s)")

            plan = _build_capture_plan(repo, include_heavy, include_large, include_huge)
            if plan["copy_count"] > 0:
                plans.append(plan)
                _plog(
                    f"  queued capture: {plan['copy_count']} file(s), {_fmt_bytes(plan['copy_bytes'])}",
                    "ok",
                )
            else:
                _plog("  no eligible files queued after safety filters", "dim")

        def _finish(msg: str, color: str):
            _capture_running[0] = False
            if _capture_btn_ref[0] is not None:
                _capture_btn_ref[0].configure(state="normal")
            _set_status(msg, color)

        def _bg_capture():
            copied_files = 0
            copied_bytes = 0
            touched_repos = 0
            for idx, plan in enumerate(plans, start=1):
                repo = plan["repo"]
                entries = plan["entries"]
                apps = " / ".join(plan.get("apps") or _repo_apps(repo, repo.name))
                _plog(f"[{idx:02d}/{len(plans):02d}] CAPTURE {repo} | app:{apps}", "batch")
                if not entries:
                    _plog("  nothing to copy", "dim")
                    continue
                local_copied = 0
                for src, dst, sz, _status in entries:
                    if _copy_if_needed(src, dst, _plog):
                        copied_files += 1
                        copied_bytes += sz
                        local_copied += 1
                if local_copied > 0:
                    touched_repos += 1
                    _plog(
                        f"  captured {local_copied} file(s) from {repo.name}",
                        "ok",
                    )
            _touch_machine(
                "capture_complete",
                f"repos={touched_repos};files={copied_files};bytes={copied_bytes};bootstrap={bootstrap_reqs}",
            )
            _plog(
                f"Reverse capture complete: {copied_files} file(s), {_fmt_bytes(copied_bytes)} "
                f"from {touched_repos} repo(s). Bootstrap requests logged: {bootstrap_reqs}.",
                "ok",
            )
            root.after(0, lambda: _finish(
                f"Capture complete - {copied_files} file(s) copied to USB.",
                _T["ok"] if copied_files > 0 else _T["warn"],
            ))
            root.after(250, lambda: _load_patch_log(_selected_path[0]))

        if not plans:
            _touch_machine("capture_complete", f"repos=0;files=0;bootstrap={bootstrap_reqs}")
            _plog("No files queued for reverse capture.", "dim")
            _finish("No reverse-capture changes queued.", _T["warn"])
            return

        _set_status(f"Reverse capture running ({len(plans)} selected repo plan(s))...")
        threading.Thread(target=_bg_capture, daemon=True).start()

    def _add_repo_to_patch_cycle():
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Select local repo root to include in offline patch cycle")
        if not d:
            return
        p = Path(d)
        try:
            r = subprocess.run(
                ["git", "-C", str(p), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=6)
            if r.returncode != 0:
                _plog(f"Selected path is not a git repo: {p}", "err")
                _set_status("Selected path is not a git repo.", _T["warn"])
                return
            git_root = Path(r.stdout.strip())
            if not _is_citl_repo(git_root):
                _plog(f"Selected repo is not recognized as a CITL app repo: {git_root}", "err")
                _set_status("Only CITL app repos can be added to patch cycle.", _T["warn"])
                return
            _pin_repo_path(git_root, note="ui_add_repo")
            _set_status(f"Repo added to patch cycle: {git_root}")
            _plog(f"Repo added to offline patch cycle: {git_root}", "ok")
            root.after(100, lambda: _load_patch_log(git_root))
        except Exception as e:
            _plog(f"Could not add repo: {e}", "err")
            _set_status("Could not add repo.", _T["err"])

    _btn(ph2, "Reload Patch Log", _T["btn"],
         lambda: _load_patch_log(_selected_path[0])).pack(side="left", padx=(0, 4))
    _apply_btn_ref[0] = _btn(
        ph2, "Apply Selected", _T["warn"], _apply_selected_repos)
    _apply_btn_ref[0].pack(side="left", padx=(0, 4))
    _capture_btn_ref[0] = _btn(
        ph2, "Capture Selected -> USB", _T["accent"], _capture_selected_updates_to_usb)
    _capture_btn_ref[0].pack(side="left", padx=(0, 4))
    _btn(ph2, "Select Pending", _T["btn"], _select_pending_rows).pack(side="left", padx=(0, 4))
    _btn(ph2, "Select This Device", _T["btn"], _select_current_host_rows).pack(side="left", padx=(0, 4))
    _btn(ph2, "Select Same App", _T["btn"], _select_same_app_rows).pack(side="left", padx=(0, 4))
    _btn(ph2, "Add CITL Repo...", _T["btn"], _add_repo_to_patch_cycle).pack(side="left")

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


    # ── Tab 4: CITL Staff Tools ────────────────────────────────────────────────────────────
    tools_tab = tk.Frame(right_nb, bg=_T["bg"])
    right_nb.add(tools_tab, text="  CITL Staff Tools  ")

    tk.Label(tools_tab,
             text="  CITL Staff Tools  ──  Work Utility  ─  Display Tools  ─  LLM Suite",
             fg=_T["accent"], bg=_T["hi"],
             font=("Consolas", 11, "bold"), anchor="w", padx=8, pady=8).pack(fill="x")

    def _open_toplevel(title, builder_fn):
        win = tk.Toplevel(root)
        win.title(title)
        win.configure(bg=_T["bg"])
        win.geometry("1100x760")
        win.lift()
        try:
            win.attributes("-topmost", True)
            root.after(300, lambda: win.attributes("-topmost", False))
        except Exception:
            pass
        try:
            builder_fn(win)
        except Exception as exc:
            import traceback as _tb
            tk.Label(win,
                     text="Could not load tool:\n\n" + str(exc) + "\n\n" + _tb.format_exc(4),
                     fg=_T["err"], bg=_T["bg"],
                     font=("Consolas", 9), justify="left",
                     padx=20, pady=20).pack(fill="both", expand=True)

    def _launch_staff_toolkit(win):
        import importlib, sys as _s
        for _p in (str(HERE), str(REPO_ROOT)):
            if _p not in _s.path:
                _s.path.insert(0, _p)
        _s.modules.pop("citl_staff_toolkit", None)
        mod = importlib.import_module("citl_staff_toolkit")
        mod.StaffToolkit(win)

    def _launch_workstation(win):
        win.destroy()
        import subprocess as _sp, sys as _s2
        _sp.Popen([_s2.executable, str(HERE / "citl_workstation_apps.py")], cwd=str(HERE))

    def _launch_llmops(win):
        import importlib, sys as _s
        for _p in (str(HERE), str(REPO_ROOT)):
            if _p not in _s.path:
                _s.path.insert(0, _p)
        _s.modules.pop("citl_llmops_suite", None)
        mod = importlib.import_module("citl_llmops_suite")
        mod.LLMOpsSuite(win)

    _TOOL_DEFS = [
        {
            "name":    "CITL Work & Preparedness Launcher",
            "tag":     "Day-to-day staff launcher: track selection, O365 SSO, GitHub onboarding, repo-age detection.",
            "script":  HERE / "citl_staff_toolkit.py",
            "builder": _launch_staff_toolkit,
            "color":   _T["accent"],
        },
        {
            "name":    "Workstation & Display Tools",
            "tag":     "Display port tester, profile save/restore, connection diagnostics and quick-fix actions.",
            "script":  HERE / "citl_workstation_apps.py",
            "builder": _launch_workstation,
            "color":   "#4DAACC",
        },
        {
            "name":    "CITL LLMOps Suite",
            "tag":     "Unified launcher: Factbook, LLM Studio, AI Hub, Academic Advisor, Screen Recorder.",
            "script":  HERE / "citl_llmops_suite.py",
            "builder": _launch_llmops,
            "color":   "#A060E0",
        },
    ]

    cards_frame = tk.Frame(tools_tab, bg=_T["bg"])
    cards_frame.pack(fill="both", expand=True, padx=16, pady=12)

    for _td in _TOOL_DEFS:
        _card = tk.Frame(cards_frame, bg=_T["panel"], bd=0, relief="flat", padx=14, pady=12)
        _card.pack(fill="x", pady=6)
        _lcol = tk.Frame(_card, bg=_T["panel"])
        _lcol.pack(side="left", fill="both", expand=True)
        tk.Label(_lcol, text=_td["name"],
                 fg=_td["color"], bg=_T["panel"],
                 font=("Consolas", 12, "bold"), justify="left", anchor="w").pack(anchor="w")
        tk.Label(_lcol, text=_td["tag"],
                 fg=_T["txt_fg"], bg=_T["panel"],
                 font=("Consolas", 8), justify="left", anchor="w").pack(anchor="w", pady=(2, 0))
        _avail_txt   = "✓ Available" if _td["script"].exists() else "✗ Script not found"
        _avail_color = _T["ok"] if _td["script"].exists() else _T["err"]
        tk.Label(_lcol, text="  " + _avail_txt + "  |  " + _td["script"].name,
                 fg=_avail_color, bg=_T["panel"],
                 font=("Consolas", 7)).pack(anchor="w", pady=(4, 0))
        _rcol = tk.Frame(_card, bg=_T["panel"])
        _rcol.pack(side="right", padx=8)
        _b = _td["builder"]
        _n = _td["name"]
        tk.Button(_rcol, text="Open  ▶",
                  bg=_td["color"], fg=_T["bg"],
                  activebackground=_T["status"], activeforeground=_T["bg"],
                  font=("Consolas", 10, "bold"),
                  relief="flat", padx=16, pady=10, cursor="hand2",
                  command=lambda b=_b, n=_n: _open_toplevel(n, b)
                  ).pack()

    tk.Label(tools_tab,
             text="  Each tool opens in its own window — all from within this single application.",
             fg=_T["skip"], bg=_T["bg"],
             font=("Consolas", 7), anchor="w").pack(fill="x", padx=16, pady=(0, 6))

    # ── Auto-propagate: copy THIS file + patch scripts to found local repos ──
    def _auto_propagate(found: List[Path]):
        """Silently copy latest repair scripts from USB into every found local repo.
        Runs after each search so updates flow automatically — no user action needed."""
        return

    def _on_quick_done(results: List[Path]):
        _refresh_list(results)
        _searching.__setitem__(0, False)
        if results:
            # Auto-populate Patch Log immediately
            root.after(100, lambda: _load_patch_log(results[0]))

    def _do_quick():
        if _searching[0]:
            return
        _searching[0] = True
        _set_status("Quick search in progress...")
        def _bg():
            results = quick_search(lambda s: root.after(0, lambda m=s: _set_status(m)))
            root.after(0, lambda: _on_quick_done(results))
        threading.Thread(target=_bg, daemon=True).start()

    # Deep search keeps patch state read-only until user chooses selected actions.
    _orig_do_deep = _do_deep
    def _do_deep():
        if _searching[0]:
            return
        _stop_deep.clear()
        _searching[0] = True
        _set_status("Deep search running — scanning all drives...")
        def _bg():
            results = deep_search(
                log=lambda s: root.after(0, lambda m=s: _set_status(m[:80])),
                stop_event=_stop_deep,
            )
            root.after(0, lambda: _on_quick_done(results))
        threading.Thread(target=_bg, daemon=True).start()

    # Rewire buttons to use the updated functions
    for w in btn_row.winfo_children():
        w.destroy()
    _btn(btn_row, "Quick Search",      _T["accent"], _do_quick).pack(fill="x", pady=1)
    _btn(btn_row, "Search All Drives", _T["warn"],   _do_deep).pack(fill="x", pady=1)
    _btn(btn_row, "Stop Search",       _T["err"],    _do_stop).pack(fill="x", pady=1)
    _btn(btn_row, "Browse...",         _T["btn"],    _do_browse).pack(fill="x", pady=1)

    # ── Auto-start ─────────────────────────────────────────────────────────
    if start_path:
        _found_paths.append(start_path)
        lb.insert("end", start_path.name)
        lb.selection_set(0)
        _selected_path[0] = start_path
        root.after(400, _run_diag)
        root.after(600, lambda: _load_patch_log(start_path))
    else:
        root.after(300, _do_quick)

    root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def run_cli(start_path: Optional[Path] = None, auto_fix: bool = False):
    _touch_machine("session_start", "cli")
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
            print("Quick search found nothing on this drive.")
            print("Run with --deep to scan all drives, or --path to specify manually.")
            return

    # Always use the most-recently-modified instance automatically
    target = found[0]
    if len(found) > 1:
        print(f"\nFound {len(found)} instance(s) — using most recent:")
        for i, p in enumerate(found):
            mark = "  <-- SELECTED (most recent)" if i == 0 else ""
            print(f"  {p}{mark}")
    else:
        print(f"\nFound: {target}")

    print(f"  (Device registry: {_REGISTRY_PATH})")
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
