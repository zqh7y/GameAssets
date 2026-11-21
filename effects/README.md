# Effects

Small effect sprites that go with the brawlers. Transparent PNGs, 128 × 128 px, drawn in the
same style as the shaded brawlers: flat colour, an outline in a darker shade, and soft
shading from the top left.

| Preview | File | Goes with | Idea |
|:---:|---|---|---|
| <img src="spark.png" height="48"> | `spark.png` | TNT | Lit fuse: sits on the tip of the fuse |
| <img src="sparkle.png" height="48"> | `sparkle.png` | Mage | Magic twinkles around the staff |
| <img src="flame.png" height="48"> | `flame.png` | Dragon | Small flames near the dragon |
| <img src="wisp.png" height="48"> | `wisp.png` | Ghost | Mist trailing low at the sides |
| <img src="leaf.png" height="48"> | `leaf.png` | Acorn | Leaves drifting around |
| <img src="bubble.png" height="48"> | `bubble.png` | Octopus | Bubbles rising |
| <img src="feather.png" height="48"> | `feather.png` | Peep | Feathers floating |

They are meant to be used sparingly: one to three small ones per card, as in
[`examples/`](../examples/). In the game they can be animated (drift, spin, fade), which the
still examples cannot show.

## Regenerating

The sprites are drawn by code, not cut from an image. Needs `numpy` and `Pillow`. Run this
from the repo root:

```bash
python3 scripts/make_effects.py
```
