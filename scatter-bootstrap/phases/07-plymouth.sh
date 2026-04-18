#!/usr/bin/env bash
# 07-plymouth — SUDO. Install a minimal Scatter Plymouth boot theme.
#
# The theme itself is a tiny two-file package:
#   - scatter.plymouth   (theme descriptor)
#   - scatter.script     (tiny ScreenObject animation showing the Scatter glyph)
# Installed into /usr/share/plymouth/themes/scatter/ and selected via
# plymouth-set-default-theme.
#
# Reversible: we save the current default theme name in ~/.scatter/
# plymouth-previous.txt before switching.
set -eu

APPLY="${SCATTER_APPLY:-0}"
APPLY_SUDO="${SCATTER_APPLY_SUDO:-0}"
SCATTER_HOME="${SCATTER_HOME:?}"

DIM=$'\033[2m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

# Ubuntu 24.04 dropped the plymouth-set-default-theme helper. Modern
# selection is via update-alternatives on /usr/share/plymouth/themes/default.plymouth
# which is a symlink to the chosen theme's .plymouth file.
CURRENT_LINK=$(readlink -f /usr/share/plymouth/themes/default.plymouth 2>/dev/null || echo "none")
CURRENT=$(basename "$(dirname "$CURRENT_LINK")")

if [ "$CURRENT" = "scatter" ]; then
    echo "  ${GREEN}✓${RESET} Plymouth theme is already 'scatter'"
    exit 0
fi

echo "  ${DIM}current Plymouth theme:${RESET} $CURRENT"

if [ "$APPLY" -eq 0 ] || [ "$APPLY_SUDO" -eq 0 ]; then
    echo "  ${DIM}[dry-run or no --apply-sudo]${RESET} would:"
    echo "  ${DIM}    1. copy $SCATTER_HOME/scatter/ui/scatter.svg → PNG frames"
    echo "  ${DIM}    2. write /usr/share/plymouth/themes/scatter/scatter.plymouth"
    echo "  ${DIM}    3. write /usr/share/plymouth/themes/scatter/scatter.script"
    echo "  ${DIM}    4. sudo plymouth-set-default-theme scatter --rebuild-initrd"
    echo "  ${DIM}    5. save previous theme name to ~/.scatter/plymouth-previous.txt${RESET}"
    exit 0
fi

echo "  ${YELLOW}Plymouth theme installation requires building initrd${RESET}"
echo "  ${DIM}  (the boot splash will show the Scatter glyph on every boot;"
echo "  ${DIM}   reverts with: sudo plymouth-set-default-theme \$(cat ~/.scatter/plymouth-previous.txt) --rebuild-initrd)${RESET}"
read -r -p "  proceed? [y/N] " ans
if [ "$ans" != "y" ] && [ "$ans" != "Y" ]; then
    echo "  ${YELLOW}skipped${RESET}"
    exit 0
fi

# Save previous theme for reversion.
mkdir -p "$HOME/.scatter"
echo "$CURRENT" > "$HOME/.scatter/plymouth-previous.txt"

THEME_DIR="/usr/share/plymouth/themes/scatter"
sudo mkdir -p "$THEME_DIR"

# Convert SVG glyph to PNG at 256px (single frame, static splash is fine).
SVG_SRC="$SCATTER_HOME/scatter/ui/scatter.svg"
PNG_DST="/tmp/scatter-glyph-256.png"
if command -v rsvg-convert >/dev/null 2>&1; then
    rsvg-convert -w 256 -h 256 "$SVG_SRC" -o "$PNG_DST"
elif command -v inkscape >/dev/null 2>&1; then
    inkscape "$SVG_SRC" --export-type=png --export-filename="$PNG_DST" --export-width=256 >/dev/null 2>&1
else
    echo "  ${YELLOW}no rsvg-convert or inkscape — skipping PNG render; Plymouth will use a plain text splash${RESET}"
    PNG_DST=""
fi

if [ -n "$PNG_DST" ] && [ -f "$PNG_DST" ]; then
    sudo install -m 644 "$PNG_DST" "$THEME_DIR/scatter.png"
fi

# Theme descriptor.
sudo tee "$THEME_DIR/scatter.plymouth" >/dev/null <<'PLY'
[Plymouth Theme]
Name=Scatter
Description=A single glyph fading to desktop. Climate hacker palette.
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/scatter
ScriptFile=/usr/share/plymouth/themes/scatter/scatter.script
PLY

# Minimal script: black background, centered glyph, fade in/out.
sudo tee "$THEME_DIR/scatter.script" >/dev/null <<'SCR'
Window.SetBackgroundTopColor(0.04, 0.04, 0.04);
Window.SetBackgroundBottomColor(0.04, 0.04, 0.04);

glyph.image = Image("scatter.png");
glyph.sprite = Sprite(glyph.image);
glyph.sprite.SetX(Window.GetWidth()/2 - glyph.image.GetWidth()/2);
glyph.sprite.SetY(Window.GetHeight()/2 - glyph.image.GetHeight()/2);

fun refresh_callback() {
    glyph.sprite.SetOpacity(1.0);
}
Plymouth.SetRefreshFunction(refresh_callback);
SCR

# Register + select via update-alternatives (Ubuntu 24.04 method).
THEME_FILE="/usr/share/plymouth/themes/scatter/scatter.plymouth"
sudo update-alternatives --install /usr/share/plymouth/themes/default.plymouth \
    default.plymouth "$THEME_FILE" 200 2>/dev/null || true
sudo update-alternatives --set default.plymouth "$THEME_FILE"
sudo update-initramfs -u
echo "  ${GREEN}✓${RESET} Plymouth theme 'scatter' installed; next boot will show it"
echo "  ${DIM}revert: sudo update-alternatives --config default.plymouth && sudo update-initramfs -u${RESET}"
