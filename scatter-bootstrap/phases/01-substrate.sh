#!/usr/bin/env bash
# 01-substrate — non-sudo. Initialize ~/.scatter/ and set the profile.
set -eu

SCATTER_HOME="${SCATTER_HOME:?}"
APPLY="${SCATTER_APPLY:-0}"
PROFILE="${SCATTER_PROFILE:-researcher}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; RESET=$'\033[0m'

if [ "$APPLY" -eq 0 ]; then
    echo "  ${DIM}[dry-run]${RESET} would: python3 scatter_core.py init"
    echo "  ${DIM}[dry-run]${RESET} would: python3 scatter_core.py profile --set $PROFILE"
    exit 0
fi

python3 "$SCATTER_HOME/scatter_core.py" init >/dev/null
python3 "$SCATTER_HOME/scatter_core.py" profile --set "$PROFILE" >/dev/null
echo "  ${GREEN}✓${RESET} substrate at ~/.scatter/ (profile: $PROFILE)"
