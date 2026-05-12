#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXE_ONEDIR="$ROOT/dist/CITL Fixer/CITL Fixer"
EXE_ONEFILE="$ROOT/dist/CITL_Fixer"
SCRIPT="$ROOT/citl_fixer.py"

if [[ -x "$EXE_ONEDIR" ]]; then
  exec "$EXE_ONEDIR" "$@"
fi

if [[ -x "$EXE_ONEFILE" ]]; then
  exec "$EXE_ONEFILE" "$@"
fi

PY=""
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
fi

if [[ -z "$PY" ]]; then
  echo "ERROR: Python not found. Install Python 3.9+ first."
  exit 1
fi

if [[ ! -f "$SCRIPT" ]]; then
  echo "ERROR: Fixer script not found: $SCRIPT"
  exit 1
fi

exec "$PY" "$SCRIPT" "$@"
