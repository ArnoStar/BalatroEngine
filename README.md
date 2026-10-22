# BalatroEngine

A seed-exact Python re-implementation of **Balatro 1.0.1o**'s game logic.

Give it a seed and it reproduces the game exactly: deck order and every draw,
blinds, bosses, skip tags, vouchers, the whole shop queue (with editions,
Eternal/Perishable/Rental stickers, prices), booster pack contents, scoring,
joker effects, consumables, money — and, as you feed it the actions a player
takes, everything that follows from those actions.

```
$ python -m balatro analyze TESTSEED --antes 1 --rerolls 1
== Ante 1 ==  Boss: The Head   Voucher: Crystal Ball
  Small Small Blind              300 chips  skip tag: Economy Tag
        first hand: AH KH QD 9S 9C 5C 5D 4C
  ...
  Shop after Small:
    vouchers: Crystal Ball
    cards:    Raised Fist, Pareidolia, Splash, Smeared Joker (Holo)
    pack:     Buffoon Pack: Abstract Joker, Astronomer
    pack:     Jumbo Standard Pack: 9D, 6S+bonus, TH+steel, JC, TS*purple
```

No dependencies beyond the Python 3.13+ standard library.

## How Balatro's randomness works

All randomness goes through three functions in `functions/misc_functions.lua`:

* `pseudohash(str)` – a float hash of a string.
* `pseudoseed(key)` – every *key* (`'shuffle'`, `'boss'`, `'Tag1'`, `'cdt1'`,
  `'Joker1sho1'`, `'edisho1'`, `'soul_Tarot1'`, …) is its own stream stored in
  `G.GAME.pseudorandom[key]`, started at `pseudohash(key..seed)` and advanced
  with `(2.134453429141 + v*1.72431234) % 1` rounded to 13 decimals.
* `pseudorandom(seed)` – re-seeds LuaJIT's `math.random` (a Tausworthe
  generator) with that float and draws once.

Because every kind of decision has its own stream, a shop roll, a Lucky Card
check or a Wheel of Fortune spin always yields the same value for the n-th use
of its stream, no matter what else happened. What changes with the player's
choices is *how often* streams are used and *what the pools contain* (owned
jokers, cards currently on display, redeemed vouchers, pool flags, …).
`balatro/rng.py` reproduces all of it bit for bit, including LuaJIT's PRNG,
`pseudorandom_element`'s sorting (`sort_id` for cards, key order otherwise) and
`pseudoshuffle`.

## Usage

### Command line

```
python -m balatro analyze SEED [--deck red] [--stake white] [--antes 8] [--rerolls 2] [--json]
python -m balatro search --tags tag_uncommon tag_uncommon --hand H_A S_A --count 5
python -m balatro play SEED                 # play in the terminal, with `peek` (next draws) and `undo`
python -m balatro verify --runs 20          # differential test against the real game
```

`analyze` follows the convention of seed finders: every blind is selected and
beaten without playing, in each shop both packs are opened (and skipped) and
the shop is rerolled `--rerolls` times, nothing is bought.

`search` uses `balatro/quick.py`, a fast ante-1 path (≈10k seeds/s per core).

### Python

```python
from balatro import Game

G = Game("TESTSEED", deck="b_red", stake=1).start_run()
print(G.GAME.round_resets.blind_choices.Boss)           # 'bl_head'

G.act_select_blind()
print([c.config.card_key for c in G.hand.cards])         # the first hand
G.act_play([0, 1, 2, 3, 4])                              # play cards by hand index
print(G.GAME.chips, G.last_score)

G.act_discard([0, 1])
# ... act_skip_blind, act_reroll_boss, act_cash_out, act_buy(area, i, use=False),
#     act_reroll, act_end_shop, act_use(i, targets), act_sell(area, i),
#     act_pick(i, targets), act_skip_pack, act_move(area, frm, to), act_sort(mode)

what_if = G.clone()        # independent copy: explore a branch without touching G
```

The same commands are available as dicts: `G.do({"cmd": "play", "cards": [0, 1]})`.
Card areas mirror the game: `G.deck`, `G.hand`, `G.discard`, `G.play`,
`G.jokers`, `G.consumeables`, `G.shop_jokers`, `G.shop_vouchers`,
`G.shop_booster`, `G.pack_cards`. The run state is `G.GAME`, with the same field
names as `G.GAME` in the Lua source.

Fast ante-1 queries:

```python
from balatro.quick import Ante1
a = Ante1("3W88D4Y5")
a.tags, a.boss, a.voucher, a.first_hand()
```

## How it was built and verified

* `balatro/` is a close port of the game's Lua (`card.lua`, `blind.lua`,
  `tag.lua`, `back.lua`, `functions/*.lua`, `game.lua`), keeping the same
  structure and names, so every rule can be checked against the source.
* The static data (all centers, blinds, tags, pools *and their order*, poker
  hands, challenges) is extracted from the game itself:
  `luajit tools/lua/extract_data.lua` → `balatro/data/game_data.json`.
* **Ground truth:** `tools/lua/boot.lua` runs the *unmodified* original game
  headlessly under plain LuaJIT (a stubbed `love` table). `tools/lua/oracle.lua`
  drives it through the game's own button callbacks and dumps the complete
  state — including every RNG stream — after each action.
* `python -m balatro.oracle.fuzz` plays random legal actions (all 15 decks, all
  8 stakes, challenges, shops, packs, consumables, boss rerolls, skips, selling,
  reordering, forced bosses and ante jumps) on both and compares the full state
  after every action. `python -m balatro.oracle.replay` re-runs a failure step
  by step.

The oracle needs `luajit` and the extracted game source next to this
repository (`../balatro_src`) or in `BALATRO_SRC`.

## Exactness notes and known limits

* **Seeded runs.** In seeded runs the game never unlocks or discovers anything,
  so the profile is fixed for the whole run. The default `Profile.everything()`
  (all unlocked) is the seed-finder convention; `Profile.fresh()` models a new
  save (locked jokers/vouchers are not in the pools, the Rare/edition tags need
  their prerequisites discovered).
* **Session-dependent: To Do List, Orbital Tag hand, The Ox tie-break.** These
  pick from `pairs(G.GAME.hands)`, whose order depends on LuaJIT's string hashes.
  Since 2020 LuaJIT keys those with a random per-process seed, so in the real
  game this order changes from one launch to the next. The seed fixes *which
  position* is chosen; pass `hands_order=` to `Game` to match a session.
* **Cosmetic only:** the art variant of the first-shop Buffoon pack and of the
  Charm/Meteor tag packs is chosen from LuaJIT's global state (which animations
  also consume); both variants are identical.
* **Event timing.** The engine reproduces the game's event queue (one blocking
  event per frame, then the state machine, then `Card:update`). Effects the game
  runs in non-blocking timed events (dissolves, pack generation) are placed
  where they land at normal play speed.
* Not modelled: saving/continuing a run, the tutorial run (seed `TUTORIAL`).

## Tests

```
python -m pytest                 # unit tests; oracle tests run if luajit + game source are present
python -m pytest -m slow         # short differential fuzz run against the original game
```

## Legal

Balatro is © LocalThunk (published by Playstack). This is an unofficial fan
project, not affiliated with or endorsed by them. The game's source is not
included: `balatro/data/game_data.json` is generated from your own copy of the
game by `tools/lua/extract_data.lua`, and the oracle tooling needs the game
files to run.
