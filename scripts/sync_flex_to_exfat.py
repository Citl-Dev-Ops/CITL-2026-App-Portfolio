#!/usr/bin/env python3
"""Portable CITL updater for removable exFAT/FAT/NTFS drives.

Purpose:
- Keep launch/update-critical CITL files synchronized across USB devices.
- Avoid destructive full wipes by default (copies changed/new files only).
- Optionally mirror (delete stale files) when explicitly requested.

Examples:
    python scripts/sync_flex_to_exfat.py
    python scripts/sync_flex_to_exfat.py --target K:\\
    python scripts/sync_flex_to_exfat.py --dry-run
    python scripts/sync_flex_to_exfat.py --mirror --target /media/user/CITL_USB
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Iterable, List, Sequence

try:
    import psutil
except Exception:
    psutil = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST_ROOT = "CITL"

# Keep this list focused on launch/update reliability for cross-device use.
DEFAULT_ITEMS: Sequence[str] = (
    "citl_fixer.py",
    "citl_bootstrap.py",
    "COPY_THIS_USB_TO_NEXT_WINDOWS.cmd",
    "COPY_THIS_USB_TO_NEXT_UBUNTU.sh",
    "SYNC_CITL_APPS_TO_USB_WINDOWS.cmd",
    "SYNC_CITL_APPS_TO_USB_UBUNTU.sh",
    "SYNC_EXES_TO_USB_WINDOWS.cmd",
    "INSTALL_CITL_APPS_PORTABLE.cmd",
    "scripts/windows/sync_usb_apps.ps1",
    "scripts/windows/install_citl_apps_portable.ps1",
    "scripts/windows/usb_run.ps1",
    "factbook-assistant/citl_app_sync.py",
    "factbook-assistant/citl_sync_hub.py",
    "citl_flex_troubleshooter",
)


def is_portable_fs(fstype: str) -> bool:
    if not fstype:
        return False
    return fstype.strip().lower() in {"exfat", "fat32", "vfat", "fat", "ntfs"}


def _canon_drive_token(p: Path) -> str:
    try:
        rp = p.resolve()
    except OSError:
        rp = p
    if os.name == "nt":
        return rp.anchor.lower()
    return str(rp)


def find_removable_targets(include_current_drive: bool = False) -> List[Path]:
    targets: List[Path] = []
    if psutil is None:
        return targets

    source_token = _canon_drive_token(ROOT)
    seen = set()
    for part in psutil.disk_partitions(all=False):
        try:
            fstype = (part.fstype or "").strip()
            if not is_portable_fs(fstype):
                continue
            mount = Path(part.mountpoint)
            if not mount.exists():
                continue
            opts = (part.opts or "").lower()
            if "ro" in opts.split(","):
                continue
            token = _canon_drive_token(mount)
            if (not include_current_drive) and token == source_token:
                continue
            if token in seen:
                continue
            seen.add(token)
            targets.append(mount)
        except Exception:
            continue
    return targets


def _files_equal(src: Path, dst: Path) -> bool:
    try:
        s = src.stat()
        d = dst.stat()
    except OSError:
        return False
    return s.st_size == d.st_size and int(s.st_mtime) == int(d.st_mtime)


def _copy_file(src: Path, dst: Path, dry_run: bool) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and _files_equal(src, dst):
        return False
    if not dry_run:
        shutil.copy2(src, dst)
    return True


def _sync_dir(src_dir: Path, dst_dir: Path, dry_run: bool, mirror: bool) -> tuple[int, int]:
    copied = 0
    deleted = 0
    src_files = []
    for root, _, files in os.walk(src_dir):
        r = Path(root)
        for fn in files:
            s = r / fn
            rel = s.relative_to(src_dir)
            src_files.append(rel)
            d = dst_dir / rel
            if _copy_file(s, d, dry_run):
                copied += 1

    if mirror and dst_dir.exists():
        src_set = {str(p).replace("\\", "/") for p in src_files}
        for root, _, files in os.walk(dst_dir):
            r = Path(root)
            for fn in files:
                d = r / fn
                rel = str(d.relative_to(dst_dir)).replace("\\", "/")
                if rel not in src_set:
                    if not dry_run:
                        d.unlink(missing_ok=True)
                    deleted += 1
    return copied, deleted


def sync_items_to_target(
    target_mount: Path,
    items: Iterable[str],
    dry_run: bool = False,
    mirror: bool = False,
    dest_root: str = DEFAULT_DEST_ROOT,
) -> dict:
    dest_base = target_mount / dest_root
    copied = 0
    deleted = 0
    missing = []
    synced = []

    for rel in items:
        src = ROOT / rel
        dst = dest_base / rel
        if not src.exists():
            missing.append(rel)
            continue

        if src.is_dir():
            c, d = _sync_dir(src, dst, dry_run=dry_run, mirror=mirror)
            copied += c
            deleted += d
            synced.append(rel + "/")
        else:
            if _copy_file(src, dst, dry_run):
                copied += 1
            synced.append(rel)

    manifest = {
        "tool": "sync_flex_to_exfat.py",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_root": str(ROOT),
        "target_mount": str(target_mount),
        "dest_root": dest_root,
        "dry_run": dry_run,
        "mirror": mirror,
        "copied_count": copied,
        "deleted_count": deleted,
        "missing_sources": missing,
        "synced_items": synced,
    }

    if not dry_run:
        dest_base.mkdir(parents=True, exist_ok=True)
        (dest_base / "_portable_sync_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    return manifest


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Sync launch/update CITL payload to exFAT/FAT/NTFS USB drives.")
    ap.add_argument("--target", action="append", default=[],
                    help="Explicit target mount path (repeat for multiple).")
    ap.add_argument("--item", action="append", default=[],
                    help="Extra repo-relative item to sync (file or directory).")
    ap.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    ap.add_argument("--mirror", action="store_true",
                    help="Delete stale files in target copies for synced directories.")
    ap.add_argument("--include-current-drive", action="store_true",
                    help="Allow syncing back onto the current source drive.")
    ap.add_argument("--dest-root", default=DEFAULT_DEST_ROOT,
                    help=f"Destination folder name on each target (default: {DEFAULT_DEST_ROOT}).")
    return ap.parse_args()


def main() -> int:
    ns = parse_args()

    if psutil is None and not ns.target:
        print("psutil is not available; pass --target <path> explicitly.")
        return 2

    targets: List[Path] = []
    for raw in ns.target:
        p = Path(raw)
        if p.exists():
            targets.append(p)
        else:
            print(f"[WARN] target does not exist: {p}")

    if not targets:
        targets = find_removable_targets(include_current_drive=ns.include_current_drive)

    if not targets:
        print("No writable removable exFAT/FAT/NTFS targets found.")
        return 1

    items = list(DEFAULT_ITEMS)
    if ns.item:
        items.extend(ns.item)

    print(f"Source: {ROOT}")
    print(f"Targets: {', '.join(str(t) for t in targets)}")
    print(f"Items: {len(items)}  |  dry_run={ns.dry_run}  mirror={ns.mirror}")

    failures = 0
    for t in targets:
        try:
            m = sync_items_to_target(
                t, items=items, dry_run=ns.dry_run,
                mirror=ns.mirror, dest_root=ns.dest_root
            )
            print(
                f"[OK] {t} -> {m['dest_root']}  "
                f"copied={m['copied_count']} deleted={m['deleted_count']} "
                f"missing={len(m['missing_sources'])}"
            )
        except Exception as e:
            failures += 1
            print(f"[FAIL] {t}: {e}")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
