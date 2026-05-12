#!/usr/bin/env python3
"""
CITL USB Repair Cloner
======================
Offline-first Windows tool to diagnose, clone, image, restore, and repair
CITL Sync USB drives so they remain launchable.

This script is designed to run from:
  - repository root
  - scripts/windows/
  - a copied USB toolkit folder
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import string
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


TOOL_NAME = "CITL USB Repair Cloner"
TIME_FMT = "%Y%m%d_%H%M%S"

# Repo/USB markers that identify a CITL suite root.
CITL_MARKERS = (
    "factbook-assistant/citl_app_sync.py",
    "START_CITL_WINDOWS.cmd",
    "RUN_APP_SYNC_WINDOWS.cmd",
    "1-CITL-SYNC",
)

# Files we always try to keep up to date on a launchable target.
LAUNCHER_REL_FILES = (
    "START_CITL_WINDOWS.cmd",
    "RUN_APP_SYNC_WINDOWS.cmd",
    "INSTALL_CITL_APPS_PORTABLE.cmd",
    "SYNC_EXES_TO_USB_WINDOWS.cmd",
    "RUN_CITL_USB_REPAIR_CLONER_WINDOWS.cmd",
    "BUILD_CITL_USB_REPAIR_CLONER_WINDOWS.cmd",
    "CITL App Sync.cmd",
    "CITL Sync Hub.cmd",
    "scripts/windows/install_citl_apps_portable.ps1",
    "scripts/windows/sync_usb_apps.ps1",
    "scripts/windows/citl_usb_repair_clone.py",
)

# Dist bundle mapping used to keep numbered USB folders launchable.
APP_BUNDLES = (
    {
        "source_rel": "dist/CITL App Sync",
        "exe": "CITL App Sync.exe",
        "target_rel": "1-CITL-SYNC/CITL App Sync",
    },
    {
        "source_rel": "dist/CITL LLMOps Presentation Suite",
        "exe": "CITL LLMOps Presentation Suite.exe",
        "target_rel": "2-CITL-PRESENTATION-SUITE/CITL LLMOps Presentation Suite",
    },
    {
        "source_rel": "dist/CITL Workstation Apps",
        "exe": "CITL Workstation Apps.exe",
        "target_rel": "3-CITL-WORKSTATION-APPS/CITL Workstation Apps",
    },
    {
        "source_rel": "dist/CITL Field Apps",
        "exe": "CITL Field Apps.exe",
        "target_rel": "4-CITL-FIELD-APPS/CITL Field Apps",
    },
    {
        "source_rel": "powerflow_builder/dist/CITL Ticketing Automation GUI",
        "exe": "CITL Ticketing Automation GUI.exe",
        "target_rel": "6-CITL-WORK-TICKETING/CITL Ticketing Automation GUI",
    },
)

CRITICAL_LAUNCH_PATHS = (
    "START_CITL_WINDOWS.cmd",
    "RUN_APP_SYNC_WINDOWS.cmd",
    "scripts/windows/install_citl_apps_portable.ps1",
)

ENTRY_EXE_ALTERNATES = (
    "1-CITL-SYNC/CITL Sync Hub/CITL Sync Hub.exe",
    "1-CITL-SYNC/CITL App Sync/CITL App Sync.exe",
)

ROBO_EXCLUDE_DIRS = (
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".edge_headless_tmp",
    "_pycache_tmp",
    "tmp_decomp",
)

ROBO_EXCLUDE_FILES = (
    "*.pyc",
    "*.pyo",
    "*.tmp",
)

DEFAULT_USB_DRIVE_HINTS = ("F", "K")


def now_utc_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def info(msg: str) -> None:
    print(f"[....] {msg}")


def ok(msg: str) -> None:
    print(f"[ OK ] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def header(title: str) -> None:
    print("")
    print("=" * 72)
    print(f"{TOOL_NAME}  |  {title}")
    print("=" * 72)


def _normalize(path: Path) -> str:
    try:
        return str(path.resolve()).rstrip("\\/").lower()
    except OSError:
        return str(path).rstrip("\\/").lower()


def preferred_usb_letters() -> tuple[str, ...]:
    raw = os.environ.get("CITL_USB_DRIVE_HINT", "").strip()
    if not raw:
        return DEFAULT_USB_DRIVE_HINTS
    picks: list[str] = []
    for part in raw.replace(";", ",").split(","):
        token = part.strip().upper().replace(":", "")
        if len(token) == 1 and token in string.ascii_uppercase and token not in picks:
            picks.append(token)
    return tuple(picks) if picks else DEFAULT_USB_DRIVE_HINTS


def is_citl_root(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return any((path / rel).exists() for rel in CITL_MARKERS)


def default_repo_candidates() -> list[Path]:
    cands: list[Path] = []
    script = Path(__file__).resolve()
    cwd = Path.cwd()
    env_repo = os.environ.get("CITL_REPO", "").strip()
    home = Path.home()

    cands.extend(
        [
            cwd,
            script.parent,
            script.parent.parent,
            script.parent.parent.parent,
            home / "CITL",
            home / "Documents" / "CITL",
            home / "Desktop" / "CITL",
            Path("C:/00 HENOSIS CODING PROJECTS/CITL PROJECTS/CITL"),
        ]
    )
    if env_repo:
        cands.insert(0, Path(env_repo))

    out: list[Path] = []
    seen: set[str] = set()
    for p in cands:
        key = _normalize(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def resolve_source_root(source: str) -> Path:
    if source and source.strip().lower() != "auto":
        p = Path(source).expanduser()
        if p.exists() and p.is_dir():
            return p.resolve()
        raise RuntimeError(f"Source path not found: {source}")

    for cand in default_repo_candidates():
        if is_citl_root(cand):
            return cand.resolve()

    raise RuntimeError(
        "Could not auto-detect CITL source root. Pass --source <path>."
    )


def _parse_json_any(raw: str) -> Any:
    if not raw.strip():
        return []
    obj = json.loads(raw)
    if isinstance(obj, list):
        return obj
    return [obj]


def query_logical_disks() -> list[dict[str, Any]]:
    ps = (
        "Get-CimInstance Win32_LogicalDisk | "
        "Select-Object DeviceID,DriveType,FileSystem,VolumeName,FreeSpace,Size | "
        "ConvertTo-Json -Depth 3"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            return []
        return _parse_json_any(proc.stdout or "")
    except OSError:
        return []


def _drive_letters() -> list[str]:
    letters: list[str] = []
    for d in string.ascii_uppercase:
        root = Path(f"{d}:/")
        if root.exists():
            letters.append(d)
    return letters


def test_write_access(root: Path) -> tuple[bool, str]:
    probe = root / f".citl_probe_{uuid.uuid4().hex}.tmp"
    try:
        probe.write_text("citl-probe\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, "ok"
    except OSError as ex:
        return False, str(ex)


def path_summary(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        free_gb = round(usage.free / (1024**3), 2)
        size_gb = round(usage.total / (1024**3), 2)
    except OSError:
        free_gb = 0.0
        size_gb = 0.0

    markers_found = [rel for rel in CITL_MARKERS if (path / rel).exists()]
    writable, write_msg = test_write_access(path)

    return {
        "path": str(path),
        "markers_found": markers_found,
        "writable": writable,
        "write_test": write_msg,
        "free_gb": free_gb,
        "size_gb": size_gb,
    }


def discover_targets() -> list[dict[str, Any]]:
    disks = query_logical_disks()
    disk_by_letter: dict[str, dict[str, Any]] = {}
    for d in disks:
        dev = str(d.get("DeviceID", "")).strip().upper()
        if len(dev) >= 2 and dev[1] == ":":
            disk_by_letter[dev[0]] = d

    targets: list[dict[str, Any]] = []
    hints = set(preferred_usb_letters())
    for letter in _drive_letters():
        root = Path(f"{letter}:/")
        meta = path_summary(root)
        logical = disk_by_letter.get(letter, {})
        drive_type = int(logical.get("DriveType", 0) or 0)
        fs = str(logical.get("FileSystem", "") or "").strip()
        vol = str(logical.get("VolumeName", "") or "").strip()

        score = 0
        if drive_type == 2:
            score += 80  # removable
            if letter in hints:
                score += 500  # operator-declared preferred USB letter(s)
        if meta["markers_found"]:
            score += 140
        if (root / "factbook-assistant" / "citl_app_sync.py").exists():
            score += 120
        if (root / "1-CITL-SYNC").exists():
            score += 100
        if (root / "START_CITL_WINDOWS.cmd").exists():
            score += 60
        if fs.upper() in {"EXFAT", "NTFS"}:
            score += 30
        else:
            score -= 50
        if not meta["writable"]:
            score -= 180
        if meta["free_gb"] < 4:
            score -= 30

        targets.append(
            {
                "path": str(root),
                "device_id": f"{letter}:",
                "drive_type": drive_type,
                "file_system": fs,
                "volume_name": vol,
                "score": score,
                **meta,
            }
        )

    targets.sort(key=lambda x: x.get("score", 0), reverse=True)
    return targets


def select_best_target(candidates: list[dict[str, Any]]) -> Path | None:
    preferred = set(preferred_usb_letters())
    removable: list[dict[str, Any]] = []
    fixed_marked: list[dict[str, Any]] = []

    for c in candidates:
        if c.get("score", -9999) < 0:
            continue
        if not c.get("writable", False):
            continue
        has_markers = bool(c.get("markers_found"))
        drive_type = int(c.get("drive_type", 0) or 0)
        if drive_type == 2:
            removable.append(c)
            continue
        if has_markers:
            fixed_marked.append(c)

    if removable:
        removable.sort(
            key=lambda c: (
                str(c.get("device_id", "")).strip().upper().replace(":", "") in preferred,
                int(c.get("score", 0) or 0),
            ),
            reverse=True,
        )
        return Path(removable[0]["path"]).resolve()

    # Final fallback: allow fixed drives only when clearly CITL-marked.
    if fixed_marked:
        fixed_marked.sort(key=lambda c: int(c.get("score", 0) or 0), reverse=True)
        return Path(fixed_marked[0]["path"]).resolve()
    return None


def run_robocopy(
    src: Path,
    dst: Path,
    *,
    mirror: bool = True,
    dry_run: bool = False,
    exclude_dirs: tuple[str, ...] = ROBO_EXCLUDE_DIRS,
    exclude_files: tuple[str, ...] = ROBO_EXCLUDE_FILES,
) -> tuple[bool, int]:
    if not src.exists():
        fail(f"Source missing: {src}")
        return False, 16

    dst.mkdir(parents=True, exist_ok=True)
    cmd = [
        "robocopy",
        str(src),
        str(dst),
        "/MIR" if mirror else "/E",
        "/Z",
        "/R:2",
        "/W:1",
        "/FFT",
        "/XJ",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP",
        "/MT:8",
    ]
    if exclude_dirs:
        cmd += ["/XD", *exclude_dirs]
    if exclude_files:
        cmd += ["/XF", *exclude_files]
    if dry_run:
        cmd.append("/L")

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    rc = int(proc.returncode)
    if rc <= 7:
        ok(f"robocopy ok ({rc}) :: {src} -> {dst}")
        return True, rc

    fail(f"robocopy failed ({rc}) :: {src} -> {dst}")
    if proc.stdout:
        warn("robocopy stdout (tail):")
        print("\n".join(proc.stdout.splitlines()[-12:]))
    if proc.stderr:
        warn("robocopy stderr (tail):")
        print("\n".join(proc.stderr.splitlines()[-12:]))
    return False, rc


def ensure_instance_id(target_root: Path, dry_run: bool) -> None:
    instance_path = target_root / "citl_instance.json"
    if instance_path.exists():
        return
    payload = {
        "instance_id": f"CITL-{uuid.uuid4().hex[:8].upper()}",
        "type": "USB",
        "created": now_utc_iso(),
        "path": str(target_root),
    }
    if dry_run:
        info(f"[DRY RUN] would create {instance_path}")
        return
    instance_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    ok(f"created instance id: {instance_path}")


def copy_launcher_files(source_root: Path, target_root: Path, dry_run: bool) -> None:
    for rel in LAUNCHER_REL_FILES:
        src = source_root / rel
        dst = target_root / rel
        if not src.exists():
            continue
        if dry_run:
            info(f"[DRY RUN] launcher sync: {src} -> {dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
            ok(f"launcher sync: {rel}")
        except OSError as ex:
            warn(f"launcher sync failed ({rel}): {ex}")


def sync_exe_bundles(source_root: Path, target_root: Path, dry_run: bool) -> None:
    info("syncing EXE bundles to numbered USB folders...")
    for bundle in APP_BUNDLES:
        src = source_root / bundle["source_rel"]
        exe = src / bundle["exe"]
        dst = target_root / bundle["target_rel"]
        if not exe.exists():
            warn(f"bundle missing exe; skipped: {exe}")
            continue
        run_robocopy(
            src,
            dst,
            mirror=True,
            dry_run=dry_run,
            exclude_dirs=(),
            exclude_files=(),
        )


def verify_launchable(target_root: Path) -> dict[str, Any]:
    missing = [rel for rel in CRITICAL_LAUNCH_PATHS if not (target_root / rel).exists()]
    entry_hits = [rel for rel in ENTRY_EXE_ALTERNATES if (target_root / rel).exists()]
    has_entry_exe = len(entry_hits) > 0
    if not has_entry_exe:
        missing.append(
            "1-CITL-SYNC/CITL Sync Hub/CITL Sync Hub.exe OR 1-CITL-SYNC/CITL App Sync/CITL App Sync.exe"
        )
    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "entry_exe_found": entry_hits,
        "checked_at_utc": now_utc_iso(),
    }


def write_report(target_root: Path, report: dict[str, Any], *, dry_run: bool) -> None:
    logs_dir = target_root / "logs"
    stamp = dt.datetime.now().strftime(TIME_FMT)
    out = logs_dir / f"citl_usb_repair_report_{stamp}.json"
    if dry_run:
        info(f"[DRY RUN] would write report: {out}")
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    ok(f"report written: {out}")


def clone_suite(
    source_root: Path,
    target_root: Path,
    *,
    dry_run: bool = False,
    mirror: bool = True,
) -> dict[str, Any]:
    if _normalize(source_root) == _normalize(target_root):
        raise RuntimeError("Source and target are the same path; aborting.")

    header("Clone")
    info(f"source: {source_root}")
    info(f"target: {target_root}")

    writable, write_msg = test_write_access(target_root)
    if not writable and not dry_run:
        raise RuntimeError(f"Target is not writable: {target_root} :: {write_msg}")

    sync_ok, rc = run_robocopy(source_root, target_root, mirror=mirror, dry_run=dry_run)
    copy_launcher_files(source_root, target_root, dry_run=dry_run)
    sync_exe_bundles(source_root, target_root, dry_run=dry_run)
    ensure_instance_id(target_root, dry_run=dry_run)
    verify = verify_launchable(target_root)

    report = {
        "action": "clone",
        "source": str(source_root),
        "target": str(target_root),
        "robocopy_ok": sync_ok,
        "robocopy_exit": rc,
        "verify": verify,
        "timestamp_utc": now_utc_iso(),
        "dry_run": dry_run,
    }
    write_report(target_root, report, dry_run=dry_run)
    return report


def image_suite(
    source_root: Path,
    image_parent: Path,
    *,
    name: str = "",
    dry_run: bool = False,
    force: bool = False,
) -> Path:
    stamp = dt.datetime.now().strftime(TIME_FMT)
    image_name = name.strip() if name.strip() else f"CITL_USB_IMAGE_{stamp}"
    image_root = (image_parent / image_name).resolve()

    header("Image Capture")
    info(f"source: {source_root}")
    info(f"image : {image_root}")

    if image_root.exists() and not force:
        raise RuntimeError(f"Image path already exists: {image_root} (use --force)")
    if image_root.exists() and force and not dry_run:
        shutil.rmtree(image_root, ignore_errors=True)

    report = clone_suite(source_root, image_root, dry_run=dry_run, mirror=True)

    meta = {
        "tool": TOOL_NAME,
        "created_utc": now_utc_iso(),
        "source": str(source_root),
        "image_root": str(image_root),
        "clone_report": report,
        "critical_paths": list(CRITICAL_LAUNCH_PATHS),
    }
    meta_path = image_root / "citl_usb_image_manifest.json"
    if dry_run:
        info(f"[DRY RUN] would write image manifest: {meta_path}")
    else:
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        ok(f"image manifest written: {meta_path}")
    return image_root


def restore_image(
    image_root: Path,
    target_root: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if not image_root.exists() or not image_root.is_dir():
        raise RuntimeError(f"Image root missing: {image_root}")
    if not force:
        info("restore uses /MIR. Existing target files not in image will be removed.")
        info("pass --force to acknowledge destructive mirror behavior.")
        raise RuntimeError("Restore requires --force for safety.")
    return clone_suite(image_root, target_root, dry_run=dry_run, mirror=True)


def repair_target(target_root: Path, source_root: Path | None, *, dry_run: bool = False) -> dict[str, Any]:
    header("Repair")
    info(f"target: {target_root}")

    if source_root:
        info(f"source: {source_root}")
        copy_launcher_files(source_root, target_root, dry_run=dry_run)
        sync_exe_bundles(source_root, target_root, dry_run=dry_run)
    ensure_instance_id(target_root, dry_run=dry_run)
    verify = verify_launchable(target_root)
    report = {
        "action": "repair",
        "source": str(source_root) if source_root else "",
        "target": str(target_root),
        "verify": verify,
        "timestamp_utc": now_utc_iso(),
        "dry_run": dry_run,
    }
    write_report(target_root, report, dry_run=dry_run)
    return report


def parse_target_path(target_arg: str) -> Path:
    t = target_arg.strip()
    if not t or t.lower() == "auto":
        candidates = discover_targets()
        best = select_best_target(candidates)
        if not best:
            raise RuntimeError("No writable CITL-capable USB target found. Use --target <path>.")
        ok(f"auto target: {best}")
        return best
    p = Path(t).expanduser()
    if not p.exists():
        raise RuntimeError(f"Target path not found: {t}")
    return p.resolve()


def diagnose() -> int:
    header("Diagnose")
    targets = discover_targets()
    if not targets:
        fail("No mounted drives detected.")
        return 2

    print("Detected drives (highest score first):")
    for t in targets:
        print(
            f"  {t['device_id']:<3} score={t['score']:>4} "
            f"fs={t.get('file_system','') or '-':<6} "
            f"writable={'yes' if t.get('writable') else 'no '} "
            f"free={t.get('free_gb',0):>7} GB "
            f"vol={t.get('volume_name','') or '-'}"
        )
        if t.get("markers_found"):
            print(f"      markers: {', '.join(t['markers_found'])}")
        if not t.get("writable"):
            print(f"      write-test: {t.get('write_test')}")

    best = select_best_target(targets)
    if best:
        ok(f"best writable CITL target: {best}")
        return 0
    warn("No writable CITL target qualified.")
    return 1


def menu_mode(default_source: Path) -> int:
    header("Interactive Menu")
    print(f"Detected source: {default_source}")
    print("1) Diagnose drives")
    print("2) Clone source -> USB target")
    print("3) Capture image (source -> image folder)")
    print("4) Restore image -> USB target")
    print("5) Repair target launchability")
    print("0) Exit")
    choice = input("Select action [0-5]: ").strip()

    if choice == "0":
        return 0
    if choice == "1":
        return diagnose()
    if choice == "2":
        tgt = input("Target path (or 'auto'): ").strip() or "auto"
        target = parse_target_path(tgt)
        rep = clone_suite(default_source, target, dry_run=False, mirror=True)
        return 0 if rep["verify"]["ok"] else 1
    if choice == "3":
        parent = input("Image parent folder (blank=./images_usb): ").strip()
        image_parent = Path(parent).expanduser() if parent else (default_source / "images_usb")
        image_parent.mkdir(parents=True, exist_ok=True)
        image_root = image_suite(default_source, image_parent, dry_run=False, force=False)
        ok(f"image captured: {image_root}")
        return 0
    if choice == "4":
        img = input("Image folder path: ").strip()
        if not img:
            fail("image path is required")
            return 2
        tgt = input("Target path (or 'auto'): ").strip() or "auto"
        target = parse_target_path(tgt)
        rep = restore_image(Path(img).expanduser(), target, dry_run=False, force=True)
        return 0 if rep["verify"]["ok"] else 1
    if choice == "5":
        tgt = input("Target path (or 'auto'): ").strip() or "auto"
        target = parse_target_path(tgt)
        rep = repair_target(target, default_source, dry_run=False)
        return 0 if rep["verify"]["ok"] else 1

    warn("Unknown option.")
    return 2


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=TOOL_NAME)
    p.add_argument(
        "--action",
        choices=("menu", "diagnose", "clone", "image", "restore", "repair"),
        default="menu",
        help="Action to run. Default: menu.",
    )
    p.add_argument("--source", default="auto", help="Source CITL root path. Default: auto.")
    p.add_argument("--target", default="auto", help="Target USB/root path. Default: auto.")
    p.add_argument("--image-path", default="", help="Image folder path (restore) or parent folder (image).")
    p.add_argument("--image-name", default="", help="Optional image folder name for --action image.")
    p.add_argument("--dry-run", action="store_true", help="Preview operations without writing.")
    p.add_argument("--force", action="store_true", help="Allow overwrite/mirror destructive operations.")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        source_root = resolve_source_root(args.source)
    except RuntimeError as ex:
        fail(str(ex))
        return 2

    try:
        if args.action == "menu":
            return menu_mode(source_root)

        if args.action == "diagnose":
            return diagnose()

        if args.action == "clone":
            target = parse_target_path(args.target)
            rep = clone_suite(source_root, target, dry_run=args.dry_run, mirror=True)
            if args.dry_run:
                return 0
            return 0 if rep["verify"]["ok"] else 1

        if args.action == "image":
            image_parent = Path(args.image_path).expanduser() if args.image_path else (source_root / "images_usb")
            if not image_parent.exists() and not args.dry_run:
                image_parent.mkdir(parents=True, exist_ok=True)
            image_root = image_suite(
                source_root,
                image_parent,
                name=args.image_name,
                dry_run=args.dry_run,
                force=args.force,
            )
            ok(f"image ready: {image_root}")
            return 0

        if args.action == "restore":
            if not args.image_path.strip():
                raise RuntimeError("--image-path is required for restore.")
            target = parse_target_path(args.target)
            rep = restore_image(
                Path(args.image_path).expanduser(),
                target,
                dry_run=args.dry_run,
                force=args.force,
            )
            if args.dry_run:
                return 0
            return 0 if rep["verify"]["ok"] else 1

        if args.action == "repair":
            target = parse_target_path(args.target)
            rep = repair_target(target, source_root, dry_run=args.dry_run)
            if args.dry_run:
                return 0
            return 0 if rep["verify"]["ok"] else 1

    except RuntimeError as ex:
        fail(str(ex))
        return 2
    except Exception as ex:  # noqa: BLE001
        fail(f"Unexpected error: {ex}")
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
