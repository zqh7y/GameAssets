"""Cut the pick-a-card backgrounds out of their green-screen sheet as transparent PNGs.

Source (in cards/source/):
  - cards_greenscreen.jpg : two cards on a green screen
      left  = jackpot (rare) card, with heavenly light inside its window
      right = basic (regular) card

Output: cards/jackpot.png and cards/basic.png (RGBA, same canvas size)

Requires: numpy, Pillow
Run from the repo root:  python3 scripts/extract_cards.py
"""

from pathlib import Path

import numpy as np
from PIL import Image

from extract_brawlers import crop_to_alpha, dilate, key_green, label

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "cards" / "source" / "cards_greenscreen.jpg"
OUT = ROOT / "cards"

# Names for the cards on the sheet, left to right.
SHEET_NAMES = ["jackpot", "basic"]


def clean_rim(rgba: np.ndarray, width: int = 8) -> np.ndarray:
    """Remove the green tint the screen leaves on the soft outer rim of the cards.

    Every colour on the card rim (brown outline, cream frame) has green no higher than
    the average of red and blue, so anything greener than that near the edge is spill.
    The faint outermost halo is also trimmed so the outline ends crisply.
    """
    out = rgba.astype(np.float32)
    rim = dilate(rgba[..., 3] == 0, width) & (rgba[..., 3] > 0)
    r, g, b, a = out[..., 0], out[..., 1], out[..., 2], out[..., 3]
    g[rim] = np.minimum(g[rim], (r[rim] + b[rim]) / 2)
    a[rim] = np.clip((a[rim] / 255.0 - 0.25) / 0.5, 0.0, 1.0) * 255.0
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def cut_cards() -> dict[str, Image.Image]:
    rgba = clean_rim(key_green(SRC))
    labels, n = label(rgba[..., 3] >= 128)
    found = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(labels == i)
        if len(xs) > 20000:  # ignore specks
            found.append((xs.min(), i))
    if len(found) != len(SHEET_NAMES):
        raise SystemExit(f"expected {len(SHEET_NAMES)} cards on the sheet, found {len(found)}")
    found.sort()
    return {name: crop_to_alpha(rgba, dilate(labels == i, 2)) for name, (_, i) in zip(SHEET_NAMES, found)}


def same_canvas(cards: dict[str, Image.Image]) -> dict[str, Image.Image]:
    """Centre every card on a canvas of the same size, so they are interchangeable in-game."""
    w = max(c.width for c in cards.values())
    h = max(c.height for c in cards.values())
    out = {}
    for name, card in cards.items():
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.paste(card, ((w - card.width) // 2, (h - card.height) // 2))
        out[name] = canvas
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, card in same_canvas(cut_cards()).items():
        card.save(OUT / f"{name}.png", optimize=True)
        print(f"{name:8s} {card.size}")


if __name__ == "__main__":
    main()
