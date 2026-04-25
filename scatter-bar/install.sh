#!/usr/bin/env bash
# Install the Scatter Bar GNOME Shell extension.
# No sudo — extensions install under ~/.local/share/gnome-shell/extensions/.
#
# After install:
#   1. Log out + back in (or restart GNOME Shell: Alt+F2, r, Enter on X11;
#      Wayland requires a full log out).
#   2. Enable: gnome-extensions enable scatter-bar@scattercomputing.org
set -eu

UUID="scatter-bar@scattercomputing.org"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/gnome-shell/extensions/$UUID"

echo "Installing Scatter Bar extension..."
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -r "$SRC" "$DEST"
rm -f "$DEST/install.sh"

echo "  ✓ installed at $DEST"

# Window controls: minimize, maximize, close — on the right, in that order.
# Every window gets the full set so users always have a way to step a window
# out of the way without closing it. Pixel-art glyph theming for these
# buttons (vs. Adwaita's default dots) is a separate, GTK-theme-level pass.
if command -v gsettings >/dev/null 2>&1; then
    gsettings set org.gnome.desktop.wm.preferences button-layout 'appmenu:minimize,maximize,close' || true
    echo "  ✓ window controls: 'appmenu:minimize,maximize,close'"
fi
echo
echo "  next steps:"
echo "    1. log out + log back in (or restart the shell on X11)"
echo "    2. gnome-extensions enable $UUID"
echo "    3. the router at http://127.0.0.1:8787 must be running"
echo "    4. click 'scatter' in the top bar, type, press Enter"
echo
echo "  to remove: rm -rf $DEST"
