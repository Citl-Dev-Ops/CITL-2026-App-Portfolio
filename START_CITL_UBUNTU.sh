#!/usr/bin/env bash
# ============================================================
# CITL USB Quick Launch -- Ubuntu / Linux  (auto-wizard edition)
# Double-click in Files manager or run in terminal.
# Automatically: discovers repos, writes USB instance ID,
# syncs files, bootstraps venv, creates .desktop shortcuts,
# and launches the CITL App Sync GUI.
#
# Exclusions: *.gguf  *.bin  blobs/  ollama/  .venv/
# Ollama must be installed via the USB GPU bootstrapper,
# NOT synced as a file blob.
# ============================================================
set -uo pipefail

USB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKER="factbook-assistant/citl_app_sync.py"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/citl"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/usb_launch_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

# ---- Notification helpers ------------------------------------------------
_notify() {
    local icon="${2:-dialog-information}"
    command -v notify-send &>/dev/null &&
        notify-send "CITL App Suite" "$1" --icon="$icon" 2>/dev/null || true
}
_notify_warn()  { _notify "$1" "dialog-warning"; }
_notify_error() { _notify "$1" "dialog-error";   }

_zenity_ask() {
    # Returns 0=yes 1=no/cancel
    local title="$1" text="$2"
    if command -v zenity &>/dev/null; then
        zenity --question --title="$title" --text="$text" 2>/dev/null
    else
        # Terminal fallback
        echo ""
        read -r -p "$text [y/N] " resp
        [[ "${resp,,}" == "y" ]]
    fi
}

_zenity_info() {
    if command -v zenity &>/dev/null; then
        zenity --info --title="CITL App Suite" --text="$1" 2>/dev/null || true
    else
        echo " [INFO] $1"
    fi
}

echo ""
echo " ====================================================="
echo "  CITL App Suite -- USB Quick Launch (Ubuntu/Linux)"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo " ====================================================="
echo ""
echo " USB root : $USB_ROOT"

# ---- Write USB instance ID if not present --------------------------------
INSTANCE_FILE="$USB_ROOT/citl_instance.json"
if [[ ! -f "$INSTANCE_FILE" ]]; then
    # Generate a short hex ID
    INST_ID="CITL-$(cat /proc/sys/kernel/random/uuid 2>/dev/null | tr -d '-' | head -c 8 | tr '[:lower:]' '[:upper:]' || echo "XXXX$(date +%s | tail -c 5)")"
    cat > "$INSTANCE_FILE" <<ENDJSON
{
  "instance_id": "$INST_ID",
  "type": "USB",
  "label": "USB-LINUX-${INST_ID: -4}",
  "created": "$(date -Iseconds)",
  "path": "$USB_ROOT"
}
ENDJSON
    echo " [OK] USB instance ID created: $INST_ID"
else
    INST_ID=$(python3 -c "import json; d=json.load(open('$INSTANCE_FILE')); print(d.get('instance_id','?'))" 2>/dev/null || echo "?")
    echo " [OK] USB instance ID: $INST_ID"
fi

# ---- Discover existing local CITL repos ----------------------------------
echo ""
echo " Scanning for local CITL repos..."
LOCAL_REPO=""
STALE=0

declare -a CANDIDATES=(
    "$HOME/Desktop/CITL"
    "$HOME/Documents/CITL"
    "$HOME/Downloads/CITL"
    "$HOME/CITL"
    "/opt/CITL"
    "/srv/CITL"
)
# Also check Desktop and Documents subfolders one level deep
for base in "$HOME/Desktop" "$HOME/Documents"; do
    [[ -d "$base" ]] || continue
    while IFS= read -r -d '' dir; do
        CANDIDATES+=("$dir")
    done < <(find "$base" -maxdepth 2 -type d -name "CITL*" -print0 2>/dev/null)
done

for candidate in "${CANDIDATES[@]}"; do
    [[ -f "$candidate/$MARKER" ]] || continue
    mtime=$(stat -c %Y "$candidate/$MARKER" 2>/dev/null || echo 0)
    now=$(date +%s)
    age_days=$(( (now - mtime) / 86400 ))
    # Read local instance ID if present
    local_id=$(python3 -c "import json; d=json.load(open('$candidate/citl_instance.json')); print(d.get('instance_id','?'))" 2>/dev/null || echo "(no ID)")
    echo "   Found: $candidate  [$local_id]  (${age_days}d old)"
    if [[ -z "$LOCAL_REPO" ]]; then
        LOCAL_REPO="$candidate"
        if (( age_days > 14 )); then
            STALE=1
            echo "   [WARN] Repo is stale (${age_days} days > 14 day threshold)"
            _notify_warn "Local CITL repo is ${age_days} days old - USB sync will update it."
        fi
    fi
done

if [[ -z "$LOCAL_REPO" ]]; then
    echo " No local CITL repo found."
    INSTALL_DEST="$HOME/Desktop/CITL"
    _notify_warn "No local CITL repo found. Will install to $INSTALL_DEST"
else
    INSTALL_DEST="$LOCAL_REPO"
fi

# ---- Auto-decision: install vs sync vs update ----------------------------
echo ""
if [[ -z "$LOCAL_REPO" ]]; then
    echo " === FIRST-TIME INSTALL ==="
    echo " Destination: $INSTALL_DEST"
    _notify "Installing CITL to $INSTALL_DEST..."
    DO_SYNC=1
    IS_FRESH_INSTALL=1
else
    IS_FRESH_INSTALL=0
    if [[ "$STALE" -eq 1 ]]; then
        echo " === STALE REPO - AUTO-SYNCING FROM USB ==="
        DO_SYNC=1
    else
        echo " === REPO IS FRESH - CHECKING FOR USB UPDATES ==="
        # Compare USB and local marker timestamps
        usb_mtime=$(stat -c %Y "$USB_ROOT/$MARKER" 2>/dev/null || echo 0)
        local_mtime=$(stat -c %Y "$LOCAL_REPO/$MARKER" 2>/dev/null || echo 0)
        if (( usb_mtime > local_mtime )); then
            echo " USB has newer files - syncing..."
            DO_SYNC=1
        else
            echo " Local repo is up to date."
            DO_SYNC=0
        fi
    fi
fi

# ---- rsync from USB to local (skip large files/Ollama) -------------------
RSYNC_EXCLUDES=(
    --exclude='.git/'
    --exclude='__pycache__/'
    --exclude='*.pyc'
    --exclude='.venv/'
    --exclude='models/'
    --exclude='ollama/'
    --exclude='blobs/'
    --exclude='*.gguf'
    --exclude='*.bin'
    --exclude='*.blob'
    --exclude='build/'
    --exclude='dist/'
    --exclude='*.log'
    --exclude='*.tmp'
    --max-size=500m
)

if [[ "${DO_SYNC:-0}" -eq 1 ]]; then
    mkdir -p "$INSTALL_DEST"
    if command -v rsync &>/dev/null; then
        echo ""
        echo " Syncing files (rsync, excluding Ollama/large files)..."
        rsync -av --progress "${RSYNC_EXCLUDES[@]}" "$USB_ROOT/" "$INSTALL_DEST/" 2>&1 | \
            grep -E '(sending|total size|files transferred|NEWER|^[^/])' || true
        echo " [OK] rsync complete"
    else
        echo " [WARN] rsync not available. Using cp (slower, no delta)..."
        cp -rfu "$USB_ROOT/factbook-assistant" "$INSTALL_DEST/" 2>/dev/null || true
        cp -rfu "$USB_ROOT/scripts"            "$INSTALL_DEST/" 2>/dev/null || true
        cp -rfu "$USB_ROOT/data"               "$INSTALL_DEST/" 2>/dev/null || true
        for f in *.sh *.cmd *.txt *.md *.cfg *.ini; do
            [[ -f "$USB_ROOT/$f" ]] && cp -fu "$USB_ROOT/$f" "$INSTALL_DEST/" 2>/dev/null || true
        done
        echo " [OK] File copy complete"
    fi

    # ---- Write local instance ID if not present --------------------------
    LOCAL_INST="$INSTALL_DEST/citl_instance.json"
    if [[ ! -f "$LOCAL_INST" ]]; then
        LOCAL_INST_ID="CITL-$(cat /proc/sys/kernel/random/uuid 2>/dev/null | tr -d '-' | head -c 8 | tr '[:lower:]' '[:upper:]' || echo "LOCAL$(date +%s | tail -c 4)")"
        cat > "$LOCAL_INST" <<ENDJSON
{
  "instance_id": "$LOCAL_INST_ID",
  "type": "PC",
  "label": "PC-$(hostname)-${LOCAL_INST_ID: -4}",
  "created": "$(date -Iseconds)",
  "path": "$INSTALL_DEST"
}
ENDJSON
        echo " [OK] Local instance ID created: $LOCAL_INST_ID"
    fi
fi

TARGET_REPO="$INSTALL_DEST"

# ---- Bootstrap Python venv -----------------------------------------------
VENV="$TARGET_REPO/.venv"
PYTHON=""

# Find Python 3
for py in \
    "$VENV/bin/python" \
    "$(command -v python3 2>/dev/null || true)" \
    "$(command -v python  2>/dev/null || true)"; do
    [[ -z "$py" || ! -x "$py" ]] && continue
    ver=$("$py" --version 2>&1 | grep -oP '3\.\d+' || true)
    [[ -n "$ver" ]] && { PYTHON="$py"; break; }
done

if [[ -z "$PYTHON" ]]; then
    echo ""
    echo " [ERROR] Python 3 not found."
    echo " Install with: sudo apt install python3 python3-tk python3-venv"
    _notify_error "Python 3 not found.\nRun: sudo apt install python3 python3-tk python3-venv"
    exit 1
fi
echo ""
echo " Python: $PYTHON"

# Check tkinter
if ! "$PYTHON" -c "import tkinter" 2>/dev/null; then
    echo " [WARN] tkinter not found - attempting to install..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y python3-tk 2>/dev/null || {
            echo " [ERROR] Could not install python3-tk. Run manually: sudo apt install python3-tk"
            _notify_error "tkinter not found.\nRun: sudo apt install python3-tk"
            exit 1
        }
    fi
fi

# Create venv if absent or broken
if [[ ! -x "$VENV/bin/python" ]]; then
    echo " Creating virtual environment at $VENV ..."
    "$PYTHON" -m venv "$VENV" 2>&1
    PYTHON="$VENV/bin/python"
    echo " [OK] venv created"
fi

# Install requirements
for req in "$TARGET_REPO/requirements-linux.txt" \
           "$TARGET_REPO/requirements.txt"; do
    if [[ -f "$req" ]]; then
        echo " Installing requirements from $req ..."
        "$VENV/bin/pip" install -r "$req" --quiet 2>&1 | tail -3
        break
    fi
done

# ---- Create .desktop shortcut on Desktop ---------------------------------
DESKTOP_SHORTCUT="$HOME/Desktop/CITL App Sync.desktop"
if [[ ! -f "$DESKTOP_SHORTCUT" ]]; then
    cat > "$DESKTOP_SHORTCUT" <<EODESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=CITL App Sync
Comment=CITL App Sync - RTC/Whatcom Community College
Exec=$VENV/bin/python $TARGET_REPO/factbook-assistant/citl_app_sync.py
Icon=utilities-file-manager
Terminal=false
Categories=Utility;Education;
EODESKTOP
    chmod +x "$DESKTOP_SHORTCUT"
    echo " [OK] Desktop shortcut created: $DESKTOP_SHORTCUT"
fi

# ---- Launch App Sync GUI -------------------------------------------------
SYNC_PY="$TARGET_REPO/factbook-assistant/citl_app_sync.py"
if [[ ! -f "$SYNC_PY" ]]; then
    echo " [ERROR] citl_app_sync.py not found at: $SYNC_PY"
    _notify_error "CITL App Sync not found at:\n$SYNC_PY"
    exit 1
fi

echo ""
echo " Launching CITL App Sync GUI..."
_notify "CITL App Sync launching..."
nohup "$VENV/bin/python" "$SYNC_PY" > "$LOG_DIR/sync_gui.log" 2>&1 &
GUI_PID=$!
echo " [OK] CITL App Sync launched (PID $GUI_PID)"
echo " Log: $LOG_DIR/sync_gui.log"
echo ""
echo " Done. CITL is running."
