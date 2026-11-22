"""Build the brawler cards for the "choose a card" screen, with a moving preview.

The cards are wide and short, and three of them stack on top of each other on the screen.
Every brawler has its own card: a plain card in its colour, one big 3D object that floats on
it (Peep's feather...), and about 100 small ones that drift across it, as if a breeze were
blowing through. The brawler stands on the left and pops out over the top of the card; its
name and skill are written next to it.

Source: cards/brawlers/source/*.jpg, sheets on a green screen. A sheet has one brawler (the
        empty card at the top, one big 3D object below it, small ones next to that) or several
        brawlers in rows (the card on the left, the big object in the middle, small ones on the
        right). The file name lists the brawlers on it, top to bottom: tnt-dragon-wizard.jpg.

Output, per brawler, in cards/brawlers/<brawler>/:
  card.png           the card, 960 x 300 px: shorter than on the sheet, with crisp corners
  object.png         the big 3D object
  particles/<n>.png  the small ones, biggest first (4 to 9 of them, as drawn)
plus cards/brawlers/cards.json (where everything goes and how it moves, for the game), a still
of every card in examples/card_<brawler>.png, and a moving preview of three cards stacked like
on the real screen in examples/cards_screen.gif.

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/make_brawler_cards.py
To also save every card as its own moving preview:  python3 scripts/make_brawler_cards.py --gifs <folder>
"""

import argparse
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from extract_brawlers import crop_to_alpha, dilate, key_green, label
from shade_brawlers import blur

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "cards" / "brawlers" / "source"
OUT = ROOT / "cards" / "brawlers"
EXAMPLES = ROOT / "examples"
FONT = ROOT / "fonts" / "LilitaOne-Regular.ttf"
NAMES = {k: v["name"] for k, v in json.loads((ROOT / "brawlers" / "sizes.json").read_text()).items()}

# Skill text. Placeholders until the real skills are written.
SKILLS = {
    "chick": "Pecks the closest enemy, super fast.",
    "tnt": "Runs in and blows up everything around it.",
    "dragon": "Breathes fire on every enemy in front of it.",
    "wizard": "Casts magic bolts from far away.",
    "ghost": "Swipes enemies with its icy claws.",
    "acorn": "Swings its leaf and knocks enemies back.",
    "octopus": "Slaps enemies with its tentacle.",
}

# The particles are placed at random, but the same way every time for a brawler, so a card
# always looks the same. Each brawler has its own pattern, so stacked cards do not match.
SEEDS = {"chick": 7, "tnt": 11, "dragon": 23, "wizard": 31, "ghost": 41, "acorn": 53, "octopus": 61}

# The big object's longest side, in card pixels, where the default (LAYOUT["object"]["height"])
# is too big: round and wide objects look bigger than a tall, thin feather at the same size.
OBJECT_SIZE = {"wizard": 232, "acorn": 246, "octopus": 216}

# The three cards stacked in the screen preview, top to bottom.
SCREEN = ["chick", "tnt", "wizard"]
SCREEN_SCALE = 0.5         # the screen preview is drawn at half size, to keep the file small

# ---------------------------------------------------------------- layout and motion
# Everything below is in pixels of the card (960 x 300), measured from its top left corner.
# The same numbers go into cards.json for the game.

LAYOUT = {
    "card": {"width": 960, "height": 300, "corner_radius": 42},
    # The brawler stands on the left, its feet near the bottom, popping out over the top.
    # It is `height` tall, unless that would make it wider than `max_width` (the Octopus).
    "brawler": {"feet": [150, 282], "height": 318, "max_width": 266},
    # Name and skill: left aligned, in the middle of the card.
    "name": {"left": 292, "top": 56, "size": 92},
    "skill": {"left": 295, "top": 168, "size": 33, "line_height": 40, "width": 360},
    # The big 3D object floats on the right and pops out over the top edge.
    "object": {"center": [838, 116], "height": 272},
}

MOTION = {
    "loop_ms": 3000,      # every motion repeats within this time, so a preview can loop
    # The brawler breathes (stretches up a little and back) and rocks gently.
    "brawler": {"breathe": 0.03, "breathe_ms": 1500, "rock_deg": 1.5, "rock_ms": 3000},
    # The big object bobs up and down and rocks.
    "object": {"bob_px": 8, "bob_ms": 1500, "rock_deg": 5, "rock_ms": 3000},
    # A soft shine sweeps across the card once per loop.
    "shine": {"start_ms": 900, "duration_ms": 700, "strength": 0.30},
    # The particles. Each one appears, drifts with the wind and fades out, again and again.
    # Three layers give depth: far ones are smaller, slower, paler and a little blurred.
    "particles": {
        "wind_deg": 14,   # the wind blows to the right and a little downwards
        "layers": [
            {"name": "far",  "count": 48, "size": [24, 34], "speed": 24, "sway_px": 4,  "spin_deg": 18,
             "life_ms": 3000, "fade_to_card": 0.50, "blur_px": 1.0},
            {"name": "mid",  "count": 36, "size": [36, 50], "speed": 42, "sway_px": 7,  "spin_deg": 28,
             "life_ms": 3000, "fade_to_card": 0.22, "blur_px": 0.4},
            {"name": "near", "count": 16, "size": [52, 70], "speed": 64, "sway_px": 10, "spin_deg": 36,
             "life_ms": 1500, "fade_to_card": 0.0, "blur_px": 0.0, "keep_off_text": True},
        ],
        "tumbling": 0.6,  # this share of them flip over as they fall, like real feathers
    },
}

SS = 2                     # the preview is drawn at twice the size, then scaled down
FPS = 25
MARGIN = (36, 64, 52, 40)  # room around the card in the preview: left, top, right, bottom
BACKGROUND = (30, 24, 50)  # the screen behind the cards in the preview


# ---------------------------------------------------------------- cutting the sheet

def bands(solid: np.ndarray, count: int) -> list[slice]:
    """Split a sheet into `count` rows, at its widest empty gaps."""
    if count == 1:
        return [slice(0, solid.shape[0])]
    rows = np.nonzero(solid.any(axis=1))[0]
    gaps, start = [], None
    for y in range(rows[0], rows[-1] + 1):
        empty = not solid[y].any()
        if empty and start is None:
            start = y
        elif not empty and start is not None:
            gaps.append((y - start, (start + y) // 2))
            start = None
    if len(gaps) < count - 1:
        raise SystemExit(f"expected {count} rows on the sheet, found {len(gaps) + 1}")
    cuts = sorted(middle for _, middle in sorted(gaps, reverse=True)[:count - 1])
    edges = [0] + cuts + [solid.shape[0]]
    return [slice(a, b) for a, b in zip(edges, edges[1:])]


def cut_sheet(path: Path, count: int) -> list[tuple[np.ndarray, Image.Image, list[Image.Image]]]:
    """For every brawler on a sheet, top to bottom: its card (RGBA array, cropped), its big
    object, and its small objects, biggest first.

    In each brawler's part of the sheet, the widest piece is the card, the biggest of the
    others is the big object, and the rest are the small ones.
    """
    rgba = key_green(path)
    solid = rgba[..., 3] >= 128
    labels, n = label(dilate(solid, 2))
    out = []
    for number, band in enumerate(bands(solid, count), start=1):
        inside = np.zeros_like(solid)
        inside[band] = True
        parts = []
        for i in range(1, n + 1):
            region = (labels == i) & inside
            ys, xs = np.nonzero(region & solid)
            if len(xs) > 300:
                parts.append((xs.max() - xs.min(), len(xs), region))
        if len(parts) < 3:
            raise SystemExit(f"{path.name}, row {number}: expected a card, a big object and small ones, found {len(parts)} pieces")
        parts.sort(key=lambda p: -p[0])
        card = np.asarray(crop_to_alpha(rgba, dilate(parts[0][2], 2)))
        rest = sorted(parts[1:], key=lambda p: -p[1])
        big = crop_to_alpha(rgba, dilate(rest[0][2], 2))
        small = [crop_to_alpha(rgba, dilate(p[2], 2)) for p in rest[1:]]
        out.append((card, big, small))
    return out


def rounded_mask(width: int, height: int, radius: float, scale: int = 4) -> np.ndarray:
    """A smooth rounded rectangle, as alpha from 0 to 1."""
    big = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, width * scale - 1, height * scale - 1), radius * scale, fill=255)
    return np.asarray(big.resize((width, height), Image.LANCZOS)).astype(np.float32) / 255.0


def resample(channel: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(Image.fromarray(channel.astype(np.float32), "F").resize(size, Image.BICUBIC))


def make_card(card: np.ndarray) -> Image.Image:
    """The card at its final size, with a crisp new outline.

    The card on the sheet is taller than wanted, so its content is stretched to the new shape;
    it is a smooth gradient, so that does not show. The corners are drawn again afterwards,
    so they stay round instead of being stretched along.
    """
    w, h = LAYOUT["card"]["width"], LAYOUT["card"]["height"]
    alpha = card[..., 3].astype(np.float32) / 255.0
    ys, xs = np.nonzero(alpha > 0.5)
    inset = 3                                            # the outermost pixels touched the green screen
    box = (slice(ys.min() + inset, ys.max() + 1 - inset), slice(xs.min() + inset, xs.max() + 1 - inset))
    a = alpha[box]
    colour = card[..., :3].astype(np.float32)[box]
    # Resize the colour weighted by its alpha, so the transparent corners do not bleed in.
    weight = resample(a, (w, h))
    mixed = [resample(colour[..., c] * a, (w, h)) for c in range(3)]
    # Where the new corners reach past the old ones, take the colour from close by.
    soft_weight = blur(np.clip(weight, 0, 1), 6)
    out = np.zeros((h, w, 4), dtype=np.float32)
    for c in range(3):
        near = blur(mixed[c], 6)
        out[..., c] = np.where(weight > 0.5, mixed[c] / np.maximum(weight, 1e-3), near / np.maximum(soft_weight, 1e-3))
    out[..., 3] = rounded_mask(w, h, LAYOUT["card"]["corner_radius"]) * 255
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGBA")


# ---------------------------------------------------------------- particles

def make_particles(rng: random.Random, small_count: int) -> list[dict]:
    """Every particle's fixed settings: which sprite, how big, where, and its timing."""
    w, h = LAYOUT["card"]["width"], LAYOUT["card"]["height"]
    loop = MOTION["loop_ms"]
    text = (LAYOUT["name"]["left"] - 20, LAYOUT["name"]["top"] - 10,
            LAYOUT["skill"]["left"] + LAYOUT["skill"]["width"], LAYOUT["skill"]["top"] + 2 * LAYOUT["skill"]["line_height"] + 10)
    wind = math.radians(MOTION["particles"]["wind_deg"])
    out = []
    for depth, layer in enumerate(MOTION["particles"]["layers"]):
        for _ in range(layer["count"]):
            while True:
                x, y = rng.uniform(-30, w + 30), rng.uniform(-20, h + 20)
                inside_text = text[0] < x < text[2] and text[1] < y < text[3]
                if not (layer.get("keep_off_text") and inside_text):
                    break
            direction = wind + math.radians(rng.uniform(-12, 12))
            speed = layer["speed"] * rng.uniform(0.8, 1.2)
            out.append({
                "depth": depth,
                "sprite": rng.randrange(small_count),
                "size": rng.uniform(*layer["size"]),
                "home": (x, y),
                "velocity": (speed * math.cos(direction), speed * math.sin(direction)),
                "life": layer["life_ms"],
                "phase": rng.random(),
                "angle": rng.uniform(0, 360),
                "spin": layer["spin_deg"] * rng.uniform(0.6, 1.0) * rng.choice((-1, 1)),
                "spin_ms": loop / rng.choice((1, 2)),
                "sway": layer["sway_px"] * rng.uniform(0.6, 1.0),
                "sway_ms": loop / rng.choice((1, 2)),
                "tumble_ms": loop / rng.choice((1, 2)) if rng.random() < MOTION["particles"]["tumbling"] else 0,
                "offset": rng.random(),
            })
    return out


def particle_at(p: dict, ms: float) -> tuple[float, float, float, float, float]:
    """(x, y, angle, flip, opacity) of a particle at this moment."""
    u = (ms / p["life"] + p["phase"]) % 1.0                 # where it is in its life, 0 to 1
    drift = (u - 0.5) * p["life"] / 1000
    x = p["home"][0] + p["velocity"][0] * drift
    y = p["home"][1] + p["velocity"][1] * drift
    y += p["sway"] * math.sin(2 * math.pi * (ms / p["sway_ms"] + p["offset"]))
    angle = p["angle"] + p["spin"] * math.sin(2 * math.pi * (ms / p["spin_ms"] + p["offset"]))
    flip = math.cos(2 * math.pi * (ms / p["tumble_ms"] + p["offset"])) if p["tumble_ms"] else 1.0
    opacity = math.sin(math.pi * u) ** 0.8
    return x, y, angle, flip, opacity


# ---------------------------------------------------------------- drawing

def premultiplied(img: Image.Image) -> Image.Image:
    return img.convert("RGBa")


def turned(img: Image.Image, size: float, flip: float, angle: float) -> Image.Image:
    """A sprite with its longest side `size` px, squeezed sideways by `flip` (negative mirrors it),
    and turned by `angle` degrees."""
    k = size / max(img.size)
    w, h = max(1, round(img.width * k * abs(flip))), max(1, round(img.height * k))
    out = premultiplied(img).resize((w, h), Image.LANCZOS)
    if flip < 0:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    return out.rotate(angle, resample=Image.BICUBIC, expand=True).convert("RGBA")


def faded(img: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 0.999:
        return img
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda v: round(v * opacity)))
    return out


def stamp(canvas: Image.Image, img: Image.Image, cx: float, cy: float) -> None:
    """Draw `img` centred on (cx, cy); it may be partly outside the canvas."""
    x, y = round(cx - img.width / 2), round(cy - img.height / 2)
    left, top = max(0, -x), max(0, -y)
    if left >= img.width or top >= img.height:
        return                                            # entirely off the canvas
    if left or top:
        img = img.crop((left, top, img.width, img.height))
    if img.width > 0 and img.height > 0:
        canvas.alpha_composite(img, (max(0, x), max(0, y)))


def tinted(img: Image.Image, colour: tuple, amount: float) -> Image.Image:
    """`img` blended toward `colour` by `amount` (0 to 1), keeping its shape."""
    if amount <= 0:
        return img
    a = np.asarray(img).astype(np.float32)
    a[..., :3] += (np.array(colour, dtype=np.float32) - a[..., :3]) * amount
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8), "RGBA")


def soft_ellipse(size: tuple, box: tuple, colour: tuple, blur: float) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(box, fill=colour)
    return layer.filter(ImageFilter.GaussianBlur(blur))


def text_layer(size: tuple, brawler: str, card_colour: tuple) -> Image.Image:
    """The name and the skill text, drawn once (they do not move)."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ox, oy = MARGIN[0] * SS, MARGIN[1] * SS
    outline = (74, 40, 16, 255)

    # Name: white to cream, with a thick dark outline and a soft drop shadow.
    spec = LAYOUT["name"]
    font = ImageFont.truetype(str(FONT), spec["size"] * SS)
    name = NAMES[brawler]
    x, y = ox + spec["left"] * SS, oy + spec["top"] * SS
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((x, y + 7 * SS), name, font=font, fill=(74, 40, 16, 150),
                                stroke_width=7 * SS, stroke_fill=(74, 40, 16, 150))
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(3 * SS)))
    ImageDraw.Draw(layer).text((x, y), name, font=font, fill=outline, stroke_width=7 * SS, stroke_fill=outline)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).text((x, y), name, font=font, fill=255)
    _, top, _, bottom = font.getbbox(name)
    ramp = np.linspace(0, 1, size[1], dtype=np.float32)[:, None]
    t = np.clip((ramp * size[1] - (y + top)) / max(bottom - top, 1), 0, 1)
    fill = np.zeros((size[1], size[0], 4), dtype=np.float32)
    fill[..., :3] = np.array([255, 255, 255]) + (np.array([255, 236, 186]) - np.array([255, 255, 255])) * t[..., None]
    fill[..., 3] = np.asarray(mask)
    layer.alpha_composite(Image.fromarray(fill.astype(np.uint8), "RGBA"))

    # Skill: one or two lines, in a dark colour on a light card or white on a dark one.
    spec = LAYOUT["skill"]
    font = ImageFont.truetype(str(FONT), spec["size"] * SS)
    words, lines = SKILLS.get(brawler, "").split(), [""]
    for word in words:
        trial = (lines[-1] + " " + word).strip()
        if font.getlength(trial) <= spec["width"] * SS or not lines[-1]:
            lines[-1] = trial
        else:
            lines.append(word)
    r, g, b = card_colour
    light_card = 0.299 * r + 0.587 * g + 0.114 * b > 150      # how bright the card looks
    d = ImageDraw.Draw(layer)
    for i, line in enumerate(lines[:2]):
        at = (ox + spec["left"] * SS, oy + (spec["top"] + i * spec["line_height"]) * SS)
        if light_card:
            d.text(at, line, font=font, fill=(110, 58, 18, 255))
        else:
            edge = tuple(int(v * 0.35) for v in card_colour) + (255,)   # a deep tone of the card
            d.text(at, line, font=font, fill=(255, 255, 255, 255), stroke_width=3 * SS, stroke_fill=edge)
    return layer


def shine_band(size: tuple, x: float) -> Image.Image:
    """A soft diagonal band of white light centred on column x."""
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = (xx - x) + (yy - h / 2) * 0.45                    # leans to the right
    band = np.exp(-(d / (34 * SS)) ** 2)
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., :3] = 255
    out[..., 3] = np.clip(band * 255 * MOTION["shine"]["strength"], 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def build_preview(brawler: str, card: Image.Image, big: Image.Image, small: list[Image.Image],
                  gif_folder: Path | None = None) -> list[Image.Image]:
    """Render the card's loop. Saves a still to examples/, and the moving preview to `gif_folder`
    if one is given. Returns the frames."""
    w, h = LAYOUT["card"]["width"], LAYOUT["card"]["height"]
    size = ((MARGIN[0] + w + MARGIN[2]) * SS, (MARGIN[1] + h + MARGIN[3]) * SS)
    ox, oy = MARGIN[0] * SS, MARGIN[1] * SS
    loop = MOTION["loop_ms"]

    card_big = card.resize((w * SS, h * SS), Image.LANCZOS)
    card_mask = Image.new("L", size, 0)
    card_mask.paste(card_big.getchannel("A"), (ox, oy))
    card_colour = tuple(int(v) for v in np.asarray(card)[..., :3].reshape(-1, 3).mean(axis=0))
    shade = tuple(max(0, int(v * 0.62)) for v in card_colour)          # a darker tone of the card, for shadows

    def clipped(layer: Image.Image) -> Image.Image:
        """Keep only the part of `layer` that is on the card."""
        a = np.asarray(layer.getchannel("A")).astype(np.uint16) * np.asarray(card_mask) // 255
        out = layer.copy()
        out.putalpha(Image.fromarray(a.astype(np.uint8)))
        return out

    # The still parts, drawn once.
    base = Image.new("RGBA", size, BACKGROUND + (255,))
    drop = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(drop).rounded_rectangle((ox, oy + 10 * SS, ox + w * SS, oy + (h + 10) * SS),
                                           LAYOUT["card"]["corner_radius"] * SS, fill=(0, 0, 0, 130))
    base.alpha_composite(drop.filter(ImageFilter.GaussianBlur(14 * SS)))
    base.alpha_composite(card_big, (ox, oy))
    words = text_layer(size, brawler, card_colour)

    # Particle sprites, per layer: far ones paler (closer to the card colour).
    layers = MOTION["particles"]["layers"]
    sprites = [[tinted(s, card_colour, layer["fade_to_card"]) for s in small] for layer in layers]
    particles = make_particles(random.Random(SEEDS.get(brawler, 7)), len(small))

    spec_b, move_b = LAYOUT["brawler"], MOTION["brawler"]
    body = Image.open(ROOT / "brawlers" / "shaded" / f"{brawler}.png").convert("RGBA")
    body = body.crop(body.getbbox())
    feet = (ox + spec_b["feet"][0] * SS, oy + spec_b["feet"][1] * SS)
    tall = spec_b["height"]                                          # its size on the card
    if body.width * tall / body.height > spec_b["max_width"]:
        tall = body.height * spec_b["max_width"] / body.width
    wide = body.width * tall / body.height
    spec_o, move_o = LAYOUT["object"], MOTION["object"]
    object_size = OBJECT_SIZE.get(brawler, spec_o["height"])

    frames = []
    for ms in np.arange(0, loop, 1000 / FPS):
        frame = base.copy()

        # Particles, far to near, each layer blurred by its depth, all kept on the card.
        for depth, layer in enumerate(layers):
            sheet = Image.new("RGBA", size, (0, 0, 0, 0))
            for p in particles:
                if p["depth"] != depth:
                    continue
                x, y, angle, flip, opacity = particle_at(p, ms)
                if opacity < 0.02 or abs(flip) < 0.04:
                    continue
                img = faded(turned(sprites[depth][p["sprite"]], p["size"] * SS, flip, angle), opacity)
                stamp(sheet, img, ox + x * SS, oy + y * SS)
            if layer["blur_px"]:
                sheet = sheet.filter(ImageFilter.GaussianBlur(layer["blur_px"] * SS))
            frame.alpha_composite(clipped(sheet))

        # The shine sweeping across.
        shine = MOTION["shine"]
        u = (ms - shine["start_ms"]) / shine["duration_ms"]
        if 0 <= u <= 1:
            frame.alpha_composite(clipped(shine_band(size, ox + (-0.15 + 1.3 * u) * w * SS)))

        # The big object: bobbing and rocking, with its shadow on the card.
        bob = move_o["bob_px"] * math.sin(2 * math.pi * ms / move_o["bob_ms"])
        rock = move_o["rock_deg"] * math.sin(2 * math.pi * ms / move_o["rock_ms"])
        cx, cy = ox + spec_o["center"][0] * SS, oy + (spec_o["center"][1] + bob) * SS
        lift = (bob + move_o["bob_px"]) / (2 * move_o["bob_px"])            # 0 at its lowest, 1 at its highest
        sw, sh = 150 * SS * (1.05 - 0.15 * (1 - lift)), 34 * SS
        sy = oy + (spec_o["center"][1] + object_size * 0.40) * SS
        frame.alpha_composite(clipped(soft_ellipse(size, (cx - 40 * SS - sw / 2, sy - sh / 2, cx - 40 * SS + sw / 2, sy + sh / 2),
                                                   shade + (int(70 + 40 * (1 - lift)),), 12 * SS)))
        stamp(frame, turned(big, object_size * SS, 1.0, rock), cx, cy)

        # The brawler: breathing and rocking on its feet, with its shadow on the card.
        breathe = 1 + move_b["breathe"] * math.sin(2 * math.pi * ms / move_b["breathe_ms"])
        rock = move_b["rock_deg"] * math.sin(2 * math.pi * ms / move_b["rock_ms"])
        sw = max(tall, wide) * 0.62 * SS / math.sqrt(breathe)
        frame.alpha_composite(clipped(soft_ellipse(size, (feet[0] - sw / 2, feet[1] - 12 * SS, feet[0] + sw / 2, feet[1] + 14 * SS),
                                                   shade + (120,), 6 * SS)))
        k = tall * SS / body.height
        stood = premultiplied(body).resize((round(body.width * k / math.sqrt(breathe)), round(body.height * k * breathe)), Image.LANCZOS)
        pad = Image.new("RGBa", (stood.width * 2, stood.height * 2), (0, 0, 0, 0))
        pad.paste(stood, (stood.width // 2, 0))                              # feet in the middle of the pad
        stood = pad.rotate(-rock, resample=Image.BICUBIC, center=(stood.width, stood.height)).convert("RGBA")
        stamp(frame, stood, feet[0], feet[1])

        frame.alpha_composite(words)
        frames.append(frame.resize((size[0] // SS, size[1] // SS), Image.LANCZOS).convert("RGB"))

    frames[0].save(EXAMPLES / f"card_{brawler}.png", optimize=True)
    if gif_folder is not None:
        save_gif(frames, gif_folder / f"card_{brawler}.gif")
    return frames


def distinct_colours(sprite: Image.Image, bins: int = 24, share: float = 0.003) -> list[tuple]:
    """One light and one dark tone of every hue that covers a noticeable part of a sprite."""
    a = np.asarray(sprite.convert("RGBA"))
    px = a[a[..., 3] > 200][:, :3]
    hsv = np.asarray(Image.fromarray(px.reshape(-1, 1, 3).astype(np.uint8)).convert("HSV")).reshape(-1, 3).astype(int)
    keep = (hsv[:, 1] > 60) & (hsv[:, 2] > 50)                      # colourful, not dark
    px, hsv = px[keep], hsv[keep]
    out = []
    for k in range(bins):
        in_bin = (hsv[:, 0] * bins // 256) == k
        if in_bin.sum() < share * len(px):
            continue
        value = hsv[in_bin, 2]
        for part in (value >= np.median(value), value < np.median(value)):
            if part.any():
                out.append(tuple(int(c) for c in np.median(px[in_bin][part], axis=0)))
    return out


def save_gif(frames: list[Image.Image], path: Path, keep: list[tuple] = ()) -> None:
    """A looping GIF. One shared palette for every frame, so colours do not flicker.

    A GIF has only 255 colours, chosen from the frames by area. A small spot of its own colour
    can lose out (Peep's orange beak next to TNT's big red card turned red), so the colours in
    `keep` get a place in the palette first.
    """
    sample = Image.new("RGB", (frames[0].width, frames[0].height * 4))
    for i, f in enumerate(frames[:: max(1, len(frames) // 4)][:4]):
        sample.paste(f, (0, i * f.height))
    keep = list(dict.fromkeys(keep))[:128]
    if keep:
        rest = 255 - len(keep)
        chosen = sample.quantize(colors=rest, method=Image.Quantize.MEDIANCUT).getpalette()[: 3 * rest]
        palette = Image.new("P", (1, 1))
        palette.putpalette([c for colour in keep for c in colour] + chosen + [0, 0, 0] * (256 - 255))
    else:
        palette = sample.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    images = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=round(1000 / FPS), loop=0, disposal=1, optimize=False)


def build_screen(frames: dict[str, list[Image.Image]]) -> None:
    """Three cards stacked like on the real screen. Each runs a second behind the one above,
    so their shines sweep down the screen one after another."""
    names = [b for b in SCREEN if b in frames]
    if not names:
        return
    first = frames[names[0]][0]
    w, h = round(first.width * SCREEN_SCALE), round(first.height * SCREEN_SCALE)
    count, offset = len(frames[names[0]]), round(FPS)              # one second between the cards
    small = {b: [f.resize((w, h), Image.LANCZOS) for f in frames[b]] for b in names}
    screen = []
    for i in range(count):
        page = Image.new("RGB", (w, h * len(names)), BACKGROUND)
        for row, b in enumerate(names):
            page.paste(small[b][(i + row * offset) % count], (0, row * h))
        screen.append(page)
    keep = []
    for b in names:
        body = Image.open(ROOT / "brawlers" / "shaded" / f"{b}.png")
        keep += distinct_colours(body.crop(body.getbbox()))
    save_gif(screen, EXAMPLES / "cards_screen.gif", keep)


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--gifs", type=Path, help="also save every card as its own moving preview in this folder")
    args = parser.parse_args()

    sheets = sorted(SRC.glob("*.jpg"))
    if not sheets:
        raise SystemExit("no sheets in cards/brawlers/source/")
    meta = {"layout": LAYOUT, "motion": MOTION, "font": "fonts/LilitaOne-Regular.ttf", "brawlers": {}}
    screen = {}
    for sheet in sheets:
        names = sheet.stem.split("-")
        for brawler, (card_part, big, small) in zip(names, cut_sheet(sheet, len(names))):
            card = make_card(card_part)
            folder = OUT / brawler
            (folder / "particles").mkdir(parents=True, exist_ok=True)
            for old in (folder / "particles").glob("*.png"):
                old.unlink()
            card.save(folder / "card.png", optimize=True)
            big.save(folder / "object.png", optimize=True)
            for i, piece in enumerate(small, start=1):
                piece.save(folder / "particles" / f"{i}.png", optimize=True)
            meta["brawlers"][brawler] = {
                "name": NAMES[brawler],
                "skill": SKILLS.get(brawler, ""),
                "card": f"{brawler}/card.png",
                "object": f"{brawler}/object.png",
                "object_size": OBJECT_SIZE.get(brawler, LAYOUT["object"]["height"]),
                "particles": [f"{brawler}/particles/{i}.png" for i in range(1, len(small) + 1)],
                "particle_seed": SEEDS.get(brawler, 7),
            }
            frames = build_preview(brawler, card, big, small, args.gifs)
            if brawler in SCREEN:
                screen[brawler] = frames
            print(f"{brawler:8s} card {card.size}, object {big.size}, {len(small)} particles")
    order = [b for b in NAMES if b in meta["brawlers"]]
    meta["brawlers"] = {b: meta["brawlers"][b] for b in order}
    (OUT / "cards.json").write_text(json.dumps(meta, indent=2) + "\n")
    build_screen(screen)


if __name__ == "__main__":
    main()
