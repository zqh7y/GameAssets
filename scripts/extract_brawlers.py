"""Cut brawler sprites out of their source images and save them as transparent PNGs.

Sources (in brawlers/source/):
  - greenscreen_sheet.jpg : several brawlers on a green screen -> chroma-keyed and split
  - *_black.png           : one brawler on a solid black background -> black removed

Output: brawlers/<name>.png (RGBA, tightly cropped with a small padding)

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/extract_brawlers.py
"""

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "brawlers" / "source"
OUT = ROOT / "brawlers"
PAD = 4  # transparent pixels kept around each cropped sprite

# Names for the green-screen sheet, in reading order (top row left->right, then bottom row).
SHEET_NAMES = ["chick", "tnt", "dragon", "wizard", "ghost"]
BLACK_BG_SOURCES = {"acorn": "acorn_black.png", "octopus": "octopus_black.png"}


# ---------------------------------------------------------------- helpers

def flood_from_border(passable: np.ndarray) -> np.ndarray:
    """Pixels reachable from the image border through `passable` pixels (4-connected)."""
    seeds = np.zeros_like(passable, dtype=bool)
    seeds[0, :] = seeds[-1, :] = seeds[:, 0] = seeds[:, -1] = True
    return flood(passable, seeds & passable)


def flood(passable: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """Pixels reachable from `seeds` through `passable` pixels (4-connected)."""
    h, w = passable.shape
    seen = seeds.copy()
    q = deque(zip(*np.nonzero(seeds)))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and passable[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return seen


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(r):
        m = out.copy()
        m[1:, :] |= out[:-1, :]
        m[:-1, :] |= out[1:, :]
        m[:, 1:] |= out[:, :-1]
        m[:, :-1] |= out[:, 1:]
        out = m
    return out


def label(mask: np.ndarray):
    """8-connected component labelling. Returns (labels, count)."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    n = 0
    for sy, sx in zip(*np.nonzero(mask)):
        if labels[sy, sx]:
            continue
        n += 1
        labels[sy, sx] = n
        q = deque([(sy, sx)])
        while q:
            y, x = q.popleft()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = n
                        q.append((ny, nx))
    return labels, n


def crop_to_alpha(rgba: np.ndarray, region: np.ndarray | None = None, min_alpha: int = 8) -> Image.Image:
    a = rgba[..., 3]
    keep = a >= min_alpha
    if region is not None:
        keep &= region
    ys, xs = np.nonzero(keep)
    y0, y1 = ys.min(), ys.max() + 1
    x0, x1 = xs.min(), xs.max() + 1
    crop = rgba[y0:y1, x0:x1].copy()
    if region is not None:
        crop[..., 3] = np.where(region[y0:y1, x0:x1], crop[..., 3], 0)
    h, w = crop.shape[:2]
    canvas = np.zeros((h + 2 * PAD, w + 2 * PAD, 4), dtype=np.uint8)
    canvas[PAD:PAD + h, PAD:PAD + w] = crop
    return Image.fromarray(canvas, "RGBA")


def unmix(rgb: np.ndarray, alpha: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """Recover foreground colour from pixel = a*fg + (1-a)*bg."""
    a = alpha[..., None]
    fg = (rgb - (1.0 - a) * bg) / np.maximum(a, 1e-3)
    return np.clip(fg, 0, 255)


# ---------------------------------------------------------------- green screen

def window_stack(arr: np.ndarray, ys: np.ndarray, xs: np.ndarray, r: int) -> np.ndarray:
    """Values of `arr` in a (2r+1)^2 window around each (y, x). Shape (N, K, ...)."""
    h, w = arr.shape[:2]
    out = []
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out.append(arr[np.clip(ys + dy, 0, h - 1), np.clip(xs + dx, 0, w - 1)])
    return np.stack(out, axis=1)


def key_green(path: Path, remove_shadows: bool = False) -> np.ndarray:
    """Cut the art out of a green screen. Returns an RGBA array.

    remove_shadows: also remove shadows that were drawn on the screen (darker patches of
    the same green, usually under a character's feet).
    """
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    greenness = g - np.maximum(r, b)

    # Background colour = median of the clearly green pixels. On a pure green screen those
    # have a greenness above 180. A paler or darker screen never gets that high, so there
    # "clearly green" is judged against the image border instead.
    clearly_green = greenness > 180
    if clearly_green.mean() < 0.05:
        border = np.concatenate([greenness[0], greenness[-1], greenness[:, 0], greenness[:, -1]])
        clearly_green = greenness > 0.75 * np.median(border)
    bg_global = np.median(rgb[clearly_green], axis=0)
    bg_green = bg_global[1] - max(bg_global[0], bg_global[2])

    # Pure background, the edge band next to it, and solid foreground.
    bg = greenness > 0.80 * bg_green
    greenish = greenness > 0.08 * bg_green
    # Tiny gaps where the screen shows through dark outlines are dim but strongly green
    # (green dominates the pixel), unlike muted green art such as the wizard's staff gem.
    dominance = greenness / np.maximum(g, 1.0)
    if remove_shadows:
        # A shadow on the screen is the screen colour, only darker: green dominates it just
        # as much as it dominates the background. Only open patches count, so the soft edge
        # of a dark outline (which can look the same, pixel by pixel) is left alone.
        shadowish = (dominance > 0.88 * bg_green / bg_global[1]) & (greenness > 0.40 * bg_green)
        screen = Image.fromarray(((bg | shadowish) * 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(2))
        bg |= shadowish & (np.asarray(screen) > 0.70 * 255)
    gaps = (dominance > 0.5) & (greenness > 25)
    # The band is 2px around the background plus any greenish halo touching it or a gap.
    halo = bg | gaps
    for _ in range(6):
        halo = dilate(halo, 1) & (greenish | bg)
    band = (dilate(bg, 2) | dilate(gaps, 1) | halo) & ~bg
    # Solid colours an edge pixel may be blended from: past the band and clearly not green.
    solid = ~bg & ~band & ~greenish

    alpha = np.where(bg, 0.0, 1.0)
    colour = rgb.copy()

    # Each edge pixel is a blend of a nearby solid colour F and the nearby background B:
    #   P = a*F + (1-a)*B. Try every solid neighbour as F, keep the one that explains P best.
    ys, xs = np.nonzero(band)
    R = 5
    P = rgb[ys, xs][:, None, :]                                   # (N,1,3)
    F = window_stack(rgb, ys, xs, R)                              # (N,K,3)
    F_ok = window_stack(solid, ys, xs, R)                         # (N,K)
    B_win = window_stack(rgb, ys, xs, R)
    B_ok = window_stack(bg, ys, xs, R)[..., None]
    B = np.where(B_ok.sum(1) > 0,
                 (B_win * B_ok).sum(1) / np.maximum(B_ok.sum(1), 1),
                 bg_global)[:, None, :]                           # local background (N,1,3)

    d = F - B
    a = np.clip(((P - B) * d).sum(-1) / np.maximum((d * d).sum(-1), 1e-3), 0.0, 1.0)
    err = ((P - (a[..., None] * F + (1 - a[..., None]) * B)) ** 2).sum(-1)
    err = np.where(F_ok, err, np.inf)
    best = err.argmin(1)
    has = np.isfinite(err.min(1))
    idx = np.arange(len(ys))

    a_best = a[idx, best]
    F_best = F[idx, best]
    # Fallback (no solid neighbour): linear alpha from greenness.
    a_lin = np.clip((0.80 * bg_green - greenness[ys, xs]) / (0.60 * bg_green), 0.0, 1.0)
    a_final = np.where(has, a_best, a_lin)

    fg = unmix(P[:, 0, :], a_final, B[:, 0, :])
    # Low-alpha pixels are noisy after unmixing: lean on the chosen solid colour instead.
    w = a_final[:, None]
    fg = np.where(has[:, None], w * fg + (1 - w) * F_best, fg)
    # Despill: never greener than the solid colour it came from (or than max(R, B)).
    ref = np.where(has, F_best[:, 1] - np.maximum(F_best[:, 0], F_best[:, 2]), 0.0)
    fg[:, 1] = np.minimum(fg[:, 1], np.maximum(fg[:, 0], fg[:, 2]) + np.maximum(ref, 0.0))

    alpha[ys, xs] = a_final
    colour[ys, xs] = fg

    # JPEG colour bleed leaves olive pixels next to the screen (e.g. the chick's red legs,
    # which have no dark outline). Near the edge, where the solid colour further inside is
    # not green-leaning, pull green down to the average of red and blue.
    D = 6
    edge_zone = dilate(bg | gaps, D) & ~bg
    deep = ~dilate(bg | gaps, D) & ~greenish
    ys, xs = np.nonzero(edge_zone)
    ok = window_stack(deep, ys, xs, D)[..., None]
    n_ok = ok.sum(1)
    inner = (window_stack(rgb, ys, xs, D) * ok).sum(1) / np.maximum(n_ok, 1)
    has_inner = n_ok[:, 0] > 0
    c = colour[ys, xs]
    # Strong cap where the art inside is clearly not green (red legs, blue robe...).
    strong = has_inner & (inner[:, 1] <= (inner[:, 0] + inner[:, 2]) / 2 + 5)
    c[:, 1] = np.where(strong, np.minimum(c[:, 1], (c[:, 0] + c[:, 2]) / 2), c[:, 1])
    # Mild cap where it is not green-dominant (light blues, yellows): G <= max(R, B).
    mild = has_inner & (inner[:, 1] <= np.maximum(inner[:, 0], inner[:, 2]) + 5)
    c[:, 1] = np.where(mild, np.minimum(c[:, 1], np.maximum(c[:, 0], c[:, 2])), c[:, 1])
    # Never touch green art sealed off from the screen (e.g. the wizard's staff gem).
    sealed = greenish & ~flood(greenish | bg, bg | gaps)
    keep = sealed[ys, xs]
    c[keep] = colour[ys, xs][keep]
    colour[ys, xs] = c

    out = np.dstack([colour, alpha * 255.0])
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def split_sheet(rgba: np.ndarray, names: list[str]) -> dict[str, Image.Image]:
    solid = rgba[..., 3] >= 128
    # Join pieces of the same character (e.g. a staff held next to the body).
    labels, n = label(dilate(solid, 12))
    sizes = [(labels == i).sum() for i in range(1, n + 1)]
    comps = [i + 1 for i, s in enumerate(sizes) if s > 2000]  # drop specks
    if len(comps) != len(names):
        raise SystemExit(f"expected {len(names)} brawlers on the sheet, found {len(comps)}")

    boxes = []
    for c in comps:
        ys, xs = np.nonzero(labels == c)
        boxes.append((c, ys.min(), xs.min()))
    # Reading order: group into rows by top edge, then left to right.
    boxes.sort(key=lambda t: (t[1] // 200, t[2]))

    sprites = {}
    for name, (c, _, _) in zip(names, boxes):
        region = dilate(labels == c, 2)
        sprites[name] = crop_to_alpha(rgba, region)
    return sprites


# ---------------------------------------------------------------- black background

def key_black(path: Path) -> Image.Image:
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    lum = rgb.sum(axis=2)

    # The dark outline sits around lum ~50-60; the background is ~0.
    # Flood the background from the border through near-black pixels only.
    outside = flood_from_border(lum < 30)
    # Soft edge: where the outline fades into black, alpha follows brightness.
    lo, hi = 6.0, 50.0
    soft = np.clip((lum - lo) / (hi - lo), 0.0, 1.0)
    rim = dilate(outside, 1) & ~outside & (lum < hi)  # faded outline pixels touching the background
    alpha = np.ones_like(lum)
    alpha[outside] = soft[outside]
    alpha[rim] = soft[rim]

    fg = unmix(rgb, alpha, np.zeros(3, dtype=np.float32))
    out = np.clip(np.dstack([fg, alpha * 255.0]) + 0.5, 0, 255).astype(np.uint8)
    return crop_to_alpha(out)


# ---------------------------------------------------------------- main

def main() -> None:
    sheet = key_green(SRC / "greenscreen_sheet.jpg")
    for name, img in split_sheet(sheet, SHEET_NAMES).items():
        img.save(OUT / f"{name}.png", optimize=True)
        print(f"{name:8s} {img.size}")

    for name, file in BLACK_BG_SOURCES.items():
        img = key_black(SRC / file)
        img.save(OUT / f"{name}.png", optimize=True)
        print(f"{name:8s} {img.size}")


if __name__ == "__main__":
    main()
