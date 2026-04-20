"""Scatter face — the >.< glyph with emotional range.

One vocabulary, one source of truth. Every Scatter surface that renders a face
pulls from here so idle, thinking, online, sleeping, error etc. are consistent
across the chat header, the wallpaper, the terminal prompt, and future chrome.

The face is a function expression: >state<. Outer characters are always the
redirect arrows (`>`, `<`) — code-shaped, terminal-shaped. The state lives
in the middle character. ASCII keyboard glyphs only — no fancy unicode.
This is on purpose: the face IS code, not a mascot.

Rules (anti-slop):
  1. Outer eyes are always `>` then `<` — angle brackets, redirect-shaped.
  2. Middle is one of:  . - = ! O _ x ·
       . idle / quiet     - working / line       = producing / equals
       ! alert            O open / signaling     _ dropped / sleeping
       x broken           · light / smaller
  3. State changes that are about MODE (online vs offline) change COLOR
     of the glyph, not the bracket frame.
  4. No kaomoji. No decorative unicode. No ᵕ, ω, ᗕ, etc.

A face that violates these rules is slop — the validator at the bottom of
this module catches it at import time.
"""

# Glyph vocabulary — the only characters allowed in a Scatter face.
_LEFT  = ">"
_RIGHT = "<"
_MIDDLE = set(".-=!O_x·")

FACES = {
    # state      face       # meaning
    "idle":     ">.<",      # default, awake, quiet
    "ready":    ">.<",      # same as idle — mode ≠ glyph
    "thinking": ">-<",      # line through, working
    "building": ">=<",      # equals — producing output
    "curious":  ">O<",      # open eye outward, taking in
    "happy":    ">·<",      # smaller mid-dot, lighter
    "online":   ">O<",      # alert, signaling out (rendered amber)
    "sleeping": ">_<",      # dropped, baseline
    "error":    ">x<",      # broken
    "winking":  ">!<",      # alert, punctuating
}

# Color tokens (hex) — the glyph color for each state.
# idle and ready are green; online flips to amber so mode is visually loud.
EYE_COLOR = {
    "idle":     "#00ff88",
    "ready":    "#00ff88",
    "thinking": "#c8c8d0",
    "building": "#00ff88",
    "curious":  "#c8c8d0",
    "happy":    "#00ff88",
    "online":   "#ffb800",
    "sleeping": "#5a5a6e",
    "error":    "#ff3355",
    "winking":  "#00ff88",
}


def face(state: str = "idle") -> str:
    return FACES.get(state, FACES["idle"])


def eye_color(state: str = "idle") -> str:
    return EYE_COLOR.get(state, EYE_COLOR["idle"])


# ── Slop detector ──────────────────────────────────────────────────────
# Fail loud if a face uses characters outside the canon. Run on import;
# any future "creative additions" that reach for kaomoji get rejected
# before they ship.

def _detect_slop():
    problems = []
    for name, f in FACES.items():
        if len(f) != 3:
            problems.append(f"{name}: {f!r} must be exactly 3 chars (>state<), got {len(f)}")
            continue
        left, mid, right = f[0], f[1], f[2]
        if left != _LEFT:
            problems.append(f"{name}: left {left!r} must be {_LEFT!r}")
        if right != _RIGHT:
            problems.append(f"{name}: right {right!r} must be {_RIGHT!r}")
        if mid not in _MIDDLE:
            problems.append(f"{name}: middle {mid!r} not in canon {sorted(_MIDDLE)}")
    if problems:
        raise ValueError("Scatter face slop detected:\n  " + "\n  ".join(problems))


_detect_slop()


if __name__ == "__main__":
    # Render the whole vocabulary for inspection.
    for name, f in FACES.items():
        print(f"  {name:10s} {f}  {EYE_COLOR[name]}")
