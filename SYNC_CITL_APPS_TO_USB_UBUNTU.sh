#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$ROOT/factbook-assistant/citl_app_sync.py"

if [[ ! -f "$SCRIPT" ]]; then
  echo "Missing sync utility: $SCRIPT"
  exit 1
fi

ARGS=(--source "$ROOT")
if [[ $# -eq 0 ]]; then
  ARGS+=(--sync-best-usb)
else
  ARGS+=("$@")
fi

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  exec "$ROOT/.venv/bin/python" "$SCRIPT" "${ARGS[@]}"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$SCRIPT" "${ARGS[@]}"
fi

if command -v python >/dev/null 2>&1; then
  exec python "$SCRIPT" "${ARGS[@]}"
fi

echo "Python is not available. Install python3 first."
exit 1
