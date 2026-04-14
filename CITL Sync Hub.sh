#!/usr/bin/env bash
# CITL USB Launcher - Ubuntu/Linux
# Double-click in Files manager or run in terminal
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. Try native Linux binary (built with BUILD_LINUX_EXES.sh on Ubuntu)
LINUX_EXE="$HERE/1-CITL-SYNC/linux/CITL Sync Hub/CITL Sync Hub"
if [ -x "$LINUX_EXE" ]; then
    nohup "$LINUX_EXE" &>/dev/null &
    echo "[ OK ] Launched (Linux binary): CITL Sync Hub"
    exit 0
fi

# 2. Try local installed venv
for venv_py in     "$HOME/Desktop/CITL/.venv/bin/python"     "$HOME/Documents/CITL/.venv/bin/python"     "$HOME/CITL/.venv/bin/python"     "$HERE/.venv/bin/python"; do
    if [ -x "$venv_py" ]; then
        PYTHON="$venv_py"
        break
    fi
done

# 3. Fallback to system python3
[ -z "${PYTHON:-}" ] && PYTHON=python3

# Find the script
for script_path in     "$HOME/Desktop/CITL/factbook-assistant/citl_sync_hub.py"     "$HOME/Documents/CITL/factbook-assistant/citl_sync_hub.py"     "$HOME/CITL/factbook-assistant/citl_sync_hub.py"     "$HERE/factbook-assistant/citl_sync_hub.py"; do
    if [ -f "$script_path" ]; then
        # Check tkinter
        if ! "$PYTHON" -c "import tkinter" 2>/dev/null; then
            if command -v zenity &>/dev/null; then
                zenity --info --text="Installing tkinter (python3-tk)...
Please enter your password if prompted." 2>/dev/null &
            fi
            sudo apt-get install -y python3-tk 2>/dev/null || true
        fi
        nohup "$PYTHON" "$script_path" &>/dev/null &
        echo "[ OK ] Launched: CITL Sync Hub"
        exit 0
    fi
done

echo "[ERROR] CITL Sync Hub not found. Run START_CITL_UBUNTU.sh to install first."
if command -v zenity &>/dev/null; then
    zenity --error --text="CITL Sync Hub not found.
Run START_CITL_UBUNTU.sh to install." 2>/dev/null || true
fi
exit 1
