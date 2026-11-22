"""Cut the brawlers' attack effects out of their sheet and fit each one to its attack.

Source: animations/source/attack_effects.png, a grid of flat shapes on a green screen.
        Each column is one brawler's effect, read from top to bottom in 4 steps: it appears,
        grows, hits, and breaks up.

Output: animations/<brawler>/attack_effect.png, the 4 steps side by side, drawn at the same
        scale as the brawler's frames, plus what a game needs to place and time it (returned
        to extract_animations.py, which writes it into animations.json).

The shapes are traced like the other effects (see extract_effects.py), so they stay crisp
and flat. Every step of an effect gets the same cell size, with the effect's anchor point in
the same place: its middle, or for an effect that shoots forward, the tip it grows from.

This file is used by extract_animations.py; it is not meant to be run on its own.
"""

import math
from pathlib import Path

import numpy as np
from PIL import Image

import brawler_motion as motion
import extract_effects as fx
from extract_brawlers import dilate, label

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "animations" / "source" / "attack_effects.png"
OUT = ROOT / "animations"

COLUMNS = ["chick", "tnt", "dragon", "wizard", "ghost", "acorn", "octopus"]   # the sheet, left to right
STEPS = 4
PAD = 4               # transparent pixels around the shapes in a cell

# How each effect is fitted to its brawler.
#   grows     "out" from its middle, or "forward" from its left tip
#   size      the longest side of the effect at its biggest, in pixels of the brawler's frame
#   point     where the effect's anchor goes: x, y in the brawler's frame, on its striking pose
#   lead_ms   how long before the hit lands the effect starts (optional)
#   frame_ms  how long each step shows (optional)
#   colour    paint the effect in this colour instead of the traced one (optional)
EFFECTS = {
    "chick":   {"grows": "out", "size": 120, "point": (216, 240), "colour": (245, 219, 57)},   # a click at the beak
    "tnt":     {"grows": "out", "size": 380, "point": (140, 195)},                             # an explosion
    "dragon":  {"grows": "forward", "size": 220, "point": (232, 122), "lead_ms": 30},          # fire from the mouth
    "wizard":  {"grows": "out", "size": 170, "point": (392, 163)},                             # magic at the staff
    "ghost":   {"grows": "out", "size": 200, "point": (370, 185), "lead_ms": 40},              # a swipe of its claws
    "acorn":   {"grows": "out", "size": 210, "point": (245, 140), "lead_ms": 50},              # the swing of its leaf
    "octopus": {"grows": "out", "size": 160, "point": (318, 212)},                             # a splash at the tentacle
}
# How long each step shows: it appears, grows, hits, breaks up. The first three fit inside
# the time a brawler holds its striking pose, so fire stops when the mouth closes.
FRAME_MS = [40, 50, 100, 150]


def cut_sheet() -> dict[str, list[np.ndarray]]:
    """Trace the sheet. For every brawler: its 4 steps, as RGBA images the size of a sheet column."""
    rgb = np.asarray(Image.open(SHEET).convert("RGB")).astype(np.float32)
    h, w = rgb.shape[:2]
    bg = np.median(np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]), axis=0)
    fg = np.sqrt(((rgb - bg) ** 2).sum(axis=2)) > fx.FG_DISTANCE

    out = {}
    for c, brawler in enumerate(COLUMNS):
        x0, x1 = round(c * w / len(COLUMNS)), round((c + 1) * w / len(COLUMNS))
        rgba = fx.trace(rgb[:, x0:x1], fg[:, x0:x1], bg)          # one set of colours for the whole column
        # Every shape belongs to the step whose row its middle is in.
        labels, n = label(rgba[..., 3] > 127)
        rows = [np.zeros(labels.shape, dtype=bool) for _ in range(STEPS)]
        for i in range(1, n + 1):
            shape = labels == i
            ys = np.nonzero(shape)[0]
            rows[min(int(ys.mean() * STEPS / labels.shape[0]), STEPS - 1)] |= shape
        if not all(row.any() for row in rows):
            raise SystemExit(f"{SHEET.name}: column {c + 1} ({brawler}) does not have {STEPS} steps")
        steps = []
        for row in rows:
            step = rgba.copy()
            step[..., 3] = np.where(dilate(row, 3), step[..., 3], 0)   # the shapes with their soft edges
            steps.append(step)
        out[brawler] = steps
    return out


def box_of(step: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(step[..., 3] > 127)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def anchors_of(steps: list[np.ndarray], grows: str) -> list[tuple[float, float]]:
    """The point of each step that stays put: its middle, or the tip a forward effect grows from."""
    boxes = [box_of(s) for s in steps]
    middles = [((x0 + x1) / 2, (y0 + y1) / 2) for x0, y0, x1, y1 in boxes]
    if grows == "out":
        return middles
    tips = []
    for step, (x0, _, _, _) in zip(steps[:-1], boxes):
        ys = np.nonzero((step[..., 3] > 127)[:, x0:x0 + 8])[0]        # the leftmost few columns
        tips.append((float(x0), float(ys.mean())))
    # The last step is loose pieces with no tip. On the sheet every step is centred in its
    # cell, so it sits where the step before it sat.
    (mx, my), (px, py), (tx, ty) = middles[-1], middles[-2], tips[-1]
    return tips + [(mx - (px - tx), my - (py - ty))]


def fit(brawler: str, steps: list[np.ndarray]) -> tuple[list[Image.Image], tuple[int, int]]:
    """The 4 steps as equal cells at the brawler's scale, and the anchor point inside a cell."""
    spec = EFFECTS[brawler]
    if "colour" in spec:
        for step in steps:
            step[..., :3] = spec["colour"]
    boxes = [box_of(s) for s in steps]
    anchors = anchors_of(steps, spec["grows"])
    bx0, by0, bx1, by1 = boxes[-2]                                 # the biggest step is the one before last
    k = spec["size"] / max(bx1 - bx0, by1 - by0)

    left = max(max(ax - x0, 0) for (x0, _, _, _), (ax, _) in zip(boxes, anchors)) * k
    right = max(max(x1 - ax, 0) for (_, _, x1, _), (ax, _) in zip(boxes, anchors)) * k
    up = max(max(ay - y0, 0) for (_, y0, _, _), (_, ay) in zip(boxes, anchors)) * k
    down = max(max(y1 - ay, 0) for (_, _, _, y1), (_, ay) in zip(boxes, anchors)) * k
    anchor = (math.ceil(left) + PAD, math.ceil(up) + PAD)
    size = (anchor[0] + math.ceil(right) + PAD, anchor[1] + math.ceil(down) + PAD)

    cells = []
    for step, (x0, y0, x1, y1), (ax, ay) in zip(steps, boxes, anchors):
        m = 6                                                        # keep the soft edges
        x0, y0, x1, y1 = max(x0 - m, 0), max(y0 - m, 0), min(x1 + m, step.shape[1]), min(y1 + m, step.shape[0])
        part = Image.fromarray(step[y0:y1, x0:x1], "RGBA").convert("RGBa")
        part = part.resize((max(1, round((x1 - x0) * k)), max(1, round((y1 - y0) * k))), Image.LANCZOS)
        cell = Image.new("RGBA", size, (0, 0, 0, 0))
        cell.alpha_composite(part.convert("RGBA"), (round(anchor[0] - (ax - x0) * k), round(anchor[1] - (ay - y0) * k)))
        cells.append(cell)
    return cells, anchor


def placed(point: tuple[float, float], meta: dict) -> list[float]:
    """Where a point of the striking pose is when the hit lands, measured from the brawler's spot."""
    attack = meta["animations"]["attack"]
    x, y, rotate, wide, tall = motion.motion_at(attack, attack["hit_ms"])
    px, py = (point[0] - meta["anchor"][0]) * wide, (point[1] - meta["anchor"][1]) * tall
    c, s = math.cos(math.radians(rotate)), math.sin(math.radians(rotate))
    return [round(x + c * px - s * py, 1), round(y + s * px + c * py, 1)]


def build(metas: dict[str, dict]) -> dict[str, dict]:
    """Save every brawler's effect strip. Returns its cells and what goes into animations.json."""
    traced = cut_sheet()
    out = {}
    for brawler, meta in metas.items():
        if brawler not in traced:
            continue
        spec = EFFECTS[brawler]
        cells, anchor = fit(brawler, traced[brawler])
        strip = Image.new("RGBA", (cells[0].width * STEPS, cells[0].height), (0, 0, 0, 0))
        for i, cell in enumerate(cells):
            strip.alpha_composite(cell, (i * cell.width, 0))
        strip.save(OUT / brawler / "attack_effect.png", optimize=True)

        frame_ms = spec.get("frame_ms", FRAME_MS)
        out[brawler] = {
            "frames": cells,
            "meta": {
                "file": "attack_effect.png",
                "frames": STEPS,
                "frame_width": cells[0].width,
                "frame_height": cells[0].height,
                "anchor": list(anchor),
                "at": placed(spec["point"], meta),
                "start_ms": meta["animations"]["attack"]["hit_ms"] - spec.get("lead_ms", 0),
                "duration_ms": sum(frame_ms),
                "frame_ms": frame_ms,
                "motion": motion.effect(),
            },
        }
        print(f"{brawler:8s} effect {cells[0].width} x {cells[0].height}  anchor {anchor}  at {out[brawler]['meta']['at']}")
    return out
