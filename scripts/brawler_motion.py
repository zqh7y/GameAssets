"""The smooth motion that goes on top of the brawlers' drawn poses.

A sheet gives four drawn poses per animation. Shown one after the other, that is about 8
pictures a second: too few to look smooth, however well they are lined up. Games get around
this by moving the whole sprite smoothly while the poses change. It bobs and rocks as it
walks, squashes and stretches, pulls back and lunges on an attack. This file describes that
motion for every brawler, and for the enemies.

A motion is five tracks:
    x, y              how far the sprite moves, in frame pixels (y is negative upwards)
    rotate            degrees, clockwise: a positive value leans a right-facing brawler forward
    scale_x, scale_y  how much it is stretched

Each track is a list of SAMPLES + 1 values spread evenly over the animation; in between, join
them with straight lines. The sprite is stretched and turned around its anchor point (the
centre of its body on the ground), then moved. For a mirrored strip, flip the sign of x and
rotate.

The poses change at the moments the sprite moves fastest, where the eye does not catch it.

An attack effect (fire, a spark...) has a small motion of its own: it keeps growing a little
all the way through, and fades out at the end.
"""

import math

SAMPLES = 48                    # each track has SAMPLES + 1 values
TRACKS = ("x", "y", "rotate", "scale_x", "scale_y")

WALK_MS = 520                   # one walk cycle (two steps)
ATTACK_MS = 640
WALK_STARTS = [0.0, 0.25, 0.50, 0.75]       # when each drawn pose starts, as a part of the whole
ATTACK_STARTS = [0.0, 0.22, 0.44, 0.74]     # wind up, wind up, strike, recover
HIT_AT = 0.50                               # the moment a lunge lands

# How each brawler walks. Sizes are parts of the frame height; angles are degrees.
#   waddle  steps on legs: lifts and stretches twice per cycle, rocks from side to side once
#   float   no legs: drifts up and down once per cycle, swaying a little
#   crawl   pulls itself along: flattens and rises once per cycle
WALKS = {
    "chick":   ("waddle", {"lift": 0.020, "stretch": 0.030, "rock": 3.5}),
    "tnt":     ("waddle", {"lift": 0.018, "stretch": 0.025, "rock": 2.0}),
    "dragon":  ("waddle", {"lift": 0.015, "stretch": 0.020, "rock": 2.0}),
    "wizard":  ("waddle", {"lift": 0.015, "stretch": 0.020, "rock": 2.5}),
    "acorn":   ("waddle", {"lift": 0.025, "stretch": 0.030, "rock": 4.0}),
    "ghost":   ("float",  {"bob": 0.030, "sway": 2.0, "breathe": 0.015}),
    "octopus": ("crawl",  {"pulse": 0.035, "slide": 0.020}),
    # enemies (see make_enemies.py)
    "beetle":  ("waddle", {"lift": 0.020, "stretch": 0.025, "rock": 3.0}),
}
DEFAULT_WALK = ("waddle", {"lift": 0.018, "stretch": 0.025, "rock": 2.5})

# How each brawler attacks.
#   lunge   pulls back, darts forward, lands, and returns to where it stood
#           back, forward   how far, as parts of the frame height
#           lean_back, lean degrees it tilts while winding up and while striking
#           hop             how high it jumps while winding up (optional)
#           tremble         how much it shakes while holding the strike (optional)
#   swell   stays where it is: squashes, springs up, then swells and shakes harder and harder.
#           It does not return to rest: the last pose is the moment before it bursts.
ATTACKS = {
    "chick":   ("lunge", {"back": 0.035, "forward": 0.09, "lean_back": 3.0, "lean": 3.0}),
    "dragon":  ("lunge", {"back": 0.030, "forward": 0.05, "lean_back": 3.0, "lean": 2.0, "tremble": 0.006}),
    "wizard":  ("lunge", {"back": 0.020, "forward": 0.04, "lean_back": 2.0, "lean": 2.0, "hop": 0.030}),
    "ghost":   ("lunge", {"back": 0.040, "forward": 0.10, "lean_back": 2.0, "lean": 4.0}),
    "acorn":   ("lunge", {"back": 0.030, "forward": 0.07, "lean_back": 4.0, "lean": 5.0, "hop": 0.020}),
    "octopus": ("lunge", {"back": 0.020, "forward": 0.04, "lean_back": 2.0, "lean": 2.0}),
    "tnt":     ("swell", {}),
    # enemies (see make_enemies.py)
    "beetle":  ("lunge", {"back": 0.035, "forward": 0.08, "lean_back": 4.0, "lean": 5.0, "hop": 0.015}),
}
DEFAULT_ATTACK = ("lunge", {"back": 0.03, "forward": 0.06, "lean_back": 3.0, "lean": 3.0})


# ---------------------------------------------------------------- curves

def _unit(u: float) -> float:
    return min(max(u, 0.0), 1.0)


def smooth(u: float) -> float:
    """Slow, fast, slow."""
    return 0.5 - 0.5 * math.cos(math.pi * _unit(u))


def speed_up(u: float) -> float:
    """Slow, then fast."""
    return _unit(u) ** 2


def slow_down(u: float) -> float:
    """Fast, then slow."""
    return 1 - (1 - _unit(u)) ** 2


def curve(keys: list[tuple], u: float) -> float:
    """Value at time u of a curve through keys: (time, value) or (time, value, how to get there)."""
    before = keys[0]
    for key in keys[1:]:
        if u <= key[0]:
            how = key[2] if len(key) > 2 else smooth
            span = key[0] - before[0]
            return before[1] + (key[1] - before[1]) * how((u - before[0]) / span if span else 1.0)
        before = key
    return keys[-1][1]


def _tracks(rows: list[tuple]) -> dict[str, list[float]]:
    """Turn a list of (x, y, rotate, scale_x, scale_y) into rounded tracks."""
    digits = {"x": 2, "y": 2, "rotate": 2, "scale_x": 4, "scale_y": 4}
    return {name: [round(row[i], digits[name]) + 0.0 for row in rows] for i, name in enumerate(TRACKS)}


# ---------------------------------------------------------------- walk

def walk(brawler: str, height: int) -> dict[str, list[float]]:
    style, n = WALKS.get(brawler, DEFAULT_WALK)
    rows = []
    for i in range(SAMPLES + 1):
        u = i / SAMPLES
        # Poses 1 and 3 are the steps, poses 2 and 4 the moments in between. The sprite is
        # lowest in the middle of a step and highest in the middle of an in-between, so the
        # poses change while it moves fastest.
        cycle = 2 * math.pi * (u - 0.125)
        if style == "waddle":
            up = 0.5 - 0.5 * math.cos(2 * cycle)            # 0 on the ground, 1 at the top; twice per cycle
            tall = 1 + n["stretch"] * (2 * up - 1)
            rows.append((0.0, -n["lift"] * height * up, n["rock"] * math.sin(cycle), 1 / tall ** 0.5, tall))
        elif style == "float":
            wave = math.sin(cycle)                          # up on pose 2, down on pose 4
            tall = 1 + n["breathe"] * wave
            rows.append((0.0, -n["bob"] * height * wave, n["sway"] * math.cos(cycle), 1 / tall ** 0.5, tall))
        else:                                               # crawl
            flat = math.sin(cycle)                          # flattest on pose 2, tallest on pose 4
            rows.append((n["slide"] * height * flat, 0.0, 0.0, 1 + n["pulse"] * flat, 1 - n["pulse"] * flat))
    rows[-1] = rows[0]                                      # a loop ends exactly where it starts
    return _tracks(rows)


# ---------------------------------------------------------------- attack

def attack(brawler: str, height: int) -> dict[str, list[float]]:
    style, n = ATTACKS.get(brawler, DEFAULT_ATTACK)
    rows = []
    for i in range(SAMPLES + 1):
        u = i / SAMPLES
        if style == "swell":
            # Squash down, spring up tall, then swell more and more while shaking harder.
            wide = curve([(0, 1), (0.16, 1.05, slow_down), (0.22, 1.03), (0.30, 0.96, slow_down),
                          (0.44, 1.0), (0.56, 1.04, slow_down), (0.72, 1.02), (1, 1.10, speed_up)], u)
            tall = curve([(0, 1), (0.16, 0.94, slow_down), (0.22, 0.96), (0.30, 1.06, slow_down),
                          (0.44, 1.0), (0.56, 1.04, slow_down), (0.72, 1.02), (1, 1.10, speed_up)], u)
            shake = curve([(0, 0), (0.40, 0), (0.72, 0.008), (1, 0.022, speed_up)], u)
            rows.append((shake * height * math.sin(2 * math.pi * 9 * u), 0.0,
                         shake * 60 * math.sin(2 * math.pi * 9 * u + 1.3), wide, tall))
            continue

        back, forward = n["back"] * height, n["forward"] * height
        # Pull back slowly, dart forward, bounce back a little on landing, then walk it back.
        x = curve([(0, 0), (0.36, -back), (HIT_AT, forward, speed_up), (0.60, 0.88 * forward, slow_down),
                   (0.70, 0.88 * forward), (1, 0)], u)
        if n.get("tremble") and 0.52 < u < 0.72:
            part = (u - 0.52) / 0.20
            x += n["tremble"] * height * math.sin(2 * math.pi * 3 * part) * math.sin(math.pi * part)
        y = curve([(0, 0), (0.20, 0), (0.38, -n.get("hop", 0) * height, slow_down), (HIT_AT, 0, speed_up), (1, 0)], u)
        rotate = curve([(0, 0), (0.36, -n["lean_back"]), (HIT_AT, n["lean"], speed_up),
                        (0.64, 0.3 * n["lean"], slow_down), (1, 0)], u)
        # Coil up while winding up, stretch along the dart, squash on landing, settle.
        wide = curve([(0, 1), (0.36, 1.03), (0.46, 1.06, speed_up), (0.55, 0.97, slow_down), (0.70, 1), (1, 1)], u)
        tall = curve([(0, 1), (0.36, 0.96), (0.46, 0.96), (0.55, 1.03, slow_down), (0.70, 1), (1, 1)], u)
        rows.append((x, y, rotate, wide, tall))
    return _tracks(rows)


# ---------------------------------------------------------------- attack effects

def effect() -> dict[str, list[float]]:
    """How an attack effect grows and fades over its life, as tracks: scale and opacity."""
    scale, opacity = [], []
    for i in range(SAMPLES + 1):
        u = i / SAMPLES
        scale.append(round(0.90 + 0.20 * slow_down(u), 4))                    # grows all the way, fast at first
        opacity.append(round(1 - smooth((u - 0.62) / 0.38), 3) + 0.0)        # solid, then fades over the last third
    return {"scale": scale, "opacity": opacity}


# ---------------------------------------------------------------- for animations.json and players

def _frame_ms(starts: list[float], duration: int) -> list[int]:
    edges = [round(s * duration) for s in starts] + [duration]
    return [b - a for a, b in zip(edges, edges[1:])]


def animations(brawler: str, height: int) -> dict[str, dict]:
    """Timing and motion of a brawler's walk and attack."""
    lunges = ATTACKS.get(brawler, DEFAULT_ATTACK)[0] == "lunge"
    return {
        "walk": {
            "loop": True,
            "duration_ms": WALK_MS,
            "frame_ms": _frame_ms(WALK_STARTS, WALK_MS),
            "motion": walk(brawler, height),
        },
        "attack": {
            "loop": False,
            "duration_ms": ATTACK_MS,
            "frame_ms": _frame_ms(ATTACK_STARTS, ATTACK_MS),
            "hit_ms": round(HIT_AT * ATTACK_MS) if lunges else ATTACK_MS,
            "returns_to_rest": lunges,
            "motion": attack(brawler, height),
        },
    }


def frame_at(animation: dict, ms: float) -> int:
    """Which drawn pose shows at this moment."""
    duration = animation["duration_ms"]
    ms = ms % duration if animation.get("loop") else min(max(ms, 0), duration)
    for i, length in enumerate(animation["frame_ms"]):
        if ms < length:
            return i
        ms -= length
    return len(animation["frame_ms"]) - 1


def motion_at(animation: dict, ms: float) -> tuple[float, ...]:
    """The value of every motion track at this moment, in the order the tracks are listed.

    For a brawler's animation that is (x, y, rotate, scale_x, scale_y); for an attack effect,
    (scale, opacity).
    """
    duration = animation["duration_ms"]
    u = (ms % duration) / duration if animation.get("loop") else _unit(ms / duration)
    at = u * SAMPLES
    i = min(int(at), SAMPLES - 1)
    part = at - i
    return tuple(track[i] * (1 - part) + track[i + 1] * part for track in animation["motion"].values())
