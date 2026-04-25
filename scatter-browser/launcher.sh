#!/usr/bin/env bash
# Scatter Browser launcher.
#
# Prefers LibreWolf as the underlying engine (Firefox-based, hardened
# upstream — anti-fingerprinting, no telemetry, container tabs); falls
# back to plain Firefox if LibreWolf isn't installed yet. Either way the
# Scatter profile, userChrome.css, and policies.json apply on top.
#
# Profile: ~/.scatter/scatter-browser-profile/
# First run: copies user.js + chrome/userChrome.css from this repo.
# Subsequent runs refresh those files so edits to the repo propagate.
#
# Optional firejail sandbox: scatter-browser.profile in this directory.
set -eu

SCATTER_HOME="${SCATTER_HOME:-$HOME/scatter-system}"
PROFILE_DIR="$HOME/.scatter/scatter-browser-profile"
SRC_DIR="$SCATTER_HOME/scatter-browser/profile"
USERJS_SRC="$SRC_DIR/user.js"
USERCHROME_SRC="$SRC_DIR/userChrome.css"
FIREJAIL_PROFILE="$SCATTER_HOME/scatter-browser/scatter-browser.profile"

# Learner profile refusal — no web for kids in the v0 build.
PROFILE=$(python3 "$SCATTER_HOME/scatter_core.py" profile 2>/dev/null || echo researcher)
if [ "$PROFILE" = "learner" ]; then
    echo "Scatter: the learner profile stays local — no web browsing in this build."
    exit 1
fi

# Pick the engine. LibreWolf wins; Firefox is the fallback so the bar
# doesn't dead-end while LibreWolf is being installed.
if command -v librewolf >/dev/null 2>&1; then
    ENGINE="librewolf"
elif command -v firefox >/dev/null 2>&1; then
    ENGINE="firefox"
    echo "Scatter Browser: LibreWolf not yet installed; running on Firefox."
    echo "  To install LibreWolf: bash $SCATTER_HOME/scatter-browser/install.sh"
else
    echo "Scatter Browser: no Firefox-family engine found."
    echo "  Install LibreWolf: bash $SCATTER_HOME/scatter-browser/install.sh"
    exit 1
fi

# Profile dir + chrome/ subdir for userChrome.css.
mkdir -p "$PROFILE_DIR/chrome"

# Refresh prefs + chrome on every launch so the repo is source of truth.
[ -f "$USERJS_SRC" ]      && cp "$USERJS_SRC"      "$PROFILE_DIR/user.js"
[ -f "$USERCHROME_SRC" ]  && cp "$USERCHROME_SRC"  "$PROFILE_DIR/chrome/userChrome.css"

# Journal the launch.
python3 "$SCATTER_HOME/scatter_core.py" - <<PYJOURNAL 2>/dev/null || true
import scatter_core as sc
sc.journal_append("scatter_browser_launch", engine="$ENGINE")
PYJOURNAL

# Launch — firejail if the bubble profile is present, else direct.
if command -v firejail >/dev/null 2>&1 && [ -f "$FIREJAIL_PROFILE" ]; then
    exec firejail --profile="$FIREJAIL_PROFILE" "$ENGINE" --profile "$PROFILE_DIR" --no-remote "$@"
else
    exec "$ENGINE" --profile "$PROFILE_DIR" --no-remote "$@"
fi
