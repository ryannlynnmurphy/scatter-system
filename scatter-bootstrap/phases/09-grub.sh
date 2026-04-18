#!/usr/bin/env bash
# 09-grub — SUDO. Hide the GRUB boot menu on single-boot installs.
#
# ONLY runs if the machine appears to be single-boot (just one OS in GRUB's
# os-prober output). Dual-boot setups get this phase SKIPPED — hiding GRUB
# on a dual-boot machine denies access to the other OS.
#
# Changes GRUB_TIMEOUT=0, GRUB_TIMEOUT_STYLE=hidden so boot flows directly
# into Plymouth + GDM without the purple Ubuntu menu. Hold Shift at boot
# to still reach GRUB manually (Ubuntu preserves this escape hatch).
#
# Reversible: backs up /etc/default/grub before editing; restore command
# printed at the end.
set -eu

APPLY="${SCATTER_APPLY:-0}"
APPLY_SUDO="${SCATTER_APPLY_SUDO:-0}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

# --- detect dual-boot ---
OTHER_OS_COUNT=0
if [ -x /usr/bin/os-prober ]; then
    # os-prober requires root to run. Without sudo we can only check the
    # cached GRUB config. `update-grub` output in /boot/grub/grub.cfg
    # includes menuentries for all detected OSes.
    if [ -r /boot/grub/grub.cfg ]; then
        # Count non-Ubuntu menuentries roughly (excludes "Advanced" submenu)
        OTHER_OS_COUNT=$(grep -cE "^menuentry '" /boot/grub/grub.cfg 2>/dev/null || echo 0)
        # subtract the usual "Ubuntu" + "Memory test" entries
        OTHER_OS_COUNT=$((OTHER_OS_COUNT > 1 ? OTHER_OS_COUNT - 1 : 0))
    fi
fi

if [ "$OTHER_OS_COUNT" -gt 1 ]; then
    echo "  ${YELLOW}dual-boot detected${RESET} ($OTHER_OS_COUNT GRUB menuentries)"
    echo "  ${DIM}skipping: hiding GRUB on a dual-boot machine would deny access"
    echo "  ${DIM}to the other OS. Shift-at-boot still works but is not obvious.${RESET}"
    exit 0
fi

CURRENT_TIMEOUT=$(grep '^GRUB_TIMEOUT=' /etc/default/grub 2>/dev/null | head -1 | sed 's/.*=//;s/"//g')

if [ "$CURRENT_TIMEOUT" = "0" ]; then
    echo "  ${GREEN}✓${RESET} GRUB already hidden (GRUB_TIMEOUT=0)"
    exit 0
fi

echo "  ${DIM}current GRUB_TIMEOUT:${RESET} $CURRENT_TIMEOUT"

if [ "$APPLY" -eq 0 ] || [ "$APPLY_SUDO" -eq 0 ]; then
    echo "  ${DIM}[dry-run or no --apply-sudo]${RESET} would:"
    echo "  ${DIM}    1. backup /etc/default/grub → /etc/default/grub.scatter-backup"
    echo "  ${DIM}    2. set GRUB_TIMEOUT=0 and GRUB_TIMEOUT_STYLE=hidden"
    echo "  ${DIM}    3. sudo update-grub"
    echo "  ${DIM}  (Shift-at-boot still reveals the menu as an escape hatch)${RESET}"
    exit 0
fi

echo "  ${YELLOW}about to hide GRUB menu on boot${RESET}"
echo "  ${DIM}  Next boot will flow directly into Plymouth → GDM. Hold Shift"
echo "  ${DIM}  at power-on to bring the menu back if you ever need it.${RESET}"
read -r -p "  proceed? [y/N] " ans
if [ "$ans" != "y" ] && [ "$ans" != "Y" ]; then
    echo "  ${YELLOW}skipped${RESET}"
    exit 0
fi

sudo cp -n /etc/default/grub /etc/default/grub.scatter-backup
sudo sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' /etc/default/grub
if grep -q '^GRUB_TIMEOUT_STYLE=' /etc/default/grub; then
    sudo sed -i 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/' /etc/default/grub
else
    echo 'GRUB_TIMEOUT_STYLE=hidden' | sudo tee -a /etc/default/grub >/dev/null
fi
sudo update-grub
echo "  ${GREEN}✓${RESET} GRUB hidden. Next boot flows directly into Plymouth."
echo "  ${DIM}revert: sudo cp /etc/default/grub.scatter-backup /etc/default/grub && sudo update-grub${RESET}"
