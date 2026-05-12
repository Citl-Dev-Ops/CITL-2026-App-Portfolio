#!/usr/bin/env python3
"""
citl_app_sync.py  â€”  CITL App Sync Engine
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
Detects code changes in CITL git repos on this machine, packages them into
dated, beverage-nicknamed patch payloads, and applies them to the USB.

Features
â”€â”€â”€â”€â”€â”€â”€â”€
  â€¢ Scans machine for CITL git repos (all drives / home dirs)
  â€¢ Compares repo file hashes against USB baseline
  â€¢ Creates PATCH-XXXX bundles with date, app, files changed
  â€¢ Beverage-themed nicknames (Bubble Tea, Chai, Latte, etc.)
  â€¢ Color-coded by change type in the GUI
  â€¢ Excludes: .venv/, models/, *.gguf, *.bin, __pycache__, *.log >5MB
  â€¢ Persistent patch manifest: citl_patches.json on USB root

Usage
â”€â”€â”€â”€â”€
    python citl_app_sync.py              # GUI mode
    python citl_app_sync.py --cli        # CLI scan + apply
    python citl_app_sync.py --cli --dry  # CLI dry-run only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import string
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# â”€â”€ Paths â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
USB_ROOT = Path(__file__).resolve().parent
FA_DIR   = USB_ROOT / "factbook-assistant"
MANIFEST = USB_ROOT / "citl_patches.json"

IS_WIN  = platform.system() == "Windows"
IS_LIN  = platform.system() == "Linux"

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# BEVERAGE NICKNAME SYSTEM
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

_BEVERAGES = [
    ("Taro Bubble Tea",      "#9B59B6", "#F0E6FF"),
    ("Matcha Latte",         "#00C8A8", "#E6FFF9"),
    ("Chai Spice",           "#E67E22", "#FFF3E0"),
    ("Oat Milk Cortado",     "#D4A96A", "#FFF8EE"),
    ("Cold Brew",            "#2C3E50", "#C8D8E8"),
    ("Strawberry Milk Tea",  "#E91E8C", "#FFE6F4"),
    ("Lavender Oat Latte",   "#7C4DFF", "#EDE7FF"),
    ("Brown Sugar Latte",    "#8D4E00", "#F5E6D3"),
    ("Iced Hojicha",         "#6B8E23", "#F0F4E0"),
    ("Yuzu Sparkling Tea",   "#F1C40F", "#FFFDE6"),
    ("Mango Oolong",         "#FF9800", "#FFF3E0"),
    ("Pandan Coconut",       "#27AE60", "#E8F8ED"),
    ("Rose Milk Tea",        "#FF6B9D", "#FFE6EF"),
    ("Jasmine Cold Drip",    "#00BCD4", "#E0F8FF"),
    ("Black Sesame Latte",   "#424242", "#E0E0E0"),
    ("Pistachio Espresso",   "#5D9B41", "#EDF5E8"),
    ("Lychee Green Tea",     "#A8D5A2", "#F2FAF2"),
    ("Salted Caramel Mocha", "#795548", "#F5E6D3"),
    ("Butterfly Pea Lemon",  "#3F51B5", "#E8EAF6"),
    ("Tiger Milk Tea",       "#FF7043", "#FFF0EC"),
]

# Change-type color coding
_TYPE_COLOR = {
    "new":     ("#00C8A8", "NEW"),     # teal
    "modified":("#FFD166", "MOD"),     # amber
    "deleted": ("#FF6B6B", "DEL"),     # red
    "config":  ("#74B9E0", "CFG"),     # blue
    "script":  ("#B48EE8", "SCR"),     # purple
}


def _beverage_for(patch_id: int) -> Tuple[str, str, str]:
    """Returns (name, fg_color, bg_color) deterministically from patch_id."""
    return _BEVERAGES[patch_id % len(_BEVERAGES)]


def _local_machine_identity() -> str:
    """Create a stable machine identity string for patch origin tracking."""
    host = platform.node() or socket.gethostname() or "unknown-host"
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown-user"
    return f"{host}|{user}"


def _machine_beverage_for(machine_id: str) -> Tuple[str, str, str]:
    """Returns a beverage nickname and colors deterministically for this machine."""
    digest = hashlib.sha256(machine_id.encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(_BEVERAGES)
    return _BEVERAGES[idx]


def _source_platform() -> str:
    """Return a concise source platform tag for the current machine."""
    system = platform.system()
    if system == "Linux":
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as f:
                data = f.read().lower()
            if "ubuntu" in data:
                return "Ubuntu"
            if "debian" in data:
                return "Debian"
        except OSError:
            pass
        return "Linux"
    if system == "Darwin":
        return "macOS"
    return system or "Unknown"


def _platform_is_unix(platform_tag: str) -> bool:
    return platform_tag in {"Ubuntu", "Debian", "Linux", "macOS"}


def _change_type(path: str) -> str:
    lp = path.lower()
    if lp.endswith(".json") or lp.endswith(".ini") or lp.endswith(".env"):
        return "config"
    if lp.endswith((".sh", ".cmd", ".bat", ".ps1")):
        return "script"
    return "modified"


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# EXCLUSION RULES
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

_SKIP_DIRS = {
    ".venv", "venv", "__pycache__", ".git", "node_modules",
    "models", ".ollama", "dist", "build", "eggs", ".eggs",
    "site-packages", "data/indexes",
}

_SKIP_EXTS = {
    ".gguf", ".bin", ".safetensors", ".pt", ".pth",  # model weights
    ".pyc", ".pyo",                                    # bytecode
    ".exe", ".dll", ".so",                             # binaries (venv)
    ".db", ".sqlite", ".sqlite3",                      # databases
}

_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB ceiling
DEFAULT_CADENCE_HOURS = 48
PIPELINE_STATE_FILE = USB_ROOT / "citl_sync_pipeline_state.json"
PIPELINE_LOCK_FILE = USB_ROOT / ".citl_sync.lock"


def _should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in _SKIP_DIRS:
            return True
    if path.suffix.lower() in _SKIP_EXTS:
        return True
    try:
        if path.stat().st_size > _MAX_FILE_SIZE:
            return True
    except OSError:
        return True
    # Skip large log files
    if path.suffix.lower() == ".log":
        try:
            if path.stat().st_size > 5 * 1024 * 1024:
                return True
        except OSError:
            return True
    return False


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# GIT HELPERS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _git(args: List[str], cwd: Path, timeout: int = 15) -> Tuple[bool, str]:
    try:
        r = subprocess.run(
            ["git"] + args, cwd=str(cwd),
            capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""


def _git_has() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _repo_last_commit_ts(repo: Path, file: Optional[str] = None) -> Optional[datetime]:
    """Return the timestamp of the last user commit touching file (or any file)."""
    args = ["log", "--format=%aI", "-1"]
    if file:
        args += ["--", file]
    ok, out = _git(args, repo)
    if not ok or not out.strip():
        return None
    try:
        return datetime.fromisoformat(out.strip().split()[0])
    except ValueError:
        return None


def _repo_changed_files_since(repo: Path, since_iso: str) -> List[str]:
    """Files changed in repo since a given ISO date (user commits only)."""
    ok, out = _git(
        ["log", f"--since={since_iso}", "--name-only",
         "--pretty=format:", "--diff-filter=AM"],
        repo, timeout=20,
    )
    if not ok:
        return []
    return [f.strip() for f in out.splitlines() if f.strip() and ("/" in f or "." in f)]


def _group_changes_by_app(changes: List["FileChange"]) -> Dict[str, List["FileChange"]]:
    grouped: Dict[str, List["FileChange"]] = {}
    for change in changes:
        grouped.setdefault(change.app, []).append(change)
    return grouped


def _is_change_recent(change: "FileChange", hours: int = 48) -> bool:
    try:
        mtime = change.src_path.stat().st_mtime
        return (datetime.now(timezone.utc) - datetime.fromtimestamp(mtime, timezone.utc)).total_seconds() <= hours * 3600
    except OSError:
        return False


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()[:16]


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _windows_drive_filesystem(path: Path) -> str:
    if not IS_WIN:
        return ""
    drive = (path.drive or path.anchor or "").strip().rstrip("\\/").rstrip(":")
    if not drive:
        return ""
    letter = drive[0].upper()
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-Volume -DriveLetter '{letter}' -ErrorAction SilentlyContinue).FileSystem",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return (proc.stdout or "").strip().lower()
    except Exception:
        return ""


def _windows_drive_volume_id(path: Path) -> str:
    if not IS_WIN:
        return ""
    drive = (path.drive or path.anchor or "").strip().rstrip("\\/").rstrip(":")
    if not drive:
        return ""
    letter = drive[0].upper()
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-Volume -DriveLetter '{letter}' -ErrorAction SilentlyContinue).UniqueId",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        raw = (proc.stdout or "").strip()
        if raw:
            return raw
    except Exception:
        pass
    fs = _windows_drive_filesystem(path) or "unknownfs"
    return f"{letter}:/{fs}"


def _is_citl_target_dir(path: Path) -> bool:
    return (path / "citl_fixer.py").exists() and (path / "factbook-assistant").is_dir()


def _find_exfat_citl_targets() -> List[Path]:
    if not IS_WIN:
        return []
    out: List[Path] = []
    seen: set = set()
    usb_drive = (USB_ROOT.drive or "").lower()
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        try:
            root_exists = root.exists()
        except OSError:
            root_exists = False
        if not root_exists:
            continue
        if (root.drive or "").lower() == usb_drive:
            continue
        fs = _windows_drive_filesystem(root)
        # If filesystem detection is blocked, allow marker-based fallback.
        if fs and ("exfat" not in fs):
            continue
        candidates = [
            root,
            root / "PORTABLE_APPS" / "CITL",
            root / "CITL_FACTBOOK_UBUNTU V1",
            root / "CITL_FACTBOOK_UBUNTU V1" / "PORTABLE_APPS" / "CITL",
        ]
        for cand in candidates:
            try:
                rc = cand.resolve()
            except Exception:
                rc = cand
            if not rc.exists() or not rc.is_dir():
                continue
            key = str(rc).lower()
            if key in seen:
                continue
            if _is_citl_target_dir(rc):
                seen.add(key)
                out.append(rc)
    out.sort(key=lambda p: (len(str(p.parts)), str(p).lower()), reverse=True)
    return out


def pick_sync_target(target_arg: str = "auto") -> Path:
    raw = (target_arg or "auto").strip()
    if raw and raw.lower() not in {"auto", "usb", "exfat"}:
        return Path(raw).expanduser().resolve()

    # If running from a USB/external copy already, keep local behavior.
    if IS_WIN:
        fs_here = _windows_drive_filesystem(USB_ROOT)
        if "exfat" in fs_here:
            return USB_ROOT

        # Running from C:/NTFS: prefer an attached exFAT CITL target.
        targets = _find_exfat_citl_targets()
        if targets:
            return targets[0]

    return USB_ROOT


def _safe_rel_path(raw: str) -> Optional[Path]:
    value = (raw or "").replace("\\", "/").strip()
    if not value:
        return None
    rel = Path(value)
    if rel.is_absolute() or any(p in {"..", ""} for p in rel.parts):
        return None
    return Path(*rel.parts)


def _copy_with_verify(
    src: Path,
    dst: Path,
    log: Callable[[str], None] = print,
    backup_existing: bool = True,
) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if backup_existing and dst.exists():
            bak = dst.with_suffix(dst.suffix + ".sync_bak")
            shutil.copy2(dst, bak)
        shutil.copy2(src, dst)
        src_hash = _file_hash(src)
        dst_hash = _file_hash(dst)
        if not src_hash or src_hash != dst_hash:
            log(f"  ERR verify mismatch: {dst}")
            return False
        return True
    except PermissionError:
        log(f"  ERR permission denied: {dst}")
        return False
    except Exception as e:
        log(f"  ERR copy {src} -> {dst}: {e}")
        return False


def _probe_target_write_access(target_root: Path) -> Tuple[bool, str]:
    probe = target_root / ".citl_sync_write_test.tmp"
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, "write access ok"
    except PermissionError:
        return False, f"permission denied for target root: {target_root}"
    except Exception as e:
        return False, f"target write probe failed: {e}"


def _resolve_pipeline_targets(target_arg: str = "auto") -> Tuple[Path, Optional[Path], str]:
    local_root = USB_ROOT.expanduser().resolve()
    raw = (target_arg or "auto").strip()
    mode = raw.lower() if raw else "auto"

    if mode not in {"auto", "usb", "exfat"}:
        explicit = Path(raw).expanduser().resolve()
        if explicit == local_root:
            return local_root, None, "local"
        return local_root, explicit, "explicit"

    if IS_WIN:
        fs_here = _windows_drive_filesystem(local_root)
        if "exfat" in fs_here:
            return local_root, None, mode
        targets = _find_exfat_citl_targets()
        if targets:
            return local_root, targets[0], mode
        return local_root, None, mode

    target = pick_sync_target(mode)
    if target.resolve() == local_root:
        return local_root, None, mode
    return local_root, target, mode


def _load_pipeline_state() -> Dict:
    data: Dict = {"history": [], "last_run": None}
    if PIPELINE_STATE_FILE.exists():
        try:
            raw = json.loads(PIPELINE_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except Exception:
            pass
    if not isinstance(data.get("history"), list):
        data["history"] = []
    return data


def _save_pipeline_state(state: Dict) -> None:
    tmp = PIPELINE_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(PIPELINE_STATE_FILE)


def _record_pipeline_run(record: Dict) -> None:
    state = _load_pipeline_state()
    history = list(state.get("history", []))
    history.append(record)
    state["history"] = history[-100:]
    state["last_run"] = record
    _save_pipeline_state(state)


def _acquire_pipeline_lock(log: Callable[[str], None] = print) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "started_at": now,
        "pid": os.getpid(),
        "host": platform.node() or socket.gethostname(),
    }

    for attempt in range(2):
        try:
            fd = os.open(str(PIPELINE_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, json.dumps(payload).encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            try:
                age = time.time() - PIPELINE_LOCK_FILE.stat().st_mtime
            except Exception:
                age = 0
            if attempt == 0 and age > 6 * 3600:
                try:
                    PIPELINE_LOCK_FILE.unlink()
                    log("[LOCK] Removed stale sync lock (>6h old).")
                    continue
                except Exception:
                    pass
            break
        except Exception as e:
            log(f"[LOCK] Failed to create lock: {e}")
            return False

    log(f"[LOCK] Sync lock active: {PIPELINE_LOCK_FILE}")
    return False


def _release_pipeline_lock(log: Callable[[str], None] = print) -> None:
    try:
        if PIPELINE_LOCK_FILE.exists():
            PIPELINE_LOCK_FILE.unlink()
    except Exception as e:
        log(f"[LOCK] WARN unable to clear lock: {e}")


def _sync_patch_payload_to_target(
    created_patches: List[Dict],
    local_root: Path,
    target_root: Path,
    log: Callable[[str], None] = print,
    dry_run: bool = False,
    since_days: int = 14,
) -> Dict[str, int]:
    rel_paths: Dict[str, Path] = {}
    invalid = 0
    for patch in created_patches:
        for item in patch.get("files", []):
            rel = _safe_rel_path(str(item.get("path", "")))
            if rel is None:
                invalid += 1
                continue
            rel_paths[str(rel).replace("\\", "/")] = rel

    # Also mirror current local-vs-external delta so C-side direct edits are never missed.
    local_delta = detect_changes(local_root, target_root, log=lambda *_: None, since_days=since_days)
    for change in local_delta:
        rel = _safe_rel_path(change.rel_path)
        if rel is None:
            invalid += 1
            continue
        rel_paths[str(rel).replace("\\", "/")] = rel

    copied = 0
    failed = 0
    missing = 0
    for key in sorted(rel_paths):
        rel = rel_paths[key]
        src = local_root / rel
        dst = target_root / rel
        if not src.exists():
            log(f"  ERR missing local source for mirror: {src}")
            missing += 1
            failed += 1
            continue
        if dry_run:
            log(f"  [DRY][MIRROR] {rel}")
            copied += 1
            continue
        if _copy_with_verify(src, dst, log=log, backup_existing=True):
            log(f"  MIRROR OK  {rel}")
            copied += 1
        else:
            failed += 1

    manifest_synced = 0
    if not dry_run and MANIFEST.exists():
        manifest_dst = target_root / MANIFEST.name
        if _copy_with_verify(MANIFEST, manifest_dst, log=log, backup_existing=False):
            manifest_synced = 1

    return {
        "total_files": len(rel_paths),
        "copied": copied,
        "failed": failed,
        "missing": missing,
        "invalid_rel_paths": invalid,
        "manifest_synced": manifest_synced,
    }


def run_critical_pipeline(
    log: Callable[[str], None] = print,
    dry_run: bool = False,
    since_days: int = 14,
    auto_apply: bool = False,
    manual_tag: bool = False,
    cadence_hours: int = DEFAULT_CADENCE_HOURS,
    target_arg: str = "auto",
) -> List[Dict]:
    """
    Reliability-first pipeline:
      Stage 1: apply to local C-side fixer root.
      Stage 2: mirror exact staged files to external/exFAT target if available.
    """
    local_root, external_target, mode = _resolve_pipeline_targets(target_arg)
    record: Dict = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_mode": mode,
        "manual_tag": bool(manual_tag),
        "dry_run": bool(dry_run),
        "auto_apply": bool(auto_apply),
        "stage1": {"target": str(local_root)},
        "stage2": {},
    }

    log("[PIPELINE] Stage 1/2: local apply target (C-side fixer).")
    created_patches = run_full_sync(
        log=log,
        dry_run=dry_run,
        since_days=since_days,
        auto_apply=auto_apply,
        usb_target=local_root,
        manual_tag=manual_tag,
        cadence_hours=cadence_hours,
    )
    record["stage1"]["patches_created"] = len(created_patches)

    if external_target is None:
        log("[PIPELINE] Stage 2/2 skipped: no external/exFAT CITL target detected.")
        record["stage2"] = {
            "status": "skipped_no_target",
            "target": None,
        }
        _record_pipeline_run(record)
        return created_patches

    record["stage2"]["target"] = str(external_target)
    if IS_WIN:
        record["stage2"]["volume_id"] = _windows_drive_volume_id(external_target)

    if not auto_apply or dry_run:
        log("[PIPELINE] Stage 2/2 skipped: mirror requires --apply and non-dry mode.")
        record["stage2"]["status"] = "skipped_apply_disabled_or_dry"
        _record_pipeline_run(record)
        return created_patches

    can_write, write_msg = _probe_target_write_access(external_target)
    if not can_write:
        log(f"[PIPELINE] Stage 2/2 blocked: {write_msg}")
        record["stage2"]["status"] = "blocked_permissions"
        record["stage2"]["reason"] = write_msg
        _record_pipeline_run(record)
        return created_patches

    log(f"[PIPELINE] Stage 2/2: mirroring staged payload to {external_target}")
    stats = _sync_patch_payload_to_target(
        created_patches,
        local_root=local_root,
        target_root=external_target,
        log=log,
        dry_run=False,
        since_days=since_days,
    )
    if stats.get("total_files", 0) == 0:
        stage2_status = "skipped_no_delta"
    else:
        stage2_status = "ok" if stats.get("failed", 0) == 0 else "partial_fail"
    record["stage2"]["status"] = stage2_status
    record["stage2"]["stats"] = stats
    log(
        "[PIPELINE] Stage 2 result: "
        f"copied={stats['copied']}/{stats['total_files']} "
        f"failed={stats['failed']} missing={stats['missing']} "
        f"invalid={stats['invalid_rel_paths']}"
    )

    # If multiple exFAT CITL roots are mounted, mirror the same payload to each.
    if IS_WIN and mode in {"auto", "usb", "exfat"}:
        extras: List[Dict] = []
        for extra_target in _find_exfat_citl_targets():
            try:
                if extra_target.resolve() == external_target.resolve():
                    continue
            except OSError:
                if str(extra_target).lower() == str(external_target).lower():
                    continue
            extra_entry: Dict = {"target": str(extra_target)}
            can_write_extra, msg_extra = _probe_target_write_access(extra_target)
            if not can_write_extra:
                extra_entry["status"] = "blocked_permissions"
                extra_entry["reason"] = msg_extra
                extras.append(extra_entry)
                log(f"[PIPELINE][EXTRA] SKIP {extra_target} -> {msg_extra}")
                continue
            extra_stats = _sync_patch_payload_to_target(
                created_patches,
                local_root=local_root,
                target_root=extra_target,
                log=log,
                dry_run=False,
                since_days=since_days,
            )
            extra_entry["stats"] = extra_stats
            extra_entry["status"] = "ok" if extra_stats.get("failed", 0) == 0 else "partial_fail"
            extras.append(extra_entry)
            log(
                f"[PIPELINE][EXTRA] {extra_target} "
                f"copied={extra_stats['copied']}/{extra_stats['total_files']} "
                f"failed={extra_stats['failed']}"
            )
        if extras:
            record["stage2"]["additional_targets"] = extras

    _record_pipeline_run(record)
    return created_patches


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PATCH MANIFEST
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class PatchManifest:
    def __init__(self, path: Path = MANIFEST):
        self._path = path
        self._data: Dict = {"patches": [], "last_sync": None, "devices": {}}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {"patches": [], "last_sync": None, "devices": {}}
        if "devices" not in self._data:
            self._data["devices"] = {}

    def save(self):
        self._path.write_text(
            json.dumps(self._data, indent=2, default=str),
            encoding="utf-8",
        )

    @property
    def patches(self) -> List[Dict]:
        return self._data.get("patches", [])

    @property
    def last_sync(self) -> Optional[str]:
        return self._data.get("last_sync")

    def next_patch_id(self) -> int:
        existing = [p.get("patch_num", 0) for p in self.patches]
        return (max(existing) + 1) if existing else 1

    def add_patch(self, patch: Dict):
        self._data["patches"].append(patch)
        self._data["last_sync"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def get_device_record(self, device_id: str) -> Optional[Dict]:
        return self._data.get("devices", {}).get(device_id)

    def ensure_device_record(self, device_id: str, platform_tag: str) -> Dict:
        devices = self._data.setdefault("devices", {})
        record = devices.get(device_id)
        if record is not None:
            record["platform"] = platform_tag
            record["last_seen_at"] = datetime.now(timezone.utc).isoformat()
            return record

        device_num = len(devices) + 1
        if device_num <= len(_BEVERAGES):
            nickname, fg, bg = _BEVERAGES[(device_num - 1) % len(_BEVERAGES)]
        else:
            nickname, fg, bg = _machine_beverage_for(device_id)
        record = {
            "device_id": device_id,
            "device_num": device_num,
            "device_label": f"PC-{device_num:02d}",
            "nickname": nickname,
            "color_fg": fg,
            "color_bg": bg,
            "platform": platform_tag,
            "last_repo": None,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        devices[device_id] = record
        self.save()
        return record

    def mark_device_seen(self, device_id: str, repo_path: str) -> None:
        record = self.ensure_device_record(device_id, _source_platform())
        record["last_repo"] = repo_path
        record["last_seen_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def get_last_repo_for_device(self, device_id: str) -> Optional[str]:
        record = self.get_device_record(device_id)
        if record:
            return record.get("last_repo")
        return None

    def mark_applied(self, patch_id: str):
        for p in self._data["patches"]:
            if p.get("patch_id") == patch_id:
                p["applied"] = True
                p["applied_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def pending(self) -> List[Dict]:
        return [p for p in self.patches if not p.get("applied", False)]

    def get_by_id(self, patch_id: str) -> Optional[Dict]:
        return next((p for p in self.patches if p.get("patch_id") == patch_id), None)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# REPO DISCOVERY
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

_CITL_PY_MARKERS = [
    "citl_fixer.py", "citl_bootstrap.py",
    "factbook-assistant/factbook_assistant_gui.py",
    "factbook_assistant_gui.py",
    "citl_repair_all.py", "factbook-assistant/citl_repair_all.py",
    "citl_staff_toolkit.py", "citl_workstation_apps.py",
    "citl_screen_recorder.py", "citl_llmops_suite.py",
    "citl_academic_advisor.py",
]

_SKIP_SCAN_DIRS = {
    "__pycache__", ".git", ".venv", "node_modules",
    "System Volume Information", "$Recycle.Bin",
    "Windows", "Program Files", "Program Files (x86)",
    "site-packages",
}


def _system_machine_unique_value() -> str:
    """Return a best-effort stable unique value for this physical machine."""
    if IS_WIN:
        try:
            out = subprocess.check_output(
                ["reg", "query", r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            for line in out.splitlines():
                if "MachineGuid" in line:
                    return line.split()[-1].strip()
        except Exception:
            pass
    else:
        for path in [Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")]:
            try:
                if path.exists():
                    return path.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    host = platform.node() or socket.gethostname() or "unknown-host"
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown-user"
    return f"{host}|{user}" 


def _device_id() -> str:
    value = _system_machine_unique_value()
    system = platform.system() or "Unknown"
    digest = hashlib.sha256(f"{system}|{value}".encode("utf-8")).hexdigest()
    return digest


def _most_likely_scan_roots() -> List[Path]:
    roots: List[Path] = [USB_ROOT]
    home = Path.home()

    # Canonical CITL-first roots for reliability.
    if IS_WIN:
        roots.extend(
            [
                Path(r"C:\CITL"),
                home / "CITL",
                home / "PORTABLE_APPS" / "CITL",
                home / "Downloads" / "CITL",
            ]
        )
    else:
        roots.extend([home / "CITL", Path("/CITL"), Path("/media"), Path("/mnt")])

    if home.exists():
        for sub in ["CITL Apps", "CITL App Sync", "PORTABLE_APPS", "Downloads", "Documents"]:
            roots.append(home / sub)

    broad_scan = os.environ.get("CITL_SYNC_BROAD_SCAN", "").strip().lower() in {"1", "true", "yes", "on"}
    if IS_WIN:
        # Always include attached exFAT CITL paths so USB->Windows import is detected.
        for target in _find_exfat_citl_targets():
            roots.append(target)
            roots.append(target.parent)

        for wp in [
            Path(r"C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS"),
            Path(r"C:\00 HENOSIS CODING PROJECTS"),
        ]:
            roots.append(wp)

        if broad_scan:
            for sub in ["Desktop"]:
                roots.append(home / sub)
            for letter in string.ascii_uppercase:
                d = Path(letter + ":\\")
                roots.append(d)
    else:
        for mp in [Path("/opt"), Path("/home")]:
            roots.append(mp)

    # Keep unique existing dirs, in stable priority order.
    seen: set = set()
    ordered: List[Path] = []
    for root in roots:
        try:
            r = root.resolve()
        except OSError:
            continue
        if not r.exists() or not r.is_dir():
            continue
        key = str(r).lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(r)
        if len(ordered) >= 32:
            break
    return ordered


def discover_citl_repos(manifest: "PatchManifest", log: Callable[[str], None] = print) -> List[Path]:
    """Find CITL source repos for this device, preferring the remembered last repo."""
    candidates: List[Path] = []
    seen: set = set()
    remembered_path: Optional[Path] = None

    def _is_citl(p: Path) -> bool:
        return any((p / m).exists() for m in _CITL_PY_MARKERS)

    def _add(p: Path):
        try:
            k = str(p.resolve())
        except OSError:
            return
        if k not in seen:
            seen.add(k)
            candidates.append(p)
            log(f"  Found: {p}")

    device_id = _device_id()
    last_repo = manifest.get_last_repo_for_device(device_id)
    if last_repo:
        path = Path(last_repo)
        if path.is_dir() and _is_citl(path):
            remembered_path = path
            log(f"  Remembered repo candidate: {path}")
            _add(path)
        else:
            log(f"  Remembered repo no longer valid: {path}")

    likely_roots = _most_likely_scan_roots()
    log("  Scanning likely candidate locations for CITL repos...")
    for sr in likely_roots:
        if not sr.is_dir():
            continue
        if _is_citl(sr):
            _add(sr)
        try:
            for child in sr.iterdir():
                if not child.is_dir() or child.name in _SKIP_SCAN_DIRS:
                    continue
                if _is_citl(child):
                    _add(child)
                try:
                    for gc in child.iterdir():
                        if gc.is_dir() and gc.name not in _SKIP_SCAN_DIRS and _is_citl(gc):
                            _add(gc)
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError):
            pass
        if len(candidates) >= 10:
            break

    if candidates:
        if remembered_path is not None:
            try:
                rp = remembered_path.resolve()
                candidates.sort(
                    key=lambda p: 0 if p.resolve() == rp else 1
                )
            except OSError:
                pass
        manifest.mark_device_seen(device_id, str(candidates[0]))
    return candidates


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CHANGE DETECTION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class FileChange:
    __slots__ = ("rel_path", "src_path", "usb_path", "kind",
                 "src_hash", "usb_hash", "commit_date", "commit_msg")

    def __init__(self, rel_path: str, src_path: Path, usb_path: Path,
                 kind: str = "modified",
                 src_hash: str = "", usb_hash: str = "",
                 commit_date: str = "", commit_msg: str = ""):
        self.rel_path    = rel_path
        self.src_path    = src_path
        self.usb_path    = usb_path
        self.kind        = kind
        self.src_hash    = src_hash
        self.usb_hash    = usb_hash
        self.commit_date = commit_date
        self.commit_msg  = commit_msg

    @property
    def app(self) -> str:
        parts = Path(self.rel_path).parts
        if parts:
            return parts[0]
        return "root"

    @property
    def type_color(self) -> Tuple[str, str]:
        ct = _change_type(self.rel_path)
        if self.kind == "new":
            ct = "new"
        elif self.kind == "deleted":
            ct = "deleted"
        return _TYPE_COLOR.get(ct, ("#C8E8EC", "MOD"))


def _target_relative_path(repo: Path, src_path: Path) -> Optional[Tuple[Path, Path]]:
    """
    Returns (repo_relative_path, target_relative_path).
    For source repos nested inside this local CITL root, preserve local subtree
    path on target to prevent cross-app overwrite/bleed.
    """
    try:
        repo_rel = src_path.relative_to(repo)
    except ValueError:
        return None

    try:
        local_rel = src_path.relative_to(USB_ROOT)
        target_rel = local_rel
    except ValueError:
        target_rel = repo_rel

    return repo_rel, target_rel


def detect_changes(
    repo: Path,
    usb_base: Path = USB_ROOT,
    log: Callable[[str], None] = print,
    since_days: int = 14,
) -> List[FileChange]:
    """
    Compare repo Python/config/script files to USB baseline.
    Returns list of FileChange objects where repo is NEWER than USB.
    Only looks at non-venv, non-model files within the past `since_days` days.
    """
    changes: List[FileChange] = []
    since_iso = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    # Shift back N days
    from datetime import timedelta
    since_dt = datetime.now(timezone.utc) - timedelta(days=since_days)
    since_iso = since_dt.isoformat()

    # Walk the repo
    try:
        repo_files = list(repo.rglob("*"))
    except (PermissionError, OSError):
        return changes

    for src_path in repo_files:
        if not src_path.is_file():
            continue
        mapped = _target_relative_path(repo, src_path)
        if mapped is None:
            continue
        repo_rel, target_rel = mapped
        rel_str = str(target_rel).replace("\\", "/")

        if _should_skip(src_path):
            continue

        # Only track CITL source files
        if src_path.suffix.lower() not in (
            ".py", ".json", ".sh", ".cmd", ".bat", ".ps1",
            ".txt", ".md", ".cfg", ".ini", ".toml", ".yaml", ".yml",
        ):
            continue

        # Don't sync from venv site-packages
        if any(p in _SKIP_DIRS for p in repo_rel.parts):
            continue

        # Get last modification time
        try:
            src_mtime = src_path.stat().st_mtime
        except OSError:
            continue

        # Only consider files changed in the last N days
        if src_mtime < since_dt.timestamp():
            continue

        # Find where this would live on the USB
        # Mapping: repo/factbook-assistant/X â†’ USB/factbook-assistant/X
        #          repo/citl_fixer.py      â†’ USB/citl_fixer.py
        usb_path = usb_base / target_rel

        src_hash = _file_hash(src_path)

        if not usb_path.exists():
            kind = "new"
            usb_hash = ""
        else:
            usb_hash = _file_hash(usb_path)
            if src_hash == usb_hash:
                continue  # identical â€” no change
            kind = "modified"

        # Get commit info from git if available
        commit_date = ""
        commit_msg = ""
        if _git_has():
            ok, clog = _git(
                ["log", "--format=%aI|%s", "-1", "--", str(repo_rel)],
                repo, timeout=8,
            )
            if ok and "|" in clog:
                parts = clog.strip().split("|", 1)
                commit_date = parts[0].strip()
                commit_msg  = parts[1].strip()[:80] if len(parts) > 1 else ""

        changes.append(FileChange(
            rel_str, src_path, usb_path, kind,
            src_hash, usb_hash, commit_date, commit_msg,
        ))

    return changes


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PATCH BUNDLER & APPLIER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def build_patch(
    changes: List[FileChange],
    repo: Path,
    manifest: PatchManifest,
    log: Callable[[str], None] = print,
    dry_run: bool = False,
    collector: bool = False,
    collector_app: Optional[str] = None,
    manual_tag: bool = False,
    cadence_hours: int = DEFAULT_CADENCE_HOURS,
) -> Optional[Dict]:
    """Build a patch record from detected changes. Does NOT apply files yet."""
    if not changes:
        return None

    patch_num  = manifest.next_patch_id()
    bev_name, bev_fg, bev_bg = _beverage_for(patch_num)
    base_patch_id = f"PATCH-{patch_num:04d}"
    patch_id   = f"M-{base_patch_id}" if manual_tag else base_patch_id
    now        = datetime.now(timezone.utc)
    date_str   = now.strftime("%Y-%m-%d")
    time_str   = now.strftime("%H:%M:%S UTC")

    # Determine which apps are touched
    apps = sorted({c.app for c in changes})
    device_id = _device_id()
    device_record = manifest.ensure_device_record(device_id, _source_platform())
    machine_identity = _local_machine_identity()
    machine_nickname, machine_fg, machine_bg = _machine_beverage_for(machine_identity)
    machine_id_hash = hashlib.sha256(machine_identity.encode("utf-8")).hexdigest()[:12]

    # Group changes by kind
    by_kind: Dict[str, List[str]] = {}
    for c in changes:
        by_kind.setdefault(c.kind, []).append(c.rel_path)

    patch_type = "collector" if collector else "sync"
    patch_label = f"{patch_id} {bev_name}"
    if collector_app:
        patch_label = f"{patch_label} [{collector_app}]"

    patch = {
        "patch_id":    patch_id,
        "patch_num":   patch_num,
        "nickname":    bev_name,
        "color_fg":    bev_fg,
        "color_bg":    bev_bg,
        "date":        date_str,
        "time":        time_str,
        "recorded_at": now.isoformat(),
        "recorded_at_local": datetime.now().astimezone().isoformat(),
        "source_repo": str(repo),
        "source_host": platform.node() or socket.gethostname(),
        "source_platform": _source_platform(),
        "source_user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
        "source_machine_id": machine_id_hash,
        "source_machine_nickname": machine_nickname,
        "source_machine_color_fg": machine_fg,
        "source_machine_color_bg": machine_bg,
        "source_device_num": device_record.get("device_num"),
        "source_device_label": device_record.get("device_label"),
        "source_device_nickname": device_record.get("nickname"),
        "source_device_color_fg": device_record.get("color_fg"),
        "source_device_color_bg": device_record.get("color_bg"),
        "patch_type":  patch_type,
        "manual_tag":  bool(manual_tag),
        "cadence_hours": int(cadence_hours),
        "collector":   collector,
        "collector_app": collector_app,
        "patch_label": patch_label,
        "patch_description": (
            f"{len(changes)} changed file(s) across {', '.join(apps)}"
            if not collector else
            f"Collector patch for {collector_app or 'selected app'}: {len(changes)} file(s)"
        ),
        "apps":        apps,
        "total_files": len(changes),
        "by_kind":     {k: len(v) for k, v in by_kind.items()},
        "files":       [
            {
                "path":        c.rel_path,
                "kind":        c.kind,
                "src_hash":    c.src_hash,
                "usb_hash":    c.usb_hash,
                "commit_date": c.commit_date,
                "commit_msg":  c.commit_msg,
            }
            for c in changes
        ],
        "applied":     False,
        "dry_run":     dry_run,
    }

    if collector:
        log(f"  Collector patch: {patch_id}  [{bev_name}]  {collector_app or 'app-specific'}  {len(changes)} file(s)")
    else:
        log(f"  Patch: {patch_id}  [{bev_name}]  {len(changes)} file(s) across {apps}")
    return patch


def apply_patch(
    patch: Dict,
    changes: List[FileChange],
    manifest: PatchManifest,
    log: Callable[[str], None] = print,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """Copy changed files from repo to USB. Returns (applied, failed) counts."""
    applied = 0
    failed  = 0

    for c in changes:
        if dry_run:
            tag = _change_type(c.rel_path)
            log(f"  [DRY] {c.kind.upper():3} {c.rel_path}")
            applied += 1
            continue

        try:
            # Ensure destination directory exists
            c.usb_path.parent.mkdir(parents=True, exist_ok=True)

            # Backup existing file if it exists
            if c.usb_path.exists():
                bak = c.usb_path.with_suffix(c.usb_path.suffix + ".sync_bak")
                shutil.copy2(c.usb_path, bak)

            shutil.copy2(c.src_path, c.usb_path)
            log(f"  OK  {c.kind.upper():3} {c.rel_path}")
            applied += 1

        except Exception as e:
            log(f"  ERR {c.rel_path}: {e}")
            failed += 1

    if not dry_run:
        manifest.mark_applied(patch["patch_id"])

    log(f"  Applied {applied} file(s), {failed} error(s)")
    return applied, failed


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# HIGH-LEVEL SYNC RUNNER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def run_full_sync(
    log: Callable[[str], None] = print,
    dry_run: bool = False,
    since_days: int = 14,
    auto_apply: bool = False,
    usb_target: Optional[Path] = None,
    manual_tag: bool = False,
    cadence_hours: int = DEFAULT_CADENCE_HOURS,
) -> List[Dict]:
    """
    Full sync cycle:
      1. Discover repos
      2. Detect changes
      3. Build patch records
      4. Optionally apply
    Returns list of patch dicts created this run.
    """
    manifest = PatchManifest()
    created_patches: List[Dict] = []
    target_base = (usb_target or USB_ROOT).expanduser().resolve()

    log("-- CITL App Sync Engine --------------------------------")
    log(f"  Target root: {target_base}")
    if not _git_has():
        log("  WARN git not found - commit-date metadata unavailable")

    log("-- Discovering CITL repos ------------------------------")
    repos = discover_citl_repos(manifest, log)
    if not repos:
        log("  No CITL repos found on this machine.")
        return []

    for repo in repos:
        # Skip the target root itself to avoid self-comparison loops.
        try:
            if repo.resolve() == target_base.resolve():
                log(f"  Skip target root self-comparison: {repo}")
                continue
        except OSError:
            pass

        log(f"-- Scanning repo: {repo} ------------------------")
        changes = detect_changes(repo, target_base, log=log, since_days=since_days)

        if not changes:
            log(f"  No changes detected (past {since_days} days)")
            continue

        log(f"  {len(changes)} change(s) detected")
        patch = build_patch(
            changes,
            repo,
            manifest,
            log=log,
            dry_run=dry_run,
            manual_tag=manual_tag,
            cadence_hours=cadence_hours,
        )
        if patch:
            if not dry_run:
                manifest.add_patch(patch)
            created_patches.append((patch, changes))

            if auto_apply or dry_run:
                apply_patch(patch, changes, manifest, log=log, dry_run=dry_run)

    log(f"-- Sync complete: {len(created_patches)} patch(es) created --")
    return [p for p, _ in created_patches]

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# GUI EMBED ENTRY POINT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def run_sync_tab(parent, T: dict, root_tk, log_write_fn: Callable):
    """
    Build the Sync & Patches tab content into `parent` frame.
    T = CITL color theme dict. root_tk = tk.Tk() reference.
    log_write_fn(widget, line) = function to append to a ScrolledText.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
    except ImportError:
        return

    # â”€â”€ Top pane: controls + patch list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    top = tk.Frame(parent, bg=T["bg"])
    top.pack(fill="both", expand=True)

    left = tk.Frame(top, bg=T["panel"], width=320)
    left.pack(side="left", fill="y", padx=(4, 0), pady=4)
    left.pack_propagate(False)

    right = tk.Frame(top, bg=T["bg"])
    right.pack(side="left", fill="both", expand=True, padx=4, pady=4)

    # â”€â”€ Settings panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    tk.Label(left, text="Sync Settings",
             fg=T["accent"], bg=T["panel"],
             font=("Consolas", 10, "bold")).pack(fill="x", padx=8, pady=(8, 2))

    # Days back
    # Default to 48-hour cadence window for critical patch operations.
    days_var = tk.IntVar(value=2)
    df = tk.Frame(left, bg=T["panel"])
    df.pack(fill="x", padx=8, pady=2)
    tk.Label(df, text="Look back (days):", fg=T["fg"], bg=T["panel"],
             font=("Consolas", 8)).pack(side="left")
    tk.Spinbox(df, from_=1, to=365, width=5,
               textvariable=days_var,
               bg=T["txt_bg"], fg=T["txt_fg"],
               buttonbackground=T["btn"],
               font=("Consolas", 8)).pack(side="right")

    # Auto apply
    auto_var = tk.BooleanVar(value=True)
    tk.Checkbutton(left, text="Auto-apply patches",
                   variable=auto_var,
                   bg=T["panel"], fg=T["fg"],
                   selectcolor=T["btn"],
                   activebackground=T["panel"],
                   font=("Consolas", 8)).pack(fill="x", padx=8, pady=2)

    dry_var = tk.BooleanVar(value=False)
    tk.Checkbutton(left, text="Dry run (no writes)",
                   variable=dry_var,
                   bg=T["panel"], fg=T["fg"],
                   selectcolor=T["btn"],
                   activebackground=T["panel"],
                   font=("Consolas", 8)).pack(fill="x", padx=8, pady=2)

    tk.Label(left, text="Pending Patches",
             fg=T["accent"], bg=T["panel"],
             font=("Consolas", 9, "bold")).pack(fill="x", padx=8, pady=(10, 2))

    # Patch listbox
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

    # Collector candidates listbox
    coll_label = tk.Label(left, text="Collector Candidates",
                          fg=T["accent"], bg=T["panel"],
                          font=("Consolas", 9, "bold"))
    coll_label.pack(fill="x", padx=8, pady=(6, 2))
    coll_frame = tk.Frame(left, bg=T["panel"])
    coll_frame.pack(fill="both", expand=True, padx=8)
    coll_lb = tk.Listbox(coll_frame, bg=T["txt_bg"], fg=T["txt_fg"],
                         selectbackground=T["accent"], selectforeground=T["bg"],
                         font=("Consolas", 8), activestyle="none",
                         relief="flat", borderwidth=0, height=8)
    coll_sb = ttk.Scrollbar(coll_frame, orient="vertical", command=coll_lb.yview)
    coll_lb.configure(yscrollcommand=coll_sb.set)
    coll_sb.pack(side="right", fill="y")
    coll_lb.pack(side="left", fill="both", expand=True)

    _patches_cache: List[Dict] = []
    _changes_cache: Dict[str, List] = {}
    _collector_cache: List[Dict] = []

    def _refresh_lb():
        manifest = PatchManifest()
        pending = manifest.pending()
        all_p   = manifest.patches[-20:]  # show last 20
        lb.delete(0, "end")
        _patches_cache.clear()

        windows = []
        unix = []
        for p in reversed(all_p):
            plat = p.get("source_platform", "Unknown")
            if _platform_is_unix(plat):
                unix.append(p)
            else:
                windows.append(p)

        if windows:
            lb.insert("end", "â”€â”€ Windows-origin patches â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
            _patches_cache.append(None)
            for p in windows:
                num      = p.get("patch_id", "?")
                nick     = p.get("nickname", "")
                date     = p.get("date", "")
                platform_tag = p.get("source_platform", "?")
                device_id = p.get("source_device_label", "?")
                device_nic = p.get("source_device_nickname", "?")
                n_files  = p.get("total_files", 0)
                status   = "APPLIED" if p.get("applied") else "PENDING"
                entry    = f"{num} [{platform_tag[:6]}] {device_id:<5} {device_nic[:12]:<12} {date} {nick[:10]:<10} {n_files}f {status}"
                lb.insert("end", entry)
                _patches_cache.append(p)

        if unix:
            lb.insert("end", "â”€â”€ Unix/Ubuntu-origin patches â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
            _patches_cache.append(None)
            for p in unix:
                num      = p.get("patch_id", "?")
                nick     = p.get("nickname", "")
                date     = p.get("date", "")
                platform_tag = p.get("source_platform", "?")
                device_id = p.get("source_device_label", "?")
                device_nic = p.get("source_device_nickname", "?")
                n_files  = p.get("total_files", 0)
                status   = "APPLIED" if p.get("applied") else "PENDING"
                entry    = f"{num} [{platform_tag[:6]}] {device_id:<5} {device_nic[:12]:<12} {date} {nick[:10]:<10} {n_files}f {status}"
                lb.insert("end", entry)
                _patches_cache.append(p)

        if not windows and not unix:
            lb.insert("end", "No patches found.")
            _patches_cache.append(None)

        return pending

    def _refresh_collector_lb():
        coll_lb.delete(0, "end")
        for item in _collector_cache:
            status = "RECENT" if item["recent"] else "OLDER"
            entry = f"{item['app'][:18]:<18} {len(item['changes']):>2}f  {status}  [{item['machine_nickname']}]"
            coll_lb.insert("end", entry)

    def _scan_unique_app_candidates():
        _collector_cache.clear()
        machine_id = _local_machine_identity()
        machine_nickname, _, _ = _machine_beverage_for(machine_id)
        manifest = PatchManifest()
        repos = discover_citl_repos(manifest, log)
        for repo in repos:
            if repo.resolve() == USB_ROOT.resolve():
                continue
            changes = detect_changes(repo, USB_ROOT, log=lambda msg: None, since_days=days_var.get())
            if not changes:
                continue
            for app, app_changes in _group_changes_by_app(changes).items():
                _collector_cache.append({
                    "repo": repo,
                    "app": app,
                    "changes": app_changes,
                    "recent": any(_is_change_recent(c) for c in app_changes),
                    "machine_nickname": machine_nickname,
                })
        _refresh_collector_lb()

    def _create_collector_patch():
        sel = coll_lb.curselection()
        if not sel:
            _slog("  Select a collector candidate first.")
            return
        item = _collector_cache[sel[0]]
        manifest = PatchManifest()
        patch = build_patch(
            item["changes"], item["repo"], manifest,
            log=_slog, dry_run=False,
            collector=True,
            collector_app=item["app"],
        )
        if patch:
            manifest.add_patch(patch)
            _slog(f"  Collector patch {patch['patch_id']} saved to manifest.")
            _refresh_lb()

    # â”€â”€ Right: log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    sync_log_lbl = tk.Label(right, text="Sync Log",
                            fg=T["accent"], bg=T["bg"],
                            font=("Consolas", 9, "bold"), anchor="w", padx=4)
    sync_log_lbl.pack(anchor="w")

    sync_log = ScrolledText(right, height=22, state="disabled",
                            bg=T["txt_bg"], fg=T["txt_fg"],
                            font=("Consolas", 8), relief="flat",
                            insertbackground=T["accent"])
    sync_log.tag_configure("ok",   foreground=T["ok"])
    sync_log.tag_configure("err",  foreground=T["err"])
    sync_log.tag_configure("warn", foreground=T["warn"])
    sync_log.tag_configure("hdr",  foreground=T["status"],
                           font=("Consolas", 8, "bold"))
    sync_log.tag_configure("new",  foreground=T["ok"])
    sync_log.tag_configure("mod",  foreground=T["warn"])
    sync_log.tag_configure("del",  foreground=T["err"])
    sync_log.pack(fill="both", expand=True, padx=2)

    # Patch detail area
    tk.Label(right, text="Selected Patch Detail",
             fg=T["accent"], bg=T["bg"],
             font=("Consolas", 8, "bold"), anchor="w", padx=4).pack(anchor="w", pady=(4, 0))
    detail_log = ScrolledText(right, height=8, state="disabled",
                              bg=T["txt_bg"], fg=T["txt_fg"],
                              font=("Consolas", 7), relief="flat")
    detail_log.pack(fill="x", padx=2, pady=(0, 4))

    # Ctrl row
    ctrl = tk.Frame(right, bg=T["bg"])
    ctrl.pack(fill="x", padx=2, pady=(0, 4))

    def _slog(msg: str):
        def _do():
            sync_log.configure(state="normal")
            low = msg.lower()
            tag = ("ok"   if any(x in low for x in ("ok ", "applied", "found", "success"))  else
                   "err"  if any(x in low for x in ("err", "fail", "cannot"))                else
                   "warn" if any(x in low for x in ("warn", "skip", "no changes", "dry"))    else
                   "new"  if " new " in low                                                    else
                   "mod"  if " mod " in low or " modified" in low                             else
                   "hdr"  if msg.startswith("â”€â”€")                                             else "")
            sync_log.insert("end", msg + "\n", tag or ())
            sync_log.configure(state="disabled")
            sync_log.see("end")
        root_tk.after(0, _do)

    def _dlog(msg: str):
        def _do():
            detail_log.configure(state="normal")
            detail_log.insert("end", msg + "\n")
            detail_log.configure(state="disabled")
            detail_log.see("end")
        root_tk.after(0, _do)

    def _show_patch_detail(e=None):
        sel = lb.curselection()
        if not sel or sel[0] >= len(_patches_cache):
            return
        p = _patches_cache[sel[0]]
        if p is None:
            return
        detail_log.configure(state="normal")
        detail_log.delete("1.0", "end")
        detail_log.configure(state="disabled")
        bev = p.get("nickname", "")
        _dlog(f"{p.get('patch_id')}  [{bev}]  {p.get('date')} {p.get('time', '')}")
        _dlog(f"Repo:   {p.get('source_repo', 'unknown')}")
        _dlog(f"Platform: {p.get('source_platform', 'unknown')} @ {p.get('source_host', 'unknown')}")
        _dlog(f"Device:  {p.get('source_device_label', 'unknown')} / {p.get('source_device_nickname', 'unknown')}")
        _dlog(f"Apps:   {', '.join(p.get('apps', []))}")
        _dlog(f"Status: {'APPLIED' if p.get('applied') else 'PENDING'}")
        _dlog(f"Files ({p.get('total_files',0)}):")
        for f in p.get("files", [])[:20]:
            tag_str = f.get('kind','?').upper()[:3]
            cd = f.get('commit_date','')[:10]
            msg = f.get('commit_msg','')[:40]
            _dlog(f"  [{tag_str}] {f.get('path','')}  {cd}  {msg}")

    lb.bind("<<ListboxSelect>>", _show_patch_detail)

    _busy = [False]

    def _run_scan():
        if _busy[0]:
            return
        _busy[0] = True
        sync_log.configure(state="normal")
        sync_log.delete("1.0", "end")
        sync_log.configure(state="disabled")
        _slog(f"â”€â”€ Scan started {datetime.now().strftime('%H:%M:%S')} â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")

        def _bg():
            patches = run_critical_pipeline(
                log=_slog,
                dry_run=dry_var.get(),
                since_days=days_var.get(),
                auto_apply=auto_var.get(),
                target_arg="auto",
            )
            _changes_cache.update({p["patch_id"]: [] for p in patches})
            root_tk.after(0, _refresh_lb)
            root_tk.after(0, lambda: _busy.__setitem__(0, False))

        threading.Thread(target=_bg, daemon=True).start()

    def _apply_selected():
        sel = lb.curselection()
        if not sel:
            _slog("  Select a patch first.")
            return
        p = _patches_cache[-(sel[0]+1)]
        if p.get("applied"):
            _slog(f"  {p['patch_id']} already applied.")
            return
        if p.get("dry_run"):
            _slog(f"  {p['patch_id']} was a dry-run record â€” cannot apply file data.")
            return

        def _bg():
            manifest = PatchManifest()
            # Reconstruct changes from patch file list
            repo = Path(p.get("source_repo", ""))
            if not repo.is_dir():
                _slog(f"  Source repo missing: {repo}")
                return
            changes = detect_changes(repo, USB_ROOT, log=_slog, since_days=365)
            patch_files = {f["path"] for f in p.get("files", [])}
            relevant = [c for c in changes if c.rel_path in patch_files]
            apply_patch(p, relevant, manifest, log=_slog, dry_run=False)
            root_tk.after(0, _refresh_lb)

        threading.Thread(target=_bg, daemon=True).start()

    def _btn(parent, text, color, cmd):
        b = tk.Button(parent, text=text, bg=color, fg=T["bg"],
                      activebackground=T["status"], activeforeground=T["bg"],
                      relief="flat", padx=8, pady=5, cursor="hand2",
                      font=("Consolas", 9, "bold"), command=cmd)
        b.pack(side="left", fill=None, pady=2, padx=2)
        return b

    _btn(ctrl, "Scan for Changes", T["accent"], _run_scan)
    _btn(ctrl, "Apply Selected",   T["warn"],   _apply_selected)
    _btn(ctrl, "Refresh List",     T["btn"],    lambda: _refresh_lb())
    _btn(ctrl, "Refresh Collector", T["accent"], _scan_unique_app_candidates)
    _btn(ctrl, "Collect Patch",    T["warn"],   _create_collector_patch)

    # Auto-populate on load
    root_tk.after(300, _refresh_lb)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CLI ENTRY POINT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def run_cli():
    ap = argparse.ArgumentParser(description="CITL App Sync Engine")
    ap.add_argument("--dry",    action="store_true", help="Dry run â€” no writes")
    ap.add_argument("--apply",  action="store_true", help="Auto-apply detected patches")
    ap.add_argument("--days",   type=int, default=14, help="Look back N days (default 14)")
    ap.add_argument("--cadence-hours", type=int, default=DEFAULT_CADENCE_HOURS,
                    help="Auto cadence gate in hours (default 48).")
    ap.add_argument("--manual", action="store_true",
                    help="Manual override. If run inside cadence window, patch IDs are tagged with M-.")
    ap.add_argument("--target", default="auto",
                    help="External mirror target for stage 2: auto | usb | exfat | <explicit path>.")
    ap.add_argument("--status", action="store_true", help="Show patch manifest status")
    args = ap.parse_args()

    if args.status:
        m = PatchManifest()
        print(f"Total patches: {len(m.patches)}")
        print(f"Pending:       {len(m.pending())}")
        print(f"Last sync:     {m.last_sync or 'never'}")
        print("Source machine summaries:")
        machine_counts = {}
        platform_counts = {}
        for p in m.patches:
            key = p.get("source_machine_nickname", p.get("source_host", "unknown"))
            machine_counts[key] = machine_counts.get(key, 0) + 1
            plat = p.get("source_platform", "unknown")
            platform_counts[plat] = platform_counts.get(plat, 0) + 1
        for name, count in sorted(machine_counts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {name}: {count} patch(es)")
        print("Platform summaries:")
        for plat, count in sorted(platform_counts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {plat}: {count} patch(es)")
        print("\nRecent patches:")
        for p in m.patches[-10:]:
            status = "APPLIED" if p.get("applied") else "PENDING"
            src = p.get("source_machine_nickname", "?")
            host = p.get("source_host", "?")
            machine = f"{src}@{host}"
            print(f"  {p['patch_id']}  [{p.get('nickname','?')}]  {p.get('date','')} {p.get('time','')}  {p.get('total_files',0)}f  {status}  ({machine})")
        return

    manifest = PatchManifest()
    cadence_hours = max(1, int(args.cadence_hours or DEFAULT_CADENCE_HOURS))
    last_sync_dt = _parse_iso_datetime(str(manifest.last_sync or ""))
    now_dt = datetime.now(timezone.utc)
    within_cadence = False
    if last_sync_dt is not None:
        try:
            within_cadence = (now_dt - last_sync_dt).total_seconds() < (cadence_hours * 3600)
        except Exception:
            within_cadence = False

    if within_cadence and not args.manual:
        wait_sec = (cadence_hours * 3600) - int((now_dt - last_sync_dt).total_seconds())
        wait_h = max(0, wait_sec // 3600)
        wait_m = max(0, (wait_sec % 3600) // 60)
        print(
            f"[CADENCE] Skip auto run: last sync {manifest.last_sync}. "
            f"Next auto window in {wait_h}h {wait_m}m. Use --manual to override."
        )
        return

    manual_tag = bool(args.manual and within_cadence)
    local_root, external_target, _ = _resolve_pipeline_targets(args.target)
    print(f"[TARGET][LOCAL] {local_root}")
    if external_target is not None:
        print(f"[TARGET][EXTERNAL] {external_target}")
        ext_vid = _windows_drive_volume_id(external_target)
        if ext_vid:
            print(f"[TARGET][EXTERNAL_ID] {ext_vid}")
    else:
        print("[TARGET][EXTERNAL] (none detected)")
    if manual_tag:
        print("[CADENCE] Manual run within cadence window -> M- patch tag enabled.")

    if not _acquire_pipeline_lock(print):
        print("[LOCK] Exiting to avoid concurrent patch run.")
        return
    try:
        run_critical_pipeline(
            log=print,
            dry_run=args.dry,
            since_days=args.days,
            auto_apply=args.apply,
            manual_tag=manual_tag,
            cadence_hours=cadence_hours,
            target_arg=args.target,
        )
    finally:
        _release_pipeline_lock(print)


if __name__ == "__main__":
    run_cli()

