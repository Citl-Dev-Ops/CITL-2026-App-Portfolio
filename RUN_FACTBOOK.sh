#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Auto-setup if venv is missing
if [[ ! -d "$DIR/.venv" ]]; then
  echo "venv not found - running setup first..."
  if [[ -f "$DIR/scripts/linux/setup.sh" ]]; then
    bash "$DIR/scripts/linux/setup.sh"
  else
    echo "ERROR: Cannot find scripts/linux/setup.sh - please run setup manually."
    exit 1
  fi
fi

source "$DIR/.venv/bin/activate"

# Prefer the root launcher if present
if [ -f "$DIR/factbook_assistant_gui.py" ]; then
  python "$DIR/factbook_assistant_gui.py"
elif [ -f "$DIR/factbook-assistant/factbook_assistant_gui.py" ]; then
  python "$DIR/factbook-assistant/factbook_assistant_gui.py"
else
  echo "Could not find factbook_assistant_gui.py"
  echo "Look in $DIR and $DIR/factbook-assistant/"
  exit 1
fi
