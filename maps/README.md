# Maps

The map at the top of the main screen: a path seen from above, between two walls, that the
brawlers walk along from left to right while they fight. Each area has its own map. The first
one is the forest.

![The whole forest map](../examples/map_forest.jpg)

That is the whole forest map, at a third of its size. It is about 5 screens long, and its right
edge joins its left edge, so the brawlers can walk along it forever.

The map is alive. The trees, bushes, ferns, grass and flowers sway in gusts of wind that roll
along the forest. Leaves and pink petals fall from the trees, butterflies flutter over the
grass, and now and then a bird flies over and its shadow crosses the path. When a brawler walks
through a flower, a tuft of grass or a little bush, the plant is pushed aside and pressed down,
pops a few petals or leaves, and wobbles back once the brawler has passed. Plants in front of a
brawler are drawn in front of it, so the brawlers walk *through* them.

[`map_forest.mp4`](../examples/map_forest.mp4) shows all of it: three brawlers walking once
round the map (35 seconds). One picture of it:

![One screen of the forest with three brawlers](../examples/map_forest_screen.jpg)

## Files

Each area has a folder (`forest/`):

| File | What it is |
|---|---|
| `ground.png` | The whole map without the decorations that move: 5184 × 1024 px. It has the rocks, stumps, logs, pebbles and fallen leaves, and the shadows of everything |
| `props/<name>.png` | Every decoration, cut out. The moving ones are drawn over the ground by the game |
| `effects/<name>.png` | The small things that move: butterflies, the bird, falling leaves, petals |
| `map.json` | Where everything goes and how it moves |
| `map.png` | The whole map with every decoration, standing still. For a quick start, or a game that does not animate the map |
| `tile.png` | The bare map, without any decoration: 864 × 1024 px. It repeats seamlessly side by side |
| `source/` | The three original pictures |

## Drawing the map

- **Size:** one screen shows 1024 px of the map's width, at its full height. Scale the map so
  its height fills the map panel; a square panel then shows one screen.
- **Scrolling:** move the map to the left as the brawlers walk. When the scroll reaches the end
  of the map (5184 px), carry on from 0: the end joins the start seamlessly. Decorations and
  effects near either end are drawn again one map length further left or right.
- **Where characters stand:** on the open grass, between y = 380 and y = 740 (`walk`).
  Enemies too.
- **Order, back to front:**
  1. `ground.png`, with the rows of trees in it swaying (see the wind, below)
  2. the shadows of the brawlers, butterflies and birds
  3. leaves and petals lying on the ground
  4. the moving decorations and the characters together, sorted by the y of their feet: the
     one further down is drawn later. That is what lets a brawler walk through a flower.
  5. leaves and petals in the air, then the butterflies, then the birds
- **Very wide pictures:** some phones cannot show a picture more than 4096 px wide. If the game
  has to run on those, cut `ground.png` into two or more pieces and draw them side by side.

[`map.json`](forest/map.json) has:

| Field | Meaning |
|---|---|
| `size` | Width and height of the map |
| `loops` | `true`: the right edge joins the left edge |
| `screen` | How much of the map's width one screen shows (with a square map panel) |
| `walk` | Top and bottom (y) of the open grass where characters stand |
| `ground`, `still` | The two pictures of the whole map: without the moving decorations, and with everything |
| `tile` | The bare tile, and how many times it repeats across the map |
| `effects` | The pictures of the small things that move |
| `motion` | How everything moves, below |
| `props` | Every decoration, in the order they are drawn (back to front) |

For each decoration in `props`:

| Field | Meaning |
|---|---|
| `file` | Its picture |
| `x`, `y` | Where its foot goes on the map: the middle of the bottom of its trunk, stem or stone |
| `foot` | The row of its foot in its own picture |
| `scale` | How much to scale its picture |
| `shadow` | How strong its shadow on the ground is: 1, ½ for flowers and grass, 0 for pebbles and leaves |
| `sway` | How much it sways in the wind; 0 for the ones that stay still (they are in `ground.png`) |
| `reacts` | `true` for the plants on the grass that characters walk through |

Draw a decoration scaled by `scale`, with its top left corner at `x - width × scale / 2` and
`y - foot × scale`.

## How everything moves

All times are in ms and all sizes in px of the map; every number is in `motion` in `map.json`.

**The wind** (`motion.wind`) is a few waves rolling along the map from left to right. At a
spot `x` of the map, at the moment `t`:

```
wind(t, x) = sum of  strength × sin(2π × (t / period_ms − x × gusts / map width))
```

It goes from about −1 to 1. A whole number of `gusts` fits along the map, so the wind joins up
where the map loops.

**Decorations sway** with the wind at their foot. Each one leans by
`lean = sway × wind(t, x)`: every point of it moves sideways by `lean` times its height above
the foot, so the foot stays put and the top moves most (a skew). The trees' tops move about
5 px, the grass 3 to 4 px.

**The rows of trees in the ground picture** sway too. In the rows of `ground.png` above the
cliff and along the bottom (`bands`), every pixel moves sideways by
`shift_px × wind(t, x) × weight`: the weight is 1 from `full` on and fades to 0 at `still`, so
the trunks and the cliff edge stay put. In a game this is a small shader on the ground.

**Plants that are walked through** (`reacts`, settings in `motion.react`). A character is in
a plant while their feet are less than `depth_px` from its foot in y, and closer in x than
`reach` times the plant's width plus a quarter of the character's width. Meanwhile, the plant
is pushed forward, leaning by `lean`, and pressed down to `press` of its height. It moves there
and back on a spring: `spring_hz` wobbles a second, losing them at `damping` (0 would wobble for
ever, 1 not at all). The spring's lean adds to the wind's.

When a character steps into a plant, `count` petals or leaves pop out of it (`pops` says
which: petals of the flower's colour, green leaves for grass, ferns and bushes). Each one is
`size_px` big and starts inside the plant, a third to two thirds of the way up. It is thrown up at `up_px_s`
and forward at `forward_px_s`, falls back under `gravity_px_s2` while it spins and turns over,
lies on the ground for `rest_ms` and fades out over `fade_ms`.

**Falling leaves and petals** (`motion.falling`). `per_s` of them start falling every second,
anywhere on the screen, from the trees on top of the cliff (`from`). They are green leaves, pink
petals from the pink trees and the odd autumn leaf, in the proportions given by `sprites`.
`on_cliff` of them land on top of the cliff, and the rest fall past it and land on the path
(`land`). They fall at `speed_px_s`, carried right at `drift_px_s`, swinging `swing_px` from
side to side, turning and flipping over. Then they lie still for `rest_ms` and fade out.
A few (`front_per_s`) fall from the trees at the front, out of the bottom of the screen. Once
started, a leaf belongs to the map, so it moves with it as the map scrolls.

**Butterflies** (`motion.butterflies`). There are `per_screen` of them for every screen of the
map's length, each with its own spot on the grass to wander around: up to `wander_px` sideways
and up and down, slowly, with a quick flutter on top. They fly `height_px` above the ground,
with a small shadow under them, and beat their wings every `flap_ms`: a beat is the wings
closing and opening again, drawn by squeezing the picture sideways. They lean a little toward
where they are going.

**Birds** (`motion.birds`). Every `every_ms` a bird crosses the screen, from either side, at
`speed_px_s`, in a gentle curve (`curve_px`) somewhere in `y`. It beats its wings `beats` times
(each beat `flap_ms`, drawn by squeezing the picture up and down) and glides for `glide_ms`,
over and over. Its shadow, a dark blurred copy of it at `shadow` strength, falls `shadow_px`
below and to the right of it. The birds fly over the screen rather than the map, so they do not
scroll with it.

The previews play all of this with [`scripts/map_motion.py`](../scripts/map_motion.py), which
a game can follow.

## How it is made

Gemini cannot draw one sharp picture 5 screens long, so the map is built from three pictures:

- `source/base.jpg`: one square screen of the path, drawn so it can repeat side by side
- `source/props.jpg`: the decorations, on a magenta screen
- `source/effects.jpg`: the butterflies, the bird, leaves and petals, on a magenta screen

The script then:

1. **Makes the base repeat seamlessly.** It lays the base's right end over its left start and
   joins them along the line where they look most alike. It also evens out the patches of
   light on the grass, which would otherwise line up in a row along the map.
2. **Cuts the decorations and effects out.** It paints a copy of the light green tree pink, to
   match the pink trees in the base, and pink copies of the white petals for them to drop. It
   cuts the fallen leaves on the decoration sheet apart, to fall from the trees as autumn
   leaves, and turns the bird to fly sideways: Gemini drew it heading up.
3. **Lays the tile out 6 times and spreads the decorations along it**, in lanes: trees on top
   of the cliff, rocks and plants at its foot, flowers on the grass, small plants along the
   bottom edge, and big trees and bushes at the front. They are placed at random, but the same
   way every time, so no two screens look the same.

The placement and the motion are described in `AREAS` at the top of
[`scripts/make_map.py`](../scripts/make_map.py): which decorations each lane uses and how
often, how far apart they are, how big each one is, how much everything moves, and a `seed`:
change it to shuffle the decorations.

To regenerate everything (needs `numpy` and `Pillow`, plus `ffmpeg` for the video; takes about
two minutes), run this from the repo root:

```bash
python3 scripts/make_map.py
```

## A new area

1. Ask Gemini for the area's three pictures. The forest's prompts are below: change what they
   say about the forest. Attach a picture of the forest map with the first one, so the new area
   keeps the same style, and the new area's base with the other two.
2. Save them in `maps/<area>/source/` as `base.jpg`, `props.jpg` and `effects.jpg`.
3. Add the area to `AREAS` in `scripts/make_map.py`: its decorations in reading order, how wide
   each one is on the map, its lanes, and what moves.
4. Run the script.

<details>
<summary>The forest's prompts</summary>

The base, with the style reference attached:

```text
Use the attached picture ONLY as the art style reference: the same cozy cartoon style, the same thick dark-brown outlines, the same soft shading, the same warm colours and the same amount of detail. Do NOT copy its layout or its camera angle.

Draw a square (1:1) background for a mobile idle RPG: a piece of a forest path seen from above. The camera looks down from high above at a steep angle, like in top-down mobile games: you see the tops of things and a little of their front. There is no sky and no horizon.

The path runs straight across the picture from the left edge to the right edge, between two walls. A small team of heroes will walk along it from left to right and fight enemies on it, so it must be wide, flat and open. The heroes are small, each about one eighth of the picture tall.

From top to bottom:
1. Top quarter: a rocky cliff wall, warm grey-brown stone with a few cracks, running straight and level across the whole width. On top of the cliff grows a thick forest: a row of round, fluffy treetops.
2. Middle half: the path, soft green grass, flat and open. Keep it almost empty: only tiny grass tufts, a few tiny pebbles and a few tiny flowers, spread thinly and evenly. A soft shadow along the foot of the cliff.
3. Bottom quarter: the grass ends at a low rocky edge, and below it the tops of leafy bushes and trees fill the bottom of the picture, running straight across the whole width.

Very important:
- This picture will be repeated side by side many times to make one long map, so it must tile seamlessly from left to right. The cliff, the rocky edge and the grass continue straight off the left and right edges at exactly the same height on both sides.
- No landmarks anywhere: no pond, no big rock, no fallen tree, no special tree. Everything is spread evenly, so the repeat does not show.
- Light comes from the top left, shadows fall to the bottom right.
- No characters, no animals, no enemies, no text, no UI, no border.
```

The decorations, in a new chat, with the base attached:

```text
Use the attached picture as the reference: the same cozy cartoon style, the same thick dark-brown outlines, the same shading, the same colours, and the same camera angle, seen from above. Make a NEW picture, do not edit the attached one.

Draw a sheet of separate forest decorations for this map, on a solid flat magenta background (#FF00FF) with no gradient. Square picture (1:1). Every item stands alone, complete, with plenty of empty magenta around it: no item touches another item or the edge of the picture.

The items:
- 2 big round leafy trees, one dark green, one lighter yellow-green, with their short trunks showing
- 1 tall pine tree
- 1 big leafy bush and 1 small bush
- 1 big mossy rock and 1 small rock
- 1 tree stump and 1 fallen log
- 1 fern
- 1 small cluster of red mushrooms with white dots
- 3 small flower patches: white daisies, yellow flowers, blue flowers
- 1 grass tuft
- 1 small group of pebbles
- 1 small group of fallen leaves

Draw the trees big (each about a quarter of the picture tall) and the small things small.

Rules:
- No shadows on the background under the items, no glow: just the items on flat magenta.
- Light from the top left, like the attached picture.
- No pink or purple on any item, because the magenta background will be removed by its colour.
- No characters, no text, no labels, no numbers.
```

The small things that move, in a new chat, with the base attached:

```text
Use the attached picture as the reference: the same cozy cartoon style, the same thick dark-brown outlines, the same shading and colours, seen from above. Make a NEW picture, do not edit the attached one.

Draw a sheet of small separate details that will move around on this forest map, on a solid flat magenta background (#FF00FF) with no gradient. Square picture (1:1). Every item stands alone, complete, with plenty of empty magenta around it: no item touches another item or the edge of the picture.

The items:
- 3 butterflies seen from above, wings fully open, head at the top: one white, one yellow, one light blue
- 1 small brown bird seen from above, flying to the right with its wings spread wide
- 4 single small green leaves, different shapes, like the leaves of the trees
- 3 single white flower petals
- 3 single yellow flower petals
- 3 single light blue flower petals

Draw the butterflies and the bird big (each about a fifth of the picture wide) and the leaves and petals small (about a tenth of the picture).

Rules:
- No shadows on the background, no glow, no motion lines: just the items on flat magenta.
- Light from the top left, like the attached picture.
- No pink or purple on any item, because the magenta background will be removed by its colour.
- No text, no labels, no numbers.
```

</details>
