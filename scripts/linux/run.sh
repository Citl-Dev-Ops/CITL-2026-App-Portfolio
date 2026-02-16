#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"
if [[ "${1:-}" == "--portable" ]]; then
  export CITL_PORTABLE=1
fi
source .venv/bin/activate
GUI="$REPO_DIR/factbook-assistant/factbook_assistant_gui.py"
if [[ ! -f "$GUI" ]]; then
  GUI="$REPO_DIR/factbook_assistant_gui.py"
fi
echo "Launching GUI: $GUI"
python "$GUI"
