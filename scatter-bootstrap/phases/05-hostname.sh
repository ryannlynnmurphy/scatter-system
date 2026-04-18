#!/usr/bin/env bash
# 05-hostname — SUDO. Set the machine hostname to 'scatter'.
set -eu

APPLY="${SCATTER_APPLY:-0}"
APPLY_SUDO="${SCATTER_APPLY_SUDO:-0}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

CURRENT=$(hostnamectl --static 2>/dev/null || hostname)

if [ "$CURRENT" = "scatter" ]; then
    echo "  ${GREEN}✓${RESET} hostname is already 'scatter'"
    exit 0
fi

echo "  ${DIM}current hostname:${RESET} $CURRENT"

if [ "$APPLY" -eq 0 ] || [ "$APPLY_SUDO" -eq 0 ]; then
    echo "  ${DIM}[dry-run or no --apply-sudo]${RESET} would: sudo hostnamectl set-hostname scatter"
    exit 0
fi

echo "  ${YELLOW}about to change hostname to 'scatter'${RESET}"
echo "  ${DIM}  (this affects shell prompt, /etc/hosts, and any services"
echo "  ${DIM}   referencing the machine by name)${RESET}"
read -r -p "  proceed? [y/N] " ans
if [ "$ans" != "y" ] && [ "$ans" != "Y" ]; then
    echo "  ${YELLOW}skipped${RESET}"
    exit 0
fi

sudo hostnamectl set-hostname scatter
# Update /etc/hosts alias if needed (safe — adds, doesn't replace).
if ! grep -q "scatter$" /etc/hosts 2>/dev/null; then
    echo "127.0.1.1 scatter" | sudo tee -a /etc/hosts >/dev/null
fi
echo "  ${GREEN}✓${RESET} hostname set to 'scatter' (new shells will show it)"
