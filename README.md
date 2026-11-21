# GameAssets

Staging area for the next game's assets and working scripts. Once everything is ready,
it moves into the main project repo.

## Layout

- [`brawlers/`](brawlers/): brawler sprites (transparent PNGs), with their originals in `brawlers/source/`
- [`cards/`](cards/): backgrounds for the "choose a card" screen (basic and jackpot), with the original in `cards/source/`
- [`scripts/`](scripts/): helper scripts
  - `extract_brawlers.py` cuts the brawler sprites out of their source images
  - `extract_cards.py` cuts out the basic card and builds the jackpot card from it
