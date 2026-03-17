#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo " CITL Unified Update (Ubuntu/Linux)"
echo " Updates system packages, Python packages, port files, and app shortcuts."
echo ""

bash "$DIR/scripts/linux/update.sh" "$@"
