#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="$HERE/CITL_Toolkit/CITL_Launcher.ps1"
if [[ ! -e "$TARGET" ]]; then
  echo "CITL Toolkit: entry not found: $TARGET"
  exit 1
fi
echo "CITL Toolkit: no Ubuntu-native launcher for CITL_Toolkit/CITL_Launcher.ps1"
echo "Use this as a placeholder and run the Windows launcher on Windows hosts."
exit 2
