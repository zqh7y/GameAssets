"""Build an area's long map from pictures drawn by Gemini, and preview it moving.

An area is a folder in maps/ with its pictures in source/:
  base.jpg     one square piece of the path between its two walls, seen from above
  props.jpg    the area's decorations, on a magenta screen
  effects.jpg  small things that move around (butterflies, a bird, leaves and petals), on a
               magenta screen. Optional: without it the map still moves, with fewer things.

From them the script makes, in the area's folder:
  tile.png            the base, made to repeat seamlessly from left to right
  props/<name>.png    every decoration, cut out
  effects/<name>.png  the small things that move, cut out
  ground.png          the whole map without the decorations that move: the tile laid out
                      several times, with the decorations that stay still and every shadow
  map.png             the whole map with every decoration, standing still
  map.json            the map's size, where the characters walk, where every decoration is,
                      and how everything moves

The map loops: its right edge joins its left edge. How it moves is in map_motion.py.

Requires: numpy, Pillow (and ffmpeg for the video preview)
Run from the repo root:  python3 scripts/make_map.py
"""

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import brawler_motion
import map_motion
from extract_animations import posed, resized
from extract_brawlers import crop_to_alpha, dilate, key_green, label

ROOT = Path(__file__).resolve().parent.parent
MAPS = ROOT / "maps"
EXAMPLES = ROOT / "examples"

# The previews: three brawlers walking along the map, at their sizes from brawlers/sizes.json.
# A brawler of size 1 (the Mage) is drawn at 0.52 of its animation frame, about 150 px tall.
SQUAD = [("chick", 300, 650), ("wizard", 420, 575), ("tnt", 560, 640)]   # sprite, x and y of its feet
SQUAD_SIZE = 0.52
WALK_PX_S = 150          # how fast they walk, px a second
FPS = 25

# Everything about an area that is not in its pictures. All sizes and positions are pixels of
# the base picture, which is one screen wide (1024 x 1024), measured from its top left corner.
#
# A lane is a strip of the map where one kind of decoration goes. For each decoration, `y` is
# the range for its foot (the bottom of its trunk, stem or stone), or for its top when the lane
# says `"by": "top"`. `gap` is the range of distances between neighbours, and `items` says which
# decorations the lane uses and how often.
AREAS = {
    "forest": {
        "tiles": 6,          # the tile is 864 px wide, so 6 of them are about 5 screens
        "overlap": 160,      # px of the base given up to make it repeat seamlessly
        "walk": [380, 740],  # the open grass between the two walls, where characters stand
        "seed": 3,
        "props": [           # the decorations on the sheet, in reading order
            "tree", "tree_light", "pine",
            "bush", "bush_small", "rock", "rock_small",
            "stump", "log", "fern", "mushrooms",
            "daisies", "yellow_flowers", "blue_flowers", "grass", "pebbles", "leaves",
        ],
        # the base has pink trees but the sheet has none, so one is recoloured to match
        "pink": {"tree_pink": "tree_light"},
        "width": {           # how wide each decoration is on the map
            "tree": 230, "tree_light": 230, "tree_pink": 230, "pine": 165,
            "bush": 210, "bush_small": 100,
            "rock": 110, "rock_small": 62, "stump": 88, "log": 135,
            "fern": 88, "mushrooms": 52,
            "daisies": 60, "yellow_flowers": 60, "blue_flowers": 56,
            "grass": 40, "pebbles": 44, "leaves": 54,
        },
        "lanes": {
            # trees on top of the cliff, in front of the base's own row
            "cliff_top": {"y": [176, 196], "gap": [250, 430],
                          "items": {"tree": 3, "tree_light": 2, "tree_pink": 2, "pine": 2}},
            # rocks, stumps and small plants at the foot of the cliff
            "cliff_foot": {"y": [338, 362], "gap": [190, 420],
                           "items": {"rock": 2, "rock_small": 2, "stump": 1, "log": 1, "fern": 2,
                                     "mushrooms": 2, "bush_small": 2, "grass": 2}},
            # flowers and other flat things on the grass
            "ground": {"y": [400, 730], "gap": [160, 320],
                       "items": {"daisies": 2, "yellow_flowers": 2, "blue_flowers": 2, "grass": 3,
                                 "pebbles": 2, "leaves": 1}},
            # small plants along the bottom edge of the grass
            "edge": {"y": [752, 770], "gap": [260, 520],
                     "items": {"bush_small": 2, "fern": 2, "grass": 2, "daisies": 1, "mushrooms": 1}},
            # big trees and bushes at the very front, cut off by the bottom of the map
            "front": {"y": [800, 840], "by": "top", "gap": [240, 400], "grow": 1.08,
                      "items": {"tree": 2, "tree_light": 2, "tree_pink": 1, "bush": 3}},
        },
        # decorations that lie flat on the ground cast a fainter shadow, or none
        "shadow": {"daisies": 0.5, "yellow_flowers": 0.5, "blue_flowers": 0.5, "grass": 0.5,
                   "pebbles": 0.0, "leaves": 0.0},
        # The fallen leaves on the sheet are one decoration, and they are also cut apart: they
        # are the autumn leaves that fall from the trees.
        "autumn_leaves": "leaves",
        # Turn effects so they face the way they move: the bird was drawn heading up.
        "turn": {"bird": -104},
        # The pink trees drop pink petals: the white petals, recoloured.
        "pink_effects": {"petal_pink": "petal_white"},
        # How everything moves. See map_motion.py and maps/README.md.
        "motion": {
            "wind": {
                # waves rolling along the map: how much each adds, how long it takes to pass a
                # spot, and how many fit along the map
                "waves": [{"strength": 0.65, "period_ms": 3456, "gusts": 3},
                          {"strength": 0.35, "period_ms": 1728, "gusts": 8}],
                # The base's own rows of trees move too, up to `shift_px` sideways: fully past
                # `full`, fading to nothing at `still` (toward the cliff and the bottom edge).
                "bands": [{"still": 175, "full": 60}, {"still": 815, "full": 900}],
                "shift_px": 5,
            },
            # how far the top of each decoration leans at full wind, as a part of its height
            "sway": {
                "tree": 0.024, "tree_light": 0.024, "tree_pink": 0.024, "pine": 0.03,
                "bush": 0.02, "bush_small": 0.03, "fern": 0.06,
                "grass": 0.1, "daisies": 0.07, "yellow_flowers": 0.07, "blue_flowers": 0.07,
            },
            # plants on the grass that characters walk through
            "react": {
                "depth_px": 28,          # how close in y a character's feet must be to the plant's foot
                "reach": 0.4,            # ... and in x: this part of the plant's width, plus a quarter of the character's
                "lean": 0.3,             # how far the plant's top is pushed forward while a character is in it
                "press": 0.82,           # how short it gets meanwhile
                "spring_hz": 2.6,        # how fast it wobbles back once let go
                "damping": 0.22,         # how quickly the wobble dies down: 0 never, 1 at once
                "pops": {"daisies": ["petal_white"], "yellow_flowers": ["petal_yellow"],
                         "blue_flowers": ["petal_blue"], "grass": ["leaf_green"], "fern": ["leaf_green"],
                         "bush_small": ["leaf_green"]},
                "count": [3, 5],         # how many petals or leaves pop out each time
                "size_px": [12, 17],
                "up_px_s": [90, 170],
                "forward_px_s": [-30, 110],
                "gravity_px_s2": 420,
                "spin_deg_s": [-360, 360],
                "tumble_ms": [300, 500],
                "rest_ms": 500,
                "fade_ms": 400,
            },
            # leaves and petals falling from the trees
            "falling": {
                "sprites": {"leaf_green": 3, "petal_pink": 3, "leaf_autumn": 1},
                "per_s": 1.0,            # how many start falling each second, on one screen
                "from": [30, 150],       # y where they leave the trees on top of the cliff
                "on_cliff": 0.4,         # how many land on top of the cliff; the rest fall past it
                "land": [[182, 198], [345, 430]],
                "front_per_s": 0.25,     # a few fall from the trees at the front too
                "front_from": [830, 930],
                "front_fall_px": [140, 220],
                "speed_px_s": [30, 46],
                "drift_px_s": 14,        # carried to the right by the wind
                "swing_px": 12,
                "swing_ms": 1500,
                "spin_deg_s": [-80, 80],
                "tumble_ms": [700, 1200],
                "size_px": [14, 20],
                "rest_ms": 1600,
                "fade_ms": 900,
            },
            "butterflies": {
                "sprites": ["butterfly"],
                "per_screen": 1.5,       # how many live along the map, per screen of its length
                "y": [400, 720],
                "size_px": [40, 48],
                "height_px": [30, 50],   # how high they fly over the ground
                "wander_px": [90, 45],   # how far they wander from home, sideways and up and down
                "flap_ms": 180,          # one wing beat
            },
            "birds": {
                "sprite": "bird",
                "every_ms": [9000, 14000],
                "size_px": 72,
                "speed_px_s": 330,
                "y": [70, 240],
                "curve_px": [-40, 40],
                "flap_ms": 270,
                "beats": 3,              # beats, then a glide
                "glide_ms": 700,
                "margin_px": 80,         # they start and end this far outside the screen
                "shadow_px": [80, 170],  # where the shadow falls, from the bird
                "shadow": 0.3,
            },
        },
    },
}

SHADOW = (24, 44, 8)    # colour of the soft shadows under the decorations
SHADOW_ALPHA = 0.34     # their strength


# ---------------------------------------------------------------- the tile

def make_tile(base: np.ndarray, overlap: int) -> np.ndarray:
    """Make the base repeat seamlessly from left to right.

    The base's last `overlap` columns are laid over its first ones and the two are joined along
    the line where they look most alike, so the tile is `overlap` px narrower than the base and
    its right edge continues into its left edge. Any difference in brightness left across that
    line is spread over the overlap, so it does not show as an edge.
    """
    h, w, _ = base.shape
    o = overlap
    soft = np.asarray(Image.fromarray(base.astype(np.uint8)).filter(ImageFilter.GaussianBlur(12)))
    soft = soft.astype(np.float32)
    end, start = base[:, w - o:], base[:, :o]
    end_soft, start_soft = soft[:, w - o:], soft[:, :o]

    # The cheapest line from top to bottom, moving at most 1 px sideways per row. Pixels where
    # the two differ cost more, and so do differences in overall brightness.
    cost = ((end - start) ** 2).sum(-1) + 4.0 * ((end_soft - start_soft) ** 2).sum(-1)
    cost[:, :12] += 1e7
    cost[:, -12:] += 1e7
    total = cost.copy()
    step = np.zeros((h, o), np.int8)
    for y in range(1, h):
        prev = total[y - 1]
        options = np.stack([np.r_[np.inf, prev[:-1]], prev, np.r_[prev[1:], np.inf]])
        best = options.argmin(0)
        step[y] = best - 1
        total[y] += options[best, np.arange(o)]
    seam = np.zeros(h, int)
    seam[-1] = total[-1].argmin()
    for y in range(h - 1, 0, -1):
        seam[y - 1] = seam[y] + step[y, seam[y]]

    # The brightness difference across the line, smoothed along it, is split between the two
    # sides, fading out toward the ends of the overlap.
    rows = np.arange(h)
    diff = np.mean([start_soft[rows, np.clip(seam + k, 0, o - 1)] - end_soft[rows, np.clip(seam + k, 0, o - 1)]
                    for k in range(-10, 11)], axis=0)
    g = np.exp(-0.5 * (np.arange(-60, 61) / 20.0) ** 2)
    g /= g.sum()
    diff = np.stack([np.convolve(np.pad(diff[:, c], 60, mode="edge"), g, mode="valid") for c in range(3)], -1)
    x = np.arange(o, dtype=np.float32)[None, :]
    s = seam[:, None].astype(np.float32)
    to_seam = np.clip(x / np.maximum(s, 1), 0, 1)[..., None]
    from_seam = np.clip((o - 1 - x) / np.maximum(o - 1 - s, 1), 0, 1)[..., None]
    end = end + 0.5 * diff[:, None] * to_seam
    start = start - 0.5 * diff[:, None] * from_seam
    take_start = np.clip((x - s + 3) / 6, 0, 1)[..., None]
    joined = end * (1 - take_start) + start * take_start
    return np.concatenate([joined, base[:, o:w - o]], axis=1)


def even_light(tile: np.ndarray, rows: list[int], strength: float = 0.75) -> np.ndarray:
    """Soften the patches of light on the open ground.

    They are the same on every tile, so on the long map they would line up in a row. Each row
    of the ground is evened out toward its own average, fading in and out over 40 px at the
    top and bottom of `rows`. The tile still repeats seamlessly, because the averaging wraps
    around its edges.
    """
    h, w, _ = tile.shape
    # each row blurred along itself only, wrapping around the tile's edges
    g = np.exp(-0.5 * (np.minimum(np.arange(w), w - np.arange(w)) / 40.0) ** 2)
    g /= g.sum()
    low = np.real(np.fft.ifft(np.fft.fft(tile, axis=1) * np.fft.fft(g)[None, :, None], axis=1))
    change = low.mean(axis=1, keepdims=True) - low
    # smoothed from row to row, so a pebble does not leave a streak
    k = np.exp(-0.5 * (np.arange(-24, 25) / 8.0) ** 2)
    k /= k.sum()
    change = np.apply_along_axis(lambda col: np.convolve(np.pad(col, 24, mode="edge"), k, mode="valid"), 0, change)
    y = np.arange(h, dtype=np.float32)[:, None, None]
    top, bottom = rows
    fade = np.clip((y - top) / 40, 0, 1) * np.clip((bottom - y) / 40, 0, 1)
    return tile + strength * fade * change


# ---------------------------------------------------------------- cutting out

def key_magenta(path: Path) -> np.ndarray:
    """Cut the art out of a magenta screen. Returns an RGBA array.

    Magenta is the opposite of green: in the sheet's negative the screen is green, so the
    negative is keyed like a green screen and the colours are turned back.
    """
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    rgba = key_green(255.0 - rgb)
    rgba[..., :3] = 255 - rgba[..., :3]
    # Darker patches of the screen (the shade between a fern's leaves, for instance) are kept
    # as purple. Nothing on the sheet is purple, so remove them.
    c = rgba[..., :3].astype(np.float32)
    purple = np.minimum(c[..., 0], c[..., 2]) - c[..., 1]
    rgba[..., 3] = np.where((purple > 20) & (purple > 0.3 * c.max(-1)), 0, rgba[..., 3])
    return rgba


def pieces(rgba: np.ndarray, join: int, smallest: int, row_gap: int) -> list[Image.Image]:
    """The separate things on a sheet, in reading order.

    Pieces closer than about 2 x `join` px are one thing (the pebbles of a group, say). Rows
    are split where the centres jump down by more than `row_gap` px.
    """
    solid = rgba[..., 3] >= 128
    labels, n = label(dilate(solid, join) if join else solid)
    sizes = np.bincount(labels.ravel())
    centres = []
    for c in range(1, n + 1):
        if sizes[c] > smallest:
            ys, xs = np.nonzero(labels == c)
            centres.append((c, ys.mean(), xs.mean()))
    centres.sort(key=lambda t: t[1])
    rows, row = [], [centres[0]]
    for item in centres[1:]:
        if item[1] - row[-1][1] > row_gap:
            rows.append(row)
            row = []
        row.append(item)
    rows.append(row)
    ordered = [c for row in rows for c, _, _ in sorted(row, key=lambda t: t[2])]
    return [bleed(crop_to_alpha(rgba, dilate(labels == c, 2))) for c in ordered]


def split_props(rgba: np.ndarray, names: list[str]) -> dict[str, Image.Image]:
    """Cut the sheet into its decorations, named in reading order."""
    found = pieces(rgba, 8, 300, 100)
    if len(found) != len(names):
        raise SystemExit(f"expected {len(names)} decorations on the sheet, found {len(found)}")
    return dict(zip(names, found))


def colour_of(img: Image.Image) -> tuple[float, float, float]:
    """Hue (degrees), saturation and value of a cut-out thing, leaving out its dark outline."""
    arr = np.asarray(img).astype(np.float32)
    solid = arr[..., 3] > 200
    px = arr[..., :3][solid]
    px = px[px.max(1) > 0.35 * 255]
    mean = Image.fromarray(px.mean(0).reshape(1, 1, 3).astype(np.uint8)).convert("HSV").getpixel((0, 0))
    return mean[0] * 360 / 255, mean[1] / 255, mean[2] / 255


def name_effects(found: list[Image.Image]) -> dict[str, Image.Image]:
    """Name the things on an effects sheet by their size and colour, whatever their layout.

    The four biggest are the butterflies and the bird (the brown one); the small ones are green
    leaves, or white, yellow or blue petals.
    """
    by_size = sorted(found, key=lambda im: -int((np.asarray(im)[..., 3] > 128).sum()))
    big, small = by_size[:4], by_size[4:]
    named, count = {}, {}

    def add(kind: str, img: Image.Image, numbered: bool = True) -> None:
        count[kind] = count.get(kind, 0) + 1
        named[f"{kind}_{count[kind]}" if numbered else kind] = img

    for img in big:
        h, s, v = colour_of(img)
        if 10 <= h <= 40 and s > 0.35 and v < 0.8:
            add("bird", img, numbered=False)
        elif s < 0.2:
            add("butterfly_white", img, numbered=False)
        elif 170 <= h <= 250:
            add("butterfly_blue", img, numbered=False)
        else:
            add("butterfly_yellow", img, numbered=False)
    for img in small:          # still in reading order among themselves
        h, s, v = colour_of(img)
        if s < 0.2:
            add("petal_white", img)
        elif 170 <= h <= 250:
            add("petal_blue", img)
        elif 30 <= h <= 50 and v > 0.75:
            add("petal_yellow", img)
        else:
            add("leaf_green", img)
    return named


def bleed(img: Image.Image) -> Image.Image:
    """Give the clear pixels around a decoration the colour of its edge.

    They stay clear, but a game that smooths the picture when it scales it then blends the
    edge with the right colour instead of with whatever the clear pixels held.
    """
    arr = np.asarray(img).astype(np.float32)
    a = arr[..., 3:4] / 255.0
    colour = arr[..., :3] * a
    weight = a.copy()
    filled = arr[..., :3].copy()
    for radius in (1, 2, 4, 8):
        c = np.asarray(Image.fromarray(np.clip(colour, 0, 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(radius)))
        wt = np.asarray(Image.fromarray(np.clip(weight[..., 0] * 255, 0, 255).astype(np.uint8))
                        .filter(ImageFilter.BoxBlur(radius))).astype(np.float32)[..., None] / 255.0
        guess = c.astype(np.float32) / np.maximum(wt, 1e-3)
        todo = (weight < 0.02) & (wt > 0.02)
        filled = np.where(todo, guess, filled)
        weight = np.where(todo, 1.0, weight)
        colour = np.where(todo, guess, colour)
    out = np.dstack([np.where(a > 0, arr[..., :3], filled), arr[..., 3]])
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGBA")


def recolour(img: Image.Image, base: np.ndarray, leaves_only: bool = True) -> Image.Image:
    """Repaint a green tree's leaves (or a white petal) in the pink of the base's pink trees.

    Each repainted pixel takes the pink that is as light, among the base's pink pixels, as it is
    among the pixels being repainted, so the shading stays the same. A tree's trunk and the
    outlines are kept.
    """
    arr = np.asarray(img).astype(np.float32)
    hsv = np.asarray(img.convert("RGB").convert("HSV")).astype(np.float32)
    hue, sat, val = hsv[..., 0] * 360 / 255, hsv[..., 1] / 255, hsv[..., 2] / 255
    if leaves_only:
        pick = (hue > 40) & (hue < 150) & (sat > 0.2) & (val > 0.15) & (arr[..., 3] > 0)
    else:
        pick = (val > 0.5) & (arr[..., 3] > 0)

    r, g, b = base[..., 0], base[..., 1], base[..., 2]
    pink = base[(r > g + 35) & (b > g + 5) & (r > 120)]
    light = lambda c: c @ np.array([0.299, 0.587, 0.114], np.float32)
    pink = pink[np.argsort(light(pink))]
    # pinks from darkest to lightest, averaged in 64 steps
    steps = np.array([chunk.mean(0) for chunk in np.array_split(pink, 64)])

    own = light(arr[..., :3][pick])
    if leaves_only:
        rank = np.argsort(np.argsort(own)) / max(len(own) - 1, 1)
    else:
        # a petal is nearly one colour, so ranking would blow its grain up: go by lightness
        lo, hi = np.percentile(own, [2, 98])
        rank = np.clip((own - lo) / max(hi - lo, 1), 0, 1) * 0.5 + 0.45
    arr[..., :3][pick] = steps[np.minimum((rank * 64).astype(int), 63)]
    return Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8), "RGBA")


def foot(img: Image.Image) -> int:
    """Row of the decoration's lowest solid pixel (the bottom of its trunk, stem or stone)."""
    rows = np.nonzero((np.asarray(img)[..., 3] >= 128).any(1))[0]
    return int(rows.max())


def family(names, prefixes: list[str]) -> list[str]:
    """The names that start with one of the prefixes: "leaf_green" is leaf_green_1, leaf_green_2..."""
    return sorted(n for n in names if any(n == p or n.startswith(p + "_") for p in prefixes))


# ---------------------------------------------------------------- the map

def place(area: dict, props: dict[str, Image.Image], length: int) -> list[dict]:
    """Spread the decorations along every lane, at random but the same every run.

    Each lane is filled from a random start, and stops early enough that the gap between its
    last decoration and its first one (across the join of the loop) is a normal gap too.
    """
    rng = np.random.default_rng(area["seed"])
    placed = []
    for lane_name, lane in area["lanes"].items():
        names = list(lane["items"])
        weights = np.array([lane["items"][n] for n in names], np.float64)
        lo, hi = lane["gap"]
        first = x = rng.uniform(0, hi)
        last = None
        while x < first + length - lo:
            # never the same decoration twice in a row
            w = np.where(np.array(names) == last, 0.0, weights)
            name = names[rng.choice(len(names), p=w / w.sum())]
            img = props[name]
            scale = area["width"][name] / img.width * rng.uniform(0.9, 1.1) * lane.get("grow", 1.0)
            y = rng.uniform(*lane["y"])
            if lane.get("by") == "top":
                y += foot(img) * scale
            placed.append({"name": name, "lane": lane_name, "x": round(float(x % length), 1),
                           "y": round(float(y), 1), "scale": round(float(scale), 4)})
            last = name
            x += rng.uniform(lo, hi)
    placed.sort(key=lambda p: p["y"])
    return placed


def scaled(img: Image.Image, scale: float) -> Image.Image:
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")


def shadow(width: int, strength: float) -> Image.Image:
    """A soft oval shadow, darker in the middle, for a decoration `width` px wide."""
    w, h = round(width * 0.96), max(4, round(width * 0.26))
    pad = max(4, round(width * 0.08))
    mask = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    ImageDraw.Draw(mask).ellipse((pad, pad, pad + w, pad + h), fill=round(255 * SHADOW_ALPHA * strength))
    mask = mask.filter(ImageFilter.GaussianBlur(pad / 2))
    out = Image.new("RGBA", mask.size, SHADOW + (0,))
    out.putalpha(mask)
    return out


def render(tile: np.ndarray, area: dict, props: dict[str, Image.Image], placed: list[dict],
           skip: set[str] = frozenset()) -> Image.Image:
    """The whole map: the tile repeated, with every decoration and its shadow drawn on it.

    Decorations named in `skip` are left out, but their shadows are drawn.
    """
    canvas = Image.fromarray(np.clip(np.tile(tile, (1, area["tiles"], 1)) + 0.5, 0, 255).astype(np.uint8))
    canvas = canvas.convert("RGBA")
    length = canvas.width
    for p in placed:
        img = scaled(props[p["name"]], p["scale"])
        left = round(p["x"] - img.width / 2)
        top = round(p["y"] - foot(props[p["name"]]) * p["scale"])
        strength = area["shadow"].get(p["name"], 1.0)
        sh = shadow(img.width, strength) if strength > 0 else None
        # A decoration that hangs over either end of the map is drawn again at the other end,
        # so the map loops.
        for dx in (-length, 0, length):
            if left + dx >= length or left + dx + img.width <= 0:
                continue
            if sh is not None:
                # the light comes from the top left, so shadows fall a little to the right
                sx = left + dx + (img.width - sh.width) // 2 + round(img.width * 0.12)
                sy = round(p["y"]) - sh.height // 2 - round(img.width * 0.02)
                paste(canvas, sh, sx, sy)
            if p["name"] not in skip:
                paste(canvas, img, left + dx, top)
    return canvas.convert("RGB")


def paste(canvas: Image.Image, img: Image.Image, left: int, top: int) -> None:
    """alpha_composite that accepts positions partly outside the canvas."""
    l, t = max(left, 0), max(top, 0)
    r, b = min(left + img.width, canvas.width), min(top + img.height, canvas.height)
    if r <= l or b <= t:
        return
    canvas.alpha_composite(img.crop((l - left, t - top, r - left, b - top)), (l, t))


def as_json(data: dict) -> str:
    """JSON with every list of numbers, and every decoration, on one line."""
    props = data.pop("props")
    text = json.dumps(data, indent=2)
    text = re.sub(r"\[\s+(-?[\d.]+(?:,\s+-?[\d.]+)*)\s+\]", lambda m: "[" + re.sub(r"\s+", " ", m.group(1)) + "]", text)
    text = re.sub(r"\[\s+(\"[\w ]+\"(?:,\s+\"[\w ]+\")*)\s+\]", lambda m: "[" + re.sub(r"\s+", " ", m.group(1)) + "]", text)
    # small objects without anything nested on one line too
    text = re.sub(r"\{\s+([^{}\[\]]+?)\s+\}",
                  lambda m: "{" + re.sub(r"\s+", " ", m.group(1)) + "}" if len(m.group(1)) < 110 else m.group(0), text)
    text = re.sub(r"\[\s+(\{[^{}\[\]\n]+\}(?:,\s+\{[^{}\[\]\n]+\})*)\s+\]",
                  lambda m: "[\n        " + re.sub(r"\},\s+\{", "},\n        {", m.group(1)) + "\n      ]", text)
    text = text[:-2] + ',\n  "props": [\n' + ",\n".join("    " + json.dumps(p) for p in props) + "\n  ]\n}\n"
    data["props"] = props
    return text


def build(area_name: str) -> None:
    area = AREAS[area_name]
    folder = MAPS / area_name
    motion = area["motion"]
    base = np.asarray(Image.open(folder / "source" / "base.jpg").convert("RGB")).astype(np.float32)

    tile = even_light(make_tile(base, area["overlap"]), area["walk"])
    Image.fromarray(np.clip(tile + 0.5, 0, 255).astype(np.uint8)).save(folder / "tile.png", optimize=True)

    props = split_props(key_magenta(folder / "source" / "props.jpg"), area["props"])
    for new, old in area.get("pink", {}).items():
        props[new] = recolour(props[old], base)

    # the small things that move
    effects = {}
    if area.get("autumn_leaves"):
        leaves = np.asarray(props[area["autumn_leaves"]])
        for i, leaf in enumerate(pieces(leaves, 0, 30, 15), 1):
            effects[f"leaf_autumn_{i}"] = leaf
    sheet = folder / "source" / "effects.jpg"
    if sheet.exists():
        effects.update(name_effects(pieces(key_magenta(sheet), 6, 200, 60)))
    for name, degrees in area.get("turn", {}).items():
        if name in effects:
            turned = effects[name].convert("RGBa").rotate(degrees, resample=Image.BICUBIC, expand=True)
            effects[name] = bleed(turned.convert("RGBA").crop(turned.getbbox()))
    for new, old in area.get("pink_effects", {}).items():
        for name in family(list(effects), [old]):
            effects[new + name[len(old):]] = recolour(effects[name], base, leaves_only=False)

    for sub, images in (("props", props), ("effects", effects)):
        (folder / sub).mkdir(exist_ok=True)
        for old in (folder / sub).glob("*.png"):
            old.unlink()
        for name, img in images.items():
            img.save(folder / sub / f"{name}.png", optimize=True)

    length = tile.shape[1] * area["tiles"]
    placed = place(area, props, length)
    moving = {name for name, sway in motion["sway"].items() if sway > 0}
    render(tile, area, props, placed).save(folder / "map.png", optimize=True)
    render(tile, area, props, placed, skip=moving).save(folder / "ground.png", optimize=True)

    walk = area["walk"]
    info = {
        "size": [length, tile.shape[0]],
        "loops": True,
        "screen": base.shape[1],
        "walk": walk,
        "ground": "ground.png",
        "still": "map.png",
        "tile": {"file": "tile.png", "width": tile.shape[1], "height": tile.shape[0], "repeat": area["tiles"]},
        "effects": sorted(f"effects/{name}.png" for name in effects),
        "motion": motion,
        "props": [{"file": f"props/{p['name']}.png", "x": p["x"], "y": p["y"], "foot": foot(props[p["name"]]),
                   "scale": p["scale"], "shadow": area["shadow"].get(p["name"], 1.0),
                   "sway": motion["sway"].get(p["name"], 0.0),
                   "reacts": p["name"] in moving and walk[0] - 10 <= p["y"] <= walk[1] + 40} for p in placed],
    }
    (folder / "map.json").write_text(as_json(info))
    print(f"{area_name}: map {length} x {tile.shape[0]} px, tile {tile.shape[1]} px x {area['tiles']}, "
          f"{len(props)} decorations ({len(placed)} placed, {sum(p['name'] in moving for p in placed)} moving), "
          f"{len(effects)} effects")


# ---------------------------------------------------------------- previews

def strip(path: Path, count: int) -> list[Image.Image]:
    img = Image.open(path).convert("RGBA")
    w = img.width // count
    return [img.crop((i * w, 0, (i + 1) * w, img.height)) for i in range(count)]


class Walker:
    """A brawler's walk, played from its files in animations/ the way a game would."""

    def __init__(self, sprite: str, x: float, y: float):
        meta = json.loads((ROOT / "animations" / "animations.json").read_text())[sprite]
        size = json.loads((ROOT / "brawlers" / "sizes.json").read_text())[sprite]["scale"]
        self.k = k = SQUAD_SIZE * size
        self.x, self.y = x, y
        self.walk = meta["animations"]["walk"]
        self.effect = self.walk["effect"]
        folder = ROOT / "animations" / sprite
        fw, fh = meta["frame_width"], meta["frame_height"]
        self.frames = [resized(f, (round(fw * k), round(fh * k)))
                       for f in strip(folder / self.walk["file"], self.walk["frames"])]
        self.anchor = (meta["anchor"][0] * k, meta["anchor"][1] * k)
        e = self.effect
        self.steps = [resized(f, (round(e["frame_width"] * k), round(e["frame_height"] * k)))
                      for f in strip(folder / e["file"], e["frames"])]
        self.step_anchor = (e["anchor"][0] * k, e["anchor"][1] * k)
        box = self.frames[0].getbbox()
        self.width = box[2] - box[0]
        self.shadow_w = self.width * 0.72
        self.height = fh * k
        side = round(max(fw, fh) * k * 1.6)
        self.canvas, self.at = (side, side), (side / 2, side * 0.8)

    def shadow(self, shadows: ImageDraw.ImageDraw, ms: float) -> None:
        x, y, rotate, wide, tall = brawler_motion.motion_at(self.walk, ms)
        x, y = x * self.k, y * self.k
        w = self.shadow_w * wide * (1 + 3 * y / self.height)        # smaller while off the ground
        shadows.ellipse((self.x + x - w / 2, self.y - w * 0.13, self.x + x + w / 2, self.y + w * 0.09),
                        fill=SHADOW + (round(255 * 0.42),))

    def draw(self, img: Image.Image, ms: float) -> None:
        x, y, rotate, wide, tall = brawler_motion.motion_at(self.walk, ms)
        frame = self.frames[brawler_motion.frame_at(self.walk, ms)]
        sprite = posed(frame, self.anchor, (x * self.k, y * self.k, rotate, wide, tall), self.canvas, self.at)
        paste(img, sprite, round(self.x - self.at[0]), round(self.y - self.at[1]))

    def draw_steps(self, img: Image.Image, ms: float, cycle_ms: float, px_per_ms: float) -> None:
        """The dust of each step: it stays where it was left, so it moves back with the ground."""
        e = self.effect
        first = int(ms // cycle_ms) - 1
        for n in range(first, first + 3):
            for start in e["starts_ms"]:
                began = (n * self.walk["duration_ms"] + start) * cycle_ms / self.walk["duration_ms"]
                age = (ms - began) * self.walk["duration_ms"] / cycle_ms
                if not 0 <= age < e["duration_ms"]:
                    continue
                grow, opacity = brawler_motion.motion_at(e, age)
                pic = posed(self.steps[brawler_motion.frame_at(e, age)], self.step_anchor,
                            (0.0, 0.0, 0.0, grow, grow), self.canvas, self.at)
                pic.putalpha(pic.getchannel("A").point(lambda v: round(v * opacity)))
                left = self.x + e["at"][0] * self.k - px_per_ms * (ms - began) - self.at[0]
                paste(img, pic, round(left), round(self.y + e["at"][1] * self.k - self.at[1]))


def spun(sprite: Image.Image, angle: float, flip: float, opacity: float) -> Image.Image:
    """A small sprite (premultiplied) turned by `angle`, squeezed sideways by `flip` (negative:
    seen from the back), and faded."""
    w = max(1, round(sprite.width * abs(flip)))
    out = sprite.resize((w, sprite.height), Image.BICUBIC)
    if flip < 0:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    out = out.rotate(angle, resample=Image.BICUBIC, expand=True).convert("RGBA")
    if opacity < 1:
        out.putalpha(out.getchannel("A").point(lambda v: round(v * opacity)))
    return out


class Life:
    """Plays a map's motion for the previews, the way a game would.

    The camera moves `px` px a picture, so the brawlers walk once round the map in `count`
    pictures. Everything that moves is made to repeat over that time, so the video loops.
    """

    def __init__(self, area_name: str, px: int, count: int):
        folder = MAPS / area_name
        info = json.loads((folder / "map.json").read_text())
        self.mo = mo = info["motion"]
        self.length, self.height = info["size"]
        self.screen = info["screen"]
        self.px, self.count = px, count
        self.loop_ms = count * 1000 / FPS
        self.v = px * FPS / 1000                       # px a ms
        ground = np.asarray(Image.open(folder / info["ground"]).convert("RGB"))
        m = self.margin = 8
        self.wrapped = np.concatenate([ground[:, -m:], ground, ground[:, :self.screen + m]], axis=1)
        self.shift = map_motion.band_weights(mo, self.height) * mo["wind"]["shift_px"]
        self.rows = np.nonzero(self.shift > 0)[0]
        self.effects = {p.stem: Image.open(p).convert("RGBA") for p in sorted((folder / "effects").glob("*.png"))}
        self.cache = {}

        self.decos = []
        for p in info["props"]:
            if p["sway"] <= 0:
                continue
            img = scaled(Image.open(folder / p["file"]).convert("RGBA"), p["scale"])
            fy = p["foot"] * p["scale"]
            bend = p["sway"] + (mo["react"]["lean"] * 1.7 if p["reacts"] else 0.0)
            self.decos.append({"name": Path(p["file"]).stem, "img": img.convert("RGBa"), "x": p["x"],
                               "y": p["y"], "fy": fy, "m": math.ceil(bend * fy) + 3, "w": img.width,
                               "sway": p["sway"], "reacts": p["reacts"]})
        self.walkers = sorted((Walker(*s) for s in SQUAD), key=lambda w: w.y)
        walk_ms = self.walkers[0].walk["duration_ms"]
        # a whole number of walk cycles fits in the loop
        self.cycle_ms = self.loop_ms / round(self.loop_ms / walk_ms)
        self.walk_scale = walk_ms / self.cycle_ms
        rng = np.random.default_rng(11)
        self.springs()
        self.falling(rng)
        self.butterflies(rng)
        self.birds(rng)

    def sprite(self, name: str, size: float) -> Image.Image:
        """An effect scaled so its longest side is `size` px, premultiplied, ready to turn."""
        key = (name, round(size))
        if key not in self.cache:
            img = self.effects[name]
            k = size / max(img.size)
            self.cache[key] = img.convert("RGBa").resize((max(1, round(img.width * k)), max(1, round(img.height * k))),
                                                         Image.LANCZOS)
        return self.cache[key]

    def on_screen(self, x: float, cam: int, margin: float) -> float | None:
        """Where a spot of the map is on the screen, or None when it is out of sight."""
        dx = (x - cam) % self.length
        if dx > self.length - margin:
            dx -= self.length
        return dx if -margin < dx < self.screen + margin else None

    # -- the plants the brawlers walk through
    def springs(self) -> None:
        """Play the plants' springs twice round the loop and keep the second time, so the first
        pictures already show the plants touched at the end of the loop still wobbling."""
        react = self.mo["react"]
        idx = [i for i, d in enumerate(self.decos) if d["reacts"]]
        self.react_of = {i: k for k, i in enumerate(idx)}
        xs = np.array([self.decos[i]["x"] for i in idx])
        ys = np.array([self.decos[i]["y"] for i in idx])
        reach = np.array([self.decos[i]["w"] * react["reach"] for i in idx])
        springs = map_motion.Springs(react, len(idx))
        self.leaning = np.zeros((self.count, len(idx)))
        self.pressed = np.ones((self.count, len(idx)))
        self.bits = []
        was = np.zeros((len(self.walkers), len(idx)), bool)
        frame_ms = 1000 / FPS
        for i in range(-self.count, self.count):
            cam = i * self.px
            touched = np.zeros(len(idx), bool)
            for j, w in enumerate(self.walkers):
                wx = cam + w.x
                d = (wx - xs + self.length / 2) % self.length - self.length / 2
                now = (np.abs(d) < reach + w.width / 4) & (np.abs(w.y - ys) < react["depth_px"])
                for k in np.nonzero(now & ~was[j])[0]:
                    self.bits += self.burst(i * frame_ms, idx[k], j, wx - d[k])
                was[j] = now
                touched |= now
            springs.step(touched, frame_ms)
            if i >= 0:
                self.leaning[i] = springs.lean
                self.pressed[i] = springs.press
        self.touches = len(self.bits)

    def burst(self, t0: float, i: int, j: int, x: float) -> list[dict]:
        """The petals or leaves a plant pops when a brawler walks into it."""
        react, d = self.mo["react"], self.decos[i]
        names = family(self.effects, react["pops"].get(d["name"], []))
        if not names:
            return []
        rng = np.random.default_rng(1000 + 7 * i + j)       # the same every time round the loop
        out = []
        for _ in range(int(rng.integers(react["count"][0], react["count"][1] + 1))):
            out.append({"t0": t0, "x": x + rng.uniform(-0.25, 0.25) * d["w"], "y": d["y"] + rng.uniform(-3, 6),
                        "z": d["fy"] * rng.uniform(0.35, 0.7), "vx": rng.uniform(*react["forward_px_s"]),
                        "vz": rng.uniform(*react["up_px_s"]), "spin": rng.uniform(*react["spin_deg_s"]),
                        "angle": rng.uniform(0, 360), "tumble_ms": rng.uniform(*react["tumble_ms"]),
                        "sprite": self.sprite(names[int(rng.integers(len(names)))], rng.uniform(*react["size_px"]))})
        return out

    # -- leaves falling from the trees
    def falling(self, rng) -> None:
        fall = self.mo["falling"]
        names, weights = [], []
        for prefix, weight in fall["sprites"].items():
            found = family(self.effects, [prefix])
            names += found
            weights += [weight / len(found)] * len(found)
        p = np.array(weights) / sum(weights)
        self.leaves = []

        def add(t0, y, land):
            # starts somewhere on the screen of the moment; then it stays put on the map
            self.leaves.append({"t0": t0, "x": t0 * self.v + rng.uniform(-80, self.screen + 40), "y": y,
                                "land": land, "speed": rng.uniform(*fall["speed_px_s"]),
                                "spin": rng.uniform(*fall["spin_deg_s"]), "angle": rng.uniform(0, 360),
                                "phase": rng.uniform(0, 2 * math.pi), "tumble_ms": rng.uniform(*fall["tumble_ms"]),
                                "sprite": self.sprite(names[rng.choice(len(names), p=p)], rng.uniform(*fall["size_px"]))})

        for _ in range(round(fall["per_s"] * self.loop_ms / 1000)):
            y = rng.uniform(*fall["from"])
            spot = fall["land"][0] if rng.random() < fall["on_cliff"] else fall["land"][1]
            add(rng.uniform(0, self.loop_ms), y, max(y + 15, rng.uniform(*spot)))
        for _ in range(round(fall["front_per_s"] * self.loop_ms / 1000)):
            y = rng.uniform(*fall["front_from"])
            add(rng.uniform(0, self.loop_ms), y, y + rng.uniform(*fall["front_fall_px"]))

    # -- butterflies
    def butterflies(self, rng) -> None:
        b = self.mo["butterflies"]
        names = family(self.effects, b["sprites"])
        count = round(b["per_screen"] * self.length / self.screen) if names else 0
        self.flies = []

        def waves(size):
            # a slow wander, a quicker one and a flutter, each a whole number of times per loop
            return [(size * 0.6, int(rng.integers(2, 6)), rng.uniform(0, 2 * math.pi)),
                    (size * 0.3, int(rng.integers(9, 16)), rng.uniform(0, 2 * math.pi)),
                    (size * 0.1, int(rng.integers(30, 48)), rng.uniform(0, 2 * math.pi))]

        for i in range(count):
            self.flies.append({"x": (i + rng.uniform(0.2, 0.8)) * self.length / count, "y": rng.uniform(*b["y"]),
                               "height": rng.uniform(*b["height_px"]), "wander_x": waves(b["wander_px"][0]),
                               "wander_y": waves(b["wander_px"][1]),
                               "bob": [(5.0, int(rng.integers(20, 30)), rng.uniform(0, 2 * math.pi))],
                               "flap_ms": b["flap_ms"], "phase": rng.uniform(0, math.pi),
                               "sprite": self.sprite(names[i % len(names)], rng.uniform(*b["size_px"]))})

    # -- birds
    def birds(self, rng) -> None:
        b = self.mo["birds"]
        self.flock = []
        if b["sprite"] not in self.effects:
            return
        self.bird = self.sprite(b["sprite"], b["size_px"])
        t = rng.uniform(0, b["every_ms"][0])
        while t < self.loop_ms:
            self.flock.append({"t0": t, "facing": int(rng.choice([1, -1])), "y": rng.uniform(*b["y"]),
                               "curve_px": rng.uniform(*b["curve_px"]), "phase": rng.uniform(0, 1000)})
            t += rng.uniform(*b["every_ms"])

    def bird_picture(self, wings: float, facing: int, as_shadow: bool) -> Image.Image:
        img = self.bird.resize((self.bird.width, max(1, round(self.bird.height * wings))), Image.BICUBIC)
        if facing < 0:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        img = img.convert("RGBA")
        if as_shadow:
            alpha = img.getchannel("A").point(lambda v: round(v * self.mo["birds"]["shadow"]))
            img = Image.new("RGBA", img.size, SHADOW + (0,))
            img.putalpha(alpha)
            pad = Image.new("RGBA", (img.width + 16, img.height + 16), SHADOW + (0,))
            pad.alpha_composite(img, (8, 8))
            img = pad.filter(ImageFilter.GaussianBlur(3))
        return img

    # -- one picture
    def ground(self, t: float, cam: int) -> Image.Image:
        """The ground under the camera, with the base's rows of trees swaying."""
        m, left = self.margin, cam % self.length
        crop = self.wrapped[:, left:left + self.screen + 2 * m]
        out = crop[:, m:m + self.screen].astype(np.float32)
        gust = map_motion.wind(self.mo, t, left - m + np.arange(self.screen + 2 * m), self.length)
        shift = self.shift[self.rows][:, None] * gust[None, m:m + self.screen]
        src = np.arange(self.screen)[None, :] + m - shift
        i0 = np.floor(src).astype(int)
        f = (src - i0)[..., None]
        band = crop[self.rows].astype(np.float32)
        r = np.arange(len(self.rows))[:, None]
        out[self.rows] = band[r, i0] * (1 - f) + band[r, i0 + 1] * f
        return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8)).convert("RGBA")

    def draw_deco(self, img: Image.Image, d: dict, sx: float, lean: float, press: float) -> None:
        """A decoration leaning by `lean` (its top moves sideways by that part of its height)
        and pressed down to `press` of its height, its foot staying put."""
        w, h = d["img"].size
        m, fy = d["m"], d["fy"]
        lean = max(-m / fy, min(m / fy, lean))
        b = lean / press
        out = d["img"].transform((w + 2 * m, h), Image.AFFINE,
                                 (1, b, -m - b * fy, 0, 1 / press, fy * (1 - 1 / press)),
                                 resample=Image.BICUBIC).convert("RGBA")
        paste(img, out, round(sx - w / 2 - m), round(d["y"] - fy))

    def frame(self, i: int) -> Image.Image:
        t = i * 1000 / FPS
        cam = i * self.px
        walk_t = t * self.walk_scale
        img = self.ground(t, cam)

        # shadows: brawlers, butterflies, birds
        shadows = Image.new("RGBA", img.size, SHADOW + (0,))
        d = ImageDraw.Draw(shadows)
        for w in self.walkers:
            w.shadow(d, walk_t)
        flies = []
        for f in self.flies:
            x, y, h, wings, angle = map_motion.butterfly_at(f, t, self.loop_ms)
            sx = self.on_screen(x, cam, 60)
            if sx is None:
                continue
            flies.append((f, sx, y, h, wings, angle))
            sw = f["sprite"].width * 0.5 * (0.4 + 0.6 * wings)
            d.ellipse((sx + 6 - sw / 2, y - sw * 0.18, sx + 6 + sw / 2, y + sw * 0.18), fill=SHADOW + (46,))
        img.alpha_composite(shadows.filter(ImageFilter.GaussianBlur(5)))
        birds = []
        for b in self.flock:
            for t0 in (b["t0"], b["t0"] - self.loop_ms):
                pos = map_motion.bird_at(b, t - t0, self.mo["birds"], self.screen)
                if pos:
                    birds.append(pos)
        ox, oy = self.mo["birds"]["shadow_px"]
        for x, y, wings, facing in birds:
            sil = self.bird_picture(wings, facing, True)
            paste(img, sil, round(x + ox - sil.width / 2), round(y + oy - sil.height / 2))

        # falling leaves and popped petals: those lying on the ground first
        lying, flying = [], []
        for leaf in self.leaves:
            for dt, dx in ((0.0, 0.0), (self.loop_ms, self.length)):
                pos = map_motion.leaf_at(leaf, t - leaf["t0"] + dt, self.mo["falling"])
                if pos:
                    x, y, angle, flip, opacity, landed = pos
                    (lying if landed else flying).append((leaf["sprite"], x - dx - cam, y, angle, flip, opacity))
        for bit in self.bits:
            pos = map_motion.bit_at(bit, t - bit["t0"], self.mo["react"])
            if pos:
                x, y, angle, flip, opacity, landed = pos
                (lying if landed else flying).append((bit["sprite"], x - cam, y, angle, flip, opacity))
        for sprite, x, y, angle, flip, opacity in lying:
            if -30 < x < self.screen + 30:
                pic = spun(sprite, angle, flip, opacity)
                paste(img, pic, round(x - pic.width / 2), round(y - pic.height / 2))

        for w in self.walkers:
            w.draw_steps(img, t, self.cycle_ms, self.v)

        # decorations and brawlers, back to front
        items = []
        for k, dco in enumerate(self.decos):
            sx = self.on_screen(dco["x"], cam, dco["w"])
            if sx is None:
                continue
            lean = dco["sway"] * float(map_motion.wind(self.mo, t, dco["x"], self.length))
            press = 1.0
            if dco["reacts"]:
                lean += self.leaning[i, self.react_of[k]]
                press = self.pressed[i, self.react_of[k]]
            items.append((dco["y"], 0, k, sx, lean, press))
        for j, w in enumerate(self.walkers):
            items.append((w.y, 1, j, 0, 0, 0))
        for _, kind, k, sx, lean, press in sorted(items, key=lambda it: (it[0], it[1])):
            if kind == 0:
                self.draw_deco(img, self.decos[k], sx, lean, press)
            else:
                self.walkers[k].draw(img, walk_t)

        for sprite, x, y, angle, flip, opacity in flying:
            if -30 < x < self.screen + 30:
                pic = spun(sprite, angle, flip, opacity)
                paste(img, pic, round(x - pic.width / 2), round(y - pic.height / 2))
        for f, sx, y, h, wings, angle in flies:
            pic = spun(f["sprite"], angle, 0.12 + 0.88 * wings, 1.0)
            paste(img, pic, round(sx - pic.width / 2), round(y - h - pic.height / 2))
        for x, y, wings, facing in birds:
            pic = self.bird_picture(wings, facing, False)
            paste(img, pic, round(x - pic.width / 2), round(y - pic.height / 2))
        return img.convert("RGB")

    def busy(self, i: int) -> float:
        """How much is going on in a picture, to choose the still preview."""
        t, cam = i * 1000 / FPS, i * self.px
        score = sum(1.0 for bit in self.bits if 0 <= t - bit["t0"] < 900)
        for f in self.flies:
            x, *_ = map_motion.butterfly_at(f, t, self.loop_ms)
            score += 2.0 * (self.on_screen(x, cam, -40) is not None)
        for b in self.flock:
            for t0 in (b["t0"], b["t0"] - self.loop_ms):
                pos = map_motion.bird_at(b, t - t0, self.mo["birds"], self.screen)
                score += 4.0 * bool(pos and 150 < pos[0] < self.screen - 150)
        return score


def preview(area_name: str) -> None:
    """Previews of the map in examples/ (not game assets).

    map_<area>.jpg         the whole map, standing still, at a third of its size
    map_<area>_screen.jpg  one picture of the video below, at full size
    map_<area>.mp4         three brawlers walking once round the map, with everything moving
                           (needs ffmpeg)
    """
    folder = MAPS / area_name
    still = Image.open(folder / "map.png").convert("RGB")
    length, h = still.size
    EXAMPLES.mkdir(exist_ok=True)
    still.resize((length // 3, h // 3), Image.LANCZOS).save(EXAMPLES / f"map_{area_name}.jpg", quality=90)

    # The video lasts as long as the walk once round the loop, moving a whole number of px per
    # picture, and everything that moves repeats over that time. So when the video starts over,
    # nothing jumps.
    px = round(WALK_PX_S / FPS)
    count = length // px
    life = Life(area_name, px, count)
    best = max(range(0, count, 3), key=life.busy)
    life.frame(best).save(EXAMPLES / f"map_{area_name}_screen.jpg", quality=90)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found: no video")
        return
    out = EXAMPLES / f"map_{area_name}.mp4"
    size = life.screen
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size}x{h}",
           "-r", str(FPS), "-i", "-", "-vf", "scale=720:720:flags=lanczos", "-c:v", "libx264", "-preset", "slow",
           "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
        for i in range(count):
            proc.stdin.write(life.frame(i).tobytes())
        proc.stdin.close()
    print(f"video    {count} pictures, {count / FPS:.1f} s, {out.stat().st_size / 1e6:.1f} MB, "
          f"{life.touches} petals and leaves popped by the brawlers")


def main() -> None:
    for area_name in AREAS:
        build(area_name)
        preview(area_name)


if __name__ == "__main__":
    main()
