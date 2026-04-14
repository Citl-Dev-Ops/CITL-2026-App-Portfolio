#!/usr/bin/env bash
#
# CITL USB Clone - One-Click USB Duplicator (Ubuntu)
# Copies this USB to another connected USB drive
#

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="$HERE/factbook-assistant/citl_app_sync.py"
GUI_SCRIPT="$HERE/factbook-assistant/citl_usb_clone_gui.py"

echo ""
echo "============================================================"
echo "  CITL USB Clone - Easy USB Duplicator"
echo "============================================================"
echo ""

# Check for sync script
if [[ ! -f "$SYNC_SCRIPT" ]]; then
    echo "[ERROR] Cannot find citl_app_sync.py"
    echo "Expected at: $SYNC_SCRIPT"
    echo ""
    echo "This script should be run from the USB root folder."
    echo ""
    exit 1
fi

# Try GUI first
if [[ -f "$GUI_SCRIPT" ]]; then
    echo "[info] Found GUI clone utility - launching..."
    echo ""
    
    # Locate Python
    PYTHON=""
    
    if [[ -x "$HERE/.venv/bin/python3" ]]; then
        PYTHON="$HERE/.venv/bin/python3"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON="python"
    else
        echo "[ERROR] Python not found"
        echo "Please install Python 3.9+ with: sudo apt install python3"
        echo ""
        exit 1
    fi
    
    echo "[info] Python: $PYTHON"
    echo ""
    
    # Launch GUI
    "$PYTHON" "$GUI_SCRIPT" --source "$HERE"
    exit $?
fi

# Fallback: PowerShell wrapper if available (for WSL)
PS_SCRIPT="$HERE/scripts/windows/copy_usb_duplicate.ps1"
if [[ -f "$PS_SCRIPT" ]] && command -v pwsh >/dev/null 2>&1; then
    echo "[info] Found PowerShell wrapper - launching..."
    pwsh -NoProfile -ExecutionPolicy Bypass -File "$PS_SCRIPT" -SourceUsb "$HERE"
    exit $?
fi

# Final fallback: Command-line clone
echo ""
echo "============================================================"
echo "  Fallback Mode: Command-Line Clone"
echo "============================================================"
echo ""
echo "This will copy this USB ($HERE) to a detected target USB."
echo ""
echo "Requirements:"
echo "  - Another CITL USB drive connected"
echo "  - Python 3.9+ installed"
echo ""

PYTHON=""
if [[ -x "$HERE/.venv/bin/python3" ]]; then
    PYTHON="$HERE/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
fi

if [[ -z "$PYTHON" ]]; then
    echo "[ERROR] Python not found in PATH"
    echo ""
    echo "Install Python with: sudo apt install python3"
    echo "Then run this script again."
    echo ""
    exit 1
fi

echo "Running: $PYTHON $SYNC_SCRIPT --duplicate-usb --source $HERE"
echo ""

if "$PYTHON" "$SYNC_SCRIPT" --duplicate-usb --source "$HERE"; then
    echo ""
    echo "============================================================"
    echo "  SUCCESS! USB clone complete."
    echo "============================================================"
    echo ""
    exit 0
else
    echo ""
    echo "============================================================"
    echo "  ERROR! Clone operation failed"
    echo "============================================================"
    echo ""
    exit 1
fi
