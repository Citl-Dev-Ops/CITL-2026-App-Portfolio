#!/usr/bin/env bash
set -euo pipefail

USB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/CITL-Factbook"

echo "=============================================="
echo "CITL Factbook - Ubuntu 24.04 LTS Installer"
echo "Source (USB): $USB_DIR"
echo "Install dir : $INSTALL_DIR"
echo "=============================================="

# System deps
SUDO=""
command -v sudo >/dev/null 2>&1 && SUDO="sudo"

$SUDO apt-get update
$SUDO apt-get install -y \
  python3 python3-venv python3-pip python3-tk python3-dev python3-gi \
  ffmpeg rsync \
  libportaudio2 portaudio19-dev \
  alsa-utils pulseaudio-utils \
  build-essential \
  git

# Copy from USB -> local install dir (faster + avoids USB filesystem quirks)
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" --exclude "venv" --exclude "__pycache__" \
  --exclude "profile" --exclude "results" \
  --exclude "factbook-assistant/bin" \
  "$USB_DIR/" "$INSTALL_DIR/"

# Create venv + install python deps
python3 -m venv "$INSTALL_DIR/.venv"
source "$INSTALL_DIR/.venv/bin/activate"
python -m pip install --upgrade pip wheel setuptools

# Use requirements-linux.txt (Ubuntu/Linux specific)
REQ=""
if [ -f "$INSTALL_DIR/requirements-linux.txt" ]; then
  REQ="$INSTALL_DIR/requirements-linux.txt"
elif [ -f "$INSTALL_DIR/requirements.txt" ]; then
  REQ="$INSTALL_DIR/requirements.txt"
fi

if [ -n "$REQ" ]; then
  pip install -r "$REQ"
else
  echo "WARNING: No requirements file found in bundle."
  echo "Add requirements-linux.txt to the USB package and re-copy."
fi

# Run Ubuntu port sync to ensure Linux files match Windows-side changes
if python -c "import sys; sys.path.insert(0,'$INSTALL_DIR/factbook-assistant'); import citl_app_sync" 2>/dev/null; then
  echo "Running Ubuntu port sync..."
  python - <<PYEOF
import sys; sys.path.insert(0, "$INSTALL_DIR/factbook-assistant")
from citl_app_sync import port_to_ubuntu
from pathlib import Path
results = port_to_ubuntu(Path("$INSTALL_DIR"))
for k, v in results.items():
    print(f"  {k}: {v}")
PYEOF
fi

echo
echo "Install complete."
echo "Run it with:"
echo "  bash \"$INSTALL_DIR/RUN_FACTBOOK.sh\""
