#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT1="$DIR/factbook-assistant/citl_technical_writing_tutorial_creator.py"
SCRIPT2="$DIR/citl_technical_writing_tutorial_creator.py"

if [[ ! -d "$DIR/.venv" ]]; then
  echo "venv not found - running setup first..."
  if [[ -f "$DIR/scripts/linux/setup.sh" ]]; then
    bash "$DIR/scripts/linux/setup.sh"
  else
    echo "ERROR: Cannot find scripts/linux/setup.sh"
    exit 1
  fi
fi

source "$DIR/.venv/bin/activate"

SCRIPT=""
if [[ -f "$SCRIPT1" ]]; then
  SCRIPT="$SCRIPT1"
elif [[ -f "$SCRIPT2" ]]; then
  SCRIPT="$SCRIPT2"
fi

if [[ -z "$SCRIPT" ]]; then
  echo "ERROR: Cannot find citl_technical_writing_tutorial_creator.py"
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$SCRIPT"
else
  exec python "$SCRIPT"
fi
