# Scatter Design System

Single source of truth for the Scatter visual language. Every surface — shell
extension, boot splash, web UIs, app chrome — references these tokens.

## Files

- `tokens.css` — palette, type scale, spacing, radius, motion
- `buttons.css` — the button spec

## Rules

1. **One accent color (amber, `#ffb800`).** Used once per surface.
2. **Two radii: 0px (sharp) and 2px (soft).** No rounded-everywhere.
3. **No drop shadows. No gradients.**
4. **Typography:** Inter for display/body, JetBrains Mono for code/glyphs.
5. **Labels are uppercase, tracked `0.08em`, SemiBold.** Editorial register.
6. **Motion is durational** (`220ms` base, `420ms` slow). Not snappy.

## Applying in GNOME Shell extensions

GNOME Shell CSS does not support `:root` / `@import` reliably. Mirror the
values inline, and leave a comment pointing back to this directory when you
do. The comment is the contract: when tokens change here, every mirror must
be updated.

## Audit principle

When adding any new visible control anywhere in the OS, ask: does this button
match the Scatter button spec? If not, fix the spec or fix the button. Do not
ship divergent chrome.
