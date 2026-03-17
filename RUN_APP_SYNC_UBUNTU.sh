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

if [ -z "$TARGET" ]; then
  echo "Could not find RUN_APP_SYNC.sh under: $ROOT"
  exit 1
fi

exec bash "$TARGET/RUN_APP_SYNC.sh" "$@"
