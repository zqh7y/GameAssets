"""A preview of a fight on the forest map (not a game asset).

All seven brawlers walk along the map. Four Beetle Knights come at them, and the map stops
while they fight. The Ghost, the TNT, Mr Nut and Peep stand in front, each hitting the beetle
across from it; the Mage, the Dragon and the Octopus stand behind them and shoot over their
heads: their attack effect flies to a beetle as a small shot and bursts there. The beetles hit
back at the brawlers in front. A hit shows as a white flash and a little knock-back, with the
damage in numbers; each beetle has a health bar. Beaten beetles flash, squash and burst into
leaves, and the squad walks on.

It shows how the pieces fit together: the map and everything that moves on it (map_motion.py),
the brawlers' animations (animations/animations.json) and the enemies' (enemies/enemies.json).
The fight itself (who attacks when, how hard, the shots) is made up for the preview.

Output: examples/battle_forest.mp4 (needs ffmpeg) and examples/battle_forest.jpg

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/make_battle.py
"""

import heapq
import itertools
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import brawler_motion as motion
import map_motion
from extract_animations import posed, resized
from make_map import EXAMPLES, FPS, SHADOW, Life, paste, spun, strip

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "fonts" / "LilitaOne-Regular.ttf"
SIZE = 0.52              # a brawler of size 1 is drawn at this part of its animation frame, as on the map
WALK_PX_S = 150          # how fast the squad walks
ENEMY_PX_S = 60          # how fast the beetles walk

# The beetles: where each one stops on the screen (x, y of its feet) and when it gets there. Each
# one attacks the brawler in front of it every BEETLE_EVERY ms, from 400 ms after it arrives.
BEETLES = [
    {"x": 525, "y": 455, "arrives": 2650},
    {"x": 492, "y": 545, "arrives": 2800},
    {"x": 472, "y": 635, "arrives": 2950},
    {"x": 512, "y": 712, "arrives": 3100},
]
BEETLE_HP = 100
BEETLE_EVERY = 1600

# The squad: where each brawler stands (x, y of its feet on the screen), the beetle it fights,
# and when it first attacks, how often and how hard. The ones in front are close enough for
# their attack to reach. The ones behind are `ranged`: their attack effect flies to the beetle
# in SHOT_MS as a small shot and bursts there, and once their beetle is beaten they shoot at
# the nearest one left. The tall ones stand behind, so the small ones stay in sight.
SQUAD = [
    {"sprite": "wizard",  "x": 250, "y": 495, "target": 0, "ranged": True,  "first": 3150, "every": 1400, "damage": 26},
    {"sprite": "ghost",   "x": 400, "y": 455, "target": 0, "ranged": False, "first": 3000, "every": 1200, "damage": 24},
    {"sprite": "tnt",     "x": 412, "y": 545, "target": 1, "ranged": False, "first": 3300, "every": 2600, "damage": 50},
    {"sprite": "dragon",  "x": 255, "y": 585, "target": 1, "ranged": True,  "first": 3050, "every": 1300, "damage": 30},
    {"sprite": "acorn",   "x": 400, "y": 635, "target": 2, "ranged": False, "first": 3350, "every": 1000, "damage": 19},
    {"sprite": "octopus", "x": 245, "y": 675, "target": 2, "ranged": True,  "first": 3250, "every": 1100, "damage": 22},
    {"sprite": "chick",   "x": 442, "y": 712, "target": 3, "ranged": False, "first": 3450, "every": 900,  "damage": 16},
]
SHOT_MS = 220
ENEMY = "beetle"
BRAKE_MS = 500           # the squad slows down and speeds up again over this long
GONE_MS = 650            # how long the TNT is gone after it bursts, before it pops back
STOP_MS = 2650           # when the squad has stopped
AFTER_MS = 600           # how long the squad waits after the last beetle falls
END_MS = 3600            # how long it walks on after that
DIE_MS = 450             # a beaten beetle flashes, squashes and fades over this long
STILL_MS = 3480          # the moment shown in the still picture


class Actor:
    """A brawler or an enemy, played from its files the way a game would."""

    def __init__(self, sprite: str, enemy: bool):
        if enemy:
            meta = json.loads((ROOT / "enemies" / "enemies.json").read_text())[sprite]
            folder, scale = ROOT / "enemies" / sprite, meta["scale"]
        else:
            meta = json.loads((ROOT / "animations" / "animations.json").read_text())[sprite]
            folder = ROOT / "animations" / sprite
            scale = json.loads((ROOT / "brawlers" / "sizes.json").read_text())[sprite]["scale"]
        self.meta, self.enemy = meta, enemy
        self.k = k = SIZE * scale
        fw, fh = meta["frame_width"], meta["frame_height"]
        self.frames = {name: [resized(f, (round(fw * k), round(fh * k))) for f in strip(folder / a["file"], a["frames"])]
                       for name, a in meta["animations"].items()}
        self.anchor = (meta["anchor"][0] * k, meta["anchor"][1] * k)
        self.effects = {}
        for name, a in meta["animations"].items():
            e = a.get("effect")
            if e:
                cells = [resized(f, (round(e["frame_width"] * k), round(e["frame_height"] * k)))
                         for f in strip(folder / e["file"], e["frames"])]
                self.effects[name] = (e, cells, (e["anchor"][0] * k, e["anchor"][1] * k))
        box = self.frames["walk"][0].getbbox()
        self.width, self.height = (box[2] - box[0]), fh * k
        self.top = (box[1] - meta["anchor"][1] * k)              # the top of its head, from its feet
        side = round(max(fw, fh) * k * 1.9)
        self.canvas, self.at = (side, side), (side / 2, side * 0.78)
        self.attacks, self.hits, self.walking = [], [], []
        self.death = None
        self.hp = 100
        # The TNT's attack ends as it bursts: it is gone for a moment, then pops back. Standing
        # still, it uses its last walk pose (see animations/README.md).
        self.bursts = not meta["animations"]["attack"].get("returns_to_rest", True)
        self.rest = self.frames["walk"][-1] if self.bursts else self.frames["attack"][-1]

    def back(self, t: float) -> float | None:
        """For the TNT: None while it is gone after a burst, else how far it has popped back (0 to 1)."""
        if not self.bursts:
            return 1.0
        end = self.meta["animations"]["attack"]["duration_ms"]
        for s in self.attacks:
            age = t - s - end
            if 0 <= age < GONE_MS:
                return None
            if GONE_MS <= age < GONE_MS + 160:
                return (age - GONE_MS) / 160
        return 1.0

    # -- what it is doing
    def state(self, t: float) -> tuple[str, float]:
        attack = self.meta["animations"]["attack"]
        for s in self.attacks:
            if s <= t < s + attack["duration_ms"]:
                return "attack", t - s
        if any(a <= t < b for a, b in self.walking):
            return "walk", t
        return "idle", t

    def knock(self, t: float) -> tuple[float, float]:
        """How far it is knocked back, and how white it flashes, after its latest hit."""
        past = [h for h in self.hits if h[0] <= t]
        if not past:
            return 0.0, 0.0
        age = t - past[-1][0]
        push = 10 * math.exp(-age / 90) * (1 if self.enemy else -1)
        return push, max(0.0, 1 - age / 130)

    def sprite(self, t: float) -> tuple[Image.Image, tuple]:
        """Its picture at a moment, and its motion (x, y, rotate, scale_x, scale_y)."""
        state, u = self.state(t)
        if state == "idle":
            frame = self.rest
            breathe = 1 + 0.015 * math.sin(2 * math.pi * t / 1400)
            move = (0.0, 0.0, 0.0, 1 / math.sqrt(breathe), breathe)
        else:
            anim = self.meta["animations"][state]
            frame = self.frames[state][motion.frame_at(anim, u)]
            move = motion.motion_at(anim, u)
        return frame, move

    def draw(self, img: Image.Image, t: float, x: float, y: float) -> None:
        back = self.back(t)
        if back is None:
            return
        frame, (mx, my, rotate, wide, tall) = self.sprite(t)
        push, flash = self.knock(t)
        if back < 1:                                            # popping back after a burst
            pop = 0.5 - 0.5 * math.cos(math.pi * back)
            wide, tall, flash = wide * (0.4 + 0.6 * pop), tall * (0.4 + 0.6 * pop), max(flash, 1 - back)
        opacity = 1.0
        if self.death is not None and t >= self.death:
            age = t - self.death
            flash = max(flash, 1 - age / 120)
            squash = 0.5 - 0.5 * math.cos(math.pi * min(age / DIE_MS, 1))
            wide, tall = wide * (1 + 0.3 * squash), tall * (1 - 0.55 * squash)
            opacity = 1 - max(0.0, (age - 120) / (DIE_MS - 120))
        pic = posed(frame, self.anchor, (mx * self.k + push, my * self.k, rotate, wide, tall), self.canvas, self.at)
        if flash > 0:
            white = Image.new("RGBA", pic.size, (255, 255, 255, 0))
            white.putalpha(pic.getchannel("A").point(lambda v: round(v * 0.75 * flash)))
            pic.alpha_composite(white)
        if opacity < 1:
            pic.putalpha(pic.getchannel("A").point(lambda v: round(v * max(opacity, 0))))
        paste(img, pic, round(x - self.at[0]), round(y - self.at[1]))

    def shadow(self, d: ImageDraw.ImageDraw, t: float, x: float, y: float) -> None:
        back = self.back(t)
        if back is None:
            return
        _, (mx, my, rotate, wide, tall) = self.sprite(t)
        wide *= 0.4 + 0.6 * back
        push, _ = self.knock(t)
        w = self.width * 0.72 * wide * (1 + 3 * my * self.k / self.height)
        if self.death is not None and t >= self.death:
            w *= max(0.0, 1 - (t - self.death) / DIE_MS)
        cx = x + mx * self.k + push
        d.ellipse((cx - w / 2, y - w * 0.13, cx + w / 2, y + w * 0.09), fill=SHADOW + (107,))


def number(text: str, colour: tuple, size: int) -> Image.Image:
    """A damage number: the game's font, with a thick dark outline."""
    font = ImageFont.truetype(str(FONT), size)
    box = font.getbbox(text, stroke_width=4)
    img = Image.new("RGBA", (box[2] - box[0] + 8, box[3] - box[1] + 8), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((4 - box[0], 4 - box[1]), text, font=font, fill=colour + (255,),
                             stroke_width=4, stroke_fill=(58, 30, 14, 255))
    return img


class Fight:
    """The whole preview: the camera, the squad, the beetles, and everything on the map."""

    def __init__(self):
        self.brawlers = [Actor(spec["sprite"], enemy=False) for spec in SQUAD]
        self.enemies = [Actor(ENEMY, enemy=True) for _ in BEETLES]
        self.schedule()
        self.count = round(self.total_ms * FPS / 1000)
        self.life = Life("forest", round(WALK_PX_S / FPS), self.count)
        self.length = self.life.length
        self.camera()
        self.place()
        self.plants()
        self.falling()

    # -- the fight, worked out ahead
    def schedule(self) -> None:
        """Who attacks when, played out ahead in time order. A brawler attacks its beetle until
        the beetle is beaten (a ranged one then picks the nearest beetle left). A beetle hits
        back at the brawler in front of it, as long as it can finish its swing before it falls."""
        self.numbers, self.shots = [], []          # (time, target, text, colour); (launch, land, brawler, beetle)
        for b, spec in zip(self.brawlers, SQUAD):
            b.x, b.y, b.spec = spec["x"], spec["y"], spec
        for e, spec in zip(self.enemies, BEETLES):
            e.hp, e.spec = BEETLE_HP, spec
        order = itertools.count()
        queue = [(spec["first"], next(order), "attack", n, -1) for n, spec in enumerate(SQUAD)]
        heapq.heapify(queue)
        while queue:
            t, _, kind, n, j = heapq.heappop(queue)
            b, spec = self.brawlers[n], SQUAD[n]
            hit_ms = b.meta["animations"]["attack"]["hit_ms"]
            if kind == "attack":
                alive = [k for k, e in enumerate(self.enemies) if e.death is None or e.death > t]
                target = spec["target"] if spec["target"] in alive else None
                if target is None and spec["ranged"] and alive:
                    target = min(alive, key=lambda k: abs(BEETLES[k]["y"] - spec["y"]))
                if target is None:
                    continue
                b.attacks.append(t)
                land = t + hit_ms + (SHOT_MS if spec["ranged"] else 0)
                heapq.heappush(queue, (land, next(order), "hit", n, target))
                heapq.heappush(queue, (t + spec["every"], next(order), "attack", n, -1))
            else:
                e = self.enemies[j]
                if e.death is not None:
                    continue                                 # beaten already: the hit goes nowhere
                amount = spec["damage"] + (len(e.hits) * 7 + n) % 5 - 2      # a little variety
                e.hits.append((t, amount))
                e.hp -= amount
                self.numbers.append((t, e, str(amount), (255, 255, 255)))
                if spec["ranged"]:
                    self.shots.append((t - SHOT_MS, t, b, e))
                if e.hp <= 0:
                    e.death = t + 60
        for j, e in enumerate(self.enemies):
            front = next(b for b, spec in zip(self.brawlers, SQUAD) if spec["target"] == j and not spec["ranged"])
            attack = e.meta["animations"]["attack"]
            start = BEETLES[j]["arrives"] + 400 + 150 * j
            while start + attack["duration_ms"] <= e.death:
                e.attacks.append(start)
                hit = start + attack["hit_ms"]
                if front.back(hit) == 1.0:                     # the TNT may be gone, after a burst
                    amount = 9 + (len(front.hits) * 5 + j) % 6
                    front.hits.append((hit, amount))
                    self.numbers.append((hit, front, str(amount), (255, 96, 72)))
                start += BEETLE_EVERY
        last = max(e.death for e in self.enemies)
        self.resume_ms = last + DIE_MS + AFTER_MS
        self.total_ms = self.resume_ms + BRAKE_MS + END_MS
        for b in self.brawlers:
            b.walking = [(0, STOP_MS), (self.resume_ms, self.total_ms + 1)]

    def camera(self) -> None:
        """Where the camera is in every picture: walking, slowing to a stop, still, walking again."""
        v = WALK_PX_S / 1000
        speed = []
        for i in range(self.count + 1):
            t = i * 1000 / FPS
            if t < STOP_MS - BRAKE_MS:
                s = 1.0
            elif t < STOP_MS:
                s = 0.5 + 0.5 * math.cos(math.pi * (t - STOP_MS + BRAKE_MS) / BRAKE_MS)
            elif t < self.resume_ms:
                s = 0.0
            elif t < self.resume_ms + BRAKE_MS:
                s = 0.5 - 0.5 * math.cos(math.pi * (t - self.resume_ms) / BRAKE_MS)
            else:
                s = 1.0
            speed.append(s * v * 1000 / FPS)
        self.cams = np.concatenate([[0.0], np.cumsum(speed)])
        self.stopped_at = float(self.cams[round(STOP_MS * FPS / 1000)])

    def cam(self, t: float) -> float:
        i = t * FPS / 1000
        j = min(int(i), self.count)
        return float(self.cams[j] + (self.cams[min(j + 1, self.count)] - self.cams[j]) * (i - j))

    def place(self) -> None:
        """Every beetle walks in from the right and stops across from the brawlers in front."""
        for spec, e in zip(BEETLES, self.enemies):
            e.stop = self.stopped_at + spec["x"]                  # on the map
            e.y = spec["y"]
            e.arrives = spec["arrives"]
            e.walking = [(0, e.arrives)]

    def enemy_x(self, e: Actor, t: float) -> float:
        return e.stop + ENEMY_PX_S / 1000 * max(0.0, e.arrives - t)

    # -- the map
    def plants(self) -> None:
        """Play the plants' springs as the brawlers and beetles walk through them."""
        life = self.life
        react = life.mo["react"]
        idx = [i for i, d in enumerate(life.decos) if d["reacts"]]
        xs = np.array([life.decos[i]["x"] for i in idx])
        ys = np.array([life.decos[i]["y"] for i in idx])
        reach = np.array([life.decos[i]["w"] * react["reach"] for i in idx])
        springs = map_motion.Springs(react, len(idx))
        self.react_of = {i: k for k, i in enumerate(idx)}
        self.leaning = np.zeros((self.count, len(idx)))
        self.pressed = np.ones((self.count, len(idx)))
        self.bits = []
        actors = self.brawlers + self.enemies
        was = np.zeros((len(actors), len(idx)), bool)
        for i in range(self.count):
            t = i * 1000 / FPS
            cam = self.cam(t)
            touched = np.zeros(len(idx), bool)
            for j, a in enumerate(actors):
                if a.death is not None and t >= a.death:
                    was[j] = False
                    continue
                wx = self.enemy_x(a, t) if a.enemy else cam + a.x
                d = (wx - xs + self.length / 2) % self.length - self.length / 2
                now = (np.abs(d) < reach + a.width / 4) & (np.abs(a.y - ys) < react["depth_px"])
                for k in np.nonzero(now & ~was[j])[0]:
                    self.bits += life.burst(t, idx[k], j, wx - d[k])
                was[j] = now
                touched |= now
            springs.step(touched, 1000 / FPS)
            self.leaning[i] = springs.lean
            self.pressed[i] = springs.press
        # beaten beetles burst into green leaves
        rng = np.random.default_rng(5)
        names = [n for n in life.effects if n.startswith("leaf_green")]
        for e in self.enemies:
            for _ in range(9):
                self.bits.append({"t0": e.death, "x": self.enemy_x(e, e.death) + rng.uniform(-25, 25),
                                  "y": e.y + rng.uniform(-4, 6), "z": rng.uniform(20, 60),
                                  "vx": rng.uniform(-90, 150), "vz": rng.uniform(120, 230),
                                  "spin": rng.uniform(-400, 400), "angle": rng.uniform(0, 360),
                                  "tumble_ms": rng.uniform(250, 450),
                                  "sprite": life.sprite(names[int(rng.integers(len(names)))], rng.uniform(13, 18))})

    def falling(self) -> None:
        """Leaves and petals falling from the trees, starting on the screen of the moment."""
        life, fall = self.life, self.life.mo["falling"]
        rng = np.random.default_rng(13)
        names, weights = [], []
        for prefix, weight in fall["sprites"].items():
            found = [n for n in sorted(life.effects) if n.startswith(prefix)]
            names += found
            weights += [weight / len(found)] * len(found)
        p = np.array(weights) / sum(weights)
        self.leaves = []
        for _ in range(round(fall["per_s"] * self.total_ms / 1000)):
            t0 = rng.uniform(-6000, self.total_ms)
            y = rng.uniform(*fall["from"])
            spot = fall["land"][0] if rng.random() < fall["on_cliff"] else fall["land"][1]
            self.leaves.append({"t0": t0, "x": self.cam(max(t0, 0)) + rng.uniform(-80, life.screen + 40), "y": y,
                                "land": max(y + 15, rng.uniform(*spot)), "speed": rng.uniform(*fall["speed_px_s"]),
                                "spin": rng.uniform(*fall["spin_deg_s"]), "angle": rng.uniform(0, 360),
                                "phase": rng.uniform(0, 2 * math.pi), "tumble_ms": rng.uniform(*fall["tumble_ms"]),
                                "sprite": life.sprite(names[rng.choice(len(names), p=p)], rng.uniform(*fall["size_px"]))})

    # -- one picture
    def frame(self, i: int) -> Image.Image:
        life = self.life
        t = i * 1000 / FPS
        cam = self.cam(t)
        icam = round(cam)
        img = life.ground(t, icam)
        where = {id(b): (b.x, b.y) for b in self.brawlers}           # every fighter's spot on the screen
        where.update({id(e): (self.enemy_x(e, t) - icam, e.y) for e in self.enemies})
        actors = [(a, *where[id(a)]) for a in self.brawlers + self.enemies
                  if a.death is None or t < a.death + DIE_MS]

        # shadows
        shadows = Image.new("RGBA", img.size, SHADOW + (0,))
        d = ImageDraw.Draw(shadows)
        for a, x, y in actors:
            a.shadow(d, t, x, y)
        flies = []
        for f in life.flies:
            x, y, h, wings, angle = map_motion.butterfly_at(f, t, life.loop_ms)
            sx = life.on_screen(x, icam, 60)
            if sx is not None:
                flies.append((f, sx, y, h, wings, angle))
                sw = f["sprite"].width * 0.5 * (0.4 + 0.6 * wings)
                d.ellipse((sx + 6 - sw / 2, y - sw * 0.18, sx + 6 + sw / 2, y + sw * 0.18), fill=SHADOW + (46,))
        img.alpha_composite(shadows.filter(ImageFilter.GaussianBlur(5)))
        birds = []
        for b in life.flock:
            pos = map_motion.bird_at(b, t - b["t0"], life.mo["birds"], life.screen)
            if pos:
                birds.append(pos)
        ox, oy = life.mo["birds"]["shadow_px"]
        for x, y, wings, facing in birds:
            sil = life.bird_picture(wings, facing, True)
            paste(img, sil, round(x + ox - sil.width / 2), round(y + oy - sil.height / 2))

        # leaves and petals: lying ones first
        lying, flying = [], []
        for leaf in self.leaves:
            pos = map_motion.leaf_at(leaf, t - leaf["t0"], life.mo["falling"])
            if pos:
                x, y, angle, flip, opacity, landed = pos
                (lying if landed else flying).append((leaf["sprite"], x - icam, y, angle, flip, opacity))
        for bit in self.bits:
            pos = map_motion.bit_at(bit, t - bit["t0"], life.mo["react"])
            if pos:
                x, y, angle, flip, opacity, landed = pos
                (lying if landed else flying).append((bit["sprite"], x - icam, y, angle, flip, opacity))
        for sprite, x, y, angle, flip, opacity in lying:
            if -30 < x < life.screen + 30:
                pic = spun(sprite, angle, flip, opacity)
                paste(img, pic, round(x - pic.width / 2), round(y - pic.height / 2))

        self.dust(img, t, icam)

        # decorations and fighters, back to front
        items = []
        for k, dco in enumerate(life.decos):
            sx = life.on_screen(dco["x"], icam, dco["w"])
            if sx is None:
                continue
            lean = dco["sway"] * float(map_motion.wind(life.mo, t, dco["x"], self.length))
            press = 1.0
            if dco["reacts"]:
                lean += self.leaning[i, self.react_of[k]]
                press = self.pressed[i, self.react_of[k]]
            items.append((dco["y"], 0, k, sx, lean, press))
        for n, (a, x, y) in enumerate(actors):
            items.append((y, 1, n, x, 0, 0))
        for y, kind, k, sx, lean, press in sorted(items, key=lambda it: (it[0], it[1])):
            if kind == 0:
                life.draw_deco(img, life.decos[k], sx, lean, press)
            else:
                a, x, ay = actors[k]
                a.draw(img, t, x, ay)

        for sprite, x, y, angle, flip, opacity in flying:
            if -30 < x < life.screen + 30:
                pic = spun(sprite, angle, flip, opacity)
                paste(img, pic, round(x - pic.width / 2), round(y - pic.height / 2))
        self.attack_effects(img, t, actors, where)
        self.health_bars(img, t, actors)
        self.damage_numbers(img, t, where)
        for f, sx, y, h, wings, angle in flies:
            pic = spun(f["sprite"], angle, 0.12 + 0.88 * wings, 1.0)
            paste(img, pic, round(sx - pic.width / 2), round(y - h - pic.height / 2))
        for x, y, wings, facing in birds:
            pic = life.bird_picture(wings, facing, False)
            paste(img, pic, round(x - pic.width / 2), round(y - pic.height / 2))
        return img.convert("RGB")

    def dust(self, img: Image.Image, t: float, icam: int) -> None:
        """The dust of the brawlers' steps, left where it was kicked up."""
        for b in self.brawlers:
            walk = b.meta["animations"]["walk"]
            e = walk.get("effect")
            if not e:
                continue
            cells, anchor = b.effects["walk"][1], b.effects["walk"][2]
            for start, end in b.walking:
                first = int(max(start, t - e["duration_ms"] - walk["duration_ms"]) // walk["duration_ms"])
                for n in range(first, int(t // walk["duration_ms"]) + 1):
                    for s in e["starts_ms"]:
                        began = n * walk["duration_ms"] + s
                        age = t - began
                        if not (start <= began < end and 0 <= age < e["duration_ms"]):
                            continue
                        grow, opacity = motion.motion_at(e, age)
                        pic = posed(cells[motion.frame_at(e, age)], anchor, (0.0, 0.0, 0.0, grow, grow), b.canvas, b.at)
                        pic.putalpha(pic.getchannel("A").point(lambda v: round(v * opacity)))
                        x = self.cam(began) + b.x + e["at"][0] * b.k - icam
                        paste(img, pic, round(x - b.at[0]), round(b.y + e["at"][1] * b.k - b.at[1]))

    def attack_effects(self, img: Image.Image, t: float, actors: list, where: dict) -> None:
        for a, x, y in actors:
            if "attack" not in a.effects or (not a.enemy and a.spec["ranged"]):
                continue
            e, cells, anchor = a.effects["attack"]
            for s in a.attacks:
                age = t - s - e["starts_ms"][0]
                if not 0 <= age < e["duration_ms"]:
                    continue
                grow, opacity = motion.motion_at(e, age)
                pic = posed(cells[motion.frame_at(e, age)], anchor, (0.0, 0.0, 0.0, grow, grow), a.canvas, a.at)
                pic.putalpha(pic.getchannel("A").point(lambda v: round(v * opacity)))
                paste(img, pic, round(x + e["at"][0] * a.k - a.at[0]), round(y + e["at"][1] * a.k - a.at[1]))
        # shots: the first step of the effect flies from the brawler to the beetle, then the
        # whole effect plays there
        for launch, land, b, target in self.shots:
            e, cells, anchor = b.effects["attack"]
            tx, ty = where[id(target)]
            tx, ty = tx - target.width * 0.25, ty + target.top * 0.5        # the middle of the beetle's front
            if launch <= t < land:
                u = (t - launch) / (land - launch)
                sx, sy = b.x + e["at"][0] * b.k, b.y + e["at"][1] * b.k
                px, py = sx + (tx - sx) * u, sy + (ty - sy) * u - 40 * math.sin(math.pi * u)
                pic = cells[0] if cells[0].getbbox() else cells[1]
                pic = pic.crop(pic.getbbox())
                pic = resized(pic, (max(1, round(pic.width * 0.8)), max(1, round(pic.height * 0.8))))
                paste(img, pic, round(px - pic.width / 2), round(py - pic.height / 2))
            age = t - land
            if 0 <= age < e["duration_ms"]:
                grow, opacity = motion.motion_at(e, age)
                pic = posed(cells[motion.frame_at(e, age)], anchor, (0.0, 0.0, 0.0, grow, grow), b.canvas, b.at)
                pic.putalpha(pic.getchannel("A").point(lambda v: round(v * opacity)))
                if e.get("frame_width") and anchor[0] < cells[0].width * 0.3:     # fire grows forward from its tip
                    tx -= target.width * 0.2
                paste(img, pic, round(tx - b.at[0]), round(ty - b.at[1]))

    def health_bars(self, img: Image.Image, t: float, actors: list) -> None:
        d = ImageDraw.Draw(img)
        for a, x, y in actors:
            if not a.enemy or t < a.arrives - 400:
                continue
            hp = BEETLE_HP - sum(h[1] for h in a.hits if h[0] <= t)
            fade = 1.0 if a.death is None or t < a.death else max(0.0, 1 - (t - a.death) / 200)
            if fade <= 0:
                continue
            w, h = 46, 8
            top = y + a.top - 16
            left = x - w / 2
            alpha = round(255 * fade)
            d.rounded_rectangle((left - 2, top - 2, left + w + 2, top + h + 2), radius=5, fill=(58, 30, 14, alpha))
            d.rounded_rectangle((left, top, left + w, top + h), radius=4, fill=(96, 60, 40, alpha))
            fill = max(0.0, hp / BEETLE_HP) * w
            if fill > 2:
                d.rounded_rectangle((left, top, left + fill, top + h), radius=4, fill=(112, 214, 74, alpha))
                d.rounded_rectangle((left + 2, top + 1, left + max(fill - 2, 3), top + 3), radius=2,
                                    fill=(190, 245, 150, alpha))

    def damage_numbers(self, img: Image.Image, t: float, where: dict) -> None:
        for n, (hit, target, text, colour) in enumerate(self.numbers):
            age = t - hit
            if not 0 <= age < 800:
                continue
            x, y = where[id(target)]
            pop = 1 + 0.45 * max(0.0, 1 - age / 140)
            rise = 46 * (1 - (1 - age / 800) ** 2)
            pic = number(text, colour, round(26 * pop * (0.85 if not target.enemy else 1.0)))
            if age > 550:
                pic.putalpha(pic.getchannel("A").point(lambda v: round(v * (1 - (age - 550) / 250))))
            side = (n * 37) % 30 - 15
            paste(img, pic, round(x + side - pic.width / 2), round(y + target.top - 30 - rise - pic.height / 2))


def main() -> None:
    fight = Fight()
    print(f"fight: {fight.count} pictures, {fight.total_ms / 1000:.1f} s; beetles fall at "
          f"{', '.join(str(round(e.death)) for e in fight.enemies)} ms")
    EXAMPLES.mkdir(exist_ok=True)
    # the still: early in the fight, with everyone in sight and at it
    fight.frame(round(STILL_MS * FPS / 1000)).save(EXAMPLES / "battle_forest.jpg", quality=90)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found: no video")
        return
    out = EXAMPLES / "battle_forest.mp4"
    size = fight.life.screen
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size}x{fight.life.height}",
           "-r", str(FPS), "-i", "-", "-vf", "scale=720:720:flags=lanczos", "-c:v", "libx264", "-preset", "slow",
           "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
        for i in range(fight.count):
            proc.stdin.write(fight.frame(i).tobytes())
        proc.stdin.close()
    print(f"video    {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
