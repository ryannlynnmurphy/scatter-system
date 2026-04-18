"""Scatter face — the (◉.◉) mascot with emotional range.

One vocabulary, one source of truth. Every Scatter surface that renders a face
pulls from here so idle, thinking, online, sleeping, error etc. are consistent
across the chat header, the wallpaper, the terminal prompt, and future chrome.

Rules (anti-slop):
  1. EYES are always in the circle family: ◉ ● ○ ◎ ╳
  2. MOUTH is always minimal punctuation: . _ · — o !
  3. Emotional states that are about MODE (online, offline) change COLOR
     of a constant face, not the glyph. Glyph changes are reserved for
     activity (thinking, sleeping, error).
  4. No kaomoji. No decorative unicode. No ᵕ, ω, ᗕ, etc.

A face that violates these rules is slop — the validator at the bottom of
this module catches it at import time.
"""

# Glyph vocabulary — the only characters allowed in a Scatter face.
# Lowercase x is the "broken/dead eye" family — smaller and cuter than ╳.
_EYES  = set("◉●○◎x")
_MOUTH = set(". _·—o")

FACES = {
    # state      face         # meaning
    "idle":     "(◉.◉)",      # default, awake, neutral
    "ready":    "(◉.◉)",      # same as idle — mode ≠ glyph
    "thinking": "(●_●)",      # eyes focused, mouth pensive
    "building": "(●.●)",      # focused, narrower eyes, steady mouth
    "curious":  "(◎.◎)",      # wide eyes, open mouth-dot
    "happy":    "(◉·◉)",      # same eyes as idle, smaller mouth = lightness
    "online":   "(◉.◉)",      # glyph identical to idle; render in amber
    "sleeping": "(○—○)",      # empty eyes, flat mouth
    "error":    "(x.x)",      # small, cute, dead — not aggressive
    "winking":  "(●.◉)",      # one focused, one open — circle family only
}

# Color tokens (hex) — the eye/glyph color for each state.
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
        if not (f.startswith("(") and f.endswith(")")):
            problems.append(f"{name}: {f!r} must be wrapped in ()")
            continue
        inner = f[1:-1]
        if len(inner) != 3:
            problems.append(f"{name}: {f!r} inner must be exactly 3 chars, got {len(inner)}")
            continue
        left, mouth, right = inner[0], inner[1], inner[2]
        if left not in _EYES:
            problems.append(f"{name}: left eye {left!r} not in canon {sorted(_EYES)}")
        if right not in _EYES:
            problems.append(f"{name}: right eye {right!r} not in canon {sorted(_EYES)}")
        if mouth not in _MOUTH:
            problems.append(f"{name}: mouth {mouth!r} not in canon {sorted(_MOUTH)}")
    if problems:
        raise ValueError("Scatter face slop detected:\n  " + "\n  ".join(problems))


_detect_slop()


if __name__ == "__main__":
    # Render the whole vocabulary for inspection.
    for name, f in FACES.items():
        print(f"  {name:10s} {f}  {EYE_COLOR[name]}")
