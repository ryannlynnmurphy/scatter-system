#!/usr/bin/env python3
"""Generate the suite's iconic marks — flat green-on-black typographic tiles.

The 8-bit motifs in generate_icons.py were placeholders; the user asked for
something clean and dramatic. Each Scatter-suite app gets a single (or 2-3)
letter rendered in JetBrains Mono ExtraBold, green on a true-black tile.
Editorial register: no gradients, no shadows, no shine. Just the letter.

Third-party app icons (Browser, Files, Terminal, AppFlowy, OnlyOffice,
Zotero, Claude Code, scatter-code) are left to generate_icons.py — those
represent external products and should feel distinct.

Run:  python3 generate_marks.py
"""

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    raise SystemExit("Pillow required: pip install Pillow") from e


HERE = Path(__file__).resolve().parent
ICONS = HERE / "icons"
ICONS.mkdir(exist_ok=True)

SIZE = 64                 # target px (matches stylesheet orb size)
RENDER = 256              # render at 4x then downscale for clean edges
BG = (10, 10, 10)         # --scatter-black
ACCENT = (0, 255, 136)    # --scatter-green
QUIET = (170, 170, 170)   # --scatter-body, used for control tiles
RADIUS = 12               # tile corner radius (at SIZE)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-ExtraBold.ttf",
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
]


def _load_font(size_px: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size_px)
    raise FileNotFoundError("no suitable font found; install jetbrains-mono")


# Mark = (text, color). Most suite apps get a single letter in green.
# Collisions resolved with two-letter caps. Special glyphs preserved
# where they're stronger than a letter (Home keeps its house glyph).
MARKS = {
    # — Scatter suite —
    "home":    ("⌂",  ACCENT),
    "schools": ("Sc", ACCENT),
    "studio":  ("St", ACCENT),
    "music":   ("M",  ACCENT),
    "write":   ("W",  ACCENT),
    "draft":   ("D",  ACCENT),
    "film":    ("F",  ACCENT),
    "stream":  ("Sr", ACCENT),
    # — Control tiles —
    "gear":      ("•",   QUIET),
    "history":   ("···", QUIET),
    "all-apps":  ("+",   QUIET),
}


def _measure(draw: ImageDraw.ImageDraw, font, text: str):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[0], bbox[1]


def _make_tile(text: str, color: tuple[int, int, int]) -> Image.Image:
    """Render a single tile at RENDER px and downscale to SIZE for AA."""
    img = Image.new("RGBA", (RENDER, RENDER), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded black tile.
    radius = int(RADIUS * (RENDER / SIZE))
    draw.rounded_rectangle(
        (0, 0, RENDER - 1, RENDER - 1),
        radius=radius,
        fill=BG + (255,),
    )

    # Find the largest font size that fits the text inside ~70% of the tile.
    target = int(RENDER * 0.62)
    size_px = int(RENDER * 0.66)
    while size_px > 16:
        font = _load_font(size_px)
        w, h, _, _ = _measure(draw, font, text)
        if w <= target and h <= target:
            break
        size_px -= 6

    w, h, ox, oy = _measure(draw, font, text)
    x = (RENDER - w) // 2 - ox
    y = (RENDER - h) // 2 - oy
    # Optical centering nudge: glyphs sit better with a slight upward bias.
    y -= int(RENDER * 0.02)
    draw.text((x, y), text, fill=color + (255,), font=font)

    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    for slug, (text, color) in MARKS.items():
        out = ICONS / f"{slug}.png"
        tile = _make_tile(text, color)
        tile.save(out)
        print(f"wrote {out.name}: '{text}' @ {SIZE}px")


if __name__ == "__main__":
    main()
