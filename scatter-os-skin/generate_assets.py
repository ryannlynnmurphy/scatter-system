#!/usr/bin/env python3
"""Generate the images used by the Plymouth + GRUB themes."""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BLACK = (10, 10, 10)
GREEN = (0, 255, 136)
AMBER = (255, 184, 0)
TEXT  = (200, 200, 208)
MUTED = (90, 90, 110)

HERE = Path(__file__).resolve().parent
PLY  = HERE / "plymouth"
GRUB = HERE / "grub"


def font(size: int):
    for p in [
        "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
        "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def draw_pixel_face(d: ImageDraw.ImageDraw, cx: int, cy: int, s: int):
    """(◉.◉) face at integer scale s px per cell."""
    def cell(x, y, c): d.rectangle((cx + x*s, cy + y*s, cx + x*s + s - 1, cy + y*s + s - 1), fill=c)
    # parens (left/right brackets simplified)
    for y in range(-3, 4): cell(-8, y, TEXT)
    cell(-9, -4, TEXT); cell(-9, 4, TEXT)
    for y in range(-3, 4): cell(7, y, TEXT)
    cell(8, -4, TEXT); cell(8, 4, TEXT)
    # eyes (outlined + green pupil)
    for x, y in [(-6,-3),(-5,-3),(-4,-3),(-3,-3),(-6,2),(-5,2),(-4,2),(-3,2),(-6,-2),(-6,-1),(-6,0),(-6,1),(-3,-2),(-3,-1),(-3,0),(-3,1)]:
        cell(x, y, TEXT)
    for x, y in [(-5,-2),(-4,-2),(-5,-1),(-4,-1),(-5,0),(-4,0),(-5,1),(-4,1)]:
        cell(x, y, GREEN)
    for x, y in [(1,-3),(2,-3),(3,-3),(4,-3),(1,2),(2,2),(3,2),(4,2),(1,-2),(1,-1),(1,0),(1,1),(4,-2),(4,-1),(4,0),(4,1)]:
        cell(x, y, TEXT)
    for x, y in [(2,-2),(3,-2),(2,-1),(3,-1),(2,0),(3,0),(2,1),(3,1)]:
        cell(x, y, GREEN)
    # mouth dot
    cell(-1, 5, AMBER); cell(0, 5, AMBER)


def splash(w=1920, h=1080, with_tagline=True):
    img = Image.new("RGB", (w, h), BLACK)
    d = ImageDraw.Draw(img)
    # subtle dotted grid
    for y in range(0, h, 40):
        for x in range(0, w, 40):
            if (x // 40 + y // 40) % 11 == 0:
                d.rectangle((x, y, x + 1, y + 1), fill=(30, 30, 42))
    # face
    draw_pixel_face(d, cx=w // 2, cy=h // 2 - 80, s=12)
    # wordmark
    f_big = font(120)
    f_tag = font(48)
    f_small = font(28)
    word = "SCATTER"
    tw = d.textlength(word, font=f_big)
    d.text(((w - tw) / 2, h // 2 + 80), word, font=f_big, fill=GREEN)
    if with_tagline:
        tag = "the alignment OS"
        tw2 = d.textlength(tag, font=f_tag)
        d.text(((w - tw2) / 2, h // 2 + 230), tag, font=f_tag, fill=AMBER)
        foot = "small tech • local • yours"
        tw3 = d.textlength(foot, font=f_small)
        d.text(((w - tw3) / 2, h - 100), foot, font=f_small, fill=MUTED)
    return img


def progress_dot(size=32, color=GREEN):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # pixel square dot (not round)
    pad = size // 4
    d.rectangle((pad, pad, size - pad - 1, size - pad - 1), fill=color + (255,))
    return img


def main():
    PLY.mkdir(parents=True, exist_ok=True)
    GRUB.mkdir(parents=True, exist_ok=True)

    sp = splash()
    sp.save(PLY / "background.png")
    sp_small = splash(1280, 720)
    sp_small.save(GRUB / "background.png")

    # Plymouth logo (face + wordmark on transparent, used by script)
    logo = Image.new("RGBA", (800, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(logo)
    draw_pixel_face(d, cx=400, cy=120, s=10)
    f = font(100)
    word = "SCATTER"
    tw = d.textlength(word, font=f)
    d.text(((800 - tw) / 2, 260), word, font=f, fill=GREEN)
    logo.save(PLY / "logo.png")

    # Progress dots for plymouth
    progress_dot(32, GREEN).save(PLY / "dot.png")
    progress_dot(32, AMBER).save(PLY / "dot-amber.png")

    # GRUB asset: simple 2-tone button for selection
    btn = Image.new("RGBA", (480, 64), (0, 0, 0, 0))
    bd = ImageDraw.Draw(btn)
    bd.rectangle((0, 0, 479, 63), outline=GREEN + (255,), width=2)
    bd.rectangle((0, 0, 3, 63), fill=GREEN + (255,))
    btn.save(GRUB / "select_bg.png")

    print("assets written to", PLY, "and", GRUB)


if __name__ == "__main__":
    main()
