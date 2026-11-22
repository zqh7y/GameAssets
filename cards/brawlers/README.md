# Brawler cards

The cards for the "choose a card" screen: wide and short, three of them stacked on top of each
other. Every brawler has its own card in its colour, with one big 3D object floating on it and
about 100 small ones drifting across it, as if a breeze were blowing through.

![Peep's card](../../examples/card_chick.gif)

Done so far: Peep. The other brawlers follow the same design.

## Files

Each brawler has a folder:

| File | What it is |
|---|---|
| `card.png` | The card, 960 × 300 px, with nothing on it |
| `object.png` | The big 3D object that floats on the right (Peep's feather) |
| `particles/1.png` to `6.png` | The small ones that drift across the card, biggest first |

[`cards.json`](cards.json) has the rest: each brawler's name and skill text, where everything
goes on the card, and how everything moves. The name and skill are written with
[`fonts/LilitaOne-Regular.ttf`](../../fonts/).

The skill text is a placeholder for now.

## How a card is drawn

All positions are in pixels of the card (960 × 300), from its top left corner. Draw, back to
front:

1. **The card.**
2. **The particles**, far layer first. Each one appears, drifts with the wind and fades out,
   over and over. Far ones are smaller, slower, paler (blended toward the card's colour by
   `fade_to_card`) and a little blurred. Some flip over as they fall, like real feathers. They
   are cut off at the card's edge.
3. **A shine** that sweeps across the card once in a while.
4. **The big object**, at `object.center` and `object.height` px tall, bobbing up and down and
   rocking, with a soft shadow on the card. It pops out over the card's top edge.
5. **The brawler**, its feet at `brawler.feet` and `brawler.height` px tall, breathing and
   rocking gently, with a soft shadow under its feet. It pops out over the card's top edge.
   It uses the shaded sprite from [`brawlers/shaded/`](../../brawlers/shaded/).
6. **The name**, white to cream, with a thick dark outline and a soft shadow.
7. **The skill text**, one or two lines: dark on a light card, white on a dark one.

The motion numbers in `cards.json` (`_ms` values are milliseconds) all repeat within
`loop_ms`, so a recorded preview loops cleanly; a game can simply let them run.

## Source

The original sheets are in [`source/`](source/), one per brawler: the empty card at the top,
the big object below it on the left and the 6 small ones on the right, on a green screen.

The card on the sheet is taller than wanted (about 2.3 times as wide as tall), so the script
stretches it to 3.2 times as wide as tall. It is a smooth gradient, so that does not show, and
the corners are drawn again so they stay round.

To regenerate everything (needs `numpy` and `Pillow`; takes about half a minute per brawler),
run this from the repo root:

```bash
python3 scripts/make_brawler_cards.py
```
