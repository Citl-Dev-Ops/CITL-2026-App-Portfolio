#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

SCRIPT="$DIR/factbook-assistant/citl_app_sync.py"
if [ ! -f "$SCRIPT" ]; then
  MSG="Could not find: $SCRIPT"
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="CITL App Sync" --text="$MSG"
  else
    echo "$MSG"
  fi
  exit 1
fi

PY=""
if [ -x "$DIR/.venv/bin/python3" ]; then
  PY="$DIR/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PY="$(command -v python)"
else
  MSG="Python 3 is not available. Install python3 or create .venv first."
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="CITL App Sync" --text="$MSG"
  else
    echo "$MSG"
  fi
  exit 1
fi

LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/citl"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_app_sync.log"

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] RUN_APP_SYNC start"
  echo "DIR=$DIR"
  echo "PY=$PY"
  "$PY" "$SCRIPT" --source "$DIR"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] RUN_APP_SYNC exit=0"
} >>"$LOG_FILE" 2>&1 || {
  RC=$?
  MSG="CITL App Sync failed (exit $RC). See log: $LOG_FILE"
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="CITL App Sync" --text="$MSG"
  else
    echo "$MSG"
  fi
  exit "$RC"
}
