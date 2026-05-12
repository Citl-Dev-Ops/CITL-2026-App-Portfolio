#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN="$ROOT/powerflow_builder/dist/citl_ticketing_automation_gui/citl_ticketing_automation_gui"
if [ ! -x "$BIN" ]; then
  echo "Binary not found or not executable: $BIN"
  echo "Build first with: bash powerflow_builder/build_ticketing_automation_bin.sh"
  exit 1
fi
exec "$BIN" "$@"
