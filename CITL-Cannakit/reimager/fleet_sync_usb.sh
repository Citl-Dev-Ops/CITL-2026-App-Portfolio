#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# fleet_sync_usb.sh  —  CITL Fleet USB Sync Tool
# Renton Technical College — CITL
#
# Updates multiple CITL fleet USB drives in one operation.
# Source: any ExFAT or CITLBOOT partition with citl_reimager/ content.
# Targets: all other connected ExFAT drives.
#
# Usage (CLI / mainframe):
#   sudo bash fleet_sync_usb.sh [--source DEVICE_OR_MOUNT] [--target DEV ...]
#                               [--all] [--list] [--dry-run] [--full-clone]
#                               [--parallel N]
#
# Usage (GUI / subprocess):
#   bash fleet_sync_usb.sh --list          → machine-readable drive list
#   bash fleet_sync_usb.sh --source /dev/sdb --all
#
# Machine-readable progress (for GUI):
#   DRIVE:path|label|size|mountpoint       (--list output)
#   PROGRESS:device|pct|message            (during sync)
#   DONE:device|SUCCESS                    (sync complete)
#   FAILED:device|reason                   (sync failed)
#   FLEET_DONE:N_ok/N_total               (all done)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_GUARD="${SCRIPT_DIR}/boot_payload_guard.sh"
[[ -f "${PAYLOAD_GUARD}" ]] && source "${PAYLOAD_GUARD}"

# ── Defaults ──────────────────────────────────────────────────────────────────
SOURCE_DEV=""
SOURCE_MNT=""
TARGET_DEVS=()
SYNC_ALL=false
LIST_MODE=false
DRY_RUN=false
FULL_CLONE=false
PARALLEL_MAX=4

# ── Arg parse ─────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)     SOURCE_DEV="$2"; shift 2;;
        --target)     TARGET_DEVS+=("$2"); shift 2;;
        --all)        SYNC_ALL=true; shift;;
        --list)       LIST_MODE=true; shift;;
        --dry-run)    DRY_RUN=true; shift;;
        --full-clone) FULL_CLONE=true; shift;;
        --parallel)   PARALLEL_MAX="$2"; shift 2;;
        -h|--help)
            sed -n '/^# Usage/,/^#.*$/p' "$0" | head -20; exit 0;;
        *) shift;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
emit() { echo "$*"; }          # machine-readable output (always printed)
log()  { echo "[FLEET] $*" >&2; }  # human log on stderr

# ── lsblk JSON helper (reliable, no column-shift) ─────────────────────────────
list_all_usb_devs() {
    # Returns one line per partition: PATH FSTYPE LABEL MOUNTPOINT SIZE TRAN(parent)
    lsblk -J -o PATH,FSTYPE,LABEL,MOUNTPOINT,SIZE,TRAN \
          --exclude 7,11 2>/dev/null | \
    python3 - <<'PYEOF'
import json, sys
data = json.load(sys.stdin)

def flat(devs, parent_tran="", acc=None):
    if acc is None: acc = []
    for d in devs:
        tran = d.get('tran') or parent_tran
        acc.append({
            'path':  d.get('path',''),
            'fstype': d.get('fstype','') or '',
            'label':  d.get('label','')  or '',
            'mnt':    d.get('mountpoint','') or '',
            'size':   d.get('size','')   or '',
            'tran':   tran,
        })
        flat(d.get('children', []), tran, acc)
    return acc

for d in flat(data.get('blockdevices', [])):
    # print all fields tab-separated
    print('\t'.join([
        d['path'], d['fstype'], d['label'], d['mnt'], d['size'], d['tran']
    ]))
PYEOF
}

# ── List mode ─────────────────────────────────────────────────────────────────
if ${LIST_MODE}; then
    found=0
    while IFS=$'\t' read -r path fstype label mnt size tran; do
        [[ "${fstype}" == "exfat" ]] || [[ "${label}" == "CITLBOOT" ]] || continue
        emit "DRIVE:${path}|${label:-unlabelled}|${size}|${mnt:-unmounted}|${fstype}|${tran:-usb}"
        found=$((found+1))
    done < <(list_all_usb_devs 2>/dev/null || true)
    [[ ${found} -eq 0 ]] && emit "NO_DRIVES"
    exit 0
fi

# ── Ensure root for mount operations ─────────────────────────────────────────
[[ "${EUID}" -eq 0 ]] || exec sudo bash "$0" "$@"

# ── ExFAT support ────────────────────────────────────────────────────────────
ensure_exfat() {
    modprobe exfat 2>/dev/null || true
    command -v mount.exfat >/dev/null 2>&1 || \
        apt-get install -y --no-install-recommends exfatprogs 2>/dev/null || \
        apt-get install -y --no-install-recommends exfat-fuse 2>/dev/null || true
}

# ── Mount a partition if not already mounted ──────────────────────────────────
mount_partition() {
    local dev="$1" type="${2:-}" label="${3:-}"
    local mnt
    mnt="$(lsblk -rno MOUNTPOINT "${dev}" 2>/dev/null | head -1)"
    if [[ -z "${mnt}" ]]; then
        mnt="/mnt/citl_fleet_$(echo "${dev}" | tr '/' '_')"
        mkdir -p "${mnt}"
        if [[ "${type}" == "exfat" ]]; then
            ensure_exfat
            mount -t exfat "${dev}" "${mnt}" 2>/dev/null || {
                log "Cannot mount ${dev} as exfat"
                echo ""
                return 1
            }
        else
            mount -r "${dev}" "${mnt}" 2>/dev/null || \
            mount    "${dev}" "${mnt}" 2>/dev/null || {
                log "Cannot mount ${dev}"
                echo ""
                return 1
            }
        fi
    fi
    echo "${mnt}"
}

# ── Find source content ───────────────────────────────────────────────────────
locate_source() {
    local src_mnt=""

    if [[ -n "${SOURCE_DEV}" ]] && [[ -b "${SOURCE_DEV}" ]]; then
        local fstype label
        fstype="$(lsblk -rno FSTYPE "${SOURCE_DEV}" 2>/dev/null | head -1)"
        label="$(lsblk -rno LABEL "${SOURCE_DEV}" 2>/dev/null | head -1)"
        src_mnt="$(mount_partition "${SOURCE_DEV}" "${fstype}" "${label}")" || \
            { log "Cannot mount source ${SOURCE_DEV}"; exit 1; }
    elif [[ -n "${SOURCE_DEV}" ]] && [[ -d "${SOURCE_DEV}" ]]; then
        src_mnt="${SOURCE_DEV}"
    else
        # Auto: find CITLBOOT or any ExFAT with citl_reimager/
        while IFS=$'\t' read -r path fstype label mnt size tran; do
            local candidate_mnt
            candidate_mnt="$(mount_partition "${path}" "${fstype}" "${label}" 2>/dev/null || true)"
            [[ -z "${candidate_mnt}" ]] && continue
            if [[ -d "${candidate_mnt}/citl_reimager" ]] || \
               [[ "${label}" == "CITLBOOT" ]]; then
                src_mnt="${candidate_mnt}"
                SOURCE_DEV="${path}"
                log "Auto-selected source: ${path} (${label:-${fstype}}) at ${src_mnt}"
                break
            fi
        done < <(list_all_usb_devs 2>/dev/null || true)
    fi

    [[ -n "${src_mnt}" ]] || { emit "FAILED:source|Cannot locate source USB"; exit 1; }

    # Find the citl_reimager dir within the source
    for candidate in \
        "${src_mnt}/citl_reimager" \
        "${src_mnt}" \
        "${SCRIPT_DIR}"; do
        [[ -f "${candidate}/citl_reimager.sh" ]] && { echo "${candidate}"; return; }
    done

    # Fallback: use script's own dir
    echo "${SCRIPT_DIR}"
}

SOURCE_CONTENT="$(locate_source)"
log "Source content: ${SOURCE_CONTENT}"

# ── Collect targets ───────────────────────────────────────────────────────────
collect_targets() {
    local src_dev_parent=""
    [[ -n "${SOURCE_DEV}" ]] && [[ -b "${SOURCE_DEV}" ]] && \
        src_dev_parent="$(lsblk -rno PKNAME "${SOURCE_DEV}" 2>/dev/null | head -1)"

    while IFS=$'\t' read -r path fstype label mnt size tran; do
        [[ "${fstype}" == "exfat" ]] || continue

        # Skip partitions on the same physical USB as the source
        local parent; parent="$(lsblk -rno PKNAME "${path}" 2>/dev/null | head -1)"
        if [[ -n "${src_dev_parent}" ]] && [[ "${parent}" == "${src_dev_parent}" ]]; then
            log "Skipping ${path} (same physical USB as source)"
            continue
        fi

        TARGET_DEVS+=("${path}")
    done < <(list_all_usb_devs 2>/dev/null || true)
}

if ${SYNC_ALL} && [[ ${#TARGET_DEVS[@]} -eq 0 ]]; then
    collect_targets
fi

if [[ ${#TARGET_DEVS[@]} -eq 0 ]]; then
    emit "FAILED:all|No target ExFAT drives found. Connect USB drives and retry."
    exit 1
fi

log "Targets (${#TARGET_DEVS[@]}): ${TARGET_DEVS[*]}"

# ── Sync one target ────────────────────────────────────────────────────────────
sync_one_target() {
    local dev="$1"
    local fstype label tgt_mnt

    fstype="$(lsblk -rno FSTYPE "${dev}" 2>/dev/null | head -1)"
    label="$(lsblk -rno LABEL  "${dev}" 2>/dev/null | head -1)"

    emit "PROGRESS:${dev}|5|Mounting ${dev}..."

    tgt_mnt="$(mount_partition "${dev}" "${fstype}" "${label}")" || {
        emit "FAILED:${dev}|Cannot mount ${dev}"
        return 1
    }

    local dest="${tgt_mnt}/citl_reimager"
    mkdir -p "${dest}"

    if ${DRY_RUN}; then
        emit "PROGRESS:${dev}|50|DRY RUN — would sync ${SOURCE_CONTENT} → ${dest}"
        sleep 1
        emit "DONE:${dev}|DRY_RUN"
        return 0
    fi

    emit "PROGRESS:${dev}|15|Syncing scripts (${SOURCE_CONTENT} → ${dest})..."

    # rsync with progress parsing
    rsync -a --delete \
          --exclude='__pycache__' --exclude='*.pyc' \
          "${SOURCE_CONTENT}/" "${dest}/" 2>&1 | \
        grep -v "^sending\|^total\|^sent" || \
        cp -r "${SOURCE_CONTENT}/." "${dest}/" 2>/dev/null || {
            emit "FAILED:${dev}|rsync/cp failed"
            return 1
        }

    emit "PROGRESS:${dev}|70|Setting permissions..."
    chmod -R a+rX "${dest}" 2>/dev/null || true
    find "${dest}" -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true

    # Write MANIFEST
    emit "PROGRESS:${dev}|85|Writing manifest..."
    cat > "${dest}/MANIFEST.txt" <<MANI
CITL Reimager Fleet Sync
Synced    : $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Source USB: ${SOURCE_DEV:-${SOURCE_CONTENT}}
Target    : ${dev}  (${label:-unlabelled})
Files     : $(find "${dest}" -type f 2>/dev/null | wc -l)
MANI

    local parent sibling_boot sibling_boot_mnt payload_status
    parent="$(lsblk -rno PKNAME "${dev}" 2>/dev/null | head -1)"
    sibling_boot=""
    sibling_boot_mnt=""
    if [[ -n "${parent}" ]]; then
        sibling_boot="$(lsblk -rno PATH,LABEL "/dev/${parent}" 2>/dev/null | \
            awk '$2=="CITLBOOT"{print $1}' | head -1)"
        if [[ -n "${sibling_boot}" ]]; then
            sibling_boot_mnt="$(mount_partition "${sibling_boot}" "vfat" "CITLBOOT" 2>/dev/null || true)"
        fi
    fi

    if declare -F citl_payload_write_status >/dev/null 2>&1; then
        payload_status="$(citl_payload_write_status "${dest}" "${sibling_boot_mnt:-}" "${tgt_mnt}" 2>/dev/null || true)"
        emit "PROGRESS:${dev}|88|Boot payload status: ${payload_status:-UNKNOWN}"
    fi

    # Fix GRUB on ExFAT-sibling CITLBOOT partitions
    emit "PROGRESS:${dev}|90|Checking for GRUB fix opportunity..."
    if [[ -n "${parent}" ]]; then
        if [[ -n "${sibling_boot}" ]] && [[ -x "${dest}/fix_usb_grub.sh" ]]; then
            if bash "${dest}/fix_usb_grub.sh" "/dev/${parent}" --quiet 2>/dev/null; then
                emit "PROGRESS:${dev}|95|GRUB config verified on /dev/${parent}"
            else
                log "GRUB fix skipped on /dev/${parent} (missing ESP or boot payload)"
                emit "PROGRESS:${dev}|95|GRUB fix skipped; check CITL_BOOT_PAYLOAD_STATUS.txt"
            fi
        fi
    fi

    sync
    emit "PROGRESS:${dev}|100|Done."
    emit "DONE:${dev}|SUCCESS|${label:-unlabelled}|$(date -u +"%H:%M:%SZ")"
}

# ── Parallel fleet sync ────────────────────────────────────────────────────────
N_OK=0; N_FAIL=0
PIDS=()

for tgt_dev in "${TARGET_DEVS[@]}"; do
    # Throttle parallelism
    while [[ ${#PIDS[@]} -ge ${PARALLEL_MAX} ]]; do
        for i in "${!PIDS[@]}"; do
            if ! kill -0 "${PIDS[${i}]}" 2>/dev/null; then
                wait "${PIDS[${i}]}" 2>/dev/null && N_OK=$((N_OK+1)) || N_FAIL=$((N_FAIL+1))
                unset 'PIDS[i]'
                PIDS=("${PIDS[@]}")
                break
            fi
        done
        sleep 0.3
    done

    (
        sync_one_target "${tgt_dev}" || emit "FAILED:${tgt_dev}|sync_one_target returned error"
    ) &
    PIDS+=($!)
done

# Wait for remaining jobs
for pid in "${PIDS[@]}"; do
    wait "${pid}" 2>/dev/null && N_OK=$((N_OK+1)) || N_FAIL=$((N_FAIL+1))
done

emit "FLEET_DONE:${N_OK}/${#TARGET_DEVS[@]}|FAILED:${N_FAIL}"
[[ ${N_FAIL} -eq 0 ]] && exit 0 || exit 1
