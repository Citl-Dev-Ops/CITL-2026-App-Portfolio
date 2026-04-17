#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  CITL Factbook Pipeline Diagnostic — Linux/macOS USB Launcher
#  Usage:
#    bash diagnose_factbook.sh         # GUI mode
#    bash diagnose_factbook.sh --cli   # CLI mode
#    bash diagnose_factbook.sh --fix   # CLI + auto-fix
# ═══════════════════════════════════════════════════════════════
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIAG="$ROOT/factbook-assistant/citl_factbook_diagnostic.py"
export PYTHONPATH="$ROOT/factbook-assistant:${PYTHONPATH:-}"

# Find Python
PY=""
if [[ -f "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"
elif command -v python3 &>/dev/null; then PY="python3"
elif command -v python  &>/dev/null; then PY="python"
fi

if [[ -z "$PY" ]]; then
    echo "ERROR: Python not found."
    echo "Install: sudo apt install python3 python3-tk"
    exit 1
fi

if [[ ! -f "$DIAG" ]]; then
    echo "ERROR: Diagnostic script not found: $DIAG"
    exit 1
fi

"$PY" "$DIAG" "$@"
