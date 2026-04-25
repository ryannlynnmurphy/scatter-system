#!/usr/bin/env bash
# Install LibreWolf via the official APT repository, then install the Scatter
# policies file (renames the default search engine to "Scatter") and the
# Scatter Browser .desktop entry.
#
# Needs sudo for the apt portion. The Scatter overrides themselves install
# without sudo into /etc/librewolf/policies/ via a sudo cp at the end.
#
# Idempotent: re-running upgrades LibreWolf, refreshes policies.json, and
# reinstalls the .desktop entry.
set -eu

SCATTER_HOME="${SCATTER_HOME:-$HOME/scatter-system}"
SRC="$SCATTER_HOME/scatter-browser"

if ! command -v apt >/dev/null 2>&1; then
    echo "scatter-browser/install.sh: apt not found — this script targets Debian/Ubuntu."
    exit 1
fi

echo "── Step 1: extrepo (LibreWolf APT repo enabler)"
sudo apt-get update -qq
sudo apt-get install -y extrepo

echo "── Step 2: enable LibreWolf repo"
sudo extrepo enable librewolf

echo "── Step 3: install LibreWolf"
sudo apt-get update -qq
sudo apt-get install -y librewolf

echo "── Step 4: install Scatter policies.json (renames search engine to Scatter)"
sudo mkdir -p /etc/librewolf/policies
sudo cp "$SRC/policies.json" /etc/librewolf/policies/policies.json

echo "── Step 5: install Scatter Browser .desktop entry"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/scatter-browser.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Scatter
GenericName=Web Browser
Comment=scatter search everywhere
Exec=$SRC/launcher.sh %U
Icon=librewolf
Terminal=false
Categories=Network;WebBrowser;
MimeType=text/html;text/xml;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;
StartupNotify=true
StartupWMClass=librewolf
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo
echo "  ✓ Scatter Browser ready"
echo "  Launch via the Scatter bar (>-< → Scatter) or:"
echo "    $SRC/launcher.sh"
