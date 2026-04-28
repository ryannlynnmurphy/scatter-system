#!/usr/bin/env bash
# One-shot: bind Ctrl+Alt+H → Scatter Home (gtk-launch).
set -euo pipefail
BASE="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0"
gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['${BASE}/']"
gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${BASE}/" name 'Scatter Home'
gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${BASE}/" command 'gtk-launch scatter-home.desktop'
gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${BASE}/" binding '<Primary><Alt>h'
echo "Scatter Home bound to Ctrl+Alt+H."
