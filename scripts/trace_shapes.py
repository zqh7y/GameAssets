"""Trace flat shapes out of a green screen, crisp and in their exact colours.

Used by animation_effects.py for the attack and walking effects. Those sheets are small, and
every shape on them is one flat colour, so the shapes are traced rather than just cut out: each
pixel is assigned to one of a few flat colours, the outline is enlarged 3x and re-sharpened,
and the result is filled with the exact flat colour. That gives crisp sprites with no green
fringe.

Requires: numpy, Pillow
"""

import numpy as np
from PIL import Image

from extract_brawlers import dilate
from shade_brawlers import blur

SCALE = 3            # output is this many times larger than the sheet
FG_DISTANCE = 45.0   # a pixel this far from the background colour is certainly a shape
MERGE = 38.0         # colours closer than this are the same flat colour


def erode(mask: np.ndarray) -> np.ndarray:
    return ~dilate(~mask, 1)


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
