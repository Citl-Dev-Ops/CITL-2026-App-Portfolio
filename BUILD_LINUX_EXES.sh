#!/usr/bin/env bash
# ============================================================
# CITL Linux EXE Builder
# Run this on Ubuntu/Linux to build native Linux binaries.
# Requires: Python 3.10+, tkinter, PyInstaller
# Usage:
#   ./BUILD_LINUX_EXES.sh
#   ./BUILD_LINUX_EXES.sh --apps synchub,appsync
#   ./BUILD_LINUX_EXES.sh --copy-to-usb /path/to/usb
# ============================================================
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$REPO/dist"
VENV="$REPO/.venv"
APPS_ARG="all"
USB_DEST=""

# ---- Parse args ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --apps)         APPS_ARG="$2"; shift 2 ;;
        --copy-to-usb)  USB_DEST="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; shift ;;
    esac
done

echo ""
echo "============================================================"
echo "  CITL Linux EXE Builder"
echo "============================================================"
echo ""
echo "  Repo    : $REPO"
echo "  Dist    : $DIST"
echo "  Apps    : $APPS_ARG"
echo ""

# ---- Find Python ----
PYTHON=""
for py in "$VENV/bin/python" python3 python; do
    command -v "$py" &>/dev/null || continue
    ver=$("$py" --version 2>&1 | grep -oP '3\.\d+' || true)
    [[ -n "$ver" ]] && { PYTHON="$py"; break; }
done
[[ -z "$PYTHON" ]] && { echo "[FAIL] Python 3 not found"; exit 1; }
echo "  Python  : $PYTHON ($($PYTHON --version 2>&1))"

# ---- Check tkinter ----
if ! "$PYTHON" -c "import tkinter" 2>/dev/null; then
    echo "[WARN] tkinter not found. Installing..."
    sudo apt-get install -y python3-tk || { echo "[FAIL] Could not install python3-tk"; exit 1; }
fi

# ---- Bootstrap venv if needed ----
if [[ ! -x "$VENV/bin/python" ]]; then
    echo "  Creating venv at $VENV ..."
    "$PYTHON" -m venv "$VENV"
    PYTHON="$VENV/bin/python"
fi

# ---- Install PyInstaller ----
if ! "$VENV/bin/python" -c "import PyInstaller" 2>/dev/null; then
    echo "  Installing PyInstaller..."
    "$VENV/bin/pip" install pyinstaller --quiet
fi

mkdir -p "$DIST"

# ---- App definitions ----
declare -A APP_SCRIPT=(
    [synchub]="factbook-assistant/citl_sync_hub.py"
    [appsync]="factbook-assistant/citl_app_sync.py"
    [stafftoolkit]="factbook-assistant/citl_staff_toolkit.py"
    [llmops]="factbook-assistant/citl_llmops_suite.py"
    [doccomposer]="factbook-assistant/citl_doc_composer.py"
)
declare -A APP_NAME=(
    [synchub]="CITL Sync Hub"
    [appsync]="CITL App Sync"
    [stafftoolkit]="CITL Staff Toolkit"
    [llmops]="CITL LLMOps Suite"
    [doccomposer]="CITL Document Composer"
)
declare -A APP_USB=(
    [synchub]="1-CITL-SYNC"
    [appsync]="1-CITL-SYNC"
    [stafftoolkit]="1-CITL-SYNC"
    [llmops]="2-CITL-PRESENTATION-SUITE"
    [doccomposer]="1-CITL-SYNC"
)

# Which apps to build
if [[ "$APPS_ARG" == "all" ]]; then
    APPS_TO_BUILD=("synchub" "appsync" "stafftoolkit" "llmops" "doccomposer")
else
    IFS=',' read -ra APPS_TO_BUILD <<< "$APPS_ARG"
fi

# ---- Build function ----
build_app() {
    local key="$1"
    local script="${APP_SCRIPT[$key]:-}"
    local name="${APP_NAME[$key]:-}"
    [[ -z "$script" ]] && { echo "[WARN] Unknown app key: $key"; return 1; }
    [[ -f "$REPO/$script" ]] || { echo "[WARN] Script not found: $REPO/$script"; return 1; }

    echo ""
    echo "---- Building: $name ----"
    local hidden="tkinter,_tkinter,tkinter.ttk,tkinter.messagebox,tkinter.filedialog,tkinter.scrolledtext,tkinter.simpledialog"
    "$VENV/bin/pyinstaller" \
        --noconfirm \
        --clean \
        --onedir \
        --windowed \
        --name "$name" \
        --distpath "$DIST" \
        --workpath "$REPO/build" \
        --hidden-import="$hidden" \
        "$REPO/$script" 2>&1 | grep -E '(INFO: Build|WARN|ERROR|completed|failed)' || true

    local out="$DIST/$name"
    if [[ -f "$out/$name" ]]; then
        local sz
        sz=$(du -sh "$out" 2>/dev/null | cut -f1)
        echo "[ OK ] $name  ->  $out  ($sz)"
        return 0
    else
        echo "[FAIL] $name: exe not found after build"
        return 1
    fi
}

BUILT=0; FAILED=0
for app_key in "${APPS_TO_BUILD[@]}"; do
    if build_app "$app_key"; then
        BUILT=$((BUILT+1))
    else
        FAILED=$((FAILED+1))
    fi
done

# ---- Copy to USB if requested ----
if [[ -n "$USB_DEST" ]]; then
    echo ""
    echo "---- Syncing to USB: $USB_DEST ----"
    for app_key in "${APPS_TO_BUILD[@]}"; do
        name="${APP_NAME[$app_key]:-}"
        usb_folder="${APP_USB[$app_key]:-1-CITL-SYNC}"
        src="$DIST/$name"
        dst="$USB_DEST/$usb_folder/linux/$name"
        [[ -d "$src" ]] || continue
        mkdir -p "$dst"
        rsync -av --update "$src/" "$dst/" 2>&1 | tail -2
        echo "  [ OK ] $name -> $dst"
    done
fi

# ---- Create shell launchers at USB root ----
if [[ -n "$USB_DEST" ]]; then
    echo ""
    echo "---- Writing USB root .sh launchers ----"
    for app_key in "${APPS_TO_BUILD[@]}"; do
        name="${APP_NAME[$app_key]:-}"
        usb_folder="${APP_USB[$app_key]:-1-CITL-SYNC}"
        launcher="$USB_DEST/$name.sh"
        cat > "$launcher" <<ENDLAUNCHER
#!/usr/bin/env bash
HERE="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
# Try Linux binary first
LINUX_EXE="\$HERE/$usb_folder/linux/$name/$name"
if [ -x "\$LINUX_EXE" ]; then
    nohup "\$LINUX_EXE" &>/dev/null &
    exit 0
fi
# Fallback: run Python source
VENV="\$HERE/.venv/bin/python"
[ -x "\$VENV" ] || VENV=python3
SCRIPT="\$HERE/factbook-assistant/${APP_SCRIPT[$app_key]##*/}"
if [ -f "\$SCRIPT" ]; then
    nohup "\$VENV" "\$SCRIPT" &>/dev/null &
else
    echo "[ERROR] Neither binary nor script found for $name"
    exit 1
fi
ENDLAUNCHER
        chmod +x "$launcher"
        echo "  [ OK ] $launcher"
    done
fi

echo ""
echo "============================================================"
echo "  Build Summary"
echo "============================================================"
echo "  Built  : $BUILT"
echo "  Failed : $FAILED"
echo ""
echo "  Linux binaries in: $DIST"
echo ""
echo "  To run: ./$DIST/\"CITL Sync Hub\"/\"CITL Sync Hub\""
echo "  To install .desktop shortcuts, run: ./START_CITL_UBUNTU.sh"
