#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# preflight_check.sh  —  CITL Reimager Boot Preflight
# Run FIRST at Ubuntu live boot before any reimager or fleet sync operation.
#
# Usage:
#   sudo bash preflight_check.sh [--fix] [--quiet]
#   --fix   : attempt to install missing tools via apt (requires internet)
#   --quiet : machine-readable output only (PASS/FAIL:tool lines)
#
# Exit code: 0 = all clear, 1 = missing required tools (--fix failed)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_GUARD="${SCRIPT_DIR}/boot_payload_guard.sh"
[[ -f "${PAYLOAD_GUARD}" ]] && source "${PAYLOAD_GUARD}"

FIX=false; QUIET=false
for arg in "$@"; do
    case "${arg}" in --fix) FIX=true;; --quiet) QUIET=true;; esac
done

GRN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[0;33m'; RST='\033[0m'
ok()   { ${QUIET} && echo "PASS:$1" || echo -e "${GRN}[PASS]${RST} $1: $2"; }
fail() { ${QUIET} && echo "FAIL:$1" || echo -e "${RED}[FAIL]${RST} $1: $2"; }
warn() { ${QUIET} && echo "WARN:$1" || echo -e "${YEL}[WARN]${RST} $1: $2"; }

MISSING_REQUIRED=()
MISSING_OPTIONAL=()

check() {
    local name="$1" cmd="$2" pkg="${3:-}" req="${4:-required}"
    if command -v "${cmd}" >/dev/null 2>&1; then
        ok "${name}" "$(command -v "${cmd}")"
    else
        if [[ "${req}" == "required" ]]; then
            fail "${name}" "not found${pkg:+ — package: ${pkg}}"
            MISSING_REQUIRED+=("${pkg:-${cmd}}")
        else
            warn "${name}" "not found (optional)${pkg:+ — package: ${pkg}}"
            MISSING_OPTIONAL+=("${pkg:-${cmd}}")
        fi
    fi
}

check_mount_exfat() {
    # Ubuntu 22.04+: exfatprogs (kernel native)  |  Ubuntu 20.04: exfat-fuse
    if mount --help 2>&1 | grep -q exfat || \
       command -v mount.exfat >/dev/null 2>&1 || \
       modinfo exfat >/dev/null 2>&1; then
        ok "exfat-mount" "kernel/fuse support present"
    else
        fail "exfat-mount" "no ExFAT mount support — install exfatprogs or exfat-fuse"
        MISSING_REQUIRED+=("exfatprogs")
    fi
}

check_efi_mode() {
    if [[ -d /sys/firmware/efi ]]; then
        ok "EFI-mode" "booted in UEFI mode"
    else
        warn "EFI-mode" "booted in BIOS/legacy mode — UEFI targets will still work if you use grub-install --target=x86_64-efi"
    fi
}

check_root() {
    if [[ "${EUID}" -eq 0 ]]; then
        ok "root" "running as root"
    else
        fail "root" "must run as root (sudo bash $0)"
        exit 1
    fi
}

check_boot_payload_visibility() {
    declare -F citl_payload_status >/dev/null 2>&1 || return 0
    local citlboot_mnt="" exfat_mnt="" status="" candidate=""
    for candidate in /run/live/medium /cdrom; do
        if [[ -d "${candidate}/casper" ]]; then
            citlboot_mnt="${candidate}"
            break
        fi
    done
    if [[ -z "${citlboot_mnt}" ]]; then
        citlboot_mnt="$(lsblk -rno LABEL,MOUNTPOINT 2>/dev/null | \
            awk '$1=="CITLBOOT" && $2!="" {print $2; exit}')"
    fi
    exfat_mnt="$(lsblk -rno FSTYPE,MOUNTPOINT 2>/dev/null | \
        awk '$1=="exfat" && $2!="" {print $2; exit}')"
    status="$(citl_payload_status "${citlboot_mnt:-}" "${exfat_mnt:-}" 2>/dev/null || true)"
    if [[ "${status}" == OK:* ]]; then
        ok "boot-payload" "${status}"
    else
        warn "boot-payload" "not visible yet (${status:-UNKNOWN}); reimager will stop before target selection if no payload is found"
    fi
}

${QUIET} || echo -e "\n${GRN}══ CITL Reimager Preflight Check ══${RST}\n"

check_root

# ── Required tools ────────────────────────────────────────────────────────────
check "bash"         bash         ""              required
check "sgdisk"       sgdisk       gdisk           required
check "mkfs.fat"     mkfs.fat     dosfstools      required
check "mkfs.ext4"    mkfs.ext4    e2fsprogs       required
check "blkid"        blkid        util-linux      required
check "wipefs"       wipefs       util-linux      required
check "partprobe"    partprobe    parted          required
check "grub-install" grub-install grub-efi-amd64  required
check "lsblk"        lsblk        util-linux      required
check "findmnt"      findmnt      util-linux      required
check "rsync"        rsync        rsync           required
check "unsquashfs"   unsquashfs   squashfs-tools  required
check_mount_exfat
check_efi_mode
check_boot_payload_visibility

# ── Optional tools ────────────────────────────────────────────────────────────
check "debootstrap"  debootstrap  debootstrap     optional
check "pv"           pv           pv              optional
check "curl"         curl         curl            optional
check "wget"         wget         wget            optional
check "ollama"       ollama       ""              optional

# ── Kernel ExFAT module ───────────────────────────────────────────────────────
if modprobe exfat 2>/dev/null; then
    ok "exfat-kmod" "loaded"
else
    warn "exfat-kmod" "cannot load — trying fuse fallback"
    modprobe fuse 2>/dev/null || true
fi

# ── Fix missing tools ─────────────────────────────────────────────────────────
if [[ ${#MISSING_REQUIRED[@]} -gt 0 ]] && ${FIX}; then
    ${QUIET} || echo -e "\n${YEL}Installing missing required tools...${RST}"

    # Detect internet
    if curl -s --connect-timeout 3 http://archive.ubuntu.com/ubuntu/ >/dev/null 2>&1 || \
       wget -q --spider --timeout=3 http://archive.ubuntu.com/ubuntu/ 2>/dev/null; then
        apt-get update -qq 2>/dev/null || true
        apt-get install -y --no-install-recommends \
            "${MISSING_REQUIRED[@]}" 2>/dev/null && \
            ok "apt-install" "installed: ${MISSING_REQUIRED[*]}" || \
            fail "apt-install" "some packages failed to install"
    else
        fail "internet" "no internet — cannot install missing tools"
        ${QUIET} || echo ""
        ${QUIET} || echo "  Manual fix on a connected machine:"
        ${QUIET} || echo "    apt-get install ${MISSING_REQUIRED[*]}"
        ${QUIET} || echo ""
        ${QUIET} || echo "  Or copy an offline package cache to /var/cache/apt/archives/"
        exit 1
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
${QUIET} || echo ""
if [[ ${#MISSING_REQUIRED[@]} -eq 0 ]]; then
    ${QUIET} || echo -e "${GRN}All required tools present. Safe to run citl_reimager.sh.${RST}"
    echo "PREFLIGHT:OK"
    exit 0
else
    ${QUIET} || echo -e "${RED}Missing required tools: ${MISSING_REQUIRED[*]}${RST}"
    ${QUIET} || echo -e "${YEL}Run with --fix to attempt installation.${RST}"
    echo "PREFLIGHT:FAIL:${MISSING_REQUIRED[*]}"
    exit 1
fi
