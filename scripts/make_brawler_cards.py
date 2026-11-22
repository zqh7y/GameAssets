"""Build the brawler cards for the "choose a card" screen, with a moving preview.

The cards are wide and short, and three of them stack on top of each other on the screen.
Every brawler has its own card: a plain card in its colour, one big 3D object that floats on
it (Peep's feather...), and about 100 small ones that drift across it, as if a breeze were
blowing through. The brawler stands on the left and pops out over the top of the card; its
name and skill are written next to it.

Source: cards/brawlers/source/<brawler>.jpg, a sheet on a green screen with the empty card at
        the top, one big 3D object below it on the left, and 6 small ones on the right.

Output, per brawler, in cards/brawlers/<brawler>/:
  card.png           the card, 960 x 300 px: shorter than on the sheet, with crisp corners
  object.png         the big 3D object
  particles/<n>.png  the small ones, n = 1 to 6, biggest first
plus cards/brawlers/cards.json (where everything goes and how it moves, for the game) and a
moving preview in examples/card_<brawler>.gif.

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/make_brawler_cards.py
"""

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
}

# ---------------------------------------------------------------- layout and motion
# Everything below is in pixels of the card (960 x 300), measured from its top left corner.
# The same numbers go into cards.json for the game.

LAYOUT = {
    "card": {"width": 960, "height": 300, "corner_radius": 42},
    # The brawler stands on the left, its feet near the bottom, popping out over the top.
    "brawler": {"feet": [150, 282], "height": 318},
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

def cut_sheet(path: Path) -> tuple[np.ndarray, Image.Image, list[Image.Image]]:
    """The card (RGBA array, cropped), the big object, and the small objects, biggest first."""
    rgba = key_green(path)
    solid = rgba[..., 3] >= 128
    labels, n = label(dilate(solid, 2))
    parts = []
    for i in range(1, n + 1):
        region = labels == i
        ys, xs = np.nonzero(region & solid)
        if len(xs) > 300:
            parts.append((ys.min(), len(xs), region))
    if len(parts) != 8:
        raise SystemExit(f"{path.name}: expected 8 pieces (card, big object, 6 small ones), found {len(parts)}")
    parts.sort(key=lambda p: p[0])                       # the card is the top piece
    card = np.asarray(crop_to_alpha(rgba, dilate(parts[0][2], 2)))
    rest = sorted(parts[1:], key=lambda p: -p[1])         # then the biggest piece is the big object
    big = crop_to_alpha(rgba, dilate(rest[0][2], 2))
    small = [crop_to_alpha(rgba, dilate(p[2], 2)) for p in rest[1:]]
    return card, big, small


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
    light_card = sum(card_colour) / 3 > 150
    ink = (110, 58, 18, 255) if light_card else (255, 255, 255, 255)
    d = ImageDraw.Draw(layer)
    for i, line in enumerate(lines[:2]):
        d.text((ox + spec["left"] * SS, oy + (spec["top"] + i * spec["line_height"]) * SS), line, font=font, fill=ink)
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


def build_preview(brawler: str, card: Image.Image, big: Image.Image, small: list[Image.Image]) -> None:
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
    particles = make_particles(random.Random(7), len(small))

    spec_b, move_b = LAYOUT["brawler"], MOTION["brawler"]
    body = Image.open(ROOT / "brawlers" / "shaded" / f"{brawler}.png").convert("RGBA")
    body = body.crop(body.getbbox())
    feet = (ox + spec_b["feet"][0] * SS, oy + spec_b["feet"][1] * SS)
    spec_o, move_o = LAYOUT["object"], MOTION["object"]

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
        sy = oy + (spec_o["center"][1] + spec_o["height"] * 0.40) * SS
        frame.alpha_composite(clipped(soft_ellipse(size, (cx - 40 * SS - sw / 2, sy - sh / 2, cx - 40 * SS + sw / 2, sy + sh / 2),
                                                   shade + (int(70 + 40 * (1 - lift)),), 12 * SS)))
        stamp(frame, turned(big, spec_o["height"] * SS, 1.0, rock), cx, cy)

        # The brawler: breathing and rocking on its feet, with its shadow on the card.
        breathe = 1 + move_b["breathe"] * math.sin(2 * math.pi * ms / move_b["breathe_ms"])
        rock = move_b["rock_deg"] * math.sin(2 * math.pi * ms / move_b["rock_ms"])
        sw = spec_b["height"] * 0.62 * SS / math.sqrt(breathe)
        frame.alpha_composite(clipped(soft_ellipse(size, (feet[0] - sw / 2, feet[1] - 12 * SS, feet[0] + sw / 2, feet[1] + 14 * SS),
                                                   shade + (120,), 6 * SS)))
        k = spec_b["height"] * SS / body.height
        stood = premultiplied(body).resize((round(body.width * k / math.sqrt(breathe)), round(body.height * k * breathe)), Image.LANCZOS)
        pad = Image.new("RGBa", (stood.width * 2, stood.height * 2), (0, 0, 0, 0))
        pad.paste(stood, (stood.width // 2, 0))                              # feet in the middle of the pad
        stood = pad.rotate(-rock, resample=Image.BICUBIC, center=(stood.width, stood.height)).convert("RGBA")
        stamp(frame, stood, feet[0], feet[1])

        frame.alpha_composite(words)
        frames.append(frame.resize((size[0] // SS, size[1] // SS), Image.LANCZOS).convert("RGB"))

    # One shared palette for every frame, so colours do not flicker from frame to frame.
    sample = Image.new("RGB", (frames[0].width, frames[0].height * 4))
    for i, f in enumerate(frames[:: max(1, len(frames) // 4)][:4]):
        sample.paste(f, (0, i * f.height))
    palette = sample.quantize(colors=255, method=Image.MEDIANCUT)
    images = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    EXAMPLES.mkdir(exist_ok=True)
    images[0].save(EXAMPLES / f"card_{brawler}.gif", save_all=True, append_images=images[1:],
                   duration=round(1000 / FPS), loop=0, disposal=1, optimize=False)
    frames[0].save(EXAMPLES / f"card_{brawler}.png", optimize=True)


# ---------------------------------------------------------------- main

def main() -> None:
    sheets = sorted(SRC.glob("*.jpg"))
    if not sheets:
        raise SystemExit("no sheets in cards/brawlers/source/")
    meta = {"layout": LAYOUT, "motion": MOTION, "font": "fonts/LilitaOne-Regular.ttf", "brawlers": {}}
    for sheet in sheets:
        brawler = sheet.stem
        card_part, big, small = cut_sheet(sheet)
        card = make_card(card_part)
        folder = OUT / brawler
        (folder / "particles").mkdir(parents=True, exist_ok=True)
        card.save(folder / "card.png", optimize=True)
        big.save(folder / "object.png", optimize=True)
        for i, s in enumerate(small, start=1):
            s.save(folder / "particles" / f"{i}.png", optimize=True)
        meta["brawlers"][brawler] = {
            "name": NAMES[brawler],
            "skill": SKILLS.get(brawler, ""),
            "card": f"{brawler}/card.png",
            "object": f"{brawler}/object.png",
            "particles": [f"{brawler}/particles/{i}.png" for i in range(1, len(small) + 1)],
        }
        build_preview(brawler, card, big, small)
        print(f"{brawler:8s} card {card.size}, object {big.size}, {len(small)} particles")
    (OUT / "cards.json").write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    main()
