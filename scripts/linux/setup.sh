#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "== CITL Setup (Ubuntu/Linux) =="
echo "Repo: $REPO_DIR"

# System deps (Ubuntu 22.04 / 24.04)
if command -v apt-get >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y \
      python3-venv python3-tk python3-dev \
      ffmpeg \
      libportaudio2 portaudio19-dev \
      alsa-utils pulseaudio-utils \
      build-essential
  else
    echo "WARN: sudo not available; install system deps manually:"
    echo "  apt-get update -y && apt-get install -y python3-venv python3-tk python3-dev ffmpeg libportaudio2 portaudio19-dev alsa-utils pulseaudio-utils build-essential"
  fi
fi

cd "$REPO_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Creating venv..."
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -U pip

# pip deps (needs internet)
if [[ -f "$REPO_DIR/requirements-linux.txt" ]]; then
  pip install -r "$REPO_DIR/requirements-linux.txt"
elif [[ -f "$REPO_DIR/requirements.txt" ]]; then
  pip install -r "$REPO_DIR/requirements.txt"
else
  echo "WARN: No requirements file found. Skipping pip install."
fi

echo "Setup complete."
echo "Next: ./scripts/linux/run.sh"
