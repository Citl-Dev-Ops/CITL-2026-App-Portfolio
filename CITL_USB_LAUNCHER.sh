#!/usr/bin/env bash
# ================================================================
#  CITL USB Launcher - Ubuntu/Linux entry point
#  Shows all CITL apps on this USB as clickable tiles.
#  EXE (AppImage/binary) first, Python tkinter fallback.
#  Works from any mount point - no hardcoded paths.
# ================================================================

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
SCRIPT="$ROOT/citl_usb_launcher.py"
EXE_APPIMAGE="$ROOT/dist/CITL_USB_Launcher/CITL_USB_Launcher"

echo ""
echo "============================================================"
echo "  CITL USB Launcher"
echo "  USB Root: $ROOT"
echo "============================================================"
echo ""

# Ensure DISPLAY is set
export DISPLAY="${DISPLAY:-:0}"
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && command -v dbus-launch >/dev/null 2>&1; then
    eval "$(dbus-launch --sh-syntax 2>/dev/null)" || true
fi

# Try built executable first
if [ -x "$EXE_APPIMAGE" ]; then
    echo "Launching EXE: $EXE_APPIMAGE"
    exec "$EXE_APPIMAGE" "$@"
fi

# Find Python with tkinter support
PY=""
if [ -f "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
fi

if [ -z "$PY" ]; then
    echo "ERROR: Python 3 not found."
    echo "Install with:  sudo apt install python3 python3-tk"
    if command -v zenity >/dev/null 2>&1; then
        zenity --error \
            --text="Python 3 not found.\n\nInstall:\n  sudo apt install python3 python3-tk" \
            --title="CITL USB Launcher" 2>/dev/null || true
    fi
    exit 1
fi

# Check tkinter is available
if ! "$PY" -c "import tkinter" 2>/dev/null; then
    echo "WARNING: tkinter not found. Attempting to install..."
    sudo apt-get install -y python3-tk 2>/dev/null || true
    if ! "$PY" -c "import tkinter" 2>/dev/null; then
        echo "ERROR: tkinter could not be installed."
        echo "Run manually:  sudo apt install python3-tk"
        exit 1
    fi
fi

if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: citl_usb_launcher.py not found at: $SCRIPT"
    echo "Re-sync this USB from the CITL repo."
    if command -v zenity >/dev/null 2>&1; then
        zenity --error \
            --text="citl_usb_launcher.py not found.\nRe-sync from CITL repo." \
            --title="CITL USB Launcher" 2>/dev/null || true
    fi
    exit 1
fi

export PYTHONPATH="$ROOT/factbook-assistant:$ROOT:${PYTHONPATH:-}"
echo "Python: $PY"
echo "Launching CITL USB Launcher..."
"$PY" "$SCRIPT" "$@"
