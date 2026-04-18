#!/usr/bin/env bash
# Install the Scatter Watts GNOME Shell extension.
# No sudo — extensions install under ~/.local/share/gnome-shell/extensions/.
#
# After install you'll need to:
#   1. Log out + back in (or restart GNOME Shell: Alt+F2, r, Enter on X11;
#      or just log out/in on Wayland).
#   2. Enable via Extensions app or:
#      gnome-extensions enable scatter-watts@scattercomputing.org
set -eu

UUID="scatter-watts@scattercomputing.org"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/gnome-shell/extensions/$UUID"

echo "Installing Scatter Watts extension..."
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -r "$SRC" "$DEST"

# Remove the install script itself from the installed copy — it's not part
# of the extension.
rm -f "$DEST/install.sh"

echo "  ✓ installed at $DEST"
echo
echo "  next steps:"
echo "    1. log out + log back in (GNOME Shell needs to pick up the new extension)"
echo "    2. enable: gnome-extensions enable $UUID"
echo "    3. you'll see 'scatter · 0.0 J' appear in the top bar; it refreshes"
echo "       every 10 seconds and rises as Scatter does work."
echo
echo "  to remove: rm -rf $DEST"
