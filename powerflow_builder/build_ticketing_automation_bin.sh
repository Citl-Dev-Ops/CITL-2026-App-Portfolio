#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_ticketing_automation_bin.sh  —  Ubuntu/Linux binary build
# CITL Ticketing & Automation Utility
# Renton Technical College — CITL
#
# Usage:
#   bash build_ticketing_automation_bin.sh [--clean] [--test]
#   --clean : wipe previous build/ and dist/ first
#   --test  : launch the resulting binary after build to verify startup
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENTRY="$ROOT/powerflow_builder/citl_work_ticketing_gui.py"
DIST="$ROOT/powerflow_builder/dist"
WORK="$ROOT/powerflow_builder/build"
NAME="citl_ticketing_automation_gui"
CLEAN=false
TEST_RUN=false

for arg in "$@"; do
    case "${arg}" in --clean) CLEAN=true;; --test) TEST_RUN=true;; esac
done

# ── Locate Python ─────────────────────────────────────────────────────────────
for candidate in \
    "$ROOT/.venv/bin/python3" \
    "$ROOT/.venv/bin/python" \
    "$(which python3 2>/dev/null || true)" \
    "$(which python 2>/dev/null || true)"; do
    if [[ -x "${candidate}" ]]; then
        PY="${candidate}"
        break
    fi
done
PY="${PY:-python3}"
echo "[BUILD] Python: $PY  ($($PY --version 2>&1))"

[[ -f "$ENTRY" ]] || { echo "[ERROR] Entry not found: $ENTRY"; exit 1; }

# ── Ensure PyInstaller ────────────────────────────────────────────────────────
if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
    echo "[BUILD] Installing PyInstaller..."
    "$PY" -m pip install --quiet pyinstaller
fi

# ── Ensure tkinter available ──────────────────────────────────────────────────
if ! "$PY" -c "import tkinter" 2>/dev/null; then
    echo "[BUILD] tkinter missing — trying apt..."
    sudo apt-get install -y python3-tk 2>/dev/null || \
        echo "[WARN] Could not install tkinter via apt — binary may not start GUI."
fi

# ── Clean ─────────────────────────────────────────────────────────────────────
if ${CLEAN}; then
    echo "[BUILD] Cleaning previous build artifacts..."
    rm -rf "$DIST/$NAME" "$WORK/$NAME"
fi

# ── Build ─────────────────────────────────────────────────────────────────────
echo "[BUILD] Building $NAME..."
"$PY" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --name "$NAME" \
    --distpath "$DIST" \
    --workpath "$WORK" \
    --hidden-import tkinter \
    --hidden-import tkinter.ttk \
    --hidden-import tkinter.scrolledtext \
    --hidden-import tkinter.messagebox \
    --hidden-import tkinter.filedialog \
    --hidden-import tkinter.simpledialog \
    --hidden-import sqlite3 \
    --hidden-import json \
    --hidden-import urllib.request \
    --hidden-import urllib.error \
    --hidden-import hashlib \
    --hidden-import threading \
    --hidden-import subprocess \
    --hidden-import platform \
    --hidden-import pathlib \
    --hidden-import datetime \
    --hidden-import re \
    --collect-submodules tkinter \
    "$ENTRY"

OUT="$DIST/$NAME/$NAME"
if [[ -f "$OUT" ]]; then
    chmod +x "$OUT"
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║  BUILD COMPLETE                                               ║"
    echo "╠═══════════════════════════════════════════════════════════════╣"
    echo "║  Binary : $OUT"
    echo "║  Size   : $(du -sh "$OUT" | cut -f1)"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "To install a desktop launcher, run:"
    echo "  bash $ROOT/CITL-REIMAGER/install_gui_launchers.sh"
    echo ""
    if ${TEST_RUN}; then
        echo "[BUILD] Launching test run (close window to finish)..."
        "$OUT" &
        sleep 3
        if kill -0 $! 2>/dev/null; then
            echo "[BUILD] Binary launched successfully."
            wait $! 2>/dev/null || true
        else
            echo "[WARN] Binary exited quickly — check for missing dependencies."
            exit 1
        fi
    fi
else
    echo "[ERROR] Build finished but binary not found at: $OUT"
    echo "        Check build log in: $WORK"
    exit 1
fi
