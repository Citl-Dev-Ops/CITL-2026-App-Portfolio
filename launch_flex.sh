#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
#  CITL FLEX Troubleshooter — USB/Linux/macOS Launcher
# ═══════════════════════════════════════════════════════
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP="$ROOT/citl_bootstrap.py"
EXE="$ROOT/dist/CITL-FLEX-Troubleshooter"

if [[ -f "$EXE" ]]; then
    "$EXE" "$@"
    exit $?
fi

PY=""
if [[ -f "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"
elif command -v python3 &>/dev/null; then PY="python3"
elif command -v python  &>/dev/null; then PY="python"
fi

if [[ -z "$PY" ]]; then
    echo "ERROR: Python not found. Install Python 3.9+."
    exit 1
fi

"$PY" "$BOOTSTRAP" --app flex "$@"
