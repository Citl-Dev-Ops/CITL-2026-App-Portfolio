#!/usr/bin/env bash
set -euo pipefail

# repo root = two levels up from scripts/linux
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

echo "== CITL Update (Ubuntu 24.04 LTS / Linux) =="
echo "Repo: $REPO_DIR"
echo ""

SUDO=""
command -v sudo >/dev/null 2>&1 && SUDO="sudo"

# -- 1. System packages --------------------------------------------------------
echo "[1/4] Upgrading system packages..."
if command -v apt-get >/dev/null 2>&1; then
  $SUDO apt-get update -y
  $SUDO apt-get upgrade -y \
    python3-venv python3-tk python3-dev python3-gi \
    ffmpeg \
    libportaudio2 portaudio19-dev \
    alsa-utils pulseaudio-utils \
    build-essential \
    git
  echo "  OK: system packages"
else
  echo "  SKIP: apt-get not available on this system."
fi
echo ""

# -- 2. Python packages --------------------------------------------------------
echo "[2/4] Upgrading Python packages..."
if [[ ! -d "$REPO_DIR/.venv" ]]; then
  echo "  venv not found - running setup.sh first..."
  bash "$REPO_DIR/scripts/linux/setup.sh"
fi

source "$REPO_DIR/.venv/bin/activate"
python -m pip install -U pip wheel setuptools | tail -1

if [[ -f "$REPO_DIR/requirements-linux.txt" ]]; then
  pip install -U -r "$REPO_DIR/requirements-linux.txt"
  echo "  OK: requirements-linux.txt"
elif [[ -f "$REPO_DIR/requirements.txt" ]]; then
  pip install -U -r "$REPO_DIR/requirements.txt"
  echo "  OK: requirements.txt (fallback)"
else
  echo "  WARN: no requirements file found."
fi
echo ""

# -- 3. Ubuntu port sync -------------------------------------------------------
echo "[3/4] Syncing Ubuntu port files..."
python - <<PYEOF
import sys
sys.path.insert(0, "$REPO_DIR/factbook-assistant")
try:
    from citl_app_sync import port_to_ubuntu
    from pathlib import Path
    results = port_to_ubuntu(Path("$REPO_DIR"))
    for k, v in results.items():
        print(f"  {k}: {v}")
    if not results:
        print("  All port files already up to date.")
except Exception as e:
    print(f"  port_to_ubuntu skipped: {e}")
PYEOF
echo ""

# -- 4. Desktop shortcuts (.desktop files) -------------------------------------
echo "[4/4] Creating/updating desktop shortcuts..."
APP_DIR="${HOME}/.local/share/applications"
mkdir -p "$APP_DIR"

# CITL Factbook
cat > "$APP_DIR/citl-factbook.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=CITL Factbook
Comment=CITL Study & Library Q&A, Transcription, Translation, TTS
Exec=bash "$REPO_DIR/RUN_FACTBOOK.sh"
Icon=applications-education
Terminal=false
Categories=Education;Utility;Science;
StartupNotify=true
EOF
chmod +x "$APP_DIR/citl-factbook.desktop"
echo "  Created: citl-factbook.desktop"

# CITL App Sync
cat > "$APP_DIR/citl-app-sync.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=CITL App Sync
Comment=CITL cross-platform sync and update utility
Exec=bash "$REPO_DIR/RUN_APP_SYNC.sh"
Icon=system-software-update
Terminal=true
Categories=Utility;System;
StartupNotify=false
EOF
chmod +x "$APP_DIR/citl-app-sync.desktop"
echo "  Created: citl-app-sync.desktop"

# Refresh GNOME / app launcher index
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" 2>/dev/null || true
fi
if command -v xdg-desktop-menu >/dev/null 2>&1; then
  xdg-desktop-menu forceupdate 2>/dev/null || true
fi

echo ""
echo "Update complete."
echo "Shortcut files written to: $APP_DIR"
echo "They will appear in GNOME / KDE / Xfce app launchers automatically."
