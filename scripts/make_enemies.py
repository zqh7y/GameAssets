"""Build the enemies the same way as the brawlers: a still sprite, a walk and an attack with
smooth motion, and the effect of the attack.

Sources, in enemies/source/, all on a magenta screen:
  <enemy>.png         the enemy on its own
  <enemy>_sheet.png   8 poses in 2 rows of 4: the walk on top, the attack below
  <enemy>_slash.png   the effect of its attack: 4 steps in a row, from left to right

Output, in enemies/<enemy>/, everything facing left, toward the brawlers:
  still.png                                the still sprite, shaded like the brawlers
  walk.png, attack.png                     4 frames side by side, shaded the same way
  walk_mirrored.png, attack_mirrored.png   the same, facing right
  attack_effect.png                        the effect of the attack, in 4 steps
plus enemies/enemies.json (the same fields as animations/animations.json) and a moving preview
in examples/enemy_<enemy>.gif.

The sheet is drawn facing right, like the brawlers' sheets, so it is lined up and timed like
theirs (see extract_animations.py and brawler_motion.py) and only turned around at the end.

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/make_enemies.py
"""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import animation_effects
import brawler_motion as motion
import trace_shapes
from extract_animations import ROWS, FRAMES, PAD, anchor_of, area, as_json, overlap_shift, posed, resized, scaled
from extract_brawlers import crop_to_alpha, dilate, key_magenta, label
from shade_brawlers import shade_sprite

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "enemies" / "source"
OUT = ROOT / "enemies"
EXAMPLES = ROOT / "examples"

ENEMIES = {
    "beetle": {
        "name": "Beetle Knight",
        "scale": 0.8,          # its size next to the brawlers, as in brawlers/sizes.json (the Mage is 1)
        "height": 260,         # px of its still sprite, like the brawlers' flat sprites
        # The poses of the attack, from the sheet's bottom row. Gemini never drew the strike
        # itself (the sword stays pulled back), so the strike is made from the ready pose: its
        # sword and the hand holding it (everything left of `cut_x`) are turned by `turn`
        # degrees around the hand (`pivot`), so the sword swings forward across the body.
        # Both are in px of the pose on the sheet, from its top left corner.
        "attack": [0, 1, "strike", 3],
        "strike": {"pose": 0, "cut_x": 38, "pivot": (25, 122), "turn": -128},
        # The slash: where its middle goes, as parts of the frame's width and height on the
        # striking pose (facing right, as drawn), its longest side at its biggest (px of the
        # frame), and how long before the hit lands it starts.
        "slash": {"grows": "out", "point": (0.80, 0.50), "size": 230, "lead_ms": 30},
    },
}

SLASH_MS = [40, 50, 100, 150]      # how long each step of the slash shows, like the brawlers' attack effects


# ---------------------------------------------------------------- cutting

def cut_poses(sheet: Path) -> list[list[np.ndarray]]:
    """The 8 poses of a sheet, cropped tight, as [row][frame] RGBA arrays."""
    rgba = key_magenta(sheet, drop_purple=False)
    solid = rgba[..., 3] >= 128
    labels, n = label(dilate(solid, 4))          # a little growth joins loose bits to their pose
    found = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero((labels == i) & solid)
        if len(xs) > 3000:
            found.append((ys.mean(), xs.mean(), i))
    if len(found) != len(ROWS) * FRAMES:
        raise SystemExit(f"{sheet.name}: expected {len(ROWS) * FRAMES} poses, found {len(found)}")
    found.sort()
    rows = [sorted(found[r * FRAMES:(r + 1) * FRAMES], key=lambda f: f[1]) for r in range(len(ROWS))]
    poses = []
    for row in rows:
        out = []
        for _, _, i in row:
            region = dilate(labels == i, 1)
            ys, xs = np.nonzero(region & solid)
            part = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()
            part[..., 3] = np.where(region[ys.min():ys.max() + 1, xs.min():xs.max() + 1], part[..., 3], 0)
            out.append(part)
        poses.append(out)
    return poses


def strike(pose: np.ndarray, spec: dict) -> np.ndarray:
    """The ready pose with its sword swung forward: the part left of `cut_x` turned around the hand."""
    h, w = pose.shape[:2]
    m = max(h, w) // 2                                     # room for the sword to swing out
    left = np.arange(w)[None, :] < spec["cut_x"]
    body, sword = pose.copy(), pose.copy()
    body[..., 3] = np.where(left, 0, body[..., 3])
    sword[..., 3] = np.where(left, sword[..., 3], 0)
    canvas = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    canvas.alpha_composite(Image.fromarray(body, "RGBA"), (m, m))
    turned = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    turned.alpha_composite(Image.fromarray(sword, "RGBA"), (m, m))
    px, py = spec["pivot"]
    turned = turned.convert("RGBa").rotate(spec["turn"], resample=Image.BICUBIC, center=(px + m, py + m))
    canvas.alpha_composite(turned.convert("RGBA"))       # the sword in front of the body
    return np.asarray(canvas.crop(canvas.getbbox()))


def cut_slash(sheet: Path) -> list[np.ndarray]:
    """The steps of a slash sheet, traced (see trace_shapes.py): one per quarter of the sheet's width."""
    rgb = np.asarray(Image.open(sheet).convert("RGB")).astype(np.float32)
    h, w = rgb.shape[:2]
    bg = np.median(np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]), axis=0)
    fg = np.sqrt(((rgb - bg) ** 2).sum(axis=2)) > trace_shapes.FG_DISTANCE
    rgba = trace_shapes.trace(rgb, fg, bg)
    labels, n = label(rgba[..., 3] > 127)
    steps = [np.zeros(labels.shape, dtype=bool) for _ in range(4)]
    for i in range(1, n + 1):
        shape = labels == i
        xs = np.nonzero(shape)[1]
        steps[min(int(xs.mean() * 4 / labels.shape[1]), 3)] |= shape
    out = []
    for step in steps:
        part = rgba.copy()
        part[..., 3] = np.where(dilate(step, 3), part[..., 3], 0)
        out.append(part)
    return out


# ---------------------------------------------------------------- one enemy

def flipped(frame: Image.Image) -> Image.Image:
    return frame.transpose(Image.FLIP_LEFT_RIGHT)


def shade(frame: Image.Image) -> Image.Image:
    return resized(shade_sprite(frame), frame.size)          # shaded at 2x for smoothness


def strip(frames: list[Image.Image]) -> Image.Image:
    out = Image.new("RGBA", (frames[0].width * len(frames), frames[0].height), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        out.alpha_composite(f, (i * f.width, 0))
    return out


def build(enemy: str) -> dict:
    spec = ENEMIES[enemy]
    folder = OUT / enemy
    folder.mkdir(parents=True, exist_ok=True)

    # --- the still sprite, at the brawlers' size, facing left
    still = Image.fromarray(key_magenta(SRC / f"{enemy}.png", drop_purple=False), "RGBA")
    still = crop_to_alpha(np.asarray(still))
    k = spec["height"] / still.height
    still = resized(still, (round(still.width * k), round(still.height * k)))
    shade(flipped(still)).save(folder / "still.png", optimize=True)

    # --- the poses
    sheet = cut_poses(SRC / f"{enemy}_sheet.png")
    walk = sheet[0]
    attack = [strike(sheet[1][spec["strike"]["pose"]], spec["strike"]) if p == "strike" else sheet[1][p]
              for p in spec["attack"]]
    poses = [walk, attack]

    # one size: walk poses made equal unless they really differ in shape, attack poses as
    # drawn, and the whole sheet scaled to the still sprite
    areas = [area(p) for p in walk]
    factors = [float(np.sqrt(np.median(areas) / a)) for a in areas]
    if max(abs(f - 1) for f in factors) > 0.06:
        factors = [1.0] * FRAMES
    factors = [factors, [1.0] * FRAMES]
    to_still = spec["height"] / float(np.median([p.shape[0] * f for p, f in zip(walk, factors[0])]))
    poses = [[scaled(p, f * to_still) for p, f in zip(row, fs)] for row, fs in zip(poses, factors)]

    # line up: walk poses by the body, attack poses matched to the last one (the resting pose)
    placed = [[[p, *anchor_of(p)] for p in row] for row in poses]
    rest = placed[1][-1]
    for frame in placed[1][:-1]:
        frame[1] -= overlap_shift(frame, rest)
    left = max(ax for row in placed for p, ax, g in row)
    right = max(p.shape[1] - ax for row in placed for p, ax, g in row)
    top = max(g + 1 for row in placed for p, ax, g in row)
    half = int(np.ceil(max(left, right))) + PAD
    cell_w, cell_h = 2 * half, top + 2 * PAD
    anchor = (half, cell_h - PAD)                            # centre bottom of every cell

    def cell(pose: np.ndarray, ax: float, ground: int) -> Image.Image:
        img = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
        img.alpha_composite(Image.fromarray(pose, "RGBA"), (round(anchor[0] - ax), anchor[1] - 1 - ground))
        return img

    cells = {name: [cell(*f) for f in row] for name, row in zip(ROWS, placed)}
    frames = {}
    for name, row in cells.items():
        frames[name] = [shade(flipped(f)) for f in row]                  # facing left: turned, then shaded
        strip(frames[name]).save(folder / f"{name}.png", optimize=True)
        strip([shade(f) for f in row]).save(folder / f"{name}_mirrored.png", optimize=True)

    # --- timing and motion, worked out facing right and then turned around
    animations = motion.animations(enemy, cell_h)
    facing_right = {"frame_width": cell_w, "frame_height": cell_h, "anchor": list(anchor),
                    "animations": animations}
    for anim in animations.values():
        anim["motion"]["x"] = [-v + 0.0 for v in anim["motion"]["x"]]
        anim["motion"]["rotate"] = [-v + 0.0 for v in anim["motion"]["rotate"]]

    # --- the slash
    s = spec["slash"]
    steps = cut_slash(SRC / f"{enemy}_slash.png")
    point = (s["point"][0] * cell_w, s["point"][1] * cell_h)
    right_motion = motion.animations(enemy, cell_h)          # untouched, facing right
    facing_right["animations"] = right_motion
    at = animation_effects.placed(point, facing_right)
    effect_cells, effect_anchor = animation_effects.fit({"grows": s["grows"], "size": s["size"]}, steps)
    effect_cells = [flipped(c) for c in effect_cells]
    effect_anchor = (effect_cells[0].width - effect_anchor[0], effect_anchor[1])
    strip(effect_cells).save(folder / "attack_effect.png", optimize=True)
    attack_anim = animations["attack"]
    attack_anim["effect"] = {
        "file": "attack_effect.png",
        "frames": len(effect_cells),
        "frame_width": effect_cells[0].width,
        "frame_height": effect_cells[0].height,
        "anchor": list(effect_anchor),
        "at": [-at[0] + 0.0, at[1]],
        "draw": "in_front",
        "starts_ms": [attack_anim["hit_ms"] - s["lead_ms"]],
        "duration_ms": sum(SLASH_MS),
        "frame_ms": list(SLASH_MS),
        "motion": motion.effect(),
    }

    print(f"{enemy:8s} frame {cell_w} x {cell_h}  anchor {anchor}  slash {effect_cells[0].size} at {attack_anim['effect']['at']}")
    meta = {
        "name": spec["name"],
        "scale": spec["scale"],
        "still": "still.png",
        "frame_width": cell_w,
        "frame_height": cell_h,
        "anchor": list(anchor),
        "animations": {name: {"file": f"{name}.png", "mirrored_file": f"{name}_mirrored.png", "frames": FRAMES, **anim}
                       for name, anim in animations.items()},
    }
    return {"meta": meta, "frames": frames, "effect": effect_cells}


# ---------------------------------------------------------------- preview

def preview(enemy: str, built: dict) -> None:
    """A GIF of the enemy on the forest path: walking toward the brawlers (left), then attacking.

    The ground slides under it while it walks, as if it were coming at the brawlers, and stops
    while it strikes. 25 pictures a second.
    """
    meta, frames, effect = built["meta"], built["frames"], built["effect"]
    k = 0.52 * meta["scale"]                                 # the size of the brawlers in the map previews
    ground_img = Image.open(ROOT / "maps" / "forest" / "ground.png").convert("RGB")
    box = (2000, 400, 2520, 720)                             # a stretch of open grass
    ground = ground_img.crop((box[0] - 400, box[1], box[2] + 400, box[3]))
    view = (box[2] - box[0], box[3] - box[1])
    cw, ch = meta["frame_width"], meta["frame_height"]
    small = lambda img: resized(img, (max(1, round(img.width * k)), max(1, round(img.height * k))))
    look = {name: [small(f) for f in fs] for name, fs in frames.items()}
    slash = [small(c) for c in effect]
    anchor = (meta["anchor"][0] * k, meta["anchor"][1] * k)
    e = meta["animations"]["attack"]["effect"]
    e_anchor = (e["anchor"][0] * k, e["anchor"][1] * k)
    side = round(max(cw, ch) * k * 1.8)
    canvas, at = (side, side), (side / 2, side * 0.78)
    walk, attack = meta["animations"]["walk"], meta["animations"]["attack"]
    walk_cycles, rest_ms = 3, 360
    total = walk_cycles * walk["duration_ms"] + attack["duration_ms"] + rest_ms
    spot = (view[0] * 0.55, view[1] * 0.68)                  # where it stands, on the view
    speed = 0.11                                             # px of the view a ms that the ground slides

    pictures = []
    for ms in range(0, total, 40):
        walking = ms < walk_cycles * walk["duration_ms"]
        slid = speed * min(ms, walk_cycles * walk["duration_ms"])
        img = ground.crop((round(400 - slid), 0, round(400 - slid) + view[0], view[1])).convert("RGBA")
        if walking:
            anim, t = walk, ms
            frame = look["walk"][motion.frame_at(walk, t)]
        else:
            anim, t = attack, ms - walk_cycles * walk["duration_ms"]
            frame = look["attack"][motion.frame_at(attack, min(t, attack["duration_ms"] - 1))]
        x, y, rotate, wide, tall = motion.motion_at(anim, min(t, anim["duration_ms"]))
        x, y = x * k, y * k
        shadow = Image.new("RGBA", img.size, (24, 44, 8, 0))
        w = frame.getbbox()[2] - frame.getbbox()[0]
        w *= 0.72 * wide * (1 + 3 * y / (ch * k))
        ImageDraw.Draw(shadow).ellipse((spot[0] + x - w / 2, spot[1] - w * 0.13, spot[0] + x + w / 2, spot[1] + w * 0.09),
                                       fill=(24, 44, 8, 107))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)))
        sprite = posed(frame, anchor, (x, y, rotate, wide, tall), canvas, at)
        img.alpha_composite(sprite, (round(spot[0] - at[0]), round(spot[1] - at[1])))
        if not walking:
            age = t - e["starts_ms"][0]
            if 0 <= age < e["duration_ms"]:
                grow, opacity = motion.motion_at(e, age)
                pic = posed(slash[motion.frame_at(e, age)], e_anchor, (0.0, 0.0, 0.0, grow, grow), canvas, at)
                pic.putalpha(pic.getchannel("A").point(lambda v: round(v * opacity)))
                img.alpha_composite(pic, (round(spot[0] + e["at"][0] * k - at[0]), round(spot[1] + e["at"][1] * k - at[1])))
        pictures.append(img.convert("RGB"))
    # One palette for the whole GIF. The grass fills most of every picture, so a palette made
    # from the pictures alone has too few blues for the beetle and turns it green: the
    # enemy's own frames and effect are added to the sample many times over.
    sprites = [f.crop(f.getbbox()) for f in look["walk"] + look["attack"] + slash]
    sample_w = max(p.width for p in pictures)
    sample = Image.new("RGB", (sample_w, view[1] * 3 + sum(sp.height for sp in sprites) * 8), (150, 175, 80))
    y = 0
    for p in pictures[::len(pictures) // 3][:3]:
        sample.paste(p, (0, y))
        y += p.height
    for _ in range(8):
        for sp in sprites:
            sample.paste(sp.convert("RGB"), (0, y), sp)
            y += sp.height
    palette = sample.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    gif = [p.quantize(palette=palette, dither=Image.Dither.NONE) for p in pictures]
    EXAMPLES.mkdir(exist_ok=True)
    gif[0].save(EXAMPLES / f"enemy_{enemy}.gif", save_all=True, append_images=gif[1:], duration=40, loop=0,
                disposal=1, optimize=False)
    print(f"preview  {view[0]} x {view[1]}, {len(gif)} pictures")


def main() -> None:
    built = {enemy: build(enemy) for enemy in ENEMIES}
    (OUT / "enemies.json").write_text(as_json({e: b["meta"] for e, b in built.items()}))
    for enemy, b in built.items():
        preview(enemy, b)


if __name__ == "__main__":
    main()
