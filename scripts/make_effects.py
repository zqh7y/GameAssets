"""Draw the small effect sprites that go with the brawlers.

Output: effects/<name>.png (transparent PNGs, 128 x 128 px)

    spark    fuse spark            (TNT)
    sparkle  magic twinkle         (Mage)
    flame    small flame           (Dragon)
    wisp     ghostly wisp          (Ghost)
    leaf     drifting leaf         (Acorn)
    bubble   bubble                (Octopus)
    feather  floating feather      (Peep)

Every effect is drawn from simple shapes at 8x the final size and scaled down, so the
edges are smooth. They share the brawlers' look: flat colour, an outline in a darker
shade, and the same soft shading from the top left.

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/make_effects.py
"""

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from shade_brawlers import shade_sprite

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "effects"

SIZE = 128          # final sprite size in pixels
SS = 8              # supersampling factor
C = SIZE * SS       # working canvas size


def blank() -> Image.Image:
    return Image.new("L", (C, C), 0)


def rounded(mask: Image.Image, radius: float) -> Image.Image:
    """Round off a shape: blur its mask and cut it again at the halfway point."""
    soft = mask.filter(ImageFilter.GaussianBlur(radius * SS))
    return soft.point(lambda v: 255 if v >= 128 else 0)


def grow(mask: Image.Image, px: float) -> Image.Image:
    """Mask enlarged by `px` final pixels on every side (used for outlines)."""
    soft = mask.filter(ImageFilter.GaussianBlur(px * SS * 0.5))
    return soft.point(lambda v: 255 if v >= 28 else 0)


def polygon(points: list[tuple[float, float]]) -> Image.Image:
    """Mask of a polygon given in final-pixel coordinates."""
    m = blank()
    ImageDraw.Draw(m).polygon([(x * SS, y * SS) for x, y in points], fill=255)
    return m


def circle(cx: float, cy: float, r: float) -> Image.Image:
    m = blank()
    ImageDraw.Draw(m).ellipse(((cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS), fill=255)
    return m


def union(*masks: Image.Image) -> Image.Image:
    out = masks[0]
    for m in masks[1:]:
        out = ImageChops.lighter(out, m)
    return out


def star(cx: float, cy: float, points: int, r_out: float, r_in: float, turn: float = 0.0) -> Image.Image:
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = turn + math.pi * i / points - math.pi / 2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return polygon(pts)


def paint(layers: list[tuple[Image.Image, tuple[int, ...]]]) -> Image.Image:
    """Stack (mask, colour) layers, bottom first, into an RGBA canvas."""
    img = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    for mask, colour in layers:
        rgba = colour if len(colour) == 4 else (*colour, 255)
        layer = Image.new("RGBA", (C, C), rgba)
        layer.putalpha(ImageChops.multiply(mask, Image.new("L", (C, C), rgba[3])))
        img.alpha_composite(layer)
    return img


def finish(img: Image.Image, shade: float = 0.8) -> Image.Image:
    """Scale down to the final size and add the same soft shading as the brawlers."""
    small = img.resize((SIZE * 2, SIZE * 2), Image.LANCZOS)
    if shade > 0:
        small = shade_sprite(small, strength=shade, up=1)
    return small.resize((SIZE, SIZE), Image.LANCZOS)


# ---------------------------------------------------------------- the effects

def spark() -> Image.Image:
    """Fuse spark: a spiky orange burst with a yellow core."""
    outer = rounded(union(star(64, 64, 4, 50, 15), star(64, 64, 4, 34, 13, math.pi / 4)), 1.6)
    inner = rounded(union(star(64, 64, 4, 30, 9), star(64, 64, 4, 19, 8, math.pi / 4)), 1.2)
    return finish(paint([
        (grow(outer, 5), (132, 46, 12)),
        (outer, (255, 150, 40)),
        (inner, (255, 232, 110)),
        (circle(64, 64, 6.5), (255, 252, 230)),
    ]))


def sparkle() -> Image.Image:
    """Magic twinkle: a slim four-point star."""
    body = rounded(star(64, 64, 4, 52, 11), 1.5)
    core = rounded(star(64, 64, 4, 30, 6), 1.0)
    return finish(paint([
        (grow(body, 4.5), (190, 118, 22)),
        (body, (255, 228, 110)),
        (core, (255, 252, 226)),
    ]))


def flame() -> Image.Image:
    """Small flame: a teardrop leaning to one side, with a yellow heart."""
    outer = rounded(union(circle(62, 82, 30), polygon([(36, 70), (90, 76), (76, 14)])), 5)
    inner = rounded(union(circle(62, 90, 17), polygon([(48, 86), (77, 88), (68, 48)])), 4)
    return finish(paint([
        (grow(outer, 5), (128, 40, 10)),
        (outer, (246, 112, 34)),
        (inner, (255, 214, 92)),
    ]))


def wisp() -> Image.Image:
    """Ghostly wisp: a pale comma with a curling tail, in the Ghost's colours."""
    blobs = [circle(52, 78, 27)]
    for i in range(1, 15):                      # tail: shrinking circles along a curve
        t = i / 14
        a = math.radians(205 + 130 * t)
        blobs.append(circle(58 + 31 * math.cos(a) + 30 * t, 62 + 32 * math.sin(a) - 4 * t, 20 * (1 - t) + 3.5))
    body = rounded(union(*blobs), 3)
    return finish(paint([
        (grow(body, 4.5), (104, 146, 176)),
        (body, (208, 234, 250)),
        (circle(47, 71, 8), (240, 250, 255)),
    ]), shade=0.6)


def leaf() -> Image.Image:
    """Drifting leaf: a pointed oval with a stem and a centre vein, tilted."""
    pts = []
    for i in range(41):                         # two arcs meeting in points at both ends
        t = i / 40
        pts.append((22 + 78 * t, 64 - 27 * math.sin(math.pi * t) ** 0.85))
    for i in range(41):
        t = 1 - i / 40
        pts.append((22 + 78 * t, 64 + 27 * math.sin(math.pi * t) ** 0.85))
    blade = rounded(polygon(pts), 1.5)
    stem = polygon([(8, 61), (26, 62), (26, 66), (8, 67)])
    vein = polygon([(26, 62.6), (88, 63.2), (88, 64.8), (26, 65.4)])
    img = paint([
        (grow(union(blade, rounded(stem, 1)), 4.5), (124, 56, 14)),
        (rounded(stem, 1), (150, 82, 26)),
        (blade, (242, 134, 42)),
        (vein, (196, 92, 22)),
    ])
    return finish(img.rotate(28, resample=Image.BICUBIC))


def bubble() -> Image.Image:
    """Bubble: a see-through ball with a rim and a white highlight."""
    ball = circle(64, 64, 44)
    ring = ImageChops.subtract(ball, circle(64, 64, 36))
    shine = rounded(polygon([(40, 52), (46, 40), (58, 34), (62, 39), (52, 44), (46, 55)]), 2)
    return finish(paint([
        (grow(ball, 4), (62, 132, 186)),
        (ball, (214, 242, 253, 105)),
        (ring, (150, 212, 244, 170)),
        (shine, (255, 255, 255)),
        (circle(82, 86, 4.5), (255, 255, 255, 220)),
    ]), shade=0)


def feather() -> Image.Image:
    """Floating feather: a curved yellow plume with a quill, in the Peep's colours."""
    pts = []
    for i in range(41):                         # upper edge, fuller
        t = i / 40
        pts.append((24 + 82 * t, 70 - 30 * math.sin(math.pi * t) ** 0.7 - 10 * t))
    for i in range(41):                         # lower edge, flatter
        t = 1 - i / 40
        pts.append((24 + 82 * t, 70 + 12 * math.sin(math.pi * t) ** 0.9 - 10 * t))
    plume = rounded(polygon(pts), 2.5)
    notch = polygon([(66, 30), (74, 46), (80, 28)])
    plume = ImageChops.subtract(plume, rounded(notch, 1))
    quill = polygon([(8, 74), (100, 61), (100, 63.6), (8, 78)])
    img = paint([
        (grow(union(plume, rounded(quill, 1)), 4.5), (156, 100, 18)),
        (plume, (255, 222, 76)),
        (rounded(quill, 0.8), (232, 168, 44)),
    ])
    return finish(img.rotate(-18, resample=Image.BICUBIC))


EFFECTS = {"spark": spark, "sparkle": sparkle, "flame": flame, "wisp": wisp,
           "leaf": leaf, "bubble": bubble, "feather": feather}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, draw in EFFECTS.items():
        img = draw()
        img.save(OUT / f"{name}.png", optimize=True)
        box = img.getbbox()
        print(f"{name:8s} {img.size}  drawn area {box[2] - box[0]} x {box[3] - box[1]}")


if __name__ == "__main__":
    main()
