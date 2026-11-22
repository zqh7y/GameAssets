"""How a map moves: the wind, the plants, and the small things that fall and fly.

The numbers are in `motion` in maps/<area>/map.json (they come from AREAS in make_map.py), and
this module turns them into positions at a given moment, for the previews. A game can follow
the same rules. Times are in ms and positions in px of the map, measured from its top left
corner; `length` is the map's width.
"""

import math

import numpy as np


# ---------------------------------------------------------------- wind

def wind(motion: dict, ms: float, x, length: int):
    """The wind at a spot of the map, from about -1 to 1.

    It is a few waves rolling along the map from left to right. A whole number of each wave
    fits along the map, so the wind joins up where the map loops.
    """
    total = 0.0
    for w in motion["wind"]["waves"]:
        total = total + w["strength"] * np.sin(2 * np.pi * (ms / w["period_ms"] - np.asarray(x) * w["gusts"] / length))
    return total


def band_weights(motion: dict, height: int) -> np.ndarray:
    """For every row of the map, how much the base's own trees there move with the wind (0 to 1)."""
    y = np.arange(height, dtype=np.float32)
    weight = np.zeros(height, np.float32)
    for band in motion["wind"]["bands"]:
        weight = np.maximum(weight, np.clip((y - band["still"]) / (band["full"] - band["still"]), 0, 1))
    return weight


def lean(motion: dict, name: str, ms: float, x: float, length: int) -> float:
    """How far a decoration's top leans in the wind, as a part of its height above its foot."""
    return motion["sway"].get(name, 0.0) * float(wind(motion, ms, x, length))


# ---------------------------------------------------------------- plants that are walked through

class Springs:
    """The plants characters walk through. Each one is pushed forward and pressed down while a
    character is in it, and springs back with a wobble when let go."""

    def __init__(self, react: dict, count: int):
        self.react = react
        self.lean = np.zeros(count)
        self.lean_v = np.zeros(count)
        self.press = np.ones(count)
        self.press_v = np.zeros(count)

    def step(self, touched: np.ndarray, dt_ms: float) -> None:
        w = 2 * math.pi * self.react["spring_hz"]
        z = self.react["damping"]
        lean_to = np.where(touched, self.react["lean"], 0.0)
        press_to = np.where(touched, self.react["press"], 1.0)
        for _ in range(4):
            dt = dt_ms / 4000
            self.lean_v += (w * w * (lean_to - self.lean) - 2 * z * w * self.lean_v) * dt
            self.lean += self.lean_v * dt
            self.press_v += (w * w * (press_to - self.press) - 2 * z * w * self.press_v) * dt
            self.press += self.press_v * dt


def bit_at(bit: dict, age: float, react: dict):
    """Where a petal or leaf that popped out of a plant is: (x, y, angle, flip, opacity, landed)
    or None.

    It flies up and forward, falls back to the ground, lies there a moment and fades. `y` is
    where it is drawn: its spot on the ground, minus its height above it.
    """
    if age < 0:
        return None
    g = react["gravity_px_s2"]
    t = age / 1000
    land = (bit["vz"] + math.sqrt(bit["vz"] ** 2 + 2 * g * bit["z"])) / g     # when it reaches the ground
    flying = min(t, land)
    x = bit["x"] + bit["vx"] * flying
    z = max(0.0, bit["z"] + bit["vz"] * flying - g * flying * flying / 2)
    angle = bit["angle"] + bit["spin"] * flying
    flip = math.cos(2 * math.pi * flying * 1000 / bit["tumble_ms"])
    landed = t >= land
    if landed:
        flip = 1.0
    opacity = 1.0
    after = (t - land) * 1000 - react["rest_ms"]
    if after > 0:
        opacity = 1 - after / react["fade_ms"]
        if opacity <= 0:
            return None
    return x, bit["y"] - z, angle, flip, opacity, landed


# ---------------------------------------------------------------- falling leaves

def leaf_at(leaf: dict, age: float, falling: dict):
    """Where a leaf falling from a tree is: (x, y, angle, flip, opacity, landed) or None.

    It falls slowly, swinging from side to side and turning over, carried to the right by the
    wind. Then it lies on the ground a moment and fades.
    """
    if age < 0:
        return None
    fall_ms = (leaf["land"] - leaf["y"]) / leaf["speed"] * 1000
    t = min(age, fall_ms)
    swing = math.sin(2 * math.pi * t / falling["swing_ms"] + leaf["phase"])
    x = leaf["x"] + falling["drift_px_s"] * t / 1000 + falling["swing_px"] * swing
    y = leaf["y"] + leaf["speed"] * t / 1000
    angle = leaf["angle"] + leaf["spin"] * t / 1000 + 20 * swing
    flip = math.cos(2 * math.pi * t / leaf["tumble_ms"])
    # it settles flat in the last moments of the fall
    settle = min(1.0, max(0.0, (t - fall_ms + 300) / 300))
    flip = flip * (1 - settle) + settle
    opacity = min(1.0, age / 250)
    after = age - fall_ms - falling["rest_ms"]
    if after > 0:
        opacity = 1 - after / falling["fade_ms"]
        if opacity <= 0:
            return None
    return x, y, angle, flip, opacity, age >= fall_ms


# ---------------------------------------------------------------- butterflies

def butterfly_at(fly: dict, ms: float, loop_ms: float):
    """Where a butterfly is: (x, y on the ground, height above it, how open its wings are, angle).

    It wanders around its home spot along a few slow waves, with a quick flutter on top, and
    bobs up and down. Every wave fits a whole number of times in `loop_ms`, so it loops.
    """
    u = 2 * math.pi * ms / loop_ms

    def wave(terms):
        return sum(a * math.sin(n * u + p) for a, n, p in terms)

    x = fly["x"] + wave(fly["wander_x"])
    y = fly["y"] + wave(fly["wander_y"])
    h = fly["height"] + wave(fly["bob"])
    # heading: tilt a little toward where it is going
    dx = sum(a * n * math.cos(n * u + p) for a, n, p in fly["wander_x"])
    angle = max(-18.0, min(18.0, -dx * 0.06))
    beat = abs(math.cos(math.pi * ms / fly["flap_ms"] + fly["phase"]))
    wings = 0.18 + 0.82 * beat
    return x, y, h, wings, angle


# ---------------------------------------------------------------- birds

def bird_at(bird: dict, age: float, birds: dict, screen: int):
    """Where a bird flying over is, on the screen: (x, y, how spread its wings are, facing) or None.

    It crosses the screen in a gentle curve, beating its wings a few times, then gliding.
    """
    travel = screen + 2 * birds["margin_px"]
    duration = travel / birds["speed_px_s"] * 1000
    if not 0 <= age < duration:
        return None
    across = age / duration
    x = -birds["margin_px"] + travel * across
    if bird["facing"] < 0:
        x = screen - x
    y = bird["y"] + bird["curve_px"] * math.sin(math.pi * across)
    beats, glide = birds["beats"], birds["glide_ms"]
    flap_ms = birds["flap_ms"]
    cycle = beats * flap_ms + glide
    inside = (age + bird["phase"]) % cycle
    if inside < beats * flap_ms:
        wings = 0.35 + 0.65 * abs(math.cos(math.pi * inside / flap_ms))
    else:
        wings = 1.0
    return x, y, wings, bird["facing"]
