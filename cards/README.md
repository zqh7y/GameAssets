# Cards

Backgrounds for the "choose a card" screen. Transparent PNGs, both 317 × 461 px (4px padding included).

| Preview | Name | File |
|:---:|---|---|
| <img src="basic.png" height="140"> | Basic (regular) | `basic.png` |
| <img src="jackpot.png" height="140"> | Jackpot (rare) | `jackpot.png` |

Both cards share the same frame. The jackpot card has heavenly light falling into its window.

## Layout

- **Window** (top): about 250 × 265 px, for the brawler
- **Label panel** (bottom): for a short text such as `+2 TNT`

## Source

The original image is in [`source/`](source/): `cards_greenscreen.jpg`, both cards on a green
screen (left = jackpot, right = basic).

To regenerate both cards (needs `numpy` and `Pillow`), run this from the repo root:

```bash
python3 scripts/extract_cards.py
```
