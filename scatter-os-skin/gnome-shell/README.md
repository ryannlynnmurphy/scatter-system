# Scatter gnome-shell chrome overrides

Source-of-truth for the panel-chrome CSS appended to the live Scatter
gnome-shell theme at `~/.themes/Scatter/gnome-shell/gnome-shell.css`.

- `scatter-chrome.css` — the override block. Manually appended to the
  compiled theme file. There is no regeneration pipeline for the
  gnome-shell theme yet, so these edits live on disk and in this file.

## What it does

- Kills the top-left Activities pill and workspace dot (off-brand).
- Mutes the top-right system status icons (wifi / sound / battery) to
  ~45% opacity; they brighten to full on hover.
- Restyles the clock: Inter 12px, `#8a8a98`, no background, centered.
- Transparent panel background, no hairline — the clock reads as a
  floating mark, not a bar.

## Applying

```bash
# Append to the live theme (idempotent — check with `grep`).
cat scatter-chrome.css >> ~/.themes/Scatter/gnome-shell/gnome-shell.css
# Reload by logging out + back in (Wayland).
```
