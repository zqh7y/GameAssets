"""Render example images that show how the brawlers look on the cards.

These are previews only, not game assets. They show the intended look: shaded brawlers at
their relative sizes (brawlers/sizes.json), standing in groups in the card window, with
ground shadows, each brawler's small particle effect and a "+N Name" label.

Input:  cards/*.png, brawlers/*.png, brawlers/sizes.json, effects/pieces/*.png
Output: examples/*.jpg

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/make_card_examples.py
"""

import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from extract_brawlers import dilate, flood
from shade_brawlers import mirror_sprite, shade_sprite

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "examples"
SIZES = json.loads((ROOT / "brawlers" / "sizes.json").read_text())

S = 2                       # examples are rendered at 2x the card size so they are easy to see

# Height of a full-size (scale 1.0) brawler as a fraction of the card window. Every brawler
# is drawn at this size times its own scale; a group is only shrunk if it would not fit.
UNIT_H = 0.72
# Where each brawler of a group stands, in multiples of the unit height: (x, ground y).
# Back row first.
FORMATIONS = {
    1: [(0.0, 0.0)],
    2: [(-0.42, -0.14), (0.42, 0.10)],
    3: [(-0.48, -0.30), (0.48, -0.30), (0.0, 0.18)],
    4: [(0.0, -0.52), (-0.60, -0.16), (0.60, -0.16), (0.0, 0.22)],
    5: [(-0.62, -0.50), (0.62, -0.50), (0.0, -0.14), (-0.66, 0.26), (0.66, 0.26)],
}
# Which brawlers of a group are mirrored, in the same order as FORMATIONS. Mixed on purpose,
# so a group looks alive instead of copy-pasted: neighbours look in different directions.
MIRRORED = {
    1: [False],
    2: [False, True],
    3: [False, True, False],
    4: [True, False, True, False],
    5: [False, True, True, True, False],
}

# Particle effects: a few of the flat shapes from effects/pieces/ per card, kept minimal.
# Each brawler uses the shapes of its own cluster (feathers for the Peep, spark for the TNT...).
#
# Attached shapes sit on a point of the brawler itself:
#   (piece, x, y, size, who)
#   piece   file name in effects/pieces/, without ".png"
#   x, y    position in the sprite, 0..1, for a brawler facing its normal way
#   size    longest side of the shape, relative to the brawler's height
#   who     "all" = every brawler in the group, "front" = only the one in front
ATTACHED = {
    "tnt": [("spark_1", 0.41, 0.00, 0.30, "all"),        # a spark on every fuse tip
            ("spark_2", 0.61, -0.09, 0.07, "front"),     # and a few sparks flying off the front one
            ("spark_5", 0.23, -0.08, 0.06, "front"),
            ("spark_9", 0.50, -0.21, 0.045, "front")],
    "wizard": [("magic_3", 0.97, 0.19, 0.21, "all"),     # a glint at the top of every staff
               ("magic_2", 0.75, 0.11, 0.15, "front"),
               ("magic_5", 1.08, 0.38, 0.06, "front")],
}
# Floating shapes drift around the whole group:
#   (piece, x, y, size, tilt)
#   x, y    relative to the group's bounding box: 0..1 across and down, so a value below 0
#           or above 1 is just outside it
#   size    longest side of the shape, relative to the brawler's height
#   tilt    degrees, counter-clockwise, added to the way the shape was drawn
FLOATING = {
    "chick": [("feathers_1", -0.04, 0.10, 0.34, 0),      # feathers falling
              ("feathers_4", 1.04, 0.36, 0.22, 0),
              ("feathers_5", 0.56, -0.07, 0.16, 0),
              ("feathers_6", 0.97, 0.02, 0.07, 0)],
    "acorn": [("leaves_1", -0.04, 0.12, 0.26, 0),        # leaves falling
              ("leaves_3", 1.04, 0.30, 0.22, 0),
              ("leaves_5", 0.50, -0.10, 0.17, 0),
              ("leaves_7", 0.93, -0.03, 0.06, 0)],
    "dragon": [("fire_2", -0.02, 0.12, 0.10, 0),         # embers rising
               ("fire_3", 0.02, 0.00, 0.075, 0),
               ("fire_7", -0.01, -0.10, 0.04, 0),
               ("fire_4", 1.02, 0.06, 0.075, 0),
               ("fire_6", 0.99, -0.06, 0.045, 0)],
    "ghost": [("mist_2", -0.07, 0.64, 0.13, 0),          # mist trailing off at the sides
              ("mist_4", -0.12, 0.77, 0.085, 0),
              ("mist_6", -0.15, 0.87, 0.05, 0),
              ("mist_3", 1.07, 0.70, 0.105, 0),
              ("mist_5", 1.12, 0.82, 0.065, 0)],
    "octopus": [("bubbles_1", -0.03, 0.08, 0.20, 0),     # bubbles
                ("bubbles_3", 1.03, 0.28, 0.14, 0),
                ("bubbles_6", 0.52, -0.10, 0.10, 0)],
}

# The label font is a placeholder: the first of these that exists is used.
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


_shaded: dict[tuple[str, bool], Image.Image] = {}


def shaded(brawler: str, flip: bool = False) -> Image.Image:
    key = (brawler, flip)
    if key not in _shaded:
        base = Image.open(ROOT / "brawlers" / f"{brawler}.png").convert("RGBA")
        base = base.crop(base.getbbox())
        if flip:
            base = mirror_sprite(brawler, base)
        _shaded[key] = shade_sprite(base)   # shaded after mirroring, so the light stays top-left
    return _shaded[key]


_effects: dict[str, Image.Image] = {}


def piece(name: str, size: float, angle: float = 0.0) -> Image.Image:
    """A shape from effects/pieces/, its longest side `size` pixels, turned by `angle` degrees."""
    if name not in _effects:
        img = Image.open(ROOT / "effects" / "pieces" / f"{name}.png").convert("RGBA")
        _effects[name] = img.crop(img.getbbox())
    src = _effects[name]
    k = max(6.0, size) / max(src.size)
    img = src.resize((max(1, round(src.width * k)), max(1, round(src.height * k))), Image.LANCZOS)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    return img


def stamp(card: Image.Image, img: Image.Image, cx: float, cy: float) -> None:
    """Draw `img` centred on (cx, cy)."""
    card.alpha_composite(img, (max(0, round(cx - img.width / 2)), max(0, round(cy - img.height / 2))))


def fit(src: Image.Image, h: float) -> Image.Image:
    """Scale a sprite to height h (a very wide sprite is limited by its width instead)."""
    k = min(h / src.height, h * 1.25 / src.width)
    return src.resize((max(1, round(src.width * k)), max(1, round(src.height * k))), Image.LANCZOS)


def window_box() -> list[int]:
    """Bounding box of the card window (x0, y0, x1, y1), in example pixels."""
    a = np.asarray(Image.open(ROOT / "cards" / "basic.png").convert("RGBA"))
    h, w = a.shape[:2]
    lum = a[..., :3].astype(np.float32).sum(axis=2) / 3
    local = np.asarray(Image.fromarray(lum.astype(np.uint8)).filter(ImageFilter.GaussianBlur(6)))
    # The window is enclosed by a thin line that is darker than its surroundings.
    wall = (lum < local.astype(np.float32) * 0.93) | (a[..., 3] < 255)
    seed = np.zeros((h, w), dtype=bool)
    seed[int(h * 0.38), w // 2] = True
    inside = flood(~dilate(wall, 1), seed)
    if not 0.30 < inside.mean() < 0.50:
        raise SystemExit(f"window detection failed (covers {inside.mean():.0%} of the card)")
    ys, xs = np.nonzero(inside)
    return [int(v) * S for v in (xs.min(), ys.min(), xs.max(), ys.max())]


def layout(brawler: str, count: int, unit_h: float, rng: random.Random):
    """A group's sprites, relative to the group's anchor: (sprite, x, ground y, mirrored)."""
    spots = FORMATIONS[count]
    ys = [s[1] for s in spots]
    units = []
    for i, (dx, dy) in enumerate(spots):
        t = (dy - min(ys)) / (max(ys) - min(ys)) if count > 1 else 1.0   # 0 = back row, 1 = front
        flip = MIRRORED[count][i]
        jitter = 1.0 + (rng.uniform(-0.04, 0.04) if count > 1 else 0.0)
        spr = fit(shaded(brawler, flip), unit_h * (0.92 + 0.08 * t) * jitter)
        if count > 1:
            spr = spr.rotate(rng.uniform(-3.0, 3.0), resample=Image.BICUBIC, expand=True)
        if t < 0.99:  # back rows fade a touch into the card colour, for depth
            haze = Image.new("RGBA", spr.size, (246, 226, 190, 0))
            haze.putalpha(spr.getchannel("A").point(lambda v: int(v * 0.10 * (1 - t))))
            spr = Image.alpha_composite(spr, haze)
        units.append((spr, dx * unit_h, dy * unit_h, flip))
    return units


def bounds(units) -> tuple[float, float, float, float]:
    x0 = min(x - s.width / 2 for s, x, y, _ in units)
    x1 = max(x + s.width / 2 for s, x, y, _ in units)
    y0 = min(y - s.height for s, x, y, _ in units)
    y1 = max(y for s, x, y, _ in units)
    return x0, y0, x1, y1


def draw_label(card: Image.Image, text_num: str, text_name: str, top: float, bottom: float) -> None:
    """Gold number and white name with a dark outline and a soft drop shadow."""
    W = card.width
    fs = 62
    while True:
        font = load_font(fs)
        gap = fs * 0.26
        wn = font.getlength(text_num)
        total = wn + gap + font.getlength(text_name)
        if total <= W * 0.78 or fs <= 30:
            break
        fs -= 2
    _, t, _, b = font.getbbox(text_num + text_name, stroke_width=5)
    tx = W / 2 - total / 2
    ty = (top + bottom) / 2 - (t + b) / 2
    parts = ((text_num, tx, (255, 214, 74, 255)), (text_name, tx + wn + gap, (255, 255, 255, 255)))

    drop = Image.new("RGBA", card.size, (0, 0, 0, 0))
    dd = ImageDraw.Draw(drop)
    for txt, x, _ in parts:
        dd.text((x, ty + 6), txt, font=font, fill=(60, 30, 10, 200), stroke_width=5, stroke_fill=(60, 30, 10, 200))
    card.alpha_composite(drop.filter(ImageFilter.GaussianBlur(3)))
    d = ImageDraw.Draw(card)
    for txt, x, colour in parts:
        d.text((x, ty), txt, font=font, fill=colour, stroke_width=5, stroke_fill=(92, 52, 28, 255))


def make_card(card_name: str, brawler: str, count: int, seed: int) -> Image.Image:
    card = Image.open(ROOT / "cards" / f"{card_name}.png").convert("RGBA")
    card = card.resize((card.width * S, card.height * S), Image.LANCZOS)
    card = card.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=2))
    wx0, wy0, wx1, wy1 = window_box()
    ww, wh = wx1 - wx0, wy1 - wy0

    # Unit size from the brawler's own scale; shrink the whole group only if it would not fit.
    unit_h = wh * UNIT_H * SIZES[brawler]["scale"]
    units = layout(brawler, count, unit_h, random.Random(seed))
    bx0, by0, bx1, by1 = bounds(units)
    k = min(1.0, ww * 0.90 / (bx1 - bx0), wh * 0.84 / (by1 - by0))
    if k < 1.0:
        unit_h *= k
        units = layout(brawler, count, unit_h, random.Random(seed))
        bx0, by0, bx1, by1 = bounds(units)
    # Centre the group in the window, a little below the middle, feet off the bottom edge.
    ox = (wx0 + wx1) / 2 - (bx0 + bx1) / 2
    oy = min(wy0 + wh * 0.54 - (by0 + by1) / 2, wy1 - wh * 0.07 - by1)
    placed = [(s, round(ox + x), round(oy + y), flip) for s, x, y, flip in units]

    # Soft glow behind the group.
    glow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    gx, gy = ox + (bx0 + bx1) / 2, oy + (by0 + by1) / 2
    gr = max(bx1 - bx0, by1 - by0) * 0.50 + ww * 0.06
    ImageDraw.Draw(glow).ellipse((gx - gr, gy - gr, gx + gr, gy + gr), fill=(255, 252, 235, 150))
    card.alpha_composite(glow.filter(ImageFilter.GaussianBlur(ww * 0.10)))

    # Ground shadows: a wide soft one plus a small darker one right under the feet.
    soft = Image.new("RGBA", card.size, (0, 0, 0, 0))
    tight = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ds, dt = ImageDraw.Draw(soft), ImageDraw.Draw(tight)
    for spr, cx, ground, _ in placed:
        sw, sh = spr.width * 0.86, spr.width * 0.20
        ds.ellipse((cx - sw / 2, ground - sh * 0.60, cx + sw / 2, ground + sh * 0.40), fill=(96, 52, 12, 105))
        tw, th = spr.width * 0.58, spr.width * 0.10
        dt.ellipse((cx - tw / 2, ground - th * 0.75, cx + tw / 2, ground + th * 0.25), fill=(70, 34, 6, 120))
    card.alpha_composite(soft.filter(ImageFilter.GaussianBlur(max(3, unit_h * 0.035))))
    card.alpha_composite(tight.filter(ImageFilter.GaussianBlur(max(2, unit_h * 0.015))))
    order = sorted(placed, key=lambda u: u[2])                   # back to front

    for spr, cx, ground, flip in order:
        left, top = cx - spr.width // 2, ground - spr.height
        card.alpha_composite(spr, (left, top))
        # Shapes attached to this brawler, drawn right after it so brawlers in front cover them.
        for name, ax, ay, size, who in ATTACHED.get(brawler, []):
            if who == "front" and spr is not order[-1][0]:
                continue
            if flip:
                ax = 1 - ax
            stamp(card, piece(name, size * spr.height), left + ax * spr.width, top + ay * spr.height)

    # Shapes floating around the group, kept inside the window.
    gx0, gy0, gw, gh = ox + bx0, oy + by0, bx1 - bx0, by1 - by0
    for name, fx, fy, size, tilt in FLOATING.get(brawler, []):
        img = piece(name, size * unit_h, tilt)
        half = max(img.size) / 2 + 6
        x = min(max(gx0 + fx * gw, wx0 + half), wx1 - half)
        y = min(max(gy0 + fy * gh, wy0 + half), wy1 - half)
        stamp(card, img, x, y)

    draw_label(card, f"+{count}", SIZES[brawler]["name"], wy1 + 26 * S, card.height - 22 * S)
    return card


def card_row(spec: list[tuple[str, str, int]], first_seed: int) -> Image.Image:
    """Several cards side by side on a plain background. spec = (card, brawler, count)."""
    cards = [make_card(c, b, n, seed=first_seed + i) for i, (c, b, n) in enumerate(spec)]
    gap, pad = 36, 60
    w = sum(c.width for c in cards) + gap * (len(cards) - 1) + pad * 2
    h = cards[0].height + pad * 2
    scene = Image.new("RGBA", (w, h), (122, 124, 104, 255))
    x = pad
    for c in cards:
        scene.alpha_composite(c, (x, pad))
        x += c.width + gap
    return scene.convert("RGB")


def size_lineup() -> Image.Image:
    """Every brawler on one baseline at its relative size, smallest first."""
    order = sorted(SIZES, key=lambda n: SIZES[n]["scale"])
    full, pad, gap = 420, 70, 56
    sprs = [fit(shaded(n), full * SIZES[n]["scale"]) for n in order]
    w = sum(s.width for s in sprs) + gap * (len(sprs) - 1) + pad * 2
    sc = Image.new("RGBA", (w, full + 250), (236, 214, 178, 255))
    base_y = full + 70
    ImageDraw.Draw(sc).line((pad // 2, base_y, w - pad // 2, base_y), fill=(190, 160, 120, 255), width=4)
    f_name, f_scale = load_font(34), load_font(28)
    x = pad
    for n, s in zip(order, sprs):
        sh = Image.new("RGBA", sc.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse(
            (x + s.width * 0.08, base_y - s.width * 0.09, x + s.width * 0.92, base_y + s.width * 0.07),
            fill=(96, 52, 12, 110))
        sc.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
        sc.alpha_composite(s, (x, base_y - s.height))
        d = ImageDraw.Draw(sc)
        cx = x + s.width / 2
        d.text((cx, base_y + 34), SIZES[n]["name"], font=f_name, fill=(92, 52, 28, 255), anchor="mt")
        d.text((cx, base_y + 80), f"{SIZES[n]['scale']:g}x", font=f_scale, fill=(150, 110, 70, 255), anchor="mt")
        x += s.width + gap
    return sc.convert("RGB")


def shading_before_after() -> Image.Image:
    """All brawlers flat (top row) and shaded (bottom row)."""
    names = sorted(SIZES, key=lambda n: -SIZES[n]["scale"])
    pairs = []
    for n in names:
        flat = Image.open(ROOT / "brawlers" / f"{n}.png").convert("RGBA")
        flat = flat.crop(flat.getbbox())
        pairs.append((flat.resize((flat.width * 2, flat.height * 2), Image.LANCZOS), shaded(n)))
    gap = 30
    w = sum(b.width for b, _ in pairs) + gap * (len(pairs) + 1)
    h = max(b.height for b, _ in pairs)
    sheet = Image.new("RGBA", (w, h * 2 + gap * 3), (236, 214, 178, 255))
    x = gap
    for before, after in pairs:
        sheet.alpha_composite(before, (x, gap + h - before.height))
        sheet.alpha_composite(after, (x, gap * 2 + h * 2 - after.height))
        x += before.width + gap
    return sheet.convert("RGB")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    images = {
        "cards_peep_mage_ghost.jpg": card_row([("basic", "chick", 5), ("basic", "wizard", 1), ("jackpot", "ghost", 3)], 11),
        "cards_acorn_tnt_dragon.jpg": card_row([("basic", "acorn", 4), ("basic", "tnt", 2), ("jackpot", "dragon", 2)], 11),
        "cards_octopus_dragon_tnt.jpg": card_row([("basic", "octopus", 5), ("basic", "dragon", 3), ("jackpot", "tnt", 2)], 21),
        "size_lineup.jpg": size_lineup(),
        "shading_before_after.jpg": shading_before_after(),
    }
    for name, img in images.items():
        img.save(OUT / name, quality=92, optimize=True)
        print(f"{name:30s} {img.size}")


if __name__ == "__main__":
    main()
