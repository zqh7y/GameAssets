"""Draw the effect shapes used for the brawlers' particle effects.

Output: effects/<name>.png (white shapes on a transparent background, 128 x 128 px)

    dot     filled circle        embers, sparks, mist, smoke
    ring    thin circle          bubbles, shockwaves
    glint   four-point sparkle   fuse sparks, magic twinkles
    sliver  small curved petal   feathers, leaves
    glow    soft round light     auras behind a brawler

The effects are meant to be super minimal: a few plain flat shapes in one colour, with no
outlines and no detail. So the shapes are white, and the game (or the example script) tints
them with the brawler's colour and moves them around. Five tiny sprites cover every effect.

Each shape is drawn at 8x the final size and scaled down, so the edges are smooth.

Requires: Pillow
Run from the repo root:  python3 scripts/make_effects.py
"""

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "effects"

SIZE = 128          # final sprite size in pixels
SS = 8              # supersampling factor
C = SIZE * SS       # working canvas size


def blank() -> Image.Image:
    return Image.new("L", (C, C), 0)


def circle(cx: float, cy: float, r: float) -> Image.Image:
    m = blank()
    ImageDraw.Draw(m).ellipse(((cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS), fill=255)
    return m


def polygon(points: list[tuple[float, float]]) -> Image.Image:
    """Mask of a polygon given in final-pixel coordinates."""
    m = blank()
    ImageDraw.Draw(m).polygon([(x * SS, y * SS) for x, y in points], fill=255)
    return m


def rounded(mask: Image.Image, radius: float) -> Image.Image:
    """Round off a shape: blur its mask and cut it again at the halfway point."""
    soft = mask.filter(ImageFilter.GaussianBlur(radius * SS))
    return soft.point(lambda v: 255 if v >= 128 else 0)


def white(mask: Image.Image) -> Image.Image:
    """A white sprite whose transparency is the given mask, at the final size."""
    img = Image.new("RGBA", (C, C), (255, 255, 255, 0))
    img.putalpha(mask)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


# ---------------------------------------------------------------- the shapes

def dot() -> Image.Image:
    return white(circle(64, 64, 56))


def ring() -> Image.Image:
    return white(ImageChops.subtract(circle(64, 64, 56), circle(64, 64, 45)))


def glint() -> Image.Image:
    """Four-point sparkle with long thin rays; the vertical rays are the longer ones."""
    tall, wide, waist = 60, 40, 6.5
    pts = []
    for i in range(8):
        a = math.pi * i / 4 - math.pi / 2
        r = waist if i % 2 else (tall if i % 4 == 0 else wide)
        pts.append((64 + r * math.cos(a), 64 + r * math.sin(a)))
    return white(rounded(polygon(pts), 1.0))


def sliver() -> Image.Image:
    """Small curved petal: pointed at both ends, fuller on one side."""
    pts = []
    for i in range(41):                         # upper edge, fuller
        t = i / 40
        pts.append((14 + 100 * t, 70 - 26 * math.sin(math.pi * t) ** 0.8 - 8 * t))
    for i in range(41):                         # lower edge, flatter
        t = 1 - i / 40
        pts.append((14 + 100 * t, 70 + 9 * math.sin(math.pi * t) - 8 * t))
    return white(rounded(polygon(pts), 2.0))


def glow() -> Image.Image:
    """Soft round light that fades smoothly to nothing at its edge."""
    m = Image.new("L", (SIZE, SIZE), 0)
    px = m.load()
    for y in range(SIZE):
        for x in range(SIZE):
            r = math.hypot(x - 63.5, y - 63.5) / 63.5
            px[x, y] = round(255 * max(0.0, 1 - r) ** 1.6)
    img = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 0))
    img.putalpha(m)
    return img


SHAPES = {"dot": dot, "ring": ring, "glint": glint, "sliver": sliver, "glow": glow}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, draw in SHAPES.items():
        img = draw()
        img.save(OUT / f"{name}.png", optimize=True)
        print(f"{name:8s} {img.size}")


if __name__ == "__main__":
    main()
