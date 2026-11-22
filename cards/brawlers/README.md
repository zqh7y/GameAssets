# Brawler cards

The cards for the "choose a card" screen: wide and short, three of them stacked on top of each
other. Every brawler has its own card in its colour, with one big 3D object floating on it and
about 100 small ones drifting across it, as if a breeze were blowing through.

![Three cards stacked like on the screen](../../examples/cards_screen.gif)

| Brawler | Folder | Card | Big object | Small objects |
|---|---|---|---|---|
| Peep | `chick/` | Yellow | Feather | 6 feathers |
| TNT | `tnt/` | Red | Dynamite stick | 4 sparks |
| Dragon | `dragon/` | Orange | Flame | 9 flames and embers |
| Mage | `wizard/` | Blue | Golden sparkle | 9 stars |
| Ghost | `ghost/` | Purple | Spirit flame with a heart | 6 wisps |
| Mr Nut | `acorn/` | Brown | Maple leaf | 6 leaves |
| Octopus | `octopus/` | Pink | Bubble | 6 bubbles and droplets |

A still of every card is in [`examples/`](../../examples/) (`card_<brawler>.png`).

## Files

Each brawler has a folder:

| File | What it is |
|---|---|
| `card.png` | The card, 960 × 300 px, with nothing on it |
| `object.png` | The big 3D object that floats on the right |
| `particles/<n>.png` | The small ones that drift across the card, biggest first (as many as were drawn, 4 to 9) |

[`cards.json`](cards.json) has the rest: each brawler's name and skill text, where everything
goes on the card, and how everything moves. The name and skill are written with
[`fonts/LilitaOne-Regular.ttf`](../../fonts/).

The skill texts are placeholders for now.

## How a card is drawn

All positions are in pixels of the card (960 × 300), from its top left corner. Draw, back to
front:

1. **The card.**
2. **The particles**, far layer first. Each one appears, drifts with the wind and fades out,
   over and over. Far ones are smaller, slower, paler (blended toward the card's colour by
   `fade_to_card`) and a little blurred. Some flip over as they fall, like real feathers. They
   are cut off at the card's edge. Each brawler places them its own way (`particle_seed`), so
   stacked cards do not move in step.
3. **A shine** that sweeps across the card once in a while.
4. **The big object**, at `object.center`, its longest side `object_size` px, bobbing up and
   down and rocking, with a soft shadow on the card. It pops out over the card's top edge.
   Round and wide objects (the sparkle, the leaf, the bubble) are drawn a little smaller than
   the tall, thin feather, so they look the same size.
5. **The brawler**, its feet at `brawler.feet`, `brawler.height` px tall but no wider than
   `brawler.max_width` (so the wide Octopus fits), breathing and rocking gently, with a soft
   shadow under its feet. It pops out over the card's top edge. It uses the shaded sprite from
   [`brawlers/shaded/`](../../brawlers/shaded/).
6. **The name**, white to cream, with a thick dark outline and a soft shadow.
7. **The skill text**, one or two lines: dark on a light card (Peep, Octopus), white with a
   dark edge on a darker one.

The motion numbers in `cards.json` (`_ms` values are milliseconds) all repeat within
`loop_ms`, so a recorded preview loops cleanly; a game can simply let them run. On the screen
preview each card runs a second behind the one above, so the shines sweep down one card after
another.

## Source

The original sheets are in [`source/`](source/), on a green screen:

- `chick.jpg`: Peep alone, the empty card at the top, the big object below it on the left and
  the small ones on the right
- `tnt-dragon-wizard.jpg` and `ghost-acorn-octopus.jpg`: three brawlers each, one per row, top
  to bottom as in the file name: the card on the left, the big object in the middle and the
  small ones on the right

In each brawler's part of a sheet, the widest piece is the card, the biggest of the others is
the big object, and the rest are the small ones.

The cards on the sheets are taller than wanted (1.5 to 2.3 times as wide as tall), so the
script stretches them to 3.2 times as wide as tall. They are smooth gradients, so that does not
show, and the corners are drawn again so they stay round.

To regenerate everything (needs `numpy` and `Pillow`; takes about half a minute per brawler),
run this from the repo root:

```bash
python3 scripts/make_brawler_cards.py
```

That writes the stills and the screen preview. Every card's own moving preview is about 8 MB,
so they are not kept in the repo; to make them, add a folder to write them to:

```bash
python3 scripts/make_brawler_cards.py --gifs previews
```
