#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT1="$DIR/factbook-assistant/citl_llmops_suite.py"
SCRIPT2="$DIR/citl_llmops_suite.py"

# Auto-setup if venv is missing
if [[ ! -d "$DIR/.venv" ]]; then
  echo "venv not found - running setup first..."
  if [[ -f "$DIR/scripts/linux/setup.sh" ]]; then
    bash "$DIR/scripts/linux/setup.sh"
  else
    echo "ERROR: Cannot find scripts/linux/setup.sh - run it manually first."
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
  echo "ERROR: Cannot find citl_llmops_suite.py in:"
  echo "  $SCRIPT1"
  echo "  $SCRIPT2"
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$SCRIPT"
else
  exec python "$SCRIPT"
fi
