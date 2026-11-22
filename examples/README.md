# Examples

Previews of how the brawlers look on the cards. These are **not game assets**. They show the
intended look, so the game can be built to match.

## Brawler cards

The new card design: wide and short, one per brawler, from
[`cards/brawlers/`](../cards/brawlers/). Three of them stacked like on the screen:

![Peep, TNT and Mage cards stacked](cards_screen.gif)

All seven, as stills:

![Peep's card](card_chick.png)
![TNT's card](card_tnt.png)
![Dragon's card](card_dragon.png)
![Mage's card](card_wizard.png)
![Ghost's card](card_ghost.png)
![Mr Nut's card](card_acorn.png)
![Octopus's card](card_octopus.png)

The skill texts are placeholders. Every card's own moving preview is about 8 MB, so they are
not kept here; `cards/brawlers/README.md` says how to make them.

## Earlier cards

The first, upright card design, with groups of brawlers on the basic and jackpot cards.

![Peep, Mage and Ghost on cards](cards_peep_mage_ghost.jpg)

![Mr Nut, TNT and Dragon on cards](cards_acorn_tnt_dragon.jpg)

![Octopus, Dragon and TNT on cards](cards_octopus_dragon_tnt.jpg)

What each card shows:

- **A group, not one brawler:** "+5 Peep" shows five Peeps.
- **True sizes:** every brawler is drawn at its own size from [`brawlers/sizes.json`](../brawlers/sizes.json),
  so a Peep is half as tall as a Mage. A group is only shrunk if it would not fit in the window.
- **Shaded brawlers:** the 3D-shaded sprites from [`brawlers/shaded/`](../brawlers/shaded/).
- **Mixed directions:** the brawlers in a group look in different directions, using the
  mirrored sprites from [`brawlers/shaded_mirrored/`](../brawlers/shaded_mirrored/), with
  slightly different sizes and tilts. The mirrored TNT still reads "TNT".
- **Grounding:** each brawler has a wide soft shadow plus a small dark one under its feet, the
  back row fades slightly for depth, and there is a soft glow behind the group.
- **Minimal particle effects:** three to five flat shapes per card from
  [`effects/pieces/`](../effects/pieces/), each brawler using its own cluster: feathers for
  the Peep, a spark on every TNT fuse, embers for the Dragon, glints at the Mage's staff, mist
  for the Ghost, leaves for Mr Nut and bubbles for the Octopus. In the game these would move;
  the previews show one moment.
- **Label:** gold number and white name, with a dark outline and a drop shadow.

The label font is a placeholder (whatever bold font the script finds), not the game's font.

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

Needs `numpy` and `Pillow`. Run this from the repo root:

```bash
python3 scripts/make_card_examples.py
```

The animation preview comes from a different script:

```bash
python3 scripts/extract_animations.py
```

The brawler card previews come from another one:

```bash
python3 scripts/make_brawler_cards.py
```
