#!/usr/bin/env bash
# Scatter Browser launcher — Firefox with the Scatter profile, in the bubble.
#
# Profile location: ~/.scatter/firefox-profile/
# First run: copies user.js from the repo into the profile to harden
# defaults. Subsequent runs inherit that hardening.
#
# Firejail sandbox: loaded from scatter-browser.profile in this directory.
# If firejail isn't installed, falls back to plain firefox with a clear
# notice. Install with: sudo apt install firejail
set -eu

SCATTER_HOME="${SCATTER_HOME:-$HOME/scatter-system}"
PROFILE_DIR="$HOME/.scatter/firefox-profile"
USERJS_SRC="$SCATTER_HOME/scatter-browser/profile/user.js"
FIREJAIL_PROFILE="$SCATTER_HOME/scatter-browser/scatter-browser.profile"

# Learner profile refusal
PROFILE=$(python3 "$SCATTER_HOME/scatter_core.py" profile 2>/dev/null || echo researcher)
if [ "$PROFILE" = "learner" ]; then
    echo "Scatter: the learner profile stays local — no web browsing in this build."
    exit 1
fi

# Create the Scatter Firefox profile if needed.
if [ ! -d "$PROFILE_DIR" ]; then
    echo "Scatter: first launch — creating the Scatter Firefox profile..."
    mkdir -p "$PROFILE_DIR"
fi

# Refresh user.js every launch so edits to the repo propagate. User changes
# to prefs (via about:config) persist in prefs.js, which Firefox writes on
# exit — those override user.js where they differ, but only at session
# start. This keeps scatter-browser.git-repo the source of truth for
# baseline hardening.
if [ -f "$USERJS_SRC" ]; then
    cp "$USERJS_SRC" "$PROFILE_DIR/user.js"
fi

# Journal the launch.
python3 "$SCATTER_HOME/scatter_core.py" - <<'PYJOURNAL' 2>/dev/null || true
import scatter_core as sc
sc.journal_append("scatter_browser_launch", profile="researcher")
PYJOURNAL

# Launch.
if command -v firejail >/dev/null 2>&1 && [ -f "$FIREJAIL_PROFILE" ]; then
    exec firejail --profile="$FIREJAIL_PROFILE" firefox --profile "$PROFILE_DIR" --no-remote "$@"
elif command -v firejail >/dev/null 2>&1; then
    echo "Scatter Browser: firejail present but Scatter profile missing — using default firejail firefox profile"
    exec firejail firefox --profile "$PROFILE_DIR" --no-remote "$@"
else
    echo "Scatter Browser: firejail not installed — running outside the sandbox."
    echo "  Install with: sudo apt install firejail"
    exec firefox --profile "$PROFILE_DIR" --no-remote "$@"
fi
