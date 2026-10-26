# BalatroEngine

A seed-exact Python re-implementation of the game logic of **Balatro 1.0.1o**.
It is a library only: there is no user interface.

You give it a seed, a deck and a stake, then you play by calling methods. The
engine produces what the original game produces for the same seed and the same
choices: the deck order and every draw, the blinds, bosses and skip tags, the
shop queue (editions, stickers, prices), booster pack contents, scoring, every
joker, consumable, voucher, tag, deck and challenge, and the money.

```python
from balatro import Game

G = Game("TESTSEED", deck="red", stake="white").start_run()
G.GAME.round_resets.blind_choices.Boss          # 'bl_head'
G.act_select_blind()
[c.config.card_key for c in G.hand.cards]        # ['H_A', 'H_K', 'D_Q', 'S_9', 'C_9', 'C_5', 'D_5', 'C_4']
G.act_play([0, 1, 2, 3, 4])                      # play cards by their index in the hand
G.GAME.chips                                     # 56
```

It needs only the Python standard library (3.12+).

Full documentation is in [`docs/`](docs/README.md): getting started, the game
flow, the API reference, the state reference, front-end hooks, internals and
verification.

## Install

```
pip install .            # or: uv pip install .
```

## Playing a run

`Game(seed, deck="red", stake=1, challenge=None, profile=None, hands_order=None, game_speed=1, fast_forward=True)`
creates a run. `start_run()` sets it up and runs it until the first decision.
Every `act_*` method applies one player action, then runs the game until it
waits for the player again. Indices are 0-based and follow the on-screen order,
from left to right.

| Situation | Actions |
|---|---|
| Blind select | `act_select_blind()`, `act_skip_blind()`, `act_reroll_boss()` |
| Playing a round | `act_play(cards)`, `act_discard(cards)`, `act_sort("rank" \| "suit")` |
| Round won | `act_cash_out()` |
| Shop | `act_buy("shop_jokers", i)`, `act_buy("shop_jokers", i, use=True)`, `act_buy("shop_vouchers", i)`, `act_buy("shop_booster", i)`, `act_reroll()`, `act_end_shop()` |
| Booster pack | `act_pick(i, targets=None)`, `act_skip_pack()` |
| Most of the time | `act_use(i, targets=None)` uses consumable `i`; `act_sell("jokers" \| "consumeables", i)`; `act_move(area, from, to)` reorders jokers, hand or consumables |

`targets` are the hand cards a Tarot or Spectral card acts on.
An action that the game would not allow raises `balatro.IllegalAction`.

The same actions are available as plain commands:

```python
G.do({"cmd": "play", "cards": [0, 1, 2]})
G.legal_actions()   # [{'cmd': 'play', 'n': 8}, {'cmd': 'discard', 'n': 8}, {'cmd': 'sort', 'mode': 'rank'}, ...]
```

`legal_actions()` lists what can be done right now without changing the
game. Card choices are left open: `play` and `discard` take any 1 to 5 hand
indices, and a consumable that needs targets is listed with its `min` and
`max` number of targets.

Other things you can do:

- **Inspect the run.** `G.GAME` is the run state, with the same field names as
  `G.GAME` in the Lua source: `dollars`, `round_resets.ante`,
  `current_round.hands_left`, `hands`, `tags`, `used_vouchers`, and so on.
  The card areas are `G.deck`, `G.hand`, `G.play`, `G.discard`, `G.jokers`,
  `G.consumeables`, `G.shop_jokers`, `G.shop_vouchers`, `G.shop_booster` and
  `G.pack_cards`. Each card exposes `config.center.key`, `config.card_key`
  (for example `'H_A'`), `edition`, `seal`, `ability` and `cost`. `G.STATE` is
  one of `balatro.STATES`, and `G.is_game_over()` tells you whether the run
  has ended.
- **Branch.** `G.clone()` returns an independent copy, so you can explore a
  line of play without touching the original run. This works even while
  events are still pending.
- **Look ahead.** `G.next_draws(n)` lists the next `n` cards the deck will
  deal, in order. The deck is reshuffled when each round starts.
- **Read it quickly.** `print(G.summary())` shows the current situation:
  blind, money, jokers, consumables, hand, and the shop or pack contents.
- **Dump the state.** `G.snapshot()` returns the whole state as plain data.
- **Get the last score.** `G.last_score` holds the last hand's chips, mult and
  score.

`examples/greedy_bot.py` plays whole runs with a simple strategy; it is a
short, complete example of driving the engine.

### For front ends

A user interface needs a few things the game only shows on screen. None of
them changes the run.

- **What the player sees happen.** `G.start_feedback()` starts recording, and
  `G.stop_feedback()` stops and returns the list. Each entry has a `type` and
  `t`, the real time in seconds at which the game shows it at 60 fps:

  | `type` | Fields | What the game shows |
  |---|---|---|
  | `hand` | `handname`, `level`, `chips`, `mult`, `chip_total` (only those that change) | the scoring panel |
  | `card_text` | `card`, `effect` (`chips`, `mult`, `x_mult`, `dollars`, `again`, `debuffed`, `swap`, `message`), `amount`, `message`, `held`, `edition` | a pop-up over a card |
  | `hand_scored` | `hand`, `chips`, `mult`, `score`, `round_score` | the hand's total |
  | `round_score` | `chips` | the round score set (back to 0 at cash out) |
  | `dollars` | `amount`, `total` | money changing |
  | `status_text` | `text` | text over the play area ("Not Allowed!") |
  | `card_moved` | `card`, `to` (area name) | a card arriving in an area |
  | `card_flipped` | `card`, `facing` | a card turning over |
  | `card_removed` | `card`, `area` | a card leaving the game |
  | `card_juiced` | `card` | a card wiggling: the joker that made a scored or held card's effect |
  | `card_changed` | `card`, `change` (`edition`, `seal`) | a card shining with its new edition or seal (Aura, Hex, Déjà Vu...) |
  | `attention_text` | `card`, `key` (localization key: `k_nope_ex`) | a big text over a card (The Wheel of Fortune's "Nope!") |
  | `card_unlocked` | `key`, `set` | the "Unlocked!" notification (an unseeded run, `seeded=False`) |

  `card` is the card's `sort_id`, which never changes during a run.
- **The hand being selected.** `G.preview_hand(cards)` gives what the game
  shows while those hand cards are selected: the poker hand, its level, chips
  and mult, the scoring cards, and whether the boss blind forbids it.
- **The cash-out rows.** `G.round_eval_rows` lists the round evaluation rows
  as `(label, dollars)`.
- **Sprites.** `balatro.data.sprites()` gives where each card, blind, tag,
  seal and sticker is drawn in the game's sprite sheets. It is generated by
  `tools/lua/extract_sprites.lua`.

### Seed analysis

```python
from balatro.analyzer import analyze
print(analyze("TESTSEED", antes=2, rerolls=1).to_text())
```

This follows the seed-finder convention. It selects and wins every blind
without playing a hand, opens and skips both packs in every shop, rerolls the
shop `rerolls` times and buys nothing. For each ante it lists the boss, the
voucher, the skip tags, the first hand of each blind, the shop cards and the
contents of each pack. The `SeedReport` it returns is a dataclass.

`balatro.quick.Ante1(seed, deck)` is a fast path for seed searching. It gives
the ante-1 tags, boss, voucher and first hand, at about 10,000 seeds per
second on one core. `examples/find_royal_flush.py` uses it.

## How it reproduces the game

### Randomness

All of Balatro's randomness goes through `pseudohash`, `pseudoseed` and
`pseudorandom` in `functions/misc_functions.lua`. Each kind of decision has
its own stream of values, stored in `G.GAME.pseudorandom[key]` and keyed by
names like `'boss'`, `'Joker1sho1'` or `'soul_Tarot1'`. A stream advances only
when it is used. `pseudorandom` reseeds LuaJIT's `math.random`, a Tausworthe
generator, and draws from it. `balatro/rng.py` reproduces all of this bit for
bit, including LuaJIT's generator, the sorting inside `pseudorandom_element`,
`pseudoshuffle`, and the NaN stream that some seeds hash to.

### Timing

Balatro runs its game logic through an event queue: one blocking event per
frame, plus timed events that wait on the game clock. Several effects happen
in timed animation events, such as a destroyed card being removed when its
dissolve animation ends, an eaten joker disappearing, or a booster pack
filling up. In those cases, *when* an effect lands relative to the rest of the
queue changes what the game does. For example, a joker cut by Ceremonial
Dagger may or may not be gone before the hand is drawn, and a card destroyed
by Trading Card may or may not still be in hand when the replacements are
counted.

The engine therefore runs the game frame by frame, exactly as `Game:update`
does:

- `balatro/events.py` is a port of the event manager.
- Every event the game queues is reproduced with its trigger, delay and
  blocking flags, including events whose only role is an animation delay.
- The game clock uses the game speed setting and the speed-up during long
  scoring sequences.
- The few UI movements that game logic waits for are reproduced too: the shop
  and the round evaluation panel sliding in.

The reference is the game at its default settings: 1× game speed, 60 frames
per second, and a 16:9 window. Pass `game_speed=0.5`, `2` or `4` to match
those settings instead.

Running every frame costs time, so by default the engine skips the work of
frames in which nothing can happen: only the clocks and the moving UI panels
advance. This gives exactly the same run as frame-by-frame execution, which
the tests check, at about 50,000 frames per second. A typical action takes a
few milliseconds. Pass `fast_forward=False` to run every frame in full.

The player is assumed to act once the game is idle. When cards are selected
for a play, a discard or a consumable, the engine lets the game settle before
the button is pressed, as a player does.

### Structure

`balatro/` mirrors the Lua files, keeping the same names and structure so that
every rule can be checked against the source:

| Python module | Lua source |
|---|---|
| `game.py` | `game.lua` (state machine, `start_run`, frame loop) |
| `state_events.py` | `functions/state_events.lua` (play, discard, scoring, end of round) |
| `common.py` | `functions/common_events.lua`, `functions/misc_functions.lua` |
| `buttons.py` | `functions/button_callbacks.lua` |
| `card.py`, `jokers.py`, `consumables.py` | `card.lua` |
| `cardarea.py`, `blind.py`, `tag.py`, `back.py` | `cardarea.lua`, `blind.lua`, `tag.lua`, `back.lua` |
| `poker.py` | `evaluate_poker_hand` and related functions |

The static data comes straight out of the game: centers, blinds, tags, pools
*and their order*, poker hands and challenges. It lives in
`balatro/data/game_data.json`, which `tools/lua/extract_data.lua` generates.
`balatro/data/sprites.json` (sprite sheet positions, for user interfaces only)
comes from `tools/lua/extract_sprites.lua`.

## Verification against the original game

`tools/lua/boot.lua` runs the **unmodified** game headlessly under LuaJIT,
with a stubbed `love` table. `tools/lua/oracle.lua` drives it through the
game's own button callbacks and dumps the complete state after every action,
including every RNG stream, both at the same settings as the engine.

```
python -m balatro.oracle.fuzz --runs 20 --seed 1            # random legal play, compared after every action
python -m balatro.oracle.fuzz --sweep jokers                # one run per joker (also: consumables, vouchers, bosses, tags)
python -m balatro.oracle.fuzz --gamespeed 4                 # the other game speed settings
python -m balatro.oracle.replay fails.jsonl --verbose       # replay a failure step by step
python tools/scenarios.py                                   # targeted timing races (Ceremonial Dagger, Trading Card, ...)
```

The fuzzer plays random legal actions across all decks, stakes and
challenges. It covers shops, packs, consumables, boss rerolls, skips, selling
and reordering. To reach later content it occasionally adds money, jokers,
forced bosses, ante jumps or a won blind; these helpers involve no randomness.
The oracle needs `luajit` and the game's extracted Lua source, either in
`../balatro_src` next to this repository or in the `BALATRO_SRC` directory.

## Exactness notes and known limits

- **Profile and unlocks.** What is unlocked and discovered changes the
  pools (locked jokers and vouchers are left out; some tags need a discovered
  edition or joker). The default, `Profile.everything()`, is the seed-finder
  convention; `Profile.fresh()` is a new save. A seeded run (the default,
  `seeded=True`) never unlocks or discovers anything, as in the game. With
  `Game(..., seeded=False)` the run unlocks and discovers as an unseeded run
  does (progress.py: `check_for_unlock`, `unlock_card`, `discover_card` at
  the game's places), so new unlocks enter the pools for the rest of the run;
  `G.PROFILE.progress` lists them, and the oracle checks them
  (`python -m balatro.oracle.fuzz --profile fresh --unlocks`). The checks the
  game makes on the main menu (career stats, discovered blinds) are
  `Profile.with_main_menu_unlocks()`, for between runs. Continuing a run from
  the main menu is the `{"cmd": "continue"}` command (it can unlock
  Throwback). Ties in the order of locked items with the same `order` may
  differ from LuaJIT's sort; only nested unlocks within one check could tell.
- **To Do List, Orbital Tag hand, The Ox tie-break.** These depend on the
  order of `pairs(G.GAME.hands)`, which follows LuaJIT's string hashes. Those
  hashes use a random seed per process, so the order changes every time the
  game is launched. The seed decides *which position* is chosen. Pass
  `hands_order=` to `Game` to match a particular session.
- **Timing.** The real game's frame times jitter. A race that the default
  timeline decides by a frame or two can go either way in the real game. Races
  decided by more than that match.
- **Cosmetic only.** The artwork variant of the first-shop Buffoon pack and of
  the Charm and Meteor tag packs comes from LuaJIT's global random state.
  Both variants are identical in play.
- **Sort ties.** Sorting the hand breaks ties between cards of the same rank
  and suit by the game's internal UI node counter. The engine uses creation
  order instead. They differ only for cards whose suit was changed by a Tarot,
  and only very late in a run.
- **Not modelled.** The game's own save and continue (use `clone()`; the
  `continue` command has the one effect continuing has on a run), the
  achievements, the tutorial (seed `TUTORIAL`), and actions taken while an
  animation is still running.

## Tests

`make test`, `make test-all`, `make lint`, `make check` and `make build`
wrap the commands below (`make` lists them).

```
python -m pytest              # unit tests; the oracle tests run if luajit and the game source are present
python -m pytest -m slow      # a short differential fuzz run
```

`tests/test_golden.py` replays runs recorded from the original game
(`fuzz --record`, stored in `tests/vectors/golden.jsonl`) and compares the
complete final state, so it checks the engine against the game without
needing LuaJIT.

## CI and releases

`.github/workflows/ci-cd.yml` runs on every push and pull request (`main`,
`dev`):

- the tests (`-m "not slow"`) on Python 3.12 and 3.13. The oracle tests are
  skipped there, since CI has no game source, but the golden runs still run;
- `ruff check` (pyflakes and syntax errors, set in `pyproject.toml`);
- the package build, checking that the wheel includes `balatro/data`.

To release, run the oracle tests locally first. Then set `version` in
`pyproject.toml`, commit, and push a tag `v<version>`
(`git tag v0.5.0 && git push origin v0.5.0`). The workflow checks that the tag
matches the version, and publishes a GitHub release with the wheel and the
source archive. BalatroWebAPI then moves to the new tag (its
`[tool.uv.sources]`, then `uv lock`).

## Legal

Balatro is © LocalThunk (published by Playstack). This is an unofficial fan
project, not affiliated with or endorsed by them. The game's source is not
included. `balatro/data/game_data.json` and `balatro/data/sprites.json` are
generated from your own copy of the game by `tools/lua/extract_data.lua` and
`tools/lua/extract_sprites.lua`, and the oracle needs the game files to run.
