"""Cut the brawlers' attack and walking effects out of their sheets and fit each one to its brawler.

Sources, in animations/source/. Both are grids of flat shapes on a green screen. Each column
is one brawler's effect, read from top to bottom in up to 4 steps: it appears, grows, is at
its biggest, and breaks up.
  - attack_effects.png  fire, an explosion, a spark...
  - walk_effects.png    what the steps leave behind: dust, sparkles, mist...

Output: animations/<brawler>/attack_effect.png and walk_effect.png, the steps side by side,
        drawn at the same scale as the brawler's frames, plus what a game needs to place and
        time them (returned to extract_animations.py, which writes it into animations.json).

The shapes are traced like the card effects (see extract_effects.py), so they stay crisp and
flat. Every step of an effect gets the same cell size, with the effect's anchor point in the
same place.

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
SRC = ROOT / "animations" / "source"
OUT = ROOT / "animations"

COLUMNS = ["chick", "tnt", "dragon", "wizard", "ghost", "acorn", "octopus"]   # a sheet, left to right
ROWS = 4
PAD = 4               # transparent pixels around the shapes in a cell

# How each effect is fitted to its brawler.
#   grows     where its anchor point is, the point that stays put while it grows:
#               "out"      its middle
#               "forward"  its left tip (it shoots to the right)
#               "up"       the middle of its bottom edge (it sits on the ground)
#               "back"     its right end (a trail left behind)
#   size      the longest side of the effect at its biggest, in pixels of the brawler's frame
#   point     attack: where the anchor goes, as x, y in the brawler's frame on its striking pose
#   offset    walk: where the anchor goes, as x, y from the brawler's spot on the ground
#   lead_ms   how long before the hit lands the effect starts (optional)
#   steps     use only this many steps of the sheet (optional)
#   colour    paint the effect in this colour instead of the traced one (optional)
KINDS = {
    "attack": {
        "sheet": "attack_effects.png",
        "file": "attack_effect.png",
        "draw": "in_front",
        # How long each step shows. The first three fit inside the time a brawler holds its
        # striking pose, so fire stops when the mouth closes.
        "frame_ms": [40, 50, 100, 150],
        "effects": {
            "chick":   {"grows": "out", "size": 120, "point": (216, 240), "colour": (245, 219, 57)},   # a click at the beak
            "tnt":     {"grows": "out", "size": 380, "point": (140, 195)},                             # an explosion
            "dragon":  {"grows": "forward", "size": 220, "point": (232, 122), "lead_ms": 30},          # fire from the mouth
            "wizard":  {"grows": "out", "size": 170, "point": (392, 163)},                             # magic at the staff
            "ghost":   {"grows": "out", "size": 200, "point": (370, 185), "lead_ms": 40},              # a swipe of its claws
            "acorn":   {"grows": "out", "size": 210, "point": (245, 140), "lead_ms": 50},              # the swing of its leaf
            "octopus": {"grows": "out", "size": 160, "point": (318, 212)},                             # a splash at the tentacle
        },
    },
    "walk": {
        "sheet": "walk_effects.png",
        "file": "walk_effect.png",
        "draw": "behind",
        # Small shapes here have colours of their own (pebbles, embers, droplets), so every
        # colour is measured from its purest pixels.
        "purest": True,
        "frame_ms": [50, 70, 110, 130],
        "effects": {
            "chick":   {"grows": "up", "size": 80, "offset": (-50, 0)},                    # a little dust
            "tnt":     {"grows": "up", "size": 115, "offset": (-60, 0)},                   # dust and pebbles
            "dragon":  {"grows": "up", "size": 105, "offset": (-70, 0)},                   # dust and embers
            "wizard":  {"grows": "up", "size": 95, "offset": (-45, 0)},                    # sparkles
            "ghost":   {"grows": "back", "size": 115, "offset": (-45, -50), "steps": 3},   # a trail of mist
            "acorn":   {"grows": "up", "size": 85, "offset": (-50, 0)},                    # dust and a leaf
            "octopus": {"grows": "up", "size": 100, "offset": (-75, 0)},                   # a wet splat
        },
    },
}


def cut_sheet(sheet: Path, purest: bool = False) -> dict[str, list[np.ndarray]]:
    """Trace a sheet. For every brawler: its steps, as RGBA images the size of a sheet column.

    A column can have fewer than 4 steps: a row with nothing in it is left out.
    purest: see extract_effects.flat_colours().
    """
    rgb = np.asarray(Image.open(sheet).convert("RGB")).astype(np.float32)
    h, w = rgb.shape[:2]
    bg = np.median(np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]), axis=0)
    fg = np.sqrt(((rgb - bg) ** 2).sum(axis=2)) > fx.FG_DISTANCE

    out = {}
    for c, brawler in enumerate(COLUMNS):
        x0, x1 = round(c * w / len(COLUMNS)), round((c + 1) * w / len(COLUMNS))
        rgba = fx.trace(rgb[:, x0:x1], fg[:, x0:x1], bg, purest)   # one set of colours for the whole column
        # Every shape belongs to the step whose row its middle is in.
        labels, n = label(rgba[..., 3] > 127)
        rows = [np.zeros(labels.shape, dtype=bool) for _ in range(ROWS)]
        for i in range(1, n + 1):
            shape = labels == i
            ys = np.nonzero(shape)[0]
            rows[min(int(ys.mean() * ROWS / labels.shape[0]), ROWS - 1)] |= shape
        steps = []
        for row in rows:
            if not row.any():
                break                                               # the steps end here
            step = rgba.copy()
            step[..., 3] = np.where(dilate(row, 3), step[..., 3], 0)   # the shapes with their soft edges
            steps.append(step)
        if len(steps) < 3:
            raise SystemExit(f"{sheet.name}: column {c + 1} ({brawler}) has only {len(steps)} steps")
        out[brawler] = steps
    return out


def box_of(step: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(step[..., 3] > 127)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def anchors_of(steps: list[np.ndarray], grows: str, loose_last: bool) -> list[tuple[float, float]]:
    """The point of each step that stays put while the effect grows."""
    boxes = [box_of(s) for s in steps]
    middles = [((x0 + x1) / 2, (y0 + y1) / 2) for x0, y0, x1, y1 in boxes]
    if grows == "out":
        return middles

    def own(i: int) -> tuple[float, float]:
        x0, y0, x1, y1 = boxes[i]
        if grows == "up":
            return (x0 + x1) / 2, float(y1)
        if grows == "back":
            return float(x1), (y0 + y1) / 2
        ys = np.nonzero((steps[i][..., 3] > 127)[:, x0:x0 + 8])[0]    # forward: the leftmost few columns
        return float(x0), float(ys.mean())

    count = len(steps) - 1 if loose_last else len(steps)
    anchors = [own(i) for i in range(count)]
    if loose_last:
        # The last step is loose pieces: it has no tip or ground edge of its own. On the sheet
        # every step is centred in its cell, so it sits where the step before it sat.
        (mx, my), (px, py), (tx, ty) = middles[-1], middles[-2], anchors[-1]
        anchors.append((mx - (px - tx), my - (py - ty)))
    return anchors


def fit(spec: dict, steps: list[np.ndarray]) -> tuple[list[Image.Image], tuple[int, int]]:
    """The steps as equal cells at the brawler's scale, and the anchor point inside a cell."""
    if "colour" in spec:
        for step in steps:
            step[..., :3] = spec["colour"]
    boxes = [box_of(s) for s in steps]
    anchors = anchors_of(steps, spec["grows"], loose_last=len(steps) == ROWS)
    bx0, by0, bx1, by1 = boxes[2]                                  # the third step is the biggest
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


def build(kind: str, metas: dict[str, dict]) -> dict[str, dict]:
    """Save every brawler's effect strip of this kind ("attack" or "walk").

    Returns, per brawler, its cells and what goes into animations.json.
    """
    about = KINDS[kind]
    traced = cut_sheet(SRC / about["sheet"], about.get("purest", False))
    out = {}
    for brawler, meta in metas.items():
        spec = about["effects"].get(brawler)
        if spec is None or brawler not in traced:
            continue
        steps = traced[brawler][:spec.get("steps", ROWS)]
        cells, anchor = fit(spec, steps)
        strip = Image.new("RGBA", (cells[0].width * len(cells), cells[0].height), (0, 0, 0, 0))
        for i, cell in enumerate(cells):
            strip.alpha_composite(cell, (i * cell.width, 0))
        strip.save(OUT / brawler / about["file"], optimize=True)

        frame_ms = list(about["frame_ms"])
        if len(cells) < ROWS:                    # no breaking-up step: the biggest one stays and fades
            frame_ms = frame_ms[:2] + [sum(frame_ms[2:])]
        animation = meta["animations"][kind]
        if kind == "attack":
            starts = [animation["hit_ms"] - spec.get("lead_ms", 0)]
            at = placed(spec["point"], meta)
        else:
            starts = [0, sum(animation["frame_ms"][:2])]      # one for each step: as poses 1 and 3 begin
            at = [float(v) for v in spec["offset"]]
        out[brawler] = {
            "frames": cells,
            "meta": {
                "file": about["file"],
                "frames": len(cells),
                "frame_width": cells[0].width,
                "frame_height": cells[0].height,
                "anchor": list(anchor),
                "at": at,
                "draw": about["draw"],
                "starts_ms": starts,
                "duration_ms": sum(frame_ms),
                "frame_ms": frame_ms,
                "motion": motion.effect(),
            },
        }
        print(f"{brawler:8s} {kind} effect: {len(cells)} steps of {cells[0].width} x {cells[0].height}, anchor {anchor}, at {at}")
    return out
