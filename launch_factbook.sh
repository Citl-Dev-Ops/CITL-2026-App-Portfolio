#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
#  CITL Factbook Assistant — USB/Linux/macOS Launcher
#  Runs bootstrap first; shows dialog/CLI if any issues
# ═══════════════════════════════════════════════════════
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP="$ROOT/citl_bootstrap.py"
EXE="$ROOT/dist/CITL-Factbook-Assistant"

# Try pre-built EXE
if [[ -f "$EXE" ]]; then
    "$EXE" "$@"
    exit $?
fi

# Find Python
PY=""
if [[ -f "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"
elif command -v python3 &>/dev/null; then PY="python3"
elif command -v python  &>/dev/null; then PY="python"
fi

if [[ -z "$PY" ]]; then
    if command -v zenity &>/dev/null; then
        zenity --error --text="Python 3.9+ is required.\nInstall it with:\n  sudo apt install python3" 2>/dev/null || true
    fi
    echo "ERROR: Python not found. Install Python 3.9+."
    exit 1
fi

# Ensure deps are available, then launch bootstrap
"$PY" "$BOOTSTRAP" --app factbook "$@"
