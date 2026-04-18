#!/usr/bin/env bash
# 06-os-release — SUDO. Add Scatter branding to /etc/os-release's PRETTY_NAME.
#
# SAFE approach: we do NOT rewrite Ubuntu's ID or VERSION fields. apt
# and many other tools rely on those. We only add a PRETTY_NAME override
# via the /etc/lsb-release and /etc/os-release PRETTY_NAME line, with a
# backup saved first. This is fully reversible.
set -eu

APPLY="${SCATTER_APPLY:-0}"
APPLY_SUDO="${SCATTER_APPLY_SUDO:-0}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

CURRENT=$(grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | sed 's/PRETTY_NAME=//;s/"//g')

if [ "$CURRENT" = "Scatter (Ubuntu 24.04)" ]; then
    echo "  ${GREEN}✓${RESET} /etc/os-release PRETTY_NAME already set to 'Scatter (Ubuntu 24.04)'"
    exit 0
fi

echo "  ${DIM}current PRETTY_NAME:${RESET} $CURRENT"

if [ "$APPLY" -eq 0 ] || [ "$APPLY_SUDO" -eq 0 ]; then
    echo "  ${DIM}[dry-run or no --apply-sudo]${RESET} would: set PRETTY_NAME='Scatter (Ubuntu 24.04)' in /etc/os-release"
    echo "  ${DIM}  (backup saved to /etc/os-release.scatter-backup first; ID= unchanged)${RESET}"
    exit 0
fi

echo "  ${YELLOW}about to modify /etc/os-release${RESET}"
echo "  ${DIM}  → PRETTY_NAME='Scatter (Ubuntu 24.04)'${RESET}"
echo "  ${DIM}  → backup: /etc/os-release.scatter-backup${RESET}"
echo "  ${DIM}  → ID=, VERSION_ID=, and other package-manager-critical fields UNCHANGED${RESET}"
read -r -p "  proceed? [y/N] " ans
if [ "$ans" != "y" ] && [ "$ans" != "Y" ]; then
    echo "  ${YELLOW}skipped${RESET}"
    exit 0
fi

sudo cp -n /etc/os-release /etc/os-release.scatter-backup
sudo sed -i 's/^PRETTY_NAME=.*/PRETTY_NAME="Scatter (Ubuntu 24.04)"/' /etc/os-release
echo "  ${GREEN}✓${RESET} /etc/os-release updated (restore: sudo cp /etc/os-release.scatter-backup /etc/os-release)"
