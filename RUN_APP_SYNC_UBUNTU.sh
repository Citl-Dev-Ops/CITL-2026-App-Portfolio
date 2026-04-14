#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""

pick() {
  local p="$1"
  if [ -f "$p/RUN_APP_SYNC.sh" ]; then
    TARGET="$p"
    return 0
  fi
  return 1
}

pick "$ROOT" || true
pick "$ROOT/CITL_FACTBOOK_UBUNTU" || true
pick "$ROOT/CITL" || true
pick "$ROOT/PORTABLE_APPS/CITL" || true

if [ -z "$TARGET" ]; then
  for d in "$ROOT"/*; do
    [ -d "$d" ] || continue
    if pick "$d"; then
      break
    fi
  done
fi

if [ -n "$TARGET" ]; then
  exec bash "$TARGET/RUN_APP_SYNC.sh" "$@"
fi

if [ -f "$ROOT/factbook-assistant/citl_app_sync.py" ]; then
  if command -v python3 >/dev/null 2>&1; then
    exec python3 "$ROOT/factbook-assistant/citl_app_sync.py" "$@"
  elif command -v python >/dev/null 2>&1; then
    exec python "$ROOT/factbook-assistant/citl_app_sync.py" "$@"
  else
    echo "Python not found. Install python3 or add python to PATH."
    exit 1
  fi
fi

echo "Could not find RUN_APP_SYNC.sh or factbook-assistant/citl_app_sync.py under: $ROOT"
exit 1
