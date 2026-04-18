#!/usr/bin/env bash
# 04-deps-apt — SUDO. Install apt packages for the full Scatter experience.
#
# This phase is gated: it runs only under --apply-sudo AND after per-phase
# confirmation. Packages stated here, each with a reason.
set -eu

APPLY="${SCATTER_APPLY:-0}"
APPLY_SUDO="${SCATTER_APPLY_SUDO:-0}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

PACKAGES=(
    "firejail:sandboxes wrapped commons apps (Scatter Browser and friends)"
    "fonts-jetbrains-mono:Research theme default mono"
    "fonts-inter:Research theme default sans (Inter covers Studio-theme sans too)"
    "fonts-liberation:general fallback"
    "gir1.2-webkit2-4.1:PyGObject WebKit2 bindings (native app shell)"
    "python3-gi:PyGObject (native app shell)"
    "ffmpeg:audio preprocessing (needed if whisper is installed via snap)"
    "plymouth:boot splash framework (required by phase 07)"
    "plymouth-themes:additional boot splash themes"
    "librsvg2-bin:rsvg-convert for SVG→PNG at Plymouth install time"
)
# NOT in the apt list (install separately if wanted):
#   - fonts-dm      (not in Ubuntu 24.04 main repos; Studio theme falls back
#                    to Inter gracefully)
#   - whisper-cpp   (snap-only on 24.04: `sudo snap install whisper-cpp`)

# Always print the plan.
echo "  ${DIM}apt packages for Scatter:${RESET}"
for entry in "${PACKAGES[@]}"; do
    pkg="${entry%%:*}"
    reason="${entry#*:}"
    # Check if already installed
    if dpkg -s "$pkg" >/dev/null 2>&1; then
        status="${GREEN}installed${RESET}"
    else
        status="${YELLOW}missing${RESET}"
    fi
    printf "    %-30s [%s] — %s\n" "$pkg" "$status" "$reason"
done
echo ""

if [ "$APPLY" -eq 0 ] || [ "$APPLY_SUDO" -eq 0 ]; then
    echo "  ${DIM}[dry-run or no --apply-sudo]${RESET} would: sudo apt install <missing packages above>"
    exit 0
fi

# Collect missing
TO_INSTALL=()
for entry in "${PACKAGES[@]}"; do
    pkg="${entry%%:*}"
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        TO_INSTALL+=("$pkg")
    fi
done

if [ "${#TO_INSTALL[@]}" -eq 0 ]; then
    echo "  ${GREEN}✓${RESET} all packages already installed"
    exit 0
fi

echo "  ${YELLOW}about to run:${RESET} sudo apt install ${TO_INSTALL[*]}"
read -r -p "  proceed? [y/N] " ans
if [ "$ans" != "y" ] && [ "$ans" != "Y" ]; then
    echo "  ${YELLOW}skipped${RESET}"
    exit 0
fi

sudo apt update
sudo apt install -y "${TO_INSTALL[@]}"
echo "  ${GREEN}✓${RESET} packages installed"
