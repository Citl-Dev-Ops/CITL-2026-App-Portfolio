#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# citl_reimager.sh  —  CITL Station Reimager CLI  v2.1
# Renton Technical College — Center for Innovative Teaching and Learning
#
# Boot from CITLBOOT USB into Ubuntu 24.04 live, then run:
# Usage:
#   sudo bash citl_reimager.sh [--profile lean|standard|full]
#                              [--target /dev/sdX] [--hostname NAME]
#                              [--allow-internet-bootstrap]
#
#
# Profiles:
#   lean     — Ubuntu minimal + phi3:mini             (16 GB+ drive)
#   standard — Ubuntu + mistral:7b + Factbook + FLEX  (64 GB+ drive)
#   full     — standard + OLMo2 7B + Molmo vision     (128 GB+ drive)
#
# Source priority (squashfs):
#   1) CITLBOOT/casper/filesystem.squashfs   (on-USB, offline)
#   2) any-ExFAT-drive/ubuntu-base/filesystem.squashfs (offline cache)
#   3) debootstrap over internet             (explicit operator approval only)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
# NOTE: IFS left at default — changing IFS breaks read/awk/arrays in subtle ways

CITL_VERSION="2.1"
UBUNTU_CODENAME="noble"   # 24.04
CITL_USER="citl"
CITL_PASS="CITL2024!"     # forced change on first login

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_GUARD="${SCRIPT_DIR}/boot_payload_guard.sh"
[[ -f "${PAYLOAD_GUARD}" ]] && source "${PAYLOAD_GUARD}"
ALLOW_INTERNET_BOOTSTRAP=false

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'
CYN='\033[0;36m'; BLD='\033[1m'; RST='\033[0m'
die()  { echo -e "\n${RED}${BLD}FATAL: $*${RST}" >&2; exit 1; }
info() { echo -e "${GRN}[OK]${RST}   $*"; }
warn() { echo -e "${YEL}[WARN]${RST} $*"; }
step() { echo -e "\n${CYN}${BLD}══ $* ══${RST}"; }

# All interactive input MUST read from /dev/tty — not from stdin,
# which may be piped or a subprocess in GUI mode.
ask() {
    local _reply=""
    read -rp "$(echo -e "${BLD}  $* ${RST}")" _reply </dev/tty || true
    echo "${_reply}"
}
confirm() {
    local yn; yn="$(ask "$1 [y/N]:")"
    [[ "${yn,,}" == "y" ]]
}

banner() {
    clear
    echo -e "${CYN}${BLD}"
    echo "  ╔══════════════════════════════════════════════════════════════╗"
    echo "  ║   CITL Station Reimager v${CITL_VERSION}                               ║"
    echo "  ║   Renton Technical College — CITL                           ║"
    echo "  ╚══════════════════════════════════════════════════════════════╝"
    echo -e "${RST}"
}

# ── Elevation ─────────────────────────────────────────────────────────────────
[[ "${EUID}" -eq 0 ]] || exec sudo bash "$0" "$@"

# ── Preflight ─────────────────────────────────────────────────────────────────
run_preflight() {
    local pf="${SCRIPT_DIR}/preflight_check.sh"
    if [[ -x "${pf}" ]]; then
        bash "${pf}" --fix || {
            warn "Preflight reported missing tools. Continuing anyway."
        }
    else
        warn "preflight_check.sh not found — skipping dependency check."
    fi
}

# ── ExFAT support ────────────────────────────────────────────────────────────
ensure_exfat() {
    modprobe exfat 2>/dev/null || modprobe fuse 2>/dev/null || true
    if ! command -v mount.exfat >/dev/null 2>&1; then
        apt-get install -y --no-install-recommends exfatprogs 2>/dev/null || \
        apt-get install -y --no-install-recommends exfat-fuse 2>/dev/null || true
    fi
}

# ── Locate source media ───────────────────────────────────────────────────────
# Sets globals: CITLBOOT_DEV, CITLBOOT_MNT, EXFAT_DEV, EXFAT_MNT, SQUASHFS
locate_sources() {
    CITLBOOT_DEV=""; CITLBOOT_MNT=""; EXFAT_DEV=""; EXFAT_MNT=""; SQUASHFS=""

    # Use lsblk JSON for reliable multi-column output (no column-shift issues)
    local blk_json
    blk_json="$(lsblk -J -o PATH,FSTYPE,LABEL,MOUNTPOINT 2>/dev/null || echo '{}')"

    # Parse with python3 (always present in Ubuntu live)
    local parse_result
    parse_result="$(python3 - <<PYEOF
import json, sys
data = json.loads('''${blk_json}''')
devs = data.get('blockdevices', [])

def flat(devs, acc=None):
    if acc is None: acc = []
    for d in devs:
        acc.append(d)
        flat(d.get('children', []), acc)
    return acc

for d in flat(devs):
    label   = (d.get('label')      or '').strip()
    fstype  = (d.get('fstype')     or '').strip()
    path    = (d.get('path')       or '').strip()
    mnt     = (d.get('mountpoint') or '').strip()
    if label == 'CITLBOOT':
        print(f'CITLBOOT:{path}:{mnt}')
    if fstype == 'exfat':
        print(f'EXFAT:{path}:{mnt}')
PYEOF
    )" 2>/dev/null || true

    while IFS=: read -r kind dev mnt; do
        case "${kind}" in
            CITLBOOT)
                CITLBOOT_DEV="${dev}"
                CITLBOOT_MNT="${mnt}"
                ;;
            EXFAT)
                [[ -z "${EXFAT_DEV}" ]] && EXFAT_DEV="${dev}" && EXFAT_MNT="${mnt}"
                ;;
        esac
    done <<< "${parse_result}"

    # Mount CITLBOOT if found but not mounted
    if [[ -n "${CITLBOOT_DEV}" ]] && [[ -z "${CITLBOOT_MNT}" ]]; then
        CITLBOOT_MNT="/mnt/citl_src_boot"
        mkdir -p "${CITLBOOT_MNT}"
        mount -r "${CITLBOOT_DEV}" "${CITLBOOT_MNT}" 2>/dev/null || CITLBOOT_MNT=""
    fi

    # Also check casper from live ISO mount path
    for live_path in /run/live/medium /cdrom "${CITLBOOT_MNT}"; do
        [[ -z "${live_path}" ]] && continue
        [[ -f "${live_path}/casper/filesystem.squashfs" ]] && \
            SQUASHFS="${live_path}/casper/filesystem.squashfs" && break
    done

    # Mount ExFAT if found but not mounted
    if [[ -n "${EXFAT_DEV}" ]] && [[ -z "${EXFAT_MNT}" ]]; then
        ensure_exfat
        EXFAT_MNT="/mnt/citl_exfat_src"
        mkdir -p "${EXFAT_MNT}"
        mount -t exfat "${EXFAT_DEV}" "${EXFAT_MNT}" 2>/dev/null || EXFAT_MNT=""
    fi

    # ExFAT offline squashfs cache
    if [[ -z "${SQUASHFS}" ]] && [[ -n "${EXFAT_MNT}" ]]; then
        [[ -f "${EXFAT_MNT}/ubuntu-base/filesystem.squashfs" ]] && \
            SQUASHFS="${EXFAT_MNT}/ubuntu-base/filesystem.squashfs"
    fi

    echo ""
    info "CITLBOOT  : ${CITLBOOT_MNT:-NOT FOUND}"
    info "ExFAT src : ${EXFAT_MNT:-NOT FOUND}"
    info "Squashfs  : ${SQUASHFS:-NOT FOUND — restore payload or approve internet bootstrap}"
    if declare -F citl_payload_status >/dev/null 2>&1; then
        local payload_status
        payload_status="$(citl_payload_status "${CITLBOOT_MNT:-}" "${EXFAT_MNT:-}" 2>/dev/null || true)"
        info "Payload   : ${payload_status:-UNKNOWN}"
    fi
}

validate_boot_payload_plan() {
    [[ -n "${SQUASHFS:-}" ]] && [[ -f "${SQUASHFS}" ]] && return 0

    if [[ "${ALLOW_INTERNET_BOOTSTRAP}" == "true" ]]; then
        warn "No offline Ubuntu payload found; internet debootstrap fallback was explicitly enabled."
        return 0
    fi

    warn "No offline Ubuntu payload was found on CITLBOOT or ExFAT."
    warn "This usually means Ubuntu live/recovery files were removed from the USB."
    if confirm "Use internet debootstrap fallback instead of a local Ubuntu payload?"; then
        ALLOW_INTERNET_BOOTSTRAP=true
        warn "Internet bootstrap approved for this run."
        return 0
    fi

    if declare -F citl_payload_write_missing_notice >/dev/null 2>&1; then
        citl_payload_write_missing_notice "${CITLBOOT_MNT:-}" || true
    fi
    die "Ubuntu payload missing. Restore CITLBOOT/casper/* or ubuntu-base/filesystem.squashfs before reimaging."
}

# ── Drive list + picker ───────────────────────────────────────────────────────
list_drives() {
    echo ""
    echo -e "${BLD}  Connected drives:${RST}"
    echo "  ──────────────────────────────────────────────────────────────"
    lsblk -o NAME,SIZE,MODEL,TRAN,FSTYPE,MOUNTPOINT --nodeps --exclude 7,11 \
          2>/dev/null || lsblk -o NAME,SIZE,TYPE --nodeps
    echo "  ──────────────────────────────────────────────────────────────"
}

pick_target() {
    local hint="${1:-}"
    local dev=""

    list_drives

    if [[ -n "${hint}" ]] && [[ -b "${hint}" ]]; then
        dev="${hint}"
        warn "Auto-target: ${dev}"
    else
        local raw; raw="$(ask "Target drive (e.g. sda, nvme0n1 — no /dev/ prefix):")"
        dev="/dev/${raw#/dev/}"
    fi

    [[ -b "${dev}" ]] || die "${dev} is not a block device."

    # Safety: refuse source USB
    if [[ -n "${CITLBOOT_DEV:-}" ]]; then
        local src_disk
        src_disk="$(lsblk -no PKNAME "${CITLBOOT_DEV}" 2>/dev/null || true)"
        [[ "/dev/${src_disk}" == "${dev}" ]] && \
            die "That is the CITLBOOT source USB. Choose a different drive."
    fi

    echo "${dev}"
}

pick_profile() {
    local preset="${1:-}"
    [[ "${preset}" =~ ^(lean|standard|full)$ ]] && { echo "${preset}"; return; }

    echo ""
    echo -e "${BLD}  Imaging profiles:${RST}"
    echo "  ─────────────────────────────────────────────────────────────────"
    echo "  1) lean      — Ubuntu minimal + phi3:mini       [16 GB+ drive]"
    echo "  2) standard  — Ubuntu + mistral:7b + Factbook   [64 GB+ drive]  ← recommended"
    echo "  3) full      — standard + OLMo2 7B + Molmo      [128 GB+ drive]"
    echo "  ─────────────────────────────────────────────────────────────────"
    local c; c="$(ask "Profile [1/2/3, default=2]:")"
    case "${c}" in
        1|lean)     echo "lean";;
        3|full)     echo "full";;
        *)          echo "standard";;
    esac
}

# ── Partition ──────────────────────────────────────────────────────────────────
# Uses globals EFI_PART, ROOT_PART (avoids mixing interactive + captured stdout)
partition_drive() {
    local dev="$1"
    step "Partitioning ${dev}  (GPT: 1 GB EFI + remainder ext4)"

    echo -e "${RED}${BLD}  WARNING: ALL DATA on ${dev} will be permanently destroyed.${RST}"
    lsblk -o NAME,SIZE,LABEL,MOUNTPOINT "${dev}" 2>/dev/null || true
    echo ""
    confirm "  Confirm destruction of ${dev}?" || die "Aborted by user."

    # Unmount everything on the target first
    swapoff -a 2>/dev/null || true
    lsblk -rno MOUNTPOINT "${dev}" 2>/dev/null | while read -r m; do
        [[ -n "${m}" ]] && umount -lf "${m}" 2>/dev/null || true
    done

    wipefs -af "${dev}"
    sgdisk --zap-all "${dev}"
    sgdisk \
        -n 1:0:+1G   -t 1:ef00 -c 1:"CITLEFI"    \
        -n 2:0:0      -t 2:8300 -c 2:"CITLROOT"   \
        "${dev}"

    # Give kernel time to re-read partition table
    partprobe "${dev}" 2>/dev/null || true
    udevadm settle 2>/dev/null || sleep 3

    # Partition naming: /dev/sda1 vs /dev/nvme0n1p1 vs /dev/mmcblk0p1
    local pfx="${dev}"
    [[ "${dev}" =~ (nvme|mmcblk) ]] && pfx="${dev}p"

    EFI_PART="${pfx}1"
    ROOT_PART="${pfx}2"

    # Verify partitions exist
    [[ -b "${EFI_PART}" ]]  || die "EFI partition ${EFI_PART} not found after partitioning."
    [[ -b "${ROOT_PART}" ]] || die "Root partition ${ROOT_PART} not found after partitioning."

    mkfs.fat -F 32 -n "CITLEFI"   "${EFI_PART}"
    mkfs.ext4 -L "CITLROOT" -F -q "${ROOT_PART}"
    sync

    info "Partitioned: EFI=${EFI_PART}  ROOT=${ROOT_PART}"
}

# ── Extract Ubuntu ────────────────────────────────────────────────────────────
extract_base() {
    local root_part="$1"
    TARGET_MNT="/mnt/citl_install_root"
    mkdir -p "${TARGET_MNT}"
    mount "${root_part}" "${TARGET_MNT}"

    if [[ -f "${SQUASHFS}" ]]; then
        step "Extracting Ubuntu 24.04 from squashfs"
        info "Source : ${SQUASHFS}"
        info "Target : ${TARGET_MNT}  (10–25 min)"

        # Prefer pv for progress if available
        if command -v pv >/dev/null 2>&1; then
            pv "${SQUASHFS}" | unsquashfs -f -d "${TARGET_MNT}" - 2>/dev/null || \
            unsquashfs -f -d "${TARGET_MNT}" "${SQUASHFS}"
        else
            unsquashfs -f -d "${TARGET_MNT}" "${SQUASHFS}" | \
                awk '/\[/{printf "\r  %-70s", $0; fflush()}' || \
            unsquashfs -f -d "${TARGET_MNT}" "${SQUASHFS}"
            echo ""
        fi

        # unsquashfs may put files in squashfs-root/ subdir — flatten if so
        if [[ -d "${TARGET_MNT}/squashfs-root" ]] && \
           [[ ! -f "${TARGET_MNT}/etc/fstab" ]]; then
            warn "unsquashfs used squashfs-root subdir — moving up..."
            mv "${TARGET_MNT}/squashfs-root/"* "${TARGET_MNT}/" 2>/dev/null || true
            rmdir "${TARGET_MNT}/squashfs-root" 2>/dev/null || true
        fi

    else
        [[ "${ALLOW_INTERNET_BOOTSTRAP}" == "true" ]] || \
            die "No offline Ubuntu payload and internet bootstrap was not approved."
        step "Bootstrapping Ubuntu ${UBUNTU_CODENAME} via debootstrap (needs internet)"
        command -v debootstrap >/dev/null 2>&1 || \
            apt-get install -y debootstrap 2>/dev/null || \
            die "No squashfs and debootstrap not available. Connect internet or use a complete CITLBOOT USB."
        debootstrap --arch=amd64 "${UBUNTU_CODENAME}" "${TARGET_MNT}" \
            http://archive.ubuntu.com/ubuntu/ || \
            die "debootstrap failed — check internet connection."
    fi

    # Ensure critical chroot directories exist before bind mounts
    for d in proc sys dev dev/pts run; do
        mkdir -p "${TARGET_MNT}/${d}"
    done

    info "Ubuntu base ready at ${TARGET_MNT}"
}

# ── Bind / unbind for chroot ──────────────────────────────────────────────────
bind_chroot() {
    local mnt="$1"
    for fs in proc sys dev dev/pts run; do
        mkdir -p "${mnt}/${fs}"
        mount --bind "/${fs}" "${mnt}/${fs}" 2>/dev/null || true
    done
}

unbind_chroot() {
    local mnt="$1"
    for fs in run dev/pts dev sys proc; do
        umount -lf "${mnt}/${fs}" 2>/dev/null || true
    done
}

# ── Configure system ──────────────────────────────────────────────────────────
configure_system() {
    local mnt="$1" efi="$2" root="$3" hostname="$4"
    step "Configuring  hostname / user / locale / fstab"

    local root_uuid efi_uuid
    root_uuid="$(blkid -s UUID -o value "${root}")"
    efi_uuid="$(blkid  -s UUID -o value "${efi}")"
    mkdir -p "${mnt}/boot/efi"

    cat > "${mnt}/etc/fstab" <<FSTAB
# CITL managed — citl_reimager.sh v${CITL_VERSION}
UUID=${root_uuid}  /         ext4  errors=remount-ro  0 1
UUID=${efi_uuid}   /boot/efi vfat  umask=0077         0 1
tmpfs              /tmp      tmpfs nosuid,nodev        0 0
FSTAB

    echo "${hostname}" > "${mnt}/etc/hostname"
    cat > "${mnt}/etc/hosts" <<HOSTS
127.0.0.1   localhost
127.0.1.1   ${hostname}
::1         localhost ip6-localhost ip6-loopback
HOSTS

    ln -sf /usr/share/zoneinfo/America/Los_Angeles "${mnt}/etc/localtime" 2>/dev/null || true
    echo "America/Los_Angeles" > "${mnt}/etc/timezone"
    echo 'LANG=en_US.UTF-8' > "${mnt}/etc/default/locale" 2>/dev/null || true

    # User — tolerates both fresh debootstrap and squashfs-extracted systems
    if ! grep -q "^${CITL_USER}:" "${mnt}/etc/passwd" 2>/dev/null; then
        chroot "${mnt}" useradd -m -s /bin/bash -c "CITL Station" \
               -G sudo,adm "${CITL_USER}" 2>/dev/null || true
    fi
    echo "${CITL_USER}:${CITL_PASS}" | chroot "${mnt}" chpasswd 2>/dev/null || true
    chroot "${mnt}" chage -d 0 "${CITL_USER}" 2>/dev/null || true   # force pw change

    echo "${CITL_USER} ALL=(ALL) NOPASSWD: /opt/citl/citl_reimager.sh" \
        > "${mnt}/etc/sudoers.d/99-citl"
    chmod 440 "${mnt}/etc/sudoers.d/99-citl"

    info "Configured: host=${hostname}  user=${CITL_USER}"
}

# ── Bootloader (host grub-install — no chroot needed, no internet needed) ────
install_bootloader() {
    local mnt="$1" efi="$2" dev="$3"
    step "Installing GRUB EFI → ${dev}"

    mount "${efi}" "${mnt}/boot/efi" 2>/dev/null || true

    # Use the HOST's grub-install binary — does not require internet or chroot apt
    grub-install \
        --target=x86_64-efi \
        --efi-directory="${mnt}/boot/efi" \
        --boot-directory="${mnt}/boot" \
        --removable \
        --no-nvram \
        "${dev}" \
        || die "grub-install failed. Is grub-efi-amd64 installed in the live environment?"

    # Write a label-based grub.cfg that survives UUID changes
    mkdir -p "${mnt}/boot/grub"
    cat > "${mnt}/boot/grub/grub.cfg" <<'GRUBCFG'
set default=0
set timeout=5
search --no-floppy --label --set=root CITLROOT

menuentry "Ubuntu — CITL Station" {
    search --no-floppy --label --set=root CITLROOT
    linux  /boot/vmlinuz root=LABEL=CITLROOT ro quiet splash
    initrd /boot/initrd.img
}

menuentry "Ubuntu — Recovery Mode" {
    search --no-floppy --label --set=root CITLROOT
    linux  /boot/vmlinuz root=LABEL=CITLROOT ro recovery nomodeset
    initrd /boot/initrd.img
}
GRUBCFG

    # Now update-grub in chroot to get the real kernel paths
    bind_chroot "${mnt}"
    chroot "${mnt}" update-grub 2>/dev/null || \
        warn "update-grub failed in chroot — label-based grub.cfg still in place."
    unbind_chroot "${mnt}"

    info "Bootloader installed."
}

# ── First-boot CITL service ───────────────────────────────────────────────────
install_citl_firstboot() {
    local mnt="$1" profile="$2"
    step "Installing CITL first-boot service  (profile: ${profile})"

    mkdir -p "${mnt}/opt/citl"

    # Copy reimager scripts to the installed system
    rsync -a --exclude='__pycache__' --exclude='*.pyc' \
          "${SCRIPT_DIR}/" "${mnt}/opt/citl/" 2>/dev/null || \
        cp -r "${SCRIPT_DIR}/"*.sh "${mnt}/opt/citl/" 2>/dev/null || true

    # Copy Ollama model cache from ExFAT if present (avoids internet on first boot)
    if [[ -n "${EXFAT_MNT:-}" ]] && [[ -d "${EXFAT_MNT}/ollama_models" ]]; then
        info "Copying Ollama model cache from ExFAT (offline)..."
        mkdir -p "${mnt}/usr/share/ollama/.ollama/models"
        rsync -a "${EXFAT_MNT}/ollama_models/" \
              "${mnt}/usr/share/ollama/.ollama/models/" 2>/dev/null || true
    fi

    # Build profile-specific model list
    local models_to_pull=""
    case "${profile}" in
        lean)
            models_to_pull="phi3:mini nomic-embed-text"
            ;;
        standard)
            models_to_pull="mistral:7b-instruct nomic-embed-text"
            ;;
        full)
            models_to_pull="mistral:7b-instruct olmo2:7b molmo7b-d-0924 nomic-embed-text"
            ;;
    esac

    cat > "${mnt}/opt/citl/install_citl_on_target.sh" <<FIRSTBOOT
#!/usr/bin/env bash
# Auto-generated by citl_reimager.sh v${CITL_VERSION}  profile=${profile}
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
LOG=/var/log/citl-firstboot.log
exec > >(tee -a "\${LOG}") 2>&1
echo "=== CITL First-Boot  \$(date) ==="

# ── Ollama ────────────────────────────────────────────────────────────────────
if ! command -v ollama >/dev/null 2>&1; then
    echo "[CITL] Installing Ollama..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL https://ollama.com/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://ollama.com/install.sh | sh
    else
        echo "[CITL] ERROR: no curl or wget — cannot install Ollama"
        exit 1
    fi
fi
systemctl enable ollama 2>/dev/null || true
systemctl start  ollama 2>/dev/null || true
sleep 8  # wait for daemon

# ── Python deps ───────────────────────────────────────────────────────────────
apt-get update -qq 2>/dev/null || true
apt-get install -y python3 python3-pip python3-venv git curl wget 2>/dev/null || true
pip3 install --quiet --break-system-packages customtkinter requests ollama 2>/dev/null || true

# ── Models (profile: ${profile}) ─────────────────────────────────────────────
for model in ${models_to_pull}; do
    echo "[CITL] Pulling \${model}..."
    timeout 7200 ollama pull "\${model}" || echo "[WARN] \${model} pull failed — continuing"
done

# ── Done ──────────────────────────────────────────────────────────────────────
rm -f /opt/citl/.firstboot_pending
echo "[CITL] First-boot complete: \$(date)"
FIRSTBOOT

    chmod +x "${mnt}/opt/citl/install_citl_on_target.sh"
    touch "${mnt}/opt/citl/.firstboot_pending"

    cat > "${mnt}/etc/systemd/system/citl-firstboot.service" <<'SVC'
[Unit]
Description=CITL First-Boot Setup
ConditionPathExists=/opt/citl/.firstboot_pending
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/citl/install_citl_on_target.sh
StandardOutput=journal+console
RemainAfterExit=yes
TimeoutStartSec=7200

[Install]
WantedBy=multi-user.target
SVC

    bind_chroot "${mnt}"
    chroot "${mnt}" systemctl enable citl-firstboot.service 2>/dev/null || true
    unbind_chroot "${mnt}"

    info "First-boot service: ${profile} profile, models: ${models_to_pull}"
}

# ── Clean up ──────────────────────────────────────────────────────────────────
finalise() {
    local mnt="${TARGET_MNT:-/mnt/citl_install_root}"
    step "Syncing and unmounting"
    # Unbind first (in case any chroot mounts were left)
    unbind_chroot "${mnt}"
    sync
    umount -lf "${mnt}/boot/efi" 2>/dev/null || true
    umount -lf "${mnt}"          2>/dev/null || true
    # Clean up temp source mounts we created
    umount -lf /mnt/citl_src_boot    2>/dev/null || true
    umount -lf /mnt/citl_exfat_src   2>/dev/null || true
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    banner

    # Arg parsing
    local profile_arg="" target_arg="" hostname_arg=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile)  profile_arg="$2";  shift 2;;
            --target)   target_arg="$2";   shift 2;;
            --hostname) hostname_arg="$2"; shift 2;;
            --allow-internet-bootstrap) ALLOW_INTERNET_BOOTSTRAP=true; shift;;
            --help|-h)
                sed -n '/^# Usage:/,/^#$/p' "$0" | head -20
                exit 0;;
            *) warn "Unknown argument: $1"; shift;;
        esac
    done

    run_preflight
    locate_sources
    validate_boot_payload_plan

    local target_dev profile hostname drive_gb
    target_dev="$(pick_target "${target_arg:-}")"
    profile="$(pick_profile "${profile_arg:-}")"

    if [[ -z "${hostname_arg}" ]]; then
        hostname_arg="$(ask "Hostname for this station [citl-station]:")"
        hostname_arg="${hostname_arg:-citl-station}"
    fi

    # Drive size advisory
    drive_gb="$(lsblk -bdno SIZE "${target_dev}" 2>/dev/null | \
        awk '{printf "%d", $1/1024/1024/1024}')"
    case "${profile}" in
        lean)     [[ ${drive_gb} -ge 16 ]] || \
            warn "Drive is ${drive_gb} GB — lean profile recommends 16 GB+";;
        standard) [[ ${drive_gb} -ge 64 ]] || \
            warn "Drive is ${drive_gb} GB — standard profile recommends 64 GB+";;
        full)     [[ ${drive_gb} -ge 128 ]] || \
            warn "Drive is ${drive_gb} GB — full profile recommends 128 GB+";;
    esac

    echo ""
    echo -e "${BLD}  Summary:${RST}"
    echo "    Target   : ${target_dev}  (${drive_gb} GB)"
    echo "    Profile  : ${profile}"
    echo "    Hostname : ${hostname_arg}"
    echo ""
    confirm "  Begin reimaging?" || die "Aborted."

    trap finalise EXIT

    # Partition (sets EFI_PART and ROOT_PART globals)
    partition_drive "${target_dev}"

    # Extract
    extract_base "${ROOT_PART}"

    # Configure
    configure_system "${TARGET_MNT}" "${EFI_PART}" "${ROOT_PART}" "${hostname_arg}"

    # Bootloader
    install_bootloader "${TARGET_MNT}" "${EFI_PART}" "${target_dev}"

    # CITL apps first-boot service
    install_citl_firstboot "${TARGET_MNT}" "${profile}"

    # Let finalise() run via trap
    trap - EXIT
    finalise

    echo ""
    echo -e "${GRN}${BLD}══════════════════════════════════════════════════════════${RST}"
    echo -e "${GRN}${BLD}  REIMAGING COMPLETE${RST}"
    echo -e "${GRN}  Drive    : ${target_dev}  (${drive_gb} GB)${RST}"
    echo -e "${GRN}  Profile  : ${profile}${RST}"
    echo -e "${GRN}  Hostname : ${hostname_arg}${RST}"
    echo -e "${GRN}  Login    : ${CITL_USER} / (set at first login prompt)${RST}"
    echo -e "${GRN}  CITL apps install automatically on first boot.${RST}"
    echo -e "${GRN}${BLD}══════════════════════════════════════════════════════════${RST}"
    echo ""
    confirm "Remove USB and reboot now?" && reboot || true
}

main "$@"
