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
- [`effects/`](effects/): small flat particle effects, one cluster per brawler, plus every single shape in `effects/pieces/` and the original in `effects/source/`
- [`animations/`](animations/): walk and attack animations for every brawler: 4 drawn poses each, the smooth motion that plays on top of them, and their effects (fire or a spark for an attack, dust or sparkles for the steps). `animations.json` describes how to play them. The originals are in `animations/source/`
- [`examples/`](examples/): previews of how the brawlers look on the cards and in motion (not game assets)
- [`scripts/`](scripts/): helper scripts
  - `extract_brawlers.py` cuts the brawler sprites out of their source images
  - `shade_brawlers.py` adds the 3D shading to the flat sprites and makes the mirrored versions
  - `extract_cards.py` cuts the basic and jackpot cards out of their source image
  - `extract_effects.py` traces the particle effects out of their source image
  - `extract_animations.py` turns the animation sheets into sprite strips and a moving preview
  - `brawler_motion.py` describes the smooth motion of every brawler's walk and attack
  - `animation_effects.py` cuts the attack and walking effects out of their sheets and fits each one to its brawler
  - `make_card_examples.py` renders the card previews in `examples/`
