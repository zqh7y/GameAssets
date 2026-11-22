# Animations

Walk and attack animations for the 7 brawlers, 4 frames each.

![All brawlers walking and attacking](../examples/animations.gif)

In this preview every brawler is drawn at the same size, so the motion is easy to judge. Their
real sizes relative to each other are in [`brawlers/sizes.json`](../brawlers/sizes.json).

## Files

Each brawler has a folder with four sprite strips. A strip is 4 frames side by side.

| File | What it is |
|---|---|
| `walk.png` | Walk cycle, loops |
| `attack.png` | Attack, plays once |
| `walk_mirrored.png`, `attack_mirrored.png` | The same, facing the other way |

The frames are shaded like the sprites in `brawlers/shaded/`, at half their pixel size (the
same size as the flat sprites in `brawlers/`).

Use the mirrored strips when a brawler faces the other way. Do not flip a strip in the game:
its light would flip too, and the TNT's letters would read backwards.

[`animations.json`](animations.json) has the numbers a game needs:

| Brawler | Folder | Frame size (px) | Anchor (x, y) |
|---|---|---|---|
| Peep | `chick/` | 242 × 273 | 121, 267 |
| TNT | `tnt/` | 280 × 333 | 140, 327 |
| Dragon | `dragon/` | 282 × 261 | 141, 255 |
| Mage | `wizard/` | 376 × 316 | 188, 310 |
| Ghost | `ghost/` | 336 × 318 | 168, 312 |
| Mr Nut | `acorn/` | 298 × 238 | 149, 232 |
| Octopus | `octopus/` | 334 × 243 | 167, 237 |

## How to play them

- **Frames:** cut a strip into 4 frames of the frame width.
- **Anchor:** draw every frame with its anchor point on the brawler's spot on the ground. The
  anchor is the centre of the body on the ground line, and it is in the same place in every
  frame of a brawler, so nothing jitters and walk and attack can be swapped freely.
- **Size:** scale each brawler by its `scale` in `brawlers/sizes.json`.
- **Walk:** loop the 4 frames, 130 ms each.
- **Attack:** play once, with the frames shown for 130, 70, 150 and 130 ms: wind up, strike,
  hold, recover. The hit lands on the third frame. The last frame is the resting pose, so it
  also works as the standing pose.
- **Effects:** no fire, magic or sparks are drawn into the frames. Add them in the game from
  [`effects/pieces/`](../effects/pieces/), for example fire at the Dragon's mouth on the
  third attack frame.
- **Ghost:** it floats, so its frames already hover at different heights.

## Known quirks

These come from the source sheets. To fix one, generate a new sheet for that brawler, replace
its file in `source/` and run the script again.

- **Mr Nut:** the walk has very little movement, and on the third attack frame it is turned
  away, so its face is hidden.
- **Ghost:** on the second and third walk frames it turns sideways, so it changes shape more
  than the others.
- **TNT and Mage:** their feet are dark red and dark blue here, but black on the still sprites.

## Source

The original sheets are in [`source/`](source/), one per brawler: 8 poses on a green screen,
the walk on the top row and the attack on the bottom row.

The script cuts the poses out, brings them to one size, lines them up and shades them. Walk
poses are lined up by the body, with the feet on the ground. Attack poses are matched to the
resting pose where the two look the same, so the body stays put and only the parts that move,
move.

One pose is repaired along the way. On the TNT sheet, the third attack pose was drawn with a
second pair of squinting eyes where the letters "TNT" should be, so the box seemed to have
four eyes. The script removes that pair and copies the letters from the next pose.

To regenerate everything (needs `numpy` and `Pillow`; takes about a minute), run this from the
repo root:

```bash
python3 scripts/extract_animations.py
```
