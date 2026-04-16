#!/usr/bin/env bash
# CITL FLEX Troubleshooter v1.0 — Linux/macOS launcher
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXE="$ROOT/dist/CITL-FLEX-Troubleshooter"
SCRIPT="$ROOT/citl_flex_troubleshooter/flex_troubleshooter_gui.py"

# Try built EXE first
if [[ -f "$EXE" ]]; then
    "$EXE" "$@"
    exit $?
fi

# Find Python
PY=""
if [[ -f "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"
elif command -v python3 &>/dev/null; then PY="python3"
elif command -v python &>/dev/null; then PY="python"
fi
if [[ -z "$PY" ]]; then
    echo "ERROR: Python not found. Install Python 3.9+ or run the bootstrap script."
    exit 1
fi

"$PY" "$SCRIPT" "$@"