#!/usr/bin/env bash
# ship-the-future.sh — one-shot sudo pass to land the Scatter chrome
# that requires root. Run once, then reboot.
#
#   sudo bash ~/scatter-system/ship-the-future.sh
#
# Does:
#   1. Install Plymouth scatter theme (composed title sequence, not dots)
#   2. Stop GDM session chooser from saying "Ubuntu" — rename to "Scatter"
#   3. Hand off to scatter-os-skin/install.sh for GRUB + os-release + initramfs
#
# User-level setup (bar extension, disable ubuntu-dock, disable desktop icons)
# has already run. Reboot after this to see it all.
set -euo pipefail

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "run me with sudo:"
    echo "  sudo bash $0"
    exit 1
fi

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BACKUP_DIR="/etc/scatter-backups"
mkdir -p "$BACKUP_DIR"

echo
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  SCATTER — shipping the future                   ║"
echo "  ║  boot splash · session label · os identity       ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo

# ── [1] Rename GDM session: Ubuntu → Scatter ────────────────────────────
echo "[1/3] session label — GDM stops saying 'Ubuntu'"
for dir in /usr/share/wayland-sessions /usr/share/xsessions; do
    [ -d "$dir" ] || continue
    for f in "$dir"/ubuntu.desktop "$dir"/ubuntu-wayland.desktop "$dir"/ubuntu-xorg.desktop; do
        [ -f "$f" ] || continue
        base="$(basename "$f")"
        backup="$BACKUP_DIR/$base.pre-scatter"
        [ -f "$backup" ] || cp "$f" "$backup"
        sed -i 's|^Name=Ubuntu.*|Name=Scatter|' "$f"
        sed -i 's|^Comment=This session logs you into Ubuntu.*|Comment=This session logs you into Scatter|' "$f"
        echo "    ✓ $f"
    done
done

# ── [2] Hand off to scatter-os-skin installer (plymouth, grub, identity) ─
echo
echo "[2/3] scatter-os-skin — plymouth + grub + os identity"
SKIN="$HERE/scatter-os-skin/install.sh"
if [ -x "$SKIN" ] || [ -f "$SKIN" ]; then
    bash "$SKIN"
else
    echo "    ! skipped — $SKIN not found"
fi

# ── [3] update-initramfs (Plymouth script lives in initramfs) ────────────
echo
echo "[3/3] update-initramfs — bake the new boot sequence"
if command -v update-initramfs >/dev/null 2>&1; then
    update-initramfs -u
    echo "    ✓ initramfs updated"
else
    echo "    ! update-initramfs not found — skipping"
fi

echo
echo "  done. the future is one reboot away:"
echo "    sudo reboot"
echo
