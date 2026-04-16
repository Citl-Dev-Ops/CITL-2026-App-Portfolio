#!/usr/bin/env python3
"""
CITL FLEX Troubleshooter — Modular EXE Builder
═══════════════════════════════════════════════
Builds one or more standalone EXEs from the FLEX troubleshooter using PyInstaller.

Targets (use --target to select one or more, or 'all'):
  full          Full app — all tabs (default)
  query         Ask / RAG query only
  diagnostics   IT Diagnostics only
  ticket        Ticket Writer only
  indexer       Index Builder only

Usage:
  python build_flex_exe.py                        # build full app
  python build_flex_exe.py --target query         # build query EXE only
  python build_flex_exe.py --target all           # build all 5 EXEs
  python build_flex_exe.py --target query ticket  # build two specific EXEs
"""
from __future__ import annotations
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE      = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
FA_DIR    = REPO_ROOT / "factbook-assistant"
DATA_DIR  = HERE / "data"
CORPUS    = HERE / "flex_embeddings.json"
MODFILE   = HERE / "Modelfile"
GUI       = HERE / "flex_troubleshooter_gui.py"

# ── Target definitions ────────────────────────────────────────────────────────
TARGETS = {
    "full": {
        "name":       "CITL-FLEX-Troubleshooter",
        "entry":      GUI,
        "entry_fn":   "main",
        "icon":       None,
        "description": "Full FLEX Troubleshooter — all tabs",
    },
    "query": {
        "name":       "FLEX-Ask",
        "entry":      GUI,
        "entry_fn":   "run_query_only",
        "icon":       None,
        "description": "Ask / RAG query mini-app",
    },
    "diagnostics": {
        "name":       "FLEX-IT-Diagnostics",
        "entry":      GUI,
        "entry_fn":   "run_diagnostics_only",
        "icon":       None,
        "description": "IT Diagnostics mini-app",
    },
    "ticket": {
        "name":       "FLEX-Ticket-Writer",
        "entry":      GUI,
        "entry_fn":   "run_ticket_only",
        "icon":       None,
        "description": "Ticket Writer mini-app",
    },
    "indexer": {
        "name":       "FLEX-Index-Builder",
        "entry":      GUI,
        "entry_fn":   "run_index_builder_only",
        "icon":       None,
        "description": "Index Builder mini-app",
    },
}


def _find_pi() -> str:
    pi = shutil.which("pyinstaller")
    if not pi:
        raise SystemExit(
            "PyInstaller not found on PATH.\n"
            "Install it: pip install pyinstaller")
    return pi


def _write_entry_shim(target: dict, shim_path: Path) -> None:
    """Write a tiny shim that calls the correct entry function."""
    fn = target["entry_fn"]
    shim_path.write_text(
        f"# Auto-generated entry shim — do not edit\n"
        f"import sys\n"
        f"from pathlib import Path\n"
        f"sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
        f"from flex_troubleshooter_gui import {fn}\n"
        f"{fn}()\n",
        encoding="utf-8",
    )


def _build_target(key: str, extra_resources: list[Path]) -> bool:
    t   = TARGETS[key]
    pi  = _find_pi()
    shim = HERE / f"_entry_{key}.py"
    _write_entry_shim(t, shim)

    add_data = []
    sep = ";" if sys.platform == "win32" else ":"

    def _add(p: Path, dest: str = "."):
        if p.exists():
            add_data.append(f"{p}{sep}{dest}")

    _add(MODFILE)
    _add(CORPUS)
    # Bundle the factbook-assistant modules so RAG works in the EXE
    for mod in [
        FA_DIR / "citl_theme.py",
        FA_DIR / "citl_modelfile.py",
        FA_DIR / "citl_translation.py",
        FA_DIR / "citl_corpus_health.py",
        FA_DIR / "citl_auto_index.py",
    ]:
        _add(mod)

    # Extra user-supplied resources
    for r in extra_resources:
        _add(Path(r))

    # Hidden imports needed for RAG
    hidden = [
        "numpy", "numpy.core", "requests",
        "citl_theme", "citl_modelfile",
    ]

    cmd = [
        pi, "--onefile", "--noconsole",
        "--name", t["name"],
        "--distpath", str(HERE / "dist"),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE / "build"),
    ]
    for ad in add_data:
        cmd += ["--add-data", ad]
    for hi in hidden:
        cmd += ["--hidden-import", hi]
    if t.get("icon") and Path(t["icon"]).exists():
        cmd += ["--icon", t["icon"]]
    cmd.append(str(shim))

    print(f"\n{'═'*60}")
    print(f"Building: {t['name']}  ({t['description']})")
    print(f"{'═'*60}")
    result = subprocess.run(cmd)

    # Clean up shim
    try:
        shim.unlink()
    except Exception:
        pass

    ok = result.returncode == 0
    if ok:
        exe = HERE / "dist" / (t["name"] + (".exe" if sys.platform == "win32" else ""))
        if exe.exists():
            size_mb = exe.stat().st_size / 1_048_576
            print(f"[OK] {exe}  ({size_mb:.1f} MB)")
        else:
            print(f"[OK] Build complete — check dist/ folder.")
    else:
        print(f"[FAIL] Build failed for {t['name']}")
    return ok


def main():
    ap = argparse.ArgumentParser(
        description="Build CITL FLEX Troubleshooter EXE(s)")
    ap.add_argument(
        "--target", nargs="+", default=["full"],
        metavar="TARGET",
        help=(f"Target(s) to build: {', '.join(TARGETS)} — or 'all'"))
    ap.add_argument(
        "--resource", action="append", default=[],
        metavar="FILE",
        help="Extra file(s) to bundle into all EXEs")
    args = ap.parse_args()

    targets = list(TARGETS.keys()) if "all" in args.target else args.target
    invalid = [t for t in targets if t not in TARGETS]
    if invalid:
        ap.error(f"Unknown target(s): {invalid}. Choose from: {list(TARGETS)}")

    extras = [Path(r) for r in args.resource]
    results = {}
    for key in targets:
        results[key] = _build_target(key, extras)

    print(f"\n{'─'*60}")
    print("Build summary:")
    for key, ok in results.items():
        status = "OK      " if ok else "FAILED  "
        print(f"  {status} {TARGETS[key]['name']}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
