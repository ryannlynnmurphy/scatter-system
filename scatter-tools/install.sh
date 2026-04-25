#!/usr/bin/env bash
# Install Phase 1 of the Scatter tool ring.
#
# What this installs:
#   - flatpak + Flathub remote (one-time, requires sudo)
#   - OnlyOffice Desktop Editors  (write / spreadsheet / slides)
#   - AppFlowy                    (notes / docs)
#   - Zotero                      (research / citations)
#   - VLC                         (media)
#   - Blanket                     (ambient focus)
#   - Excalidraw                  (web shortcut into Scatter Browser)
#
# Deferred to Phase 2 (needs Docker):
#   - Stirling-PDF
#
# Idempotent: re-running upgrades existing installs.
set -eu

SCATTER_HOME="${SCATTER_HOME:-$HOME/scatter-system}"
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"

# ── Step 1: flatpak + Flathub ────────────────────────────────────────────
if ! command -v flatpak >/dev/null 2>&1; then
    echo "── Installing flatpak"
    sudo apt-get update -qq
    sudo apt-get install -y flatpak gnome-software-plugin-flatpak
fi

if ! flatpak remotes 2>/dev/null | grep -q '^flathub'; then
    echo "── Adding Flathub remote"
    flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
fi

# ── Step 2: install each tool ────────────────────────────────────────────
install_flatpak() {
    local id="$1"
    local label="$2"
    if flatpak --user info "$id" >/dev/null 2>&1; then
        echo "  ✓ $label already installed"
    else
        echo "── Installing $label ($id)"
        flatpak install --user --noninteractive --assumeyes flathub "$id"
    fi
}

install_flatpak "org.onlyoffice.desktopeditors"   "OnlyOffice"
install_flatpak "io.appflowy.AppFlowy"            "AppFlowy"
install_flatpak "org.zotero.Zotero"               "Zotero"
install_flatpak "org.videolan.VLC"                "VLC"
install_flatpak "com.rafaelmardojai.Blanket"      "Blanket"

# ── Step 3: Excalidraw — web shortcut into Scatter Browser ───────────────
# Excalidraw has no maintained Linux desktop build; the canonical
# experience is excalidraw.com in a hardened browser. We launch it inside
# the Scatter Browser bubble so the privacy posture carries through.
cat > "$APPS_DIR/scatter-excalidraw.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Excalidraw
GenericName=Whiteboard
Comment=draw, sketch, diagram — in your bubble
Exec=$SCATTER_HOME/scatter-browser/launcher.sh --new-window https://excalidraw.com
Icon=accessories-painting
Terminal=false
Categories=Graphics;Office;
StartupNotify=true
EOF
echo "  ✓ Excalidraw shortcut written (opens in Scatter Browser)"

# ── Step 4: refresh desktop database so the bar can find them ─────────────
update-desktop-database "$APPS_DIR" 2>/dev/null || true

echo
echo "  ✓ Phase 1 tool ring installed"
echo "  Reach them from the Scatter bar (>-< → orb), or by typing"
echo "  any of: 'write', 'note', 'research', 'play music', 'focus',"
echo "  'draw' into the talk-to-scatter prompt."
echo
echo "  Phase 2 (queued): Stirling-PDF (needs Docker), Audacity, OBS,"
echo "  ProtonMail, LocalSend, Linkding, Flatnotes, Navidrome, Homepage."
