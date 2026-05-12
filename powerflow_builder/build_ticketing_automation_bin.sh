#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENTRY="$ROOT/powerflow_builder/citl_work_ticketing_gui.py"
DIST="$ROOT/powerflow_builder/dist"
WORK="$ROOT/powerflow_builder/build"
NAME="citl_ticketing_automation_gui"

if [ -x "$ROOT/.venv/bin/python3" ]; then
  PY="$ROOT/.venv/bin/python3"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi

if [ ! -f "$ENTRY" ]; then
  echo "Entry script not found: $ENTRY"
  exit 1
fi

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
  "$ENTRY"

OUT="$DIST/$NAME/$NAME"
if [ -f "$OUT" ]; then
  echo "Build complete: $OUT"
else
  echo "Build finished, but binary not found at expected path: $OUT"
fi
