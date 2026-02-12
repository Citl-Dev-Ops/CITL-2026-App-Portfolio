#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"

echo "=================================================="
echo "CITL Desktop LLM EZ Install Kits - Ubuntu Launcher"
echo "=================================================="
echo "Time   : $(date)"
echo "Host   : $(hostname)"
echo "Kernel : $(uname -srmo)"
echo "PWD    : $(pwd)"
echo "=================================================="
echo

if command -v python3 >/dev/null 2>&1; then
  echo "Python : $(python3 --version)"
else
  echo "Python : (missing)"
  echo "Install: sudo apt-get update && sudo apt-get install -y python3 python3-venv"
fi

echo

if [[ "$MODE" == "--demo" ]]; then
  echo "[DEMO MODE]"
  echo "This is a console-only run so you can screenshot proof in Windows (via WSL)."
  echo "On a real Ubuntu machine, run:"
  echo "  ./scripts/bootstrap_ubuntu.sh"
  echo "  ./scripts/run_ubuntu.sh"
  echo
  exit 0
fi

# If no GUI display is present, do a safe headless smoke test
if [[ -z "${DISPLAY:-}" ]]; then
  echo "[HEADLESS]"
  echo "No DISPLAY detected; running a smoke-test only."
  python3 - <<'PY'
import platform
print("CITL smoke test OK on:", platform.platform())
PY
  exit 0
fi

echo "[INFO]"
echo "DISPLAY detected; you can launch GUI-capable components here if needed."
echo "For now, running smoke-test:"
python3 - <<'PY'
import platform
print("CITL GUI-capable environment detected on:", platform.platform())
PY
