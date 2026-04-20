#!/usr/bin/env bash
# Install the Scatter plymouth production.
#
# This is destructive: it overwrites /usr/share/plymouth/themes/scatter,
# regenerates the initramfs, and leaves the default plymouth theme set to
# scatter. Run once after updating the source in scatter-os-skin/plymouth/.
#
# Usage:   sudo bash ~/scatter-system/scatter-os-skin/install-plymouth.sh

set -euo pipefail

SRC_PLYMOUTH="$(cd "$(dirname "$0")" && pwd)/plymouth"
SRC_GDM="$(cd "$(dirname "$0")" && pwd)/gdm"

if [[ $EUID -ne 0 ]]; then
    echo "this installs to /usr/share; rerun with sudo." >&2
    exit 1
fi

echo "→ syncing plymouth theme"
mkdir -p /usr/share/plymouth/themes/scatter
# Purge stale frames/logos before copying so removed files don't linger.
find /usr/share/plymouth/themes/scatter -maxdepth 1 -type f \
    \( -name "frame-*.png" -o -name "logo.png" -o -name "wordmark.png" \) -delete
cp -f "$SRC_PLYMOUTH"/*.png                  /usr/share/plymouth/themes/scatter/
cp -f "$SRC_PLYMOUTH"/scatter.plymouth       /usr/share/plymouth/themes/scatter/
cp -f "$SRC_PLYMOUTH"/scatter.script         /usr/share/plymouth/themes/scatter/

echo "→ syncing GDM greeter logo"
mkdir -p /usr/share/scatter
cp -f "$SRC_GDM"/greeter-logo.png            /usr/share/scatter/greeter-logo.png

echo "→ setting plymouth default to 'scatter'"
# plymouth-set-default-theme isn't present on every distro; drive the
# alternatives system directly. Register the theme if not already known,
# then select it.
SCATTER_THEME=/usr/share/plymouth/themes/scatter/scatter.plymouth
if ! update-alternatives --list default.plymouth 2>/dev/null | grep -qx "$SCATTER_THEME"; then
    update-alternatives --install /usr/share/plymouth/themes/default.plymouth \
        default.plymouth "$SCATTER_THEME" 200
fi
update-alternatives --set default.plymouth "$SCATTER_THEME"

echo "→ rebuilding initramfs (this takes a minute)"
update-initramfs -u

echo
echo "done. next reboot plays the new production."
