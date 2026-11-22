"""Build an area's long map from two pictures drawn by Gemini.

An area is a folder in maps/ with its two pictures in source/:
  base.jpg   one square piece of the path between its two walls, seen from above
  props.jpg  the area's decorations, on a magenta screen

From them the script makes, in the area's folder:
  tile.png          the base, made to repeat seamlessly from left to right
  props/<name>.png  every decoration, cut out
  map.png           the whole map: the tile laid out several times, with the decorations spread
                    along it so that no two screens look the same. Its right edge joins its left
                    edge, so it loops.
  map.json          the map's size, where the characters walk, and where every decoration is

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/make_map.py
"""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import brawler_motion as motion
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


# ---------------------------------------------------------------- the decorations

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


def split_props(rgba: np.ndarray, names: list[str]) -> dict[str, Image.Image]:
    """Cut the sheet into its decorations, named in reading order."""
    solid = rgba[..., 3] >= 128
    # Pieces of one decoration (the pebbles of a group, say) are joined first.
    labels, n = label(dilate(solid, 8))
    sizes = np.bincount(labels.ravel())
    comps = [i for i in range(1, n + 1) if sizes[i] > 300]
    if len(comps) != len(names):
        raise SystemExit(f"expected {len(names)} decorations on the sheet, found {len(comps)}")
    centres = []
    for c in comps:
        ys, xs = np.nonzero(labels == c)
        centres.append((c, ys.mean(), xs.mean()))
    # Reading order: rows are split where the centres jump down by more than 100 px.
    centres.sort(key=lambda t: t[1])
    rows, row = [], [centres[0]]
    for item in centres[1:]:
        if item[1] - row[-1][1] > 100:
            rows.append(row)
            row = []
        row.append(item)
    rows.append(row)
    ordered = [c for row in rows for c, _, _ in sorted(row, key=lambda t: t[2])]
    return {name: bleed(crop_to_alpha(rgba, dilate(labels == c, 2))) for name, c in zip(names, ordered)}


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


def recolour(img: Image.Image, base: np.ndarray) -> Image.Image:
    """Repaint a green tree's leaves in the pink of the base's pink trees.

    Each leaf pixel takes the pink that is as light, among the base's pink pixels, as it is
    among the tree's leaf pixels, so the shading stays the same. Trunk and outline are kept.
    """
    arr = np.asarray(img).astype(np.float32)
    hsv = np.asarray(img.convert("RGB").convert("HSV")).astype(np.float32)
    hue, sat, val = hsv[..., 0] * 360 / 255, hsv[..., 1] / 255, hsv[..., 2] / 255
    leaves = (hue > 40) & (hue < 150) & (sat > 0.2) & (val > 0.15) & (arr[..., 3] > 0)

    r, g, b = base[..., 0], base[..., 1], base[..., 2]
    pink = base[(r > g + 35) & (b > g + 5) & (r > 120)]
    light = lambda c: c @ np.array([0.299, 0.587, 0.114], np.float32)
    pink = pink[np.argsort(light(pink))]
    # pinks from darkest to lightest, averaged in 64 steps
    steps = np.array([chunk.mean(0) for chunk in np.array_split(pink, 64)])

    own = light(arr[..., :3][leaves])
    rank = np.argsort(np.argsort(own)) / max(len(own) - 1, 1)
    arr[..., :3][leaves] = steps[np.minimum((rank * 64).astype(int), 63)]
    return Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8), "RGBA")


def foot(img: Image.Image) -> int:
    """Row of the decoration's lowest solid pixel (the bottom of its trunk, stem or stone)."""
    rows = np.nonzero((np.asarray(img)[..., 3] >= 128).any(1))[0]
    return int(rows.max())


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


def render(tile: np.ndarray, area: dict, props: dict[str, Image.Image], placed: list[dict]) -> Image.Image:
    """The whole map: the tile repeated, with every decoration and its shadow drawn on it."""
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
            paste(canvas, img, left + dx, top)
    return canvas.convert("RGB")


def paste(canvas: Image.Image, img: Image.Image, left: int, top: int) -> None:
    """alpha_composite that accepts positions partly outside the canvas."""
    l, t = max(left, 0), max(top, 0)
    r, b = min(left + img.width, canvas.width), min(top + img.height, canvas.height)
    if r <= l or b <= t:
        return
    canvas.alpha_composite(img.crop((l - left, t - top, r - left, b - top)), (l, t))


def build(area_name: str) -> None:
    area = AREAS[area_name]
    folder = MAPS / area_name
    base = np.asarray(Image.open(folder / "source" / "base.jpg").convert("RGB")).astype(np.float32)

    tile = even_light(make_tile(base, area["overlap"]), area["walk"])
    Image.fromarray(np.clip(tile + 0.5, 0, 255).astype(np.uint8)).save(folder / "tile.png", optimize=True)

    props = split_props(key_magenta(folder / "source" / "props.jpg"), area["props"])
    for new, old in area.get("pink", {}).items():
        props[new] = recolour(props[old], base)
    (folder / "props").mkdir(exist_ok=True)
    for old in (folder / "props").glob("*.png"):
        old.unlink()
    for name, img in props.items():
        img.save(folder / "props" / f"{name}.png", optimize=True)

    length = tile.shape[1] * area["tiles"]
    placed = place(area, props, length)
    render(tile, area, props, placed).save(folder / "map.png", optimize=True)

    info = {
        "size": [length, tile.shape[0]],
        "loops": True,
        "screen": base.shape[1],
        "walk": area["walk"],
        "tile": {"file": "tile.png", "width": tile.shape[1], "height": tile.shape[0], "repeat": area["tiles"]},
    }
    entries = [{"file": f"props/{p['name']}.png", "x": p["x"], "y": p["y"], "foot": foot(props[p["name"]]),
                "scale": p["scale"], "shadow": area["shadow"].get(p["name"], 1.0)} for p in placed]
    # one decoration per line
    text = json.dumps(info, indent=2)
    text = text[:-2] + ',\n  "props": [\n' + ",\n".join("    " + json.dumps(e) for e in entries) + "\n  ]\n}\n"
    text = text.replace('[\n    %d,\n    %d\n  ]' % tuple(info["size"]), "[%d, %d]" % tuple(info["size"]))
    text = text.replace('[\n    %d,\n    %d\n  ]' % tuple(info["walk"]), "[%d, %d]" % tuple(info["walk"]))
    (folder / "map.json").write_text(text)
    print(f"{area_name}: map {length} x {tile.shape[0]} px, tile {tile.shape[1]} px x {area['tiles']}, "
          f"{len(props)} decorations, {len(placed)} placed")


# ---------------------------------------------------------------- previews

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
        self.shadow_w = (box[2] - box[0]) * 0.72
        self.height = fh * k
        side = round(max(fw, fh) * k * 1.6)
        self.canvas, self.at = (side, side), (side / 2, side * 0.8)

    def draw(self, img: Image.Image, shadows: ImageDraw.ImageDraw, ms: float) -> None:
        x, y, rotate, wide, tall = motion.motion_at(self.walk, ms)
        x, y = x * self.k, y * self.k
        w = self.shadow_w * wide * (1 + 3 * y / self.height)        # smaller while off the ground
        shadows.ellipse((self.x + x - w / 2, self.y - w * 0.13, self.x + x + w / 2, self.y + w * 0.09),
                        fill=SHADOW + (round(255 * 0.42),))
        frame = self.frames[motion.frame_at(self.walk, ms)]
        sprite = posed(frame, self.anchor, (x, y, rotate, wide, tall), self.canvas, self.at)
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
                grow, opacity = motion.motion_at(e, age)
                pic = posed(self.steps[motion.frame_at(e, age)], self.step_anchor, (0.0, 0.0, 0.0, grow, grow),
                            self.canvas, self.at)
                pic.putalpha(pic.getchannel("A").point(lambda v: round(v * opacity)))
                left = self.x + e["at"][0] * self.k - px_per_ms * (ms - began) - self.at[0]
                paste(img, pic, round(left), round(self.y + e["at"][1] * self.k - self.at[1]))


def strip(path: Path, count: int) -> list[Image.Image]:
    img = Image.open(path).convert("RGBA")
    w = img.width // count
    return [img.crop((i * w, 0, (i + 1) * w, img.height)) for i in range(count)]


def preview(area_name: str) -> None:
    """Previews of the map in examples/ (not game assets).

    map_<area>.jpg         the whole map, at a third of its size
    map_<area>_screen.jpg  one screen of it with three brawlers on it, at full size
    map_<area>.mp4         the brawlers walking once round the loop (needs ffmpeg)
    """
    full = Image.open(MAPS / area_name / "map.png").convert("RGB")
    length, h = full.size
    screen = json.loads((MAPS / area_name / "map.json").read_text())["screen"]
    EXAMPLES.mkdir(exist_ok=True)
    full.resize((length // 3, h // 3), Image.LANCZOS).save(EXAMPLES / f"map_{area_name}.jpg", quality=90)

    # The video lasts as long as the walk once round the loop, moving a whole number of px per
    # picture, and the walk cycle is stretched a touch so a whole number of cycles fits in it.
    # So when the video starts over, nothing jumps.
    px = round(WALK_PX_S / FPS)
    count = length // px
    total_ms = count * 1000 / FPS
    squad = sorted((Walker(*s) for s in SQUAD), key=lambda w: w.y)
    walk_ms = squad[0].walk["duration_ms"]
    cycle_ms = total_ms / round(total_ms / walk_ms)
    wrapped = Image.new("RGB", (length + screen, h))
    wrapped.paste(full, (0, 0))
    wrapped.paste(full.crop((0, 0, screen, h)), (length, 0))

    def picture(i: int) -> Image.Image:
        ms = i * 1000 / FPS
        left = (i * px) % length
        img = wrapped.crop((left, 0, left + screen, h)).convert("RGBA")
        shadows = Image.new("RGBA", img.size, SHADOW + (0,))
        d = ImageDraw.Draw(shadows)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        steps = Image.new("RGBA", img.size, (0, 0, 0, 0))
        for w in squad:
            w.draw_steps(steps, ms, cycle_ms, px * FPS / 1000)
            w.draw(layer, d, ms * walk_ms / cycle_ms)
        img.alpha_composite(shadows.filter(ImageFilter.GaussianBlur(5)))
        img.alpha_composite(steps)
        img.alpha_composite(layer)
        return img.convert("RGB")

    picture(int(count * 0.37)).save(EXAMPLES / f"map_{area_name}_screen.jpg", quality=90)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found: no video")
        return
    out = EXAMPLES / f"map_{area_name}.mp4"
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{screen}x{h}",
           "-r", str(FPS), "-i", "-", "-vf", "scale=720:720:flags=lanczos", "-c:v", "libx264", "-preset", "slow",
           "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
        for i in range(count):
            proc.stdin.write(picture(i).tobytes())
        proc.stdin.close()
    print(f"video    {count} pictures, {total_ms / 1000:.1f} s, {out.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    for area_name in AREAS:
        build(area_name)
        preview(area_name)


if __name__ == "__main__":
    main()
