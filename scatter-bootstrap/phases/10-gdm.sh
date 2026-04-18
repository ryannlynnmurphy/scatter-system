#!/usr/bin/env bash
# 10-gdm — SUDO. Customize the GDM login greeter with Scatter's wallpaper.
#
# GDM on Ubuntu 24.04 uses dconf overrides. This phase writes a minimal
# override that sets the background to Scatter's SVG wallpaper. Login
# prompt text, font, and layout stay GNOME's defaults — we change the
# background only. Restraint: the login greeter is not a surface Scatter's
# thesis claims cite, so we don't rebrand its chrome; we only set the
# wallpaper so the machine looks Scatter on power-on.
#
# Reversible: the override file is named for our removal.
set -eu

APPLY="${SCATTER_APPLY:-0}"
APPLY_SUDO="${SCATTER_APPLY_SUDO:-0}"
SCATTER_HOME="${SCATTER_HOME:?}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

OVERRIDE_PATH="/etc/dconf/db/gdm.d/90-scatter-wallpaper"
WALLPAPER_SVG="$SCATTER_HOME/scatter/ui/brand/scatter-wallpaper.svg"

if [ ! -f "$WALLPAPER_SVG" ]; then
    echo "  ${YELLOW}wallpaper SVG missing at $WALLPAPER_SVG — skipping${RESET}"
    exit 0
fi

if [ -f "$OVERRIDE_PATH" ] && grep -q scatter-wallpaper "$OVERRIDE_PATH" 2>/dev/null; then
    echo "  ${GREEN}✓${RESET} GDM override already set to Scatter wallpaper"
    exit 0
fi

if [ "$APPLY" -eq 0 ] || [ "$APPLY_SUDO" -eq 0 ]; then
    echo "  ${DIM}[dry-run or no --apply-sudo]${RESET} would:"
    echo "  ${DIM}    1. copy scatter-wallpaper.svg → /usr/share/backgrounds/scatter-wallpaper.svg"
    echo "  ${DIM}    2. write $OVERRIDE_PATH with GDM-specific gsettings override"
    echo "  ${DIM}    3. sudo dconf update"
    echo "  ${DIM}  (changes apply at next GDM restart or next reboot)${RESET}"
    exit 0
fi

echo "  ${YELLOW}about to set GDM login background to Scatter wallpaper${RESET}"
read -r -p "  proceed? [y/N] " ans
if [ "$ans" != "y" ] && [ "$ans" != "Y" ]; then
    echo "  ${YELLOW}skipped${RESET}"
    exit 0
fi

DEST_WALLPAPER="/usr/share/backgrounds/scatter-wallpaper.svg"
sudo install -m 644 "$WALLPAPER_SVG" "$DEST_WALLPAPER"

sudo mkdir -p "$(dirname "$OVERRIDE_PATH")"
sudo tee "$OVERRIDE_PATH" >/dev/null <<EOF
# Scatter GDM override — login screen background.
# Remove this file to revert: sudo rm $OVERRIDE_PATH && sudo dconf update
[org/gnome/desktop/background]
picture-uri='file://$DEST_WALLPAPER'
picture-uri-dark='file://$DEST_WALLPAPER'
picture-options='zoom'
EOF

sudo dconf update
echo "  ${GREEN}✓${RESET} GDM background set to Scatter wallpaper"
echo "  ${DIM}  (takes effect at next GDM restart: sudo systemctl restart gdm)"
echo "  ${DIM}  revert: sudo rm $OVERRIDE_PATH && sudo dconf update${RESET}"
