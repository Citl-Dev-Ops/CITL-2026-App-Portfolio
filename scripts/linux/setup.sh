#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "== CITL Setup (Ubuntu 24.04 LTS / Linux) =="
echo "Repo: $REPO_DIR"

# System deps (Ubuntu 24.04 LTS)
if command -v apt-get >/dev/null 2>&1; then
  SUDO=""
  command -v sudo >/dev/null 2>&1 && SUDO="sudo"
  $SUDO apt-get update -y
  $SUDO apt-get install -y \
    python3-venv python3-tk python3-dev python3-gi \
    ffmpeg \
    libportaudio2 portaudio19-dev \
    alsa-utils pulseaudio-utils \
    build-essential \
    git
else
  echo "WARN: apt-get not available; install system deps manually."
fi

cd "$REPO_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Creating venv..."
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -U pip wheel setuptools

# pip deps
if [[ -f "$REPO_DIR/requirements-linux.txt" ]]; then
  pip install -r "$REPO_DIR/requirements-linux.txt"
elif [[ -f "$REPO_DIR/requirements.txt" ]]; then
  pip install -r "$REPO_DIR/requirements.txt"
else
  echo "WARN: No requirements file found. Skipping pip install."
fi

# Keep Ubuntu port files in sync with Windows-side changes
if python -c "import sys; sys.path.insert(0,'$REPO_DIR/factbook-assistant'); import citl_app_sync" 2>/dev/null; then
  python - <<PYEOF
import sys; sys.path.insert(0, "$REPO_DIR/factbook-assistant")
from citl_app_sync import port_to_ubuntu
from pathlib import Path
results = port_to_ubuntu(Path("$REPO_DIR"))
for k, v in results.items():
    print(f"  {k}: {v}")
PYEOF
fi

echo "Setup complete."
echo "Next: bash scripts/linux/run.sh"
