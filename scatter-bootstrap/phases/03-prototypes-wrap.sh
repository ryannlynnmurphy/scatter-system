#!/usr/bin/env bash
# 03-prototypes-wrap — non-sudo. Wrap prototype apps (researcher profile only).
set -eu

SCATTER_HOME="${SCATTER_HOME:?}"
APPLY="${SCATTER_APPLY:-0}"
PROFILE="${SCATTER_PROFILE:-researcher}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

if [ "$PROFILE" = "learner" ]; then
    echo "  ${YELLOW}learner profile — prototypes skipped (dev tools, researcher-only)${RESET}"
    exit 0
fi

if [ "$APPLY" -eq 0 ]; then
    echo "  ${DIM}[dry-run]${RESET} would: scatter wrap --all-prototypes --apply"
    echo "  ${DIM}  generates launchers for Scatter Draft, Film, Music, Write"
    echo "  ${DIM}  (each starts npm run dev in its prototype dir, opens a"
    echo "  ${DIM}  chromeless GTK window).${RESET}"
    exit 0
fi

python3 "$SCATTER_HOME/scatter/wrap.py" --all-prototypes --apply >/dev/null
echo "  ${GREEN}✓${RESET} prototype apps wrapped (Draft, Film, Music, Write)"
