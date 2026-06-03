#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# fix_usb_grub.sh  —  CITL USB GRUB Repair Tool
# Run ON the mainframe (citl-mainframe2) while the target USB is plugged in.
#
# Usage:
#   sudo bash fix_usb_grub.sh /dev/sdb [--quiet]
#
# What it does:
#   1. Finds the ESP and CITLBOOT partitions on the USB
#   2. Installs GRUB EFI to the USB (--removable, never touches host NVRAM)
#   3. Writes a label-based grub.cfg that survives UUID changes and ExFAT additions
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRUB_CFG_SRC="${SCRIPT_DIR}/grub.cfg"
QUIET=false

# ── Argument check ────────────────────────────────────────────────────────────
USB_DEV=""
for arg in "$@"; do
    case "${arg}" in
        --quiet) QUIET=true;;
        /dev/*) USB_DEV="${arg}";;
    esac
done

log() { ${QUIET} || echo "$*"; }

if [[ -z "${USB_DEV}" ]]; then
    log "Usage: sudo bash $0 /dev/sdX [--quiet]"
    log "       (the whole USB device — e.g. /dev/sdb, NOT a partition)"
    lsblk -o NAME,SIZE,LABEL,FSTYPE,MOUNTPOINT 2>/dev/null | grep -v loop || true
    exit 1
fi

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: Must run as root."; exit 1; }
[[ -b "${USB_DEV}" ]] || { echo "ERROR: ${USB_DEV} is not a block device."; exit 1; }

# Safety: refuse host drives (sda, nvme0n1 typically)
HOST_BOOT="$(findmnt -no SOURCE /boot/efi 2>/dev/null || findmnt -no SOURCE / 2>/dev/null || true)"
HOST_DISK="$(lsblk -rno PKNAME "${HOST_BOOT}" 2>/dev/null | head -1 || true)"
if [[ "/dev/${HOST_DISK}" == "${USB_DEV}" ]] || \
   [[ "${HOST_BOOT}" == "${USB_DEV}" ]]; then
    echo "ERROR: ${USB_DEV} appears to be the host boot drive — refusing."
    exit 1
fi

log "════════════════════════════════════════════════════════"
log "  CITL USB GRUB Repair  →  ${USB_DEV}"
log "════════════════════════════════════════════════════════"
lsblk -o NAME,SIZE,LABEL,FSTYPE,MOUNTPOINT "${USB_DEV}" 2>/dev/null || true
log ""

# ── Find partitions (handles sda1 AND nvme0n1p1 and mmcblk0p1 naming) ────────
CITLBOOT_PART=""
ESP_PART=""

# Build partition glob that works for both /dev/sdb and /dev/nvme0n1
if [[ "${USB_DEV}" =~ (nvme|mmcblk) ]]; then
    PART_GLOB="${USB_DEV}p[0-9]*"
else
    PART_GLOB="${USB_DEV}[0-9]*"
fi

# Use lsblk JSON for reliable per-partition data
part_info="$(lsblk -J -o PATH,LABEL,FSTYPE,PARTTYPE "${USB_DEV}" 2>/dev/null | \
    python3 -c "
import json,sys
data=json.load(sys.stdin)
def flat(devs,acc=None):
    if acc is None: acc=[]
    for d in devs:
        acc.append(d)
        flat(d.get('children',[]),acc)
    return acc
for d in flat(data.get('blockdevices',[])):
    p=d.get('path',''); l=d.get('label','') or ''; f=d.get('fstype','') or ''
    pt=d.get('parttype','') or ''
    print(f'{p}\t{l}\t{f}\t{pt}')
" 2>/dev/null || true)"

while IFS=$'\t' read -r path label fstype parttype; do
    [[ "${path}" == "${USB_DEV}" ]] && continue   # skip the whole device row
    if [[ "${label}" == "CITLBOOT" ]]; then
        CITLBOOT_PART="${path}"
    fi
    if [[ "${label}" == "ESP" ]] || \
       [[ "${parttype}" == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" ]] || \
       [[ "${parttype}" == "C12A7328-F81F-11D2-BA4B-00A0C93EC93B" ]]; then
        ESP_PART="${path}"
    fi
done <<< "${part_info}"

# Fallback: scan glob for FAT partitions if lsblk JSON empty
if [[ -z "${CITLBOOT_PART}" ]] || [[ -z "${ESP_PART}" ]]; then
    for part in ${PART_GLOB}; do
        [[ -b "${part}" ]] || continue
        local_label="$(lsblk -rno LABEL "${part}" 2>/dev/null || true)"
        local_fstype="$(lsblk -rno FSTYPE "${part}" 2>/dev/null || true)"
        [[ "${local_label}" == "CITLBOOT" ]] && CITLBOOT_PART="${part}"
        if [[ -z "${ESP_PART}" ]] && [[ "${local_fstype}" == "vfat" ]]; then
            ESP_PART="${part}"
        fi
    done
fi

# If still no CITLBOOT — use first FAT32 and warn
if [[ -z "${CITLBOOT_PART}" ]]; then
    log "WARNING: No CITLBOOT partition found. Using first FAT32 partition."
    for part in ${PART_GLOB}; do
        [[ -b "${part}" ]] || continue
        local_fstype="$(lsblk -rno FSTYPE "${part}" 2>/dev/null || true)"
        if [[ "${local_fstype}" == "vfat" ]]; then
            CITLBOOT_PART="${part}"; break
        fi
    done
fi

echo "  CITLBOOT partition : ${CITLBOOT_PART:-NOT FOUND}"
echo "  ESP partition      : ${ESP_PART:-NOT FOUND}"
echo ""

# ── Mount points ──────────────────────────────────────────────────────────────
MNT_CITL="/mnt/citl_boot_repair/citlboot"
MNT_ESP="/mnt/citl_boot_repair/esp"
mkdir -p "${MNT_CITL}" "${MNT_ESP}"

cleanup() {
    echo ""
    echo "[cleanup] Unmounting..."
    umount "${MNT_CITL}" 2>/dev/null || true
    umount "${MNT_ESP}" 2>/dev/null || true
    rmdir "${MNT_CITL}" "${MNT_ESP}" /mnt/citl_boot_repair 2>/dev/null || true
}
trap cleanup EXIT

# ── Mount CITLBOOT partition ──────────────────────────────────────────────────
if [[ -n "${CITLBOOT_PART}" ]]; then
    echo "[1/4] Mounting CITLBOOT → ${MNT_CITL}"
    mount -t vfat -o uid=0,gid=0,umask=022 "${CITLBOOT_PART}" "${MNT_CITL}" 2>/dev/null || \
    mount "${CITLBOOT_PART}" "${MNT_CITL}"

    # Write grub.cfg to the main partition (GRUB searches here too)
    mkdir -p "${MNT_CITL}/boot/grub"
    cp "${GRUB_CFG_SRC}" "${MNT_CITL}/boot/grub/grub.cfg"
    echo "    → grub.cfg written to CITLBOOT/boot/grub/grub.cfg"

    # Copy CITL reimager scripts
    mkdir -p "${MNT_CITL}/opt/citl"
    cp -r "${SCRIPT_DIR}/"*.sh "${MNT_CITL}/opt/citl/" 2>/dev/null || true
    chmod +x "${MNT_CITL}/opt/citl/"*.sh 2>/dev/null || true
    echo "    → CITL reimager scripts copied to CITLBOOT/opt/citl/"
fi

# ── Mount ESP and fix GRUB ────────────────────────────────────────────────────
if [[ -n "${ESP_PART}" ]]; then
    echo "[2/4] Mounting ESP → ${MNT_ESP}"
    mount -t vfat "${ESP_PART}" "${MNT_ESP}"

    # Write grub.cfg to ESP as well (GRUB EFI looks here first)
    mkdir -p "${MNT_ESP}/boot/grub"
    mkdir -p "${MNT_ESP}/EFI/ubuntu"
    cp "${GRUB_CFG_SRC}" "${MNT_ESP}/boot/grub/grub.cfg"
    cp "${GRUB_CFG_SRC}" "${MNT_ESP}/EFI/ubuntu/grub.cfg"
    echo "    → grub.cfg written to ESP/boot/grub/grub.cfg"
    echo "    → grub.cfg written to ESP/EFI/ubuntu/grub.cfg"
fi

# ── Install GRUB EFI to the USB device ───────────────────────────────────────
if [[ -n "${ESP_PART}" ]]; then
    echo "[3/4] Installing GRUB EFI to USB (not host machine)..."
    grub-install \
        --target=x86_64-efi \
        --efi-directory="${MNT_ESP}" \
        --boot-directory="${MNT_CITL}/boot" \
        --removable \
        --no-nvram \
        "${USB_DEV}"
    echo "    → GRUB EFI installed."

    # Overwrite the auto-generated grub.cfg with our label-based one
    cp "${GRUB_CFG_SRC}" "${MNT_CITL}/boot/grub/grub.cfg"
    echo "    → Restored label-based grub.cfg (grub-install overwrites it)."
else
    echo "[3/4] No ESP found — skipping grub-install. Manual fix needed."
fi

# ── Sync and done ─────────────────────────────────────────────────────────────
echo "[4/4] Syncing writes to USB..."
sync
echo ""
echo "════════════════════════════════════════════════════════"
echo "  DONE — USB should now boot to GRUB menu."
echo "  If GRUB shell still appears, run from shell:"
echo ""
echo "    grub> search --label CITLBOOT"
echo "    grub> set root=(<found partition>)"
echo "    grub> configfile /boot/grub/grub.cfg"
echo "════════════════════════════════════════════════════════"
