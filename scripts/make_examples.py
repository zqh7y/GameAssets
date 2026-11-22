"""Render two example images of the brawlers.

These are previews only, not game assets:
  - size_lineup.jpg           every brawler at its relative size (brawlers/sizes.json)
  - shading_before_after.jpg  every brawler flat (top row) and with its 3D shading (bottom row)

Input:  brawlers/*.png, brawlers/sizes.json
Output: examples/*.jpg

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/make_examples.py
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from shade_brawlers import shade_sprite

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "examples"
SIZES = json.loads((ROOT / "brawlers" / "sizes.json").read_text())

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


_shaded: dict[str, Image.Image] = {}


def shaded(brawler: str) -> Image.Image:
    if brawler not in _shaded:
        base = Image.open(ROOT / "brawlers" / f"{brawler}.png").convert("RGBA")
        _shaded[brawler] = shade_sprite(base.crop(base.getbbox()))
    return _shaded[brawler]


def fit(src: Image.Image, h: float) -> Image.Image:
    """Scale a sprite to height h (a very wide sprite is limited by its width instead)."""
    k = min(h / src.height, h * 1.25 / src.width)
    return src.resize((max(1, round(src.width * k)), max(1, round(src.height * k))), Image.LANCZOS)


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
        "size_lineup.jpg": size_lineup(),
        "shading_before_after.jpg": shading_before_after(),
    }
    for name, img in images.items():
        img.save(OUT / name, quality=92, optimize=True)
        print(f"{name:30s} {img.size}")


if __name__ == "__main__":
    main()
