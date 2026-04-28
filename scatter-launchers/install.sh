#!/usr/bin/env bash
# scatter-launchers/install.sh — wire the seven Scatter suite apps into
# the local desktop. Idempotent; safe to re-run.
#
# What it does:
#   1. Hard-links bin/scatter-app to ~/.local/bin/scatter-app so the
#      launcher and the canonical source share an inode (same pattern as
#      scatter-bar).
#   2. Hard-links every applications/*.desktop into
#      ~/.local/share/applications/ so GNOME picks them up.
#   3. Refreshes the desktop database so the new entries are reachable
#      via gtk-launch and the GNOME app grid.
#
# Hard-links rather than copies: editing either side is the same edit.
# Hard-links rather than symlinks: snap-confined chromium occasionally
# refuses to follow symlinks out of the user's data dir.

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$BIN_DIR" "$APPS_DIR" "$HOME/.config/scatter/logs" "$HOME/.config/scatter/app-data"

# 1. Launcher script
TARGET="$BIN_DIR/scatter-app"
SOURCE="$SCRIPT_DIR/scatter-app"
[[ -e "$TARGET" ]] && rm -f "$TARGET"
ln "$SOURCE" "$TARGET"
chmod +x "$TARGET"
echo "ok  $TARGET ← scatter-launchers/scatter-app"

# 2. Desktop entries
for src in "$SCRIPT_DIR"/applications/scatter-*.desktop; do
  name=$(basename "$src")
  target="$APPS_DIR/$name"
  [[ -e "$target" ]] && rm -f "$target"
  ln "$src" "$target"
  echo "ok  $target ← scatter-launchers/applications/$name"
done

# 3. Database refresh
update-desktop-database "$APPS_DIR" 2>/dev/null || true
echo
echo "Installed. Click any of these from the GNOME app grid:"
echo "  Scatter Schools / Studio / Music / Write / Draft / Film / Stream"
echo
echo "Or summon them via the Scatter bar's >-< face (after gnome-shell reload)."
