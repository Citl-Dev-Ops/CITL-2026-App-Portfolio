#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="$HERE/factbook-assistant/citl_field_apps.py"
if [[ ! -e "$TARGET" ]]; then
  echo "CITL Field Apps: entry not found: $TARGET"
  exit 1
fi
if [[ -x "$HERE/.venv/bin/python3" ]]; then
  exec "$HERE/.venv/bin/python3" "$TARGET" "$@"
fi
if command -v python3 >/dev/null 2>&1; then exec python3 "$TARGET" "$@"; fi
exec python "$TARGET" "$@"
