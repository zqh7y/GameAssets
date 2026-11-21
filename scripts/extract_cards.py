"""Build the pick-a-card backgrounds as transparent PNGs.

Source (in cards/source/):
  - cards_greenscreen.jpg : two cards on a green screen. Only the LEFT one (basic) is used.

Output:
  - cards/basic.png   : the basic card, cut out of the green screen
  - cards/jackpot.png : the same card with a warm glow and light rays drawn inside its window

The jackpot card is made from the basic one so both frames are pixel-identical and the
light can never leak past the card edge.

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/extract_cards.py
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from extract_brawlers import crop_to_alpha, dilate, flood, key_green, label

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "cards" / "source" / "cards_greenscreen.jpg"
OUT = ROOT / "cards"

RAYS = 12                                   # number of light rays
RAY_LIGHT = np.array([255, 250, 226.0])     # colour of the rays
GLOW_LIGHT = np.array([255, 254, 244.0])    # colour of the centre glow
GOLD_TINT = np.array([1.00, 0.93, 0.76])    # warms the window between the rays


def smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def cut_basic_card() -> Image.Image:
    """Key the sheet and return the left-most card."""
    rgba = key_green(SRC)
    labels, n = label(rgba[..., 3] >= 128)
    cards = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(labels == i)
        if len(xs) > 20000:
            cards.append((xs.min(), i))
    if not cards:
        raise SystemExit("no card found on the sheet")
    _, left = min(cards)
    return crop_to_alpha(rgba, dilate(labels == left, 2))


def window_mask(card: np.ndarray) -> np.ndarray:
    """Soft mask (0..1) of the sunken window in the top part of the card.

    The window is enclosed by a thin line that is darker than whatever surrounds it
    (even where the glossy shine crosses it), so treat "darker than the local average"
    as a wall and flood-fill from the middle of the top area.
    """
    h, w = card.shape[:2]
    lum = card[..., :3].astype(np.float32).sum(axis=2) / 3
    local = np.asarray(Image.fromarray(lum.astype(np.uint8)).filter(ImageFilter.GaussianBlur(6)))
    wall = (lum < local.astype(np.float32) * 0.93) | (card[..., 3] < 255)
    seed = np.zeros((h, w), dtype=bool)
    seed[int(h * 0.38), w // 2] = True
    inside = flood(~dilate(wall, 1), seed)
    if not 0.30 < inside.mean() < 0.50:
        raise SystemExit(f"window detection failed (covers {inside.mean():.0%} of the card)")
    # Undo the 1px the thickened wall took, then soften the edge.
    inside = dilate(inside, 1)
    soft = Image.fromarray((inside * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    return np.asarray(soft).astype(np.float32) / 255.0


def add_light(card: np.ndarray) -> np.ndarray:
    """Draw a warm glow with light rays inside the card window."""
    mask = window_mask(card)
    ys, xs = np.nonzero(mask > 0.5)
    cy, cx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
    radius = max(ys.max() - ys.min(), xs.max() - xs.min()) / 2

    yy, xx = np.mgrid[: card.shape[0], : card.shape[1]].astype(np.float32)
    r = np.hypot(xx - cx, yy - cy) / radius          # 0 at the centre, ~1 at the window edge
    theta = np.arctan2(yy - cy, xx - cx)

    # Soft rays: a smooth wave around the centre, slightly rotated so no ray is perfectly
    # horizontal, with a slower second wave so the rays differ a little in strength.
    wedge = np.cos(RAYS * theta + 0.6) + 0.35 * np.cos(RAYS / 2 * theta + 1.3)
    rays = smoothstep(-0.6, 0.9, wedge)
    rays *= np.clip(1.0 - 0.45 * r, 0.0, 1.0)        # fade toward the edges
    glow = np.exp(-(r / 0.55) ** 2)                  # wide bright centre

    base = card[..., :3].astype(np.float32)
    lit = base * GOLD_TINT
    lit = lit + (RAY_LIGHT - lit) * rays[..., None] * 0.85
    lit = lit + (GLOW_LIGHT - lit) * glow[..., None]

    out = card.copy()
    m = mask[..., None]
    out[..., :3] = np.clip(base * (1 - m) + lit * m + 0.5, 0, 255).astype(np.uint8)
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    basic = cut_basic_card()
    basic.save(OUT / "basic.png", optimize=True)
    print(f"basic    {basic.size}")

    jackpot = Image.fromarray(add_light(np.asarray(basic)), "RGBA")
    jackpot.save(OUT / "jackpot.png", optimize=True)
    print(f"jackpot  {jackpot.size}")


if __name__ == "__main__":
    main()
