"""Give the flat brawler sprites soft, rounded 3D shading.

Input:  brawlers/<name>.png                   (flat sprites)
Output: brawlers/shaded/<name>.png            (same design, shaded, at 2x the size)
        brawlers/shaded_mirrored/<name>.png   (the same, facing the other way)

The mirrored sprites are mirrored first and shaded afterwards, so the light comes from the
top left in both folders. Never mirror a shaded sprite directly: its light would flip too.

How it works: every colour region of a sprite (body, wing, hat...) is "inflated" from its
dark outline inward into a smooth height map. That height map is lit from the top left,
which adds a soft highlight, a soft shadow and a few glossy spots. Outlines and dark
features are left untouched, so the design itself never changes.

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/shade_brawlers.py
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from extract_brawlers import dilate, label

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "brawlers"
OUT = ROOT / "brawlers" / "shaded"
OUT_MIRRORED = ROOT / "brawlers" / "shaded_mirrored"

LETTERED = {"tnt"}                            # sprites with the letters "TNT" on them

UPSCALE = 2                                   # shading is computed (and saved) at 2x for smoothness
LIGHT = np.array([-0.55, -0.70, 0.46])        # light direction: from the top left, toward the viewer
WARM_WHITE = np.array([255, 252, 240.0])


def blur(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur in full float precision (an 8-bit blur causes visible banding)."""
    if sigma <= 0:
        return arr.astype(np.float32)
    r = max(1, int(sigma * 3 + 0.5))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2).astype(np.float32)
    k /= k.sum()
    out = arr.astype(np.float32)
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        src = np.pad(out, pad, mode="edge")
        acc = np.zeros_like(out)
        n = out.shape[axis]
        for i, w in enumerate(k):
            acc += w * (src[i:i + n, :] if axis == 0 else src[:, i:i + n])
        out = acc
    return out


def shade_sprite(sprite: Image.Image, strength: float = 1.0, up: int = UPSCALE) -> Image.Image:
    """Return the sprite with rounded shading, `up` times larger than the input.

    To mirror a brawler, flip it BEFORE calling this, so the light still comes from the top left.
    """
    spr = sprite.convert("RGBA")
    spr = spr.resize((spr.width * up, spr.height * up), Image.LANCZOS)
    a = np.asarray(spr).astype(np.float32)
    rgb, alpha = a[..., :3], a[..., 3] / 255.0
    size = max(a.shape[:2])

    # Fill = opaque and not part of a dark outline or dark feature (eyes, shadowed face...).
    fill = (alpha > 0.9) & (rgb.max(axis=2) > 95)
    f = fill.astype(np.float32)

    # Smooth "inflated" height: each colour region rises from its outline inward. Built from
    # blurred copies of the fill mask at several scales, so there are no steps or ripples.
    fine = sum(w * blur(f, sg * up) for w, sg in ((0.5, 2.0), (0.3, 4.0), (0.2, 7.0)))
    body = blur((alpha > 0.5).astype(np.float32), 0.09 * size)   # broad roundness of the whole shape
    height = fine * 6.5 * up + body * 0.26 * size

    gy, gx = np.gradient(height)
    n = np.dstack([-gx, -gy, np.ones_like(gx)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    light = LIGHT / np.linalg.norm(LIGHT)
    flat = light[2]
    s = (n @ light - flat) / (1 - flat + 1e-6)   # 0 on flat areas, + toward the light, - away
    s = blur(np.clip(s * 0.5 + 0.5, 0, 1), 0.8 * up) * 2 - 1

    half = light + np.array([0, 0, 1.0])
    half /= np.linalg.norm(half)
    spec = blur(np.clip(n @ half, 0, 1) ** 70, 0.8 * up)        # small glossy highlights

    m = fill[..., None] * strength
    lit = np.clip(s, 0, 1)[..., None]
    dark = np.clip(-s, 0, 1)[..., None]
    out = rgb.copy()
    # Shadows: darker and a touch more saturated than the base colour.
    shadow = rgb * (rgb / 255.0) ** 0.6 * 0.80
    out = out + (shadow - out) * np.clip(dark * 0.80, 0, 1) * m
    # Lights: toward a warm white.
    out = out + (WARM_WHITE - out) * np.clip(lit * 0.36, 0, 1) * m
    out = out + (255 - out) * np.clip(spec[..., None] * 0.35, 0, 1) * m

    res = np.dstack([np.clip(out, 0, 255), a[..., 3]]).astype(np.uint8)
    return Image.fromarray(res, "RGBA")


def mirror_keep_letters(sprite: Image.Image) -> Image.Image:
    """Mirror a sprite that has the yellow letters "TNT" on it, keeping the text readable.

    "TNT" reads the same in both directions, so after mirroring only the N is wrong (it
    shows as a backwards N). This flips the N back and slants it to follow the mirrored box.
    """
    m = sprite.convert("RGBA").transpose(Image.FLIP_LEFT_RIGHT)
    a = np.asarray(m).astype(np.int32)
    r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    yellow = (r > 190) & (g > 140) & (b < 120) & (al > 200) & (r - b > 110)
    labels, n = label(yellow)
    letters = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(labels == i)
        if len(xs) > 60:  # ignore specks
            letters.append((xs.mean(), i, xs.min(), xs.max(), ys.min(), ys.max()))
    letters.sort()
    if len(letters) != 3:
        raise SystemExit(f"expected 3 letters on the sprite, found {len(letters)}")
    (_, _, ax0, _, ay0, ay1), (_, n_id, nx0, nx1, ny0, ny1), (_, _, cx0, _, cy0, cy1) = letters
    # Slope of the line of text, from the first to the last letter.
    slope = ((cy0 + cy1) - (ay0 + ay1)) / 2 / (cx0 - ax0)

    letter = labels == n_id
    cover = dilate(letter, 3)                       # the letter plus its soft edge
    ring = dilate(cover, 3) & ~cover & ~dilate(yellow, 2)
    fill = np.median(a[ring][:, :3], axis=0)        # the box colour around the letter

    pad = 8
    x0, x1, y0, y1 = int(nx0 - pad), int(nx1 + pad + 1), int(ny0 - pad), int(ny1 + pad + 1)
    patch = m.crop((x0, y0, x1, y1))
    matte = Image.fromarray((dilate(letter, 1)[y0:y1, x0:x1] * 255).astype(np.uint8))
    patch.putalpha(matte.filter(ImageFilter.GaussianBlur(0.7)))
    patch = patch.transpose(Image.FLIP_LEFT_RIGHT)  # the N reads correctly again...
    k, xc = 2 * slope, (patch.width - 1) / 2        # ...and is slanted to match the mirrored box
    patch = patch.transform(patch.size, Image.AFFINE, (1, 0, 0, -k, 1, k * xc), resample=Image.BICUBIC)

    out = a.copy()
    out[cover, :3] = fill
    res = Image.fromarray(out.astype(np.uint8), "RGBA")
    res.alpha_composite(patch, (x0, y0))
    return res


def mirror_sprite(name: str, sprite: Image.Image) -> Image.Image:
    """Mirror a FLAT sprite left-to-right. Shade the result afterwards with shade_sprite()."""
    if name in LETTERED:
        return mirror_keep_letters(sprite)
    return sprite.convert("RGBA").transpose(Image.FLIP_LEFT_RIGHT)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    OUT_MIRRORED.mkdir(exist_ok=True)
    for path in sorted(SRC.glob("*.png")):
        flat = Image.open(path)
        shaded = shade_sprite(flat)
        shaded.save(OUT / path.name, optimize=True)
        shade_sprite(mirror_sprite(path.stem, flat)).save(OUT_MIRRORED / path.name, optimize=True)
        print(f"{path.stem:8s} {shaded.size}")


if __name__ == "__main__":
    main()
