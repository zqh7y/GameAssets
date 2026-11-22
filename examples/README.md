# Examples

Previews of how the brawlers look on the cards and in motion. These are **not game assets**.
They show the intended look, so the game can be built to match.

## Brawler cards

The cards from [`cards/`](../cards/), one per brawler. All seven:

![All seven cards](cards_all.gif)

Three of them stacked like on the real screen:

![Peep, TNT and Mage cards stacked](cards_screen.gif)

Every card as a full-size still:

![Peep's card](card_chick.png)
![TNT's card](card_tnt.png)
![Dragon's card](card_dragon.png)
![Mage's card](card_wizard.png)
![Ghost's card](card_ghost.png)
![Mr Nut's card](card_acorn.png)
![Octopus's card](card_octopus.png)

The skill texts are placeholders. Every card's own moving preview is about 8 MB, so they are
not kept here; [`cards/README.md`](../cards/README.md) says how to make them.

## Animations

The walk (top) and attack (bottom) of every brawler, from [`animations/`](../animations/):
the 4 drawn poses of each animation, played together with its smooth motion and its effects
(dust and sparkles for the steps, fire and sparks for the attacks), at 25 pictures a second.
Every brawler is drawn at the same size here, so the motion is easy to judge.

![All brawlers walking and attacking](animations.gif)

## Size lineup

![All brawlers at their relative sizes](size_lineup.jpg)

## Shading, before and after

Top row: the flat sprites. Bottom row: the shaded ones.

![Flat and shaded brawlers](shading_before_after.jpg)

## Regenerating

Needs `numpy` and `Pillow`. Run these from the repo root. The card previews:

```bash
python3 scripts/make_brawler_cards.py
```

The animation preview:

```bash
python3 scripts/extract_animations.py
```

The size lineup and the shading comparison:

```bash
python3 scripts/make_examples.py
```
