#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "== CITL Setup (Ubuntu/Linux) =="
echo "Repo: $REPO_DIR"
# System deps (Ubuntu 24.x)
if command -v apt-get >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y python3-venv python3-tk ffmpeg
  else
    echo "WARN: sudo not available; install system deps manually:"
    echo "  apt-get update -y && apt-get install -y python3-venv python3-tk ffmpeg"
  fi
fi
cd "$REPO_DIR"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
# pip deps (needs internet)
pip install -r requirements-linux.txt
