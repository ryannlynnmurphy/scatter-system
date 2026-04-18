#!/usr/bin/env bash
# 02-commons-wrap — non-sudo. Wrap every commons app for the app menu.
set -eu

SCATTER_HOME="${SCATTER_HOME:?}"
APPLY="${SCATTER_APPLY:-0}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; RESET=$'\033[0m'

if [ "$APPLY" -eq 0 ]; then
    echo "  ${DIM}[dry-run]${RESET} would: scatter wrap --all --apply"
    echo "  ${DIM}  generates Scatter-themed .desktop entries + firejail profiles"
    echo "  ${DIM}  for all registered commons apps (LibreOffice, GIMP, Inkscape,"
    echo "  ${DIM}  Krita, Blender, Firefox, Thunderbird, OBS, Audacity).${RESET}"
    exit 0
fi

python3 "$SCATTER_HOME/scatter/wrap.py" --all --apply >/dev/null
echo "  ${GREEN}✓${RESET} commons apps wrapped (desktop entries + firejail profiles)"
