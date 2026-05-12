#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SYNC_PY="$REPO/factbook-assistant/citl_app_sync.py"
PKG="$REPO/bootstrap/patches/citl_bootstrap_M_20260430T004242Z_a4e6a399.zip"
ARGS=(--bootstrap-install-package "$PKG" --bootstrap-install-target local)
if [[ "${1:-}" == "--also-usb" ]]; then
  ARGS+=(--bootstrap-install-usb-if-found)
  shift
fi
ARGS+=("$@")
if [[ ! -f "$SYNC_PY" ]]; then echo "Missing: $SYNC_PY"; exit 1; fi
if [[ ! -f "$PKG" ]]; then echo "Missing: $PKG"; exit 1; fi
if [[ -x "$REPO/.venv/bin/python3" ]]; then exec "$REPO/.venv/bin/python3" "$SYNC_PY" "${ARGS[@]}"; fi
if command -v python3 >/dev/null 2>&1; then exec python3 "$SYNC_PY" "${ARGS[@]}"; fi
exec python "$SYNC_PY" "${ARGS[@]}"
