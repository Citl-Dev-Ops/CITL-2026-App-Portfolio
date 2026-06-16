#!/usr/bin/env bash
# CITL boot payload guard
#
# Keeps fleet USBs from being marked "boot repaired" when the Ubuntu live
# payload has been removed.  A bootable CITL USB needs either:
#   - a casper payload on the CITLBOOT partition, or
#   - an offline squashfs/ISO payload on the data partition for repair scripts.

citl_payload_log() {
    if [[ "${CITL_PAYLOAD_QUIET:-false}" != "true" ]]; then
        echo "[CITL-PAYLOAD] $*" >&2
    fi
}

citl_payload_has_casper() {
    local mount_dir="$1"
    [[ -n "${mount_dir}" ]] || return 1
    [[ -f "${mount_dir}/casper/vmlinuz" ]] || [[ -f "${mount_dir}/casper/vmlinuz.efi" ]] || return 1
    [[ -f "${mount_dir}/casper/initrd" ]] || [[ -f "${mount_dir}/casper/initrd.lz" ]] || return 1
    [[ -f "${mount_dir}/casper/filesystem.squashfs" ]] || return 1
}

citl_payload_has_offline_base() {
    local mount_dir="$1"
    local iso_path=""
    [[ -n "${mount_dir}" ]] || return 1
    [[ -d "${mount_dir}" ]] || return 1
    [[ -f "${mount_dir}/ubuntu-base/filesystem.squashfs" ]] && return 0
    iso_path="$(find "${mount_dir}" -maxdepth 3 -type f \
        \( -iname 'ubuntu-24*.iso' -o -iname 'ubuntu*24*.iso' -o -iname '*ubuntu*desktop*.iso' \) \
        -print -quit 2>/dev/null || true)"
    [[ -n "${iso_path}" ]]
}

citl_payload_status() {
    local citlboot_mount="${1:-}"
    local data_mount="${2:-}"
    if citl_payload_has_casper "${citlboot_mount}"; then
        echo "OK:casper:${citlboot_mount}"
        return 0
    fi
    if citl_payload_has_offline_base "${data_mount}"; then
        echo "OK:offline:${data_mount}"
        return 0
    fi
    echo "MISSING:${citlboot_mount:-none}:${data_mount:-none}"
    return 1
}

citl_payload_write_missing_notice() {
    local mount_dir="$1"
    [[ -n "${mount_dir}" ]] || return 0
    mkdir -p "${mount_dir}" 2>/dev/null || true
    cat > "${mount_dir}/CITL_BOOT_PAYLOAD_MISSING.txt" <<'NOTICE'
CITL boot payload missing

This USB has CITL tooling, but the Ubuntu live/recovery payload is absent.
That means GRUB can load, but the "Ubuntu 24.04 / CITL Reimager" entries
cannot complete boot or re-imaging.

Restore one of these before declaring the USB boot-ready:
  1. CITLBOOT/casper/vmlinuz
  2. CITLBOOT/casper/initrd
  3. CITLBOOT/casper/filesystem.squashfs

Or place an Ubuntu 24.04 desktop ISO / offline squashfs on the data partition:
  - <data>/ubuntu-24*.iso
  - <data>/CITL_Images/ubuntu-24*.iso
  - <data>/ubuntu-base/filesystem.squashfs

Do not run manual grub-install against /boot/efi.  Use CITL's guarded repair
scripts so host EFI partitions are not modified.
NOTICE
}

citl_payload_write_status() {
    local status_dir="$1"
    local citlboot_mount="${2:-}"
    local data_mount="${3:-}"
    local status=""
    [[ -n "${status_dir}" ]] || return 0
    mkdir -p "${status_dir}" 2>/dev/null || true
    status="$(citl_payload_status "${citlboot_mount}" "${data_mount}" 2>/dev/null || true)"
    cat > "${status_dir}/CITL_BOOT_PAYLOAD_STATUS.txt" <<STATUS
CITL boot payload status

Checked UTC : $(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date)
Status      : ${status}
CITLBOOT    : ${citlboot_mount:-not mounted}
Data mount  : ${data_mount:-not mounted}

Boot-ready requires CITLBOOT/casper/vmlinuz, CITLBOOT/casper/initrd, and
CITLBOOT/casper/filesystem.squashfs. An offline Ubuntu ISO/squashfs on the
data partition can support repair/reimage work, but it does not replace the
CITLBOOT casper boot payload unless GRUB is explicitly configured for it.
STATUS
    if [[ "${status}" == MISSING:* ]]; then
        citl_payload_write_missing_notice "${citlboot_mount}"
    fi
    echo "${status}"
}

citl_payload_require() {
    local citlboot_mount="${1:-}"
    local data_mount="${2:-}"
    local status
    status="$(citl_payload_status "${citlboot_mount}" "${data_mount}")" && {
        citl_payload_log "boot payload ${status}"
        return 0
    }
    citl_payload_write_missing_notice "${citlboot_mount}"
    citl_payload_log "boot payload missing; wrote CITL_BOOT_PAYLOAD_MISSING.txt"
    echo "ERROR: CITL boot payload missing. Restore casper files or Ubuntu ISO before marking USB boot-ready." >&2
    return 1
}

citl_payload_require_bootable() {
    local citlboot_mount="${1:-}"
    local data_mount="${2:-}"
    if citl_payload_has_casper "${citlboot_mount}"; then
        citl_payload_log "bootable casper payload found on ${citlboot_mount}"
        return 0
    fi
    citl_payload_write_missing_notice "${citlboot_mount}"
    citl_payload_write_status "${citlboot_mount}" "${citlboot_mount}" "${data_mount}" >/dev/null 2>&1 || true
    if citl_payload_has_offline_base "${data_mount}"; then
        echo "ERROR: Offline Ubuntu payload found on data partition, but CITLBOOT/casper is missing." >&2
        echo "Restore casper/vmlinuz, casper/initrd, and casper/filesystem.squashfs before marking this USB boot-ready." >&2
    else
        echo "ERROR: CITLBOOT/casper boot payload missing. GRUB would drop to shell." >&2
    fi
    return 1
}
