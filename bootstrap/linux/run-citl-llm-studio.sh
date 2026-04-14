#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="$HERE/CITL-LLM-Studio-Kit/app/llm_studio_gui.py"
if [[ ! -e "$TARGET" ]]; then
  echo "CITL LLM Studio: entry not found: $TARGET"
  exit 1
fi
if [[ -x "$HERE/.venv/bin/python3" ]]; then
  exec "$HERE/.venv/bin/python3" "$TARGET" "$@"
fi
if command -v python3 >/dev/null 2>&1; then exec python3 "$TARGET" "$@"; fi
exec python "$TARGET" "$@"
