#!/usr/bin/env bash
# Install the udev rule that lets adb reach phones over USB.
# Run once with sudo. It is the only system change PhoneVitals requires;
# everything else lives inside the project folder.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "sudo required: sudo $0" >&2
  exit 1
fi

RULES=/etc/udev/rules.d/51-android-phonevitals.rules

# Without this rule the /dev/bus/usb nodes belong to root and adb sees the
# phone as "no permissions". The rule assigns the device to the plugdev group,
# which the user is already a member of.
#
# The IDs are those the USB Implementers Forum assigns to manufacturers:
#   18d1  Google (Pixel, Nexus, and the AOSP mode of many others)
#   04e8  Samsung
#   2717  Xiaomi          22b8  Motorola        12d1  Huawei
#   2a70  OnePlus         22d9  Oppo/Realme     2d95  Vivo
#   0bb4  HTC             1004  LG              0fce  Sony
#   19d2  ZTE             2916  Android (generic)   0e8d  MediaTek
#   05c6  Qualcomm (diagnostic and bootloader modes)

cat > "$RULES" <<'EOF'
# PhoneVitals — USB access to Android devices for the plugdev group.
SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="04e8", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="2717", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="22b8", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="12d1", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="2a70", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="22d9", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="2d95", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0bb4", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="1004", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0fce", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="19d2", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="2916", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0e8d", MODE="0664", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="05c6", MODE="0664", GROUP="plugdev", TAG+="uaccess"
EOF

chmod 644 "$RULES"
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb

echo "✓ Rule installed in $RULES"
echo
echo "If the phone is already connected, unplug it and plug it back in."
echo "Check with:  .toolchain/platform-tools/adb devices -l"
