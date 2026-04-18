#!/usr/bin/env bash
# 08-welcome — non-sudo. Trigger scatter-welcome on first run.
#
# Uses `scatter welcome --if-needed` so nothing happens if the user has
# already been welcomed. This runs LAST in the bootstrap so every other
# piece is in place when the welcome opens.
set -eu

SCATTER_HOME="${SCATTER_HOME:?}"
APPLY="${SCATTER_APPLY:-0}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

STATUS_LINE=$(python3 "$SCATTER_HOME/scatter-welcome/welcome.py" --status 2>/dev/null || echo "welcomed: False")

if echo "$STATUS_LINE" | grep -q "True"; then
    echo "  ${GREEN}✓${RESET} already welcomed (skipping)"
    exit 0
fi

if [ "$APPLY" -eq 0 ]; then
    echo "  ${DIM}[dry-run]${RESET} would: python3 scatter-welcome/welcome.py --if-needed"
    echo "  ${DIM}  opens the chromeless welcome window (four prototype manifestos)${RESET}"
    exit 0
fi

# Detect display. If no DISPLAY/WAYLAND_DISPLAY, defer.
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    echo "  ${YELLOW}no graphical display — welcome deferred to next GUI login${RESET}"
    exit 0
fi

echo "  ${DIM}launching scatter-welcome window...${RESET}"
python3 "$SCATTER_HOME/scatter-welcome/welcome.py" --if-needed || true
echo "  ${GREEN}✓${RESET} welcome phase complete"
