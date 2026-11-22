"""Turn the brawlers' animation sheets into game-ready sprite strips.

Source (in animations/source/):
  - <brawler>.jpg : 8 poses on a green screen, in 2 rows of 4.
                    Row 1 = walk cycle, row 2 = attack.

Output, per brawler, in animations/<brawler>/:
  - walk.png, attack.png                    4 frames side by side, shaded like the still sprites
  - walk_mirrored.png, attack_mirrored.png  the same, facing the other way
plus animations/animations.json (frame size, anchor point, timing and smooth motion for
every brawler) and a moving preview of all brawlers in examples/animations.gif.

What happens to a sheet:
  1. The 8 poses are cut out of the green screen. Shadows drawn under the feet are removed.
     A TNT pose that was drawn without its letters gets them back from the pose next to it.
  2. They are brought to one size: the walk poses are made equal to each other, the attack
     poses keep the sizes they were drawn at (a pose can be bigger on purpose, like the TNT
     puffing up), and the whole sheet is scaled to the size of the brawler's still sprite.
  3. They are lined up, so nothing jitters when the frames are played:
       - walk poses by the body, with the feet on the ground line (the legs move under it)
       - attack poses by matching each one to the resting pose where the two look the same,
         so the body stays put and only the parts that move, move
     Every frame of a brawler gets the same cell size, with the anchor point (centre of the
     body, on the ground) in the same place.
  4. Each frame gets the same 3D shading as the still sprites. Mirrored frames are mirrored
     first and shaded afterwards, so the light stays top-left.

Four drawn poses are too few to look smooth on their own, so every animation also gets a
smooth motion to play on top of them (see brawler_motion.py). It is saved in animations.json
and shown in the preview.

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/extract_animations.py
"""

import json
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import brawler_motion as motion
from extract_brawlers import dilate, key_green, label
from shade_brawlers import LETTERED, letter_labels, mirror_sprite, shade_sprite

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "animations" / "source"
OUT = ROOT / "animations"
EXAMPLES = ROOT / "examples"
NAMES = {k: v["name"] for k, v in json.loads((ROOT / "brawlers" / "sizes.json").read_text()).items()}

ROWS = ["walk", "attack"]      # the rows of a sheet, top to bottom
FRAMES = 4                     # poses per row
PAD = 6                        # transparent pixels around the poses in a cell
ORDER = ["chick", "tnt", "dragon", "wizard", "ghost", "acorn", "octopus"]   # order in the preview

# Brawlers that float instead of walking: their poses keep the heights they were drawn at.
FLOATING = {"ghost"}


# ---------------------------------------------------------------- cutting

def cut_poses(sheet: Path) -> tuple[list[list[np.ndarray]], list[list[int]]]:
    """The poses of a sheet as RGBA arrays, cropped tight, and the sheet row each one ends on.

    Both are indexed [row][frame].
    """
    rgba = key_green(sheet, remove_shadows=True)
    solid = rgba[..., 3] >= 128
    labels, n = label(dilate(solid, 4))          # a little growth joins loose bits to their pose
    found = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero((labels == i) & solid)
        if len(xs) > 3000:
            found.append((ys.mean(), xs.mean(), i))
    if len(found) != len(ROWS) * FRAMES:
        raise SystemExit(f"{sheet.name}: expected {len(ROWS) * FRAMES} poses, found {len(found)}")
    found.sort()                                  # top to bottom, then left to right in each row
    rows = [sorted(found[r * FRAMES:(r + 1) * FRAMES], key=lambda f: f[1]) for r in range(len(ROWS))]

    poses, bottoms = [], []
    for row in rows:
        out, ends = [], []
        for _, _, i in row:
            region = dilate(labels == i, 1)
            ys, xs = np.nonzero(region & (rgba[..., 3] > 8))
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            part = rgba[y0:y1, x0:x1].copy()
            part[..., 3] = np.where(region[y0:y1, x0:x1], part[..., 3], 0)
            out.append(part)
            ends.append(int(np.nonzero((labels == i) & solid)[0].max()))
        poses.append(out)
        bottoms.append(ends)
    return poses, bottoms


def area(pose: np.ndarray) -> float:
    return float((pose[..., 3] >= 128).sum())


def resized(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize on premultiplied colours, so the edges do not pick up a halo."""
    return img.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")


def scaled(pose: np.ndarray, k: float) -> np.ndarray:
    size = (max(1, round(pose.shape[1] * k)), max(1, round(pose.shape[0] * k)))
    return np.asarray(resized(Image.fromarray(pose, "RGBA"), size))


# ---------------------------------------------------------------- repairs

def face_marks(pose: np.ndarray) -> list[tuple[float, float, np.ndarray]]:
    """Small dark marks drawn on a pose's body (eyes and the like): (x, y, mask), lowest first."""
    a = pose.astype(np.int32)
    solid = a[..., 3] > 200
    labels, n = label((a[..., :3].max(axis=-1) < 90) & solid)
    out = []
    for i in range(1, n + 1):
        mask = labels == i
        ys, xs = np.nonzero(mask)
        small = len(xs) >= 25 and np.ptp(xs) < 0.3 * pose.shape[1] and np.ptp(ys) < 0.3 * pose.shape[0]
        if small and solid[dilate(mask, 3)].all():            # on the body, not at its edge
            out.append((float(xs.mean()), float(ys.mean()), mask))
    return sorted(out, key=lambda m: -m[1])


def restore_letters(row: list[np.ndarray], brawler: str, row_name: str) -> list[np.ndarray]:
    """Give a pose that lost its letters the letters of the pose next to it.

    The letters go where they sit on that pose, measured from the eyes, and anything else
    drawn in that spot is removed first. On the TNT sheet, one attack pose was drawn with a
    second pair of squinting eyes where "TNT" should be, so the box seemed to have four eyes.
    """
    lettered = [len(letter_labels(p)[1]) == 3 for p in row]
    out = list(row)
    for i, pose in enumerate(row):
        donors = sorted((j for j in range(len(row)) if lettered[j]), key=lambda j: (abs(j - i), -j))
        if lettered[i] or not donors:
            continue
        donor = row[donors[0]]                                 # the nearest pose, the next one first
        marks, donor_eyes = face_marks(pose), face_marks(donor)[:2]
        eyes, others = marks[:2], marks[2:]                    # the eyes are the lowest two marks
        if len(eyes) < 2 or len(donor_eyes) < 2:
            continue

        def pair(two: list) -> tuple[np.ndarray, float]:
            """The middle of two eyes, and the distance between them."""
            (x1, y1, _), (x2, y2, _) = two
            return np.array([(x1 + x2) / 2, (y1 + y2) / 2]), float(np.hypot(x1 - x2, y1 - y2))

        (to, gap), (frm, donor_gap) = pair(eyes), pair(donor_eyes)
        k = gap / donor_gap

        # The letters of the donor, with a soft edge, at this pose's size.
        labels, ids = letter_labels(donor)
        letters = np.isin(labels, ids)
        ys, xs = np.nonzero(letters)
        x0, x1, y0, y1 = xs.min() - 4, xs.max() + 5, ys.min() - 4, ys.max() + 5
        patch = Image.fromarray(donor[y0:y1, x0:x1], "RGBA")
        matte = Image.fromarray((dilate(letters, 1)[y0:y1, x0:x1] * 255).astype(np.uint8))
        patch.putalpha(matte.filter(ImageFilter.GaussianBlur(0.7)))
        patch = resized(patch, (round(patch.width * k), round(patch.height * k)))
        px, py = (int(v) for v in (to + k * (np.array([x0, y0]) - frm)).round())

        # Paint over whatever was drawn where the letters go, then put the letters there.
        a = pose.astype(np.int32)
        dark = a[..., :3].max(axis=-1) < 90
        fixed = pose.copy()
        for mx, my, mask in others:
            if px <= mx < px + patch.width and py <= my < py + patch.height:
                cover = dilate(mask, 3)
                ring = dilate(cover, 4) & ~cover & ~dilate(dark, 1) & (a[..., 3] > 200)
                fixed[cover, :3] = np.median(a[ring][:, :3], axis=0)
        img = Image.fromarray(fixed, "RGBA")
        img.alpha_composite(patch, (px, py))
        out[i] = np.asarray(img)
        print(f"{brawler:8s} {row_name} frame {i + 1} had no letters: copied from frame {donors[0] + 1}")
    return out


# ---------------------------------------------------------------- lining up

def anchor_of(pose: np.ndarray) -> tuple[float, int]:
    """(x, ground y) of a pose: the middle of its body, and its lowest row."""
    ys, xs = np.nonzero(pose[..., 3] >= 128)
    top, ground = ys.min(), ys.max()
    body = ys <= top + 0.67 * (ground - top + 1)      # without the legs, which swing under it
    return float(xs[body].mean()), int(ground)


def overlap_shift(pose: list, ref: list) -> int:
    """How far `pose` has to move to the right to overlap `ref` best.

    Each is [rgba, anchor x, ground y]; they start with their anchors on top of each other.
    Two pixels overlap when both are solid and nearly the same colour, so the parts that
    stay the same from frame to frame (the body) decide where a pose goes, and the parts
    that move (a raised staff, a whipping tentacle) do not drag it along.
    """
    (a, ax, ag), (b, bx, bg) = pose, ref
    reach = int(0.35 * b.shape[1])
    ground = max(ag, bg)
    h = ground + 1 + max(a.shape[0] - 1 - ag, b.shape[0] - 1 - bg, 0)
    w = 2 * (max(a.shape[1], b.shape[1]) + reach)

    def canvas(img: np.ndarray, x: float, g: int) -> np.ndarray:
        out = np.zeros((h, w, 4), dtype=np.int16)
        top, left = ground - g, w // 2 - round(x)
        out[top:top + img.shape[0], left:left + img.shape[1]] = img
        return out

    def score(big_a: np.ndarray, big_b: np.ndarray, dx: int) -> int:
        width = big_a.shape[1]
        pa = big_a[:, :width - dx] if dx >= 0 else big_a[:, -dx:]
        pb = big_b[:, dx:] if dx >= 0 else big_b[:, :width + dx]
        same = np.abs(pa[..., :3] - pb[..., :3]).max(axis=-1) < 45
        return int((same & (pa[..., 3] >= 128) & (pb[..., 3] >= 128)).sum())

    def best(big_a: np.ndarray, big_b: np.ndarray, shifts: list[int]) -> int:
        pick, top_score = shifts[0], -1
        for dx in sorted(shifts, key=abs):                    # on a near tie, the smaller shift
            s = score(big_a, big_b, dx)
            if s > top_score * 1.002:
                pick, top_score = dx, s
        return pick

    full_a, full_b = canvas(a, ax, ag), canvas(b, bx, bg)
    coarse = 2 * best(full_a[::2, ::2], full_b[::2, ::2], list(range(-reach // 2, reach // 2 + 1)))
    return best(full_a, full_b, list(range(coarse - 2, coarse + 3)))


# ---------------------------------------------------------------- one brawler

def build(brawler: str) -> dict:
    poses, bottoms = cut_poses(SRC / f"{brawler}.jpg")
    floating = brawler in FLOATING

    # --- one size
    # Walk poses should all be the same size. Small differences are evened out; big ones mean
    # the poses really differ in shape (a ghost turning around), so those are left alone.
    areas = [area(p) for p in poses[0]]
    factors = [float(np.sqrt(np.median(areas) / a)) for a in areas]
    if max(abs(f - 1) for f in factors) > 0.06:
        factors = [1.0] * FRAMES
    # Attack poses keep their drawn sizes: one can be bigger on purpose (the TNT puffing up).
    factors = [factors, [1.0] * FRAMES]
    still = Image.open(ROOT / "brawlers" / f"{brawler}.png")
    still_h = still.getbbox()[3] - still.getbbox()[1]
    to_still = still_h / float(np.median([p.shape[0] * f for p, f in zip(poses[0], factors[0])]))
    poses = [[scaled(p, f * to_still) for p, f in zip(row, fs)] for row, fs in zip(poses, factors)]
    if brawler in LETTERED:
        poses = [restore_letters(row, brawler, name) for row, name in zip(poses, ROWS)]

    # --- line up
    placed = []      # [row][frame] = [pose, anchor x, ground y] in the pose's own pixels
    for r, row in enumerate(poses):
        out = []
        for i, p in enumerate(row):
            ax, ground = anchor_of(p)
            if floating:
                # Nothing touches the ground, so the poses keep the heights they were drawn
                # at: the ground is the lowest point of the row, wherever each pose hovers.
                ground += round((max(bottoms[r]) - bottoms[r][i]) * factors[r][i] * to_still)
            out.append([p, ax, ground])
        placed.append(out)
    # Attack: the last pose is the resting one and sits like a walk pose. The others are
    # matched to it.
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

    # --- shade and save
    def shade(frame: Image.Image) -> Image.Image:
        return resized(shade_sprite(frame), frame.size)      # shaded at 2x for smoothness

    def strip(frames: list[Image.Image]) -> Image.Image:
        out = Image.new("RGBA", (cell_w * len(frames), cell_h), (0, 0, 0, 0))
        for i, f in enumerate(frames):
            out.alpha_composite(f, (i * cell_w, 0))
        return out

    folder = OUT / brawler
    folder.mkdir(parents=True, exist_ok=True)
    shaded = {}
    for name, frames in cells.items():
        shaded[name] = [shade(f) for f in frames]
        strip(shaded[name]).save(folder / f"{name}.png", optimize=True)
        strip([shade(mirror_sprite(brawler, f)) for f in frames]).save(folder / f"{name}_mirrored.png", optimize=True)

    print(f"{brawler:8s} frame {cell_w} x {cell_h}  anchor {anchor}")
    return {
        "frames": shaded,
        "meta": {
            "name": NAMES[brawler],
            "frame_width": cell_w,
            "frame_height": cell_h,
            "anchor": list(anchor),
            "animations": {
                name: {"file": f"{name}.png", "mirrored_file": f"{name}_mirrored.png", "frames": FRAMES, **timing}
                for name, timing in motion.animations(brawler, cell_h).items()
            },
        },
    }


# ---------------------------------------------------------------- moving preview

def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in ("/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def posed(frame: Image.Image, anchor: tuple, move: tuple, size: tuple, at: tuple) -> Image.Image:
    """`frame` on a clear canvas of `size` with its anchor at `at`: stretched, turned, then moved."""
    x, y, rotate, wide, tall = move
    c, s = math.cos(math.radians(rotate)), math.sin(math.radians(rotate))
    ox, oy = at[0] + x, at[1] + y
    # PIL asks for the way back: where a point of the canvas comes from in the frame.
    a, b, d, e = c / wide, s / wide, -s / tall, c / tall
    back = (a, b, anchor[0] - a * ox - b * oy, d, e, anchor[1] - d * ox - e * oy)
    return frame.convert("RGBa").transform(size, Image.AFFINE, back, resample=Image.BICUBIC).convert("RGBA")


def put(img: Image.Image, sprite: Image.Image, x: int, y: int) -> None:
    """Draw `sprite` on `img` at a position that may be partly outside it."""
    left, top = max(0, -x), max(0, -y)
    if left or top:
        sprite = sprite.crop((left, top, sprite.width, sprite.height))
    img.alpha_composite(sprite, (max(0, x), max(0, y)))


def preview(built: dict[str, dict]) -> None:
    """One GIF with every brawler: walking on the top row, attacking below.

    It plays the drawn poses together with the smooth motion from animations.json, at 25
    pictures a second, the way a game would (a game can go faster still). Every brawler is
    drawn at the same size here, so the motion is easy to judge. Their real sizes relative to
    each other are in brawlers/sizes.json.
    """
    order = [b for b in ORDER if b in built] + sorted(b for b in built if b not in ORDER)
    big = 2                                      # drawn at twice the size and scaled down, for clean edges
    tile, gutter, name_h, pad = 170, 96, 42, 10
    width = gutter + tile * len(order) + pad
    height = pad + tile * 2 + name_h
    step_ms, total_ms = 40, 2 * motion.WALK_MS   # 25 pictures a second, two walk cycles
    attack_from = 120                            # the attack starts a moment after the loop does
    sand, brown = (236, 214, 178, 255), (92, 52, 28, 255)
    font = load_font(22 * big)
    canvas = (round(tile * big * 1.7),) * 2      # room for a lunge beyond the tile
    at = (canvas[0] / 2, canvas[1] * 0.80)       # where the anchor sits on that canvas
    still = (0.0, 0.0, 0.0, 1.0, 1.0)

    # Scale every brawler to fit a tile, and measure its ground shadow.
    small = {}
    for b in order:
        frames, meta = built[b]["frames"], built[b]["meta"]
        fw, fh = meta["frame_width"], meta["frame_height"]
        k = big * min((tile - 24) / fw, (tile - 40) / fh)
        size = (round(fw * k), round(fh * k))
        box = frames["walk"][0].getbbox()
        small[b] = {
            "k": k,
            "frames": {n: [resized(f, size) for f in fs] for n, fs in frames.items()},
            "anchor": (meta["anchor"][0] * k, meta["anchor"][1] * k),
            "shadow": (box[2] - box[0]) * k * 0.72,
            "height": fh * k,
        }

    def scene(ms: int) -> Image.Image:
        img = Image.new("RGBA", (width * big, height * big), sand)
        shadows = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ds = ImageDraw.Draw(shadows)
        sprites = []
        for col, b in enumerate(order):
            look, anims = small[b], built[b]["meta"]["animations"]
            for row, name in enumerate(ROWS):
                anim, t = anims[name], ms if name == "walk" else ms - attack_from
                if name == "walk" or 0 <= t < anim["duration_ms"]:
                    frame, move = look["frames"][name][motion.frame_at(anim, t)], motion.motion_at(anim, t)
                elif anim["returns_to_rest"]:
                    frame, move = look["frames"]["attack"][-1], still      # resting between attacks
                else:
                    frame, move = look["frames"]["walk"][-1], still        # the TNT starts over
                x, y, rotate, wide, tall = move
                x, y = x * look["k"], y * look["k"]
                cx = (gutter + tile * col + tile / 2) * big
                ground = (pad + tile * (row + 1) - 18) * big
                sw = look["shadow"] * wide * (1 + 3 * y / look["height"])   # smaller while off the ground
                ds.ellipse((cx + x - sw / 2, ground - sw * 0.13, cx + x + sw / 2, ground + sw * 0.09),
                           fill=(96, 52, 12, 115))
                sprite = posed(frame, look["anchor"], (x, y, rotate, wide, tall), canvas, at)
                sprites.append((sprite, round(cx - at[0]), round(ground - at[1])))
        img.alpha_composite(shadows.filter(ImageFilter.GaussianBlur(4 * big)))
        for sprite, x, y in sprites:
            put(img, sprite, x, y)
        d = ImageDraw.Draw(img)
        for row, title in enumerate(("Walk", "Attack")):
            d.text(((gutter / 2 + 4) * big, (pad + tile * row + tile / 2) * big), title, font=font, fill=brown, anchor="mm")
        for col, b in enumerate(order):
            d.text(((gutter + tile * col + tile / 2) * big, (height - name_h / 2 - 3) * big),
                   built[b]["meta"]["name"], font=font, fill=brown, anchor="mm")
        return img.resize((width, height), Image.LANCZOS)

    images = [scene(ms).convert("RGB").quantize(colors=255, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
              for ms in range(0, total_ms, step_ms)]
    EXAMPLES.mkdir(exist_ok=True)
    images[0].save(EXAMPLES / "animations.gif", save_all=True, append_images=images[1:],
                   duration=step_ms, loop=0, disposal=1, optimize=False)
    print(f"preview  {width} x {height}, {len(images)} pictures, {1000 // step_ms} a second")


def as_json(data: dict) -> str:
    """JSON with every list of numbers on one line."""
    text = json.dumps(data, indent=2)
    return re.sub(r"\[\s+(-?[\d.]+(?:,\s+-?[\d.]+)*)\s+\]",
                  lambda m: "[" + re.sub(r"\s+", " ", m.group(1)) + "]", text) + "\n"


def main() -> None:
    sheets = sorted(SRC.glob("*.jpg"))
    if not sheets:
        raise SystemExit("no sheets in animations/source/")
    built = {s.stem: build(s.stem) for s in sheets}
    (OUT / "animations.json").write_text(as_json({b: v["meta"] for b, v in built.items()}))
    preview(built)


if __name__ == "__main__":
    main()
