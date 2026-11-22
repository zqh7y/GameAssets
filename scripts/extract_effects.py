"""Trace the brawlers' particle effects out of their green-screen sheet.

Source (in effects/source/):
  - effects_greenscreen.jpg : 7 small clusters of flat shapes in a row, one per brawler

Output:
  - effects/<name>.png            each whole cluster, as it was drawn
  - effects/pieces/<name>_<n>.png every single shape of a cluster, biggest first (n = 1, 2, ...)

The sheet is small and every shape is one flat colour, so the shapes are traced rather than
just cut out: each pixel is assigned to one of the cluster's few colours, the outline is
enlarged 3x and re-sharpened, and the result is filled with the exact flat colour. That
gives crisp sprites with no green fringe.

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/extract_effects.py
"""

from pathlib import Path

import numpy as np
from PIL import Image

from extract_brawlers import dilate, label
from shade_brawlers import blur

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "effects" / "source" / "effects_greenscreen.jpg"
OUT = ROOT / "effects"
PIECES = OUT / "pieces"

# Names of the clusters on the sheet, left to right, and the brawler each belongs to.
SHEET_NAMES = ["feathers", "spark", "fire", "magic", "mist", "leaves", "bubbles"]
BRAWLER = {"feathers": "chick", "spark": "tnt", "fire": "dragon", "magic": "wizard",
           "mist": "ghost", "leaves": "acorn", "bubbles": "octopus"}

SCALE = 3            # output is this many times larger than the sheet
PAD = 4              # transparent pixels kept around each sprite (in output pixels)
FG_DISTANCE = 45.0   # a pixel this far from the background colour is certainly a shape
CLUSTER_GAP = 22     # empty columns that separate two clusters on the sheet
MERGE = 38.0         # colours closer than this are the same flat colour
MIN_PIECE = 14       # ignore traced specks smaller than this many output pixels


def erode(mask: np.ndarray) -> np.ndarray:
    return ~dilate(~mask, 1)


def find_clusters(fg: np.ndarray) -> list[tuple[int, int]]:
    """Column ranges (x0, x1) of the clusters, found from the gaps between them."""
    cols = np.nonzero(fg.any(axis=0))[0]
    runs = [[cols[0], cols[0]]]
    for x in cols[1:]:
        if x - runs[-1][1] <= CLUSTER_GAP:
            runs[-1][1] = x
        else:
            runs.append([x, x])
    return [(int(a), int(b)) for a, b in runs]


def flat_colours(pixels: np.ndarray, bg: np.ndarray, purest: bool = False) -> np.ndarray:
    """The few flat colours a set of pixels is painted in.

    purest: measure each colour from its purest pixels only. Needed when small shapes have a
    colour of their own (pebbles in a puff of dust): most of a small shape is soft edge, which
    is blended with the screen, so its average is off toward green.
    """
    q = Image.fromarray(pixels.astype(np.uint8).reshape(-1, 1, 3)).quantize(6, method=Image.MEDIANCUT)
    pal = np.array(q.getpalette()[:18], dtype=np.float32).reshape(6, 3)
    counts = np.bincount(np.asarray(q).ravel(), minlength=6)
    groups: list[list] = []          # [colour, pixel count]
    for i in np.argsort(-counts):
        if counts[i] == 0:
            continue
        for g in groups:
            if np.linalg.norm(g[0] - pal[i]) < MERGE:
                g[0] = (g[0] * g[1] + pal[i] * counts[i]) / (g[1] + counts[i])
                g[1] += counts[i]
                break
        else:
            groups.append([pal[i].copy(), int(counts[i])])
    groups = [g for g in groups if g[1] >= 0.04 * len(pixels)]
    # A soft edge blends a shape's colour with the background, which gives in-between colours
    # (orange on green looks olive). Those are not real colours of the art: drop every colour
    # that is just another, more common colour mixed with the background.
    keep: list[list] = []
    for colour, count in sorted(groups, key=lambda g: -g[1]):
        blended = False
        for other, _ in keep:
            d = other - bg
            a = float(((colour - bg) * d).sum() / (d * d).sum())
            if 0.25 < a < 0.95 and np.linalg.norm(colour - (bg + a * d)) < 22:
                blended = True
        if not blended:
            keep.append([colour, count])
    # Grouping can leave two versions of one colour (the same blue, once with a little green
    # from the screen in it). Join colours that are still close, the most common first.
    joined: list[list] = []
    for colour, count in keep:
        for g in joined:
            if np.linalg.norm(g[0] - colour) < MERGE:
                g[0] = (g[0] * g[1] + colour * count) / (g[1] + count)
                g[1] += count
                break
        else:
            joined.append([colour.copy(), count])
    colours = np.array([g[0] for g in joined], dtype=np.float32)
    if purest:
        # The purest pixels of a colour are the ones least like the screen.
        nearest = ((pixels[:, None, :] - colours[None]) ** 2).sum(-1).argmin(axis=1)
        for k in range(len(colours)):
            own = pixels[nearest == k]
            if len(own):
                far = np.sqrt(((own - bg) ** 2).sum(axis=1))
                colours[k] = np.median(own[far >= np.percentile(far, 70)], axis=0)
    # The art has no green in it, so a colour with more green than red or blue has picked
    # that up from the screen. Thin shapes do: take the extra green out.
    colours[:, 1] = np.minimum(colours[:, 1], np.maximum(colours[:, 0], colours[:, 2]))
    return colours


def resize(arr: np.ndarray, scale: int) -> np.ndarray:
    """Enlarge a float array smoothly."""
    img = Image.fromarray(arr.astype(np.float32), "F")
    return np.asarray(img.resize((arr.shape[1] * scale, arr.shape[0] * scale), Image.BICUBIC))


def trace(rgb: np.ndarray, fg: np.ndarray, bg: np.ndarray, purest: bool = False) -> np.ndarray:
    """Trace the flat shapes in `rgb` and return them as an RGBA image, SCALE times larger.

    purest: see flat_colours().
    """
    core = erode(fg)                     # pixels inside a shape, away from its soft edge
    deep = erode(core)
    sample = deep if deep.sum() >= 60 else core if core.sum() >= 30 else fg
    palette = flat_colours(rgb[sample], bg, purest)
    d = palette - bg                                                     # (K,3)

    # Every pixel is a blend of one flat colour F and the background B: P = a*F + (1-a)*B.
    # For each colour of the palette: how solid (a) the pixel would be, and how well that fits.
    p = rgb - bg
    a_all = np.clip((p[None] * d[:, None, None, :]).sum(-1) / (d * d).sum(-1)[:, None, None], 0.0, 1.0)
    err = ((p[None] - a_all[..., None] * d[:, None, None, :]) ** 2).sum(-1)
    fits = err.argmin(axis=0)                                            # best-fitting colour
    solidity = np.take_along_axis(a_all, fits[None], axis=0)[0]

    # Which flat colour is each pixel? Where the pixel is nearly pure, the best fit is
    # reliable. On the soft edge it is not (the colour there is mostly background), so the
    # answer spreads outward from the reliable pixels of the same shape instead.
    region = dilate(fg, 2)
    which = np.where(region & (deep | (solidity > 0.85)), fits, -1)
    for _ in range(4):
        grown = which.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                moved = np.roll(np.roll(which, dy, axis=0), dx, axis=1)
                take = (grown < 0) & (moved >= 0) & region
                grown[take] = moved[take]
        which = grown
    which = np.where((which < 0) & region, fits, which)                  # shapes with no pure pixel
    # Image noise leaves a few stray pixels of the wrong colour; each pixel takes the colour
    # most common among itself and its 8 neighbours.
    for _ in range(2):
        votes = np.zeros((len(palette),) + which.shape, dtype=np.int32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                moved = np.roll(np.roll(which, dy, axis=0), dx, axis=1)
                for k in range(len(palette)):
                    votes[k] += moved == k
        which = np.where(which >= 0, votes.argmax(axis=0), which)

    # How solid is each pixel: fully solid deep inside a shape, otherwise from the blend.
    alpha = np.take_along_axis(a_all, np.maximum(which, 0)[None], axis=0)[0]
    alpha = np.where(deep, 1.0, alpha)
    alpha[~region] = 0.0

    # Enlarge. The outline is smoothed and re-sharpened; each colour area is enlarged on its
    # own and the strongest one wins, which keeps the borders between two colours crisp.
    big = blur(resize(alpha, SCALE), 1.0)
    t = np.clip((big - 0.30) / 0.30, 0.0, 1.0)
    alpha_big = t * t * (3 - 2 * t)
    area = np.stack([blur(resize(alpha * (which == k), SCALE), 2.0) for k in range(len(palette))])
    colour = palette[area.argmax(axis=0)]
    out = np.dstack([colour, alpha_big * 255.0])
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def crop(rgba: np.ndarray, region: np.ndarray) -> Image.Image:
    """Cut `region` out of `rgba`, cropped tight with a small transparent padding."""
    ys, xs = np.nonzero(region & (rgba[..., 3] > 0))
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    part = rgba[y0:y1, x0:x1].copy()
    part[..., 3] = np.where(region[y0:y1, x0:x1], part[..., 3], 0)
    canvas = np.zeros((part.shape[0] + 2 * PAD, part.shape[1] + 2 * PAD, 4), dtype=np.uint8)
    canvas[PAD:-PAD, PAD:-PAD] = part
    return Image.fromarray(canvas, "RGBA")


def main() -> None:
    rgb = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
    bg = np.median(np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]), axis=0)
    fg = np.sqrt(((rgb - bg) ** 2).sum(axis=2)) > FG_DISTANCE

    clusters = find_clusters(fg)
    if len(clusters) != len(SHEET_NAMES):
        raise SystemExit(f"expected {len(SHEET_NAMES)} clusters on the sheet, found {len(clusters)}")

    OUT.mkdir(exist_ok=True)
    PIECES.mkdir(exist_ok=True)
    for old in PIECES.glob("*.png"):
        old.unlink()

    for name, (x0, x1) in zip(SHEET_NAMES, clusters):
        m = 6                                                            # margin around the cluster
        xs = slice(max(0, x0 - m), x1 + m + 1)
        rgba = trace(rgb[:, xs], fg[:, xs], bg)
        solid = rgba[..., 3] > 127

        crop(rgba, dilate(solid, 3)).save(OUT / f"{name}.png", optimize=True)

        labels, n = label(solid)
        parts = [(int((labels == i).sum()), i) for i in range(1, n + 1)]
        parts = sorted((p for p in parts if p[0] >= MIN_PIECE), reverse=True)
        for k, (_, i) in enumerate(parts, start=1):
            crop(rgba, dilate(labels == i, 3)).save(PIECES / f"{name}_{k}.png", optimize=True)
        print(f"{name:9s} for {BRAWLER[name]:8s} {len(parts):2d} pieces")


if __name__ == "__main__":
    main()
