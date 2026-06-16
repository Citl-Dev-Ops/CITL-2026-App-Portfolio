CITL Reimager boot payload requirements

Do not mark a USB boot-ready unless CITLBOOT contains all three files:

  casper/vmlinuz
  casper/initrd
  casper/filesystem.squashfs

If those files are removed, GRUB can still load but the Ubuntu/CITL entries
can fail into a GRUB shell. That is the failure this guard prevents.

Offline payloads on the ExFAT data partition can still help reimage/repair:

  ubuntu-base/filesystem.squashfs
  ubuntu-24*.iso
  CITL_Images/ubuntu-24*.iso

Those offline files do not replace the CITLBOOT casper files for booting
unless GRUB is deliberately reconfigured for an ISO-boot workflow.

Use the guarded scripts:

  sudo bash citl_reimager.sh
  sudo bash fix_usb_grub.sh /dev/sdX
  sudo bash fleet_sync_usb.sh --all

Do not run manual grub-install against /boot/efi on the host OS.
