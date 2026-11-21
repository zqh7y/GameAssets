# GameAssets

Staging area for the next game's assets and working scripts. Once everything is ready,
it moves into the main project repo.

![Example cards](examples/cards_peep_mage_ghost.jpg)

## Layout

- [`brawlers/`](brawlers/): brawler sprites (transparent PNGs)
  - `<name>.png`: flat sprites
  - `shaded/<name>.png`: the same sprites with 3D shading
  - `shaded_mirrored/<name>.png`: the shaded sprites facing the other way
  - `sizes.json`: each brawler's display name and relative size
  - `source/`: the original images
- [`cards/`](cards/): backgrounds for the "choose a card" screen (basic and jackpot), with the original in `cards/source/`
- [`effects/`](effects/): five plain white shapes (dot, ring, glint, sliver, glow) that the brawlers' particle effects are built from
- [`examples/`](examples/): previews of how the brawlers look on the cards (not game assets)
- [`scripts/`](scripts/): helper scripts
  - `extract_brawlers.py` cuts the brawler sprites out of their source images
  - `shade_brawlers.py` adds the 3D shading to the flat sprites and makes the mirrored versions
  - `extract_cards.py` cuts the basic and jackpot cards out of their source image
  - `make_effects.py` draws the effect shapes
  - `make_card_examples.py` renders the previews in `examples/`
