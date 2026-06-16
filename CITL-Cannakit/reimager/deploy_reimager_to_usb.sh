#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy_reimager_to_usb.sh  —  CITL Reimager USB Deploy Tool
# Renton Technical College — CITL
#
# Copies (or updates) the CITL Reimager toolkit onto any connected ExFAT drive.
# Can be called from:
#   - Command line:      sudo bash deploy_reimager_to_usb.sh
#   - CITL APP FIXER GUI (Python subprocess call)
#   - REPAIR_CITL_APPS.cmd (Windows batch via WSL or Git Bash)
#
# Usage:
#   bash deploy_reimager_to_usb.sh [--target-dev /dev/sdX | --target-mount /mnt/X]
#                                  [--list-only] [--quiet]
#
# Output:
#   On success: prints DEPLOYED:/path/to/mount  (parseable by GUI)
#   On failure: prints FAILED:reason
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_GUARD="${SCRIPT_DIR}/boot_payload_guard.sh"
[[ -f "${PAYLOAD_GUARD}" ]] && source "${PAYLOAD_GUARD}"
QUIET=false
LIST_ONLY=false
TARGET_DEV=""
TARGET_MOUNT=""
EXIT_CODE=0

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target-dev)   TARGET_DEV="$2";   shift 2;;
        --target-mount) TARGET_MOUNT="$2"; shift 2;;
        --list-only)    LIST_ONLY=true;    shift;;
        --quiet)        QUIET=true;        shift;;
        *) shift;;
    esac
done

log()  { ${QUIET} || echo "[CITL-DEPLOY] $*"; }
logq() { echo "$*"; }   # always prints (for GUI parsing)

# ── Find all ExFAT drives (JSON to avoid column-shift issues) ─────────────────
find_exfat_drives() {
    lsblk -J -o PATH,FSTYPE,LABEL,MOUNTPOINT,SIZE --exclude 7,11 2>/dev/null | \
    python3 - <<'PYEOF'
import json, sys
data = json.load(sys.stdin)
def flat(devs, acc=None):
    if acc is None: acc = []
    for d in devs:
        acc.append(d)
        flat(d.get('children', []), acc)
    return acc
for d in flat(data.get('blockdevices', [])):
    if (d.get('fstype') or '') == 'exfat':
        path  = d.get('path','')
        label = d.get('label','') or ''
        mnt   = d.get('mountpoint','') or ''
        size  = d.get('size','') or ''
        print(f'{path}\t{label}\t{mnt}\t{size}')
PYEOF
}

find_sibling_citlboot_mount() {
    local dev="$1"
    local parent=""
    parent="$(lsblk -rno PKNAME "${dev}" 2>/dev/null | head -1 || true)"
    [[ -n "${parent}" ]] || return 0
    lsblk -rno PATH,LABEL,MOUNTPOINT "/dev/${parent}" 2>/dev/null | \
        awk '$2=="CITLBOOT" && $3!="" {print $3; exit}'
}

# ── List mode (GUI queries this) ──────────────────────────────────────────────
if ${LIST_ONLY}; then
    found=0
    while IFS=$'\t' read -r dev label mountpt size; do
        [[ -z "${dev}" ]] && continue
        logq "DRIVE:${dev}|${label:-unlabelled}|${size}|${mountpt:-unmounted}"
        found=$((found+1))
    done < <(find_exfat_drives 2>/dev/null || true)
    [[ ${found} -eq 0 ]] && logq "NO_EXFAT_DRIVES"
    exit 0
fi

# ── Auto-select or validate target ───────────────────────────────────────────
select_target() {
    local mnt=""
    local dev=""

    if [[ -n "${TARGET_MOUNT}" ]]; then
        mnt="${TARGET_MOUNT}"
        dev="$(findmnt -no SOURCE "${mnt}" 2>/dev/null || true)"
    elif [[ -n "${TARGET_DEV}" ]]; then
        dev="${TARGET_DEV}"
        mnt="$(lsblk -rno MOUNTPOINT "${dev}" 2>/dev/null | head -1)"
        if [[ -z "${mnt}" ]]; then
            mnt="/mnt/citl_deploy_target"
            mkdir -p "${mnt}"
            mount -t exfat "${dev}" "${mnt}" || {
                logq "FAILED:Cannot mount ${dev} as exfat"
                exit 1
            }
        fi
    else
        # Auto: find the first ExFAT that is NOT the source USB
        local citl_boot_disk=""
        if command -v lsblk >/dev/null 2>&1; then
            citl_boot_disk="$(lsblk -rno PKNAME \
                "$(lsblk -rno PATH,LABEL | awk '$2=="CITLBOOT"{print $1}' | head -1)" \
                2>/dev/null || true)"
        fi

        while IFS=$'\t' read -r d label mountpt sz; do
            [[ -z "${d}" ]] && continue
            local parent; parent="$(lsblk -rno PKNAME "${d}" 2>/dev/null || true)"
            if [[ "${parent}" == "${citl_boot_disk}" ]]; then
                log "Skipping ${d} (same USB as CITLBOOT source)"
                continue
            fi
            dev="${d}"; mnt="${mountpt}"
            break
        done < <(find_exfat_drives 2>/dev/null || true)

        if [[ -z "${dev}" ]]; then
            logq "FAILED:No ExFAT drives found. Connect an ExFAT USB."
            exit 1
        fi

        if [[ -z "${mnt}" ]]; then
            mnt="/mnt/citl_deploy_target"
            mkdir -p "${mnt}"
            mount -t exfat "${dev}" "${mnt}" || {
                logq "FAILED:Cannot mount ${dev}"
                exit 1
            }
        fi
    fi

    echo "${dev}|${mnt}"
}

# ── Do the deploy ─────────────────────────────────────────────────────────────
target_info="$(select_target)"
TARGET_DEV="${target_info%%|*}"
TARGET_MOUNT="${target_info##*|}"

log "Deploying CITL Reimager → ${TARGET_MOUNT}  (${TARGET_DEV})"

DEST="${TARGET_MOUNT}/citl_reimager"
mkdir -p "${DEST}"

# Copy all reimager scripts
rsync -av --exclude='*.pyc' --exclude='__pycache__' \
      "${SCRIPT_DIR}/" "${DEST}/" 2>&1 | \
    grep -v "^sending\|^sent\|^total" || \
    cp -r "${SCRIPT_DIR}/"* "${DEST}/"

# Copy parent CITL-Cannakit scripts
CANNAKIT="$(dirname "${SCRIPT_DIR}")"
if [[ -d "${CANNAKIT}" ]]; then
    rsync -a --exclude='reimager' --exclude='__pycache__' \
          "${CANNAKIT}/" "${DEST}/cannakit/" 2>/dev/null || \
        cp -r "${CANNAKIT}" "${DEST}/cannakit" 2>/dev/null || true
fi

# Copy CITL-Desktop if present
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd 2>/dev/null || echo "")"
if [[ -d "${REPO_ROOT}/CITL-Desktop" ]]; then
    rsync -a "${REPO_ROOT}/CITL-Desktop/" "${DEST}/CITL-Desktop/" 2>/dev/null || \
        cp -r "${REPO_ROOT}/CITL-Desktop" "${DEST}/" 2>/dev/null || true
fi

# Fix permissions
chmod -R a+rX "${DEST}" 2>/dev/null || true
find "${DEST}" -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true

# Write a version manifest
cat > "${DEST}/MANIFEST.txt" <<MANIFEST
CITL Reimager v2.0
Deployed: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Source: $(hostname)
Files: $(find "${DEST}" -type f | wc -l)
MANIFEST

if declare -F citl_payload_write_status >/dev/null 2>&1; then
    CITLBOOT_MOUNT="$(find_sibling_citlboot_mount "${TARGET_DEV}" 2>/dev/null || true)"
    PAYLOAD_STATUS="$(citl_payload_write_status "${DEST}" "${CITLBOOT_MOUNT:-}" "${TARGET_MOUNT}" 2>/dev/null || true)"
    log "Boot payload status: ${PAYLOAD_STATUS:-UNKNOWN}"
    if [[ "${PAYLOAD_STATUS:-}" == MISSING:* ]]; then
        log "WARNING: boot/recovery payload missing; USB tools copied but media is not boot-ready."
    fi
fi

sync

log "Deploy complete → ${DEST}"
logq "DEPLOYED:${DEST}"
