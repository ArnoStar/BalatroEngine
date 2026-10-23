# Verification

The claim "same seed, same choices, same run" is checked against the
**original game**, run unmodified. This page describes the tools and how to
use them.

## The oracle: the original game, headless

`tools/lua/boot.lua` loads the game's own Lua source under LuaJIT, with a
stubbed `love` table instead of the LÖVE framework: no window, no sound.
`tools/lua/oracle.lua` drives it through the game's own button callbacks,
reading JSON commands on stdin and answering with the complete state after
each one (the [snapshot](state-reference.md#snapshot) format, including every
RNG stream).

The oracle runs the game at the engine's reference settings:

- game speed 1 (or `--gamespeed`), 60 frames per second;
- clocks reset to 0 when a run starts;
- for a play, a discard or a targeted consumable: the cards are selected,
  the game is let settle, then the button is pressed;
- "settled" means four quiet frames in a row, as in `Game.settle`.

Requirements: `luajit` on the `PATH`, and the game's extracted Lua source
(`game.lua`, `card.lua`, ..., from the game's executable, which is a zip
archive) in `../balatro_src` next to this repository, or in the directory
named by `BALATRO_SRC`.

From Python:

```python
from balatro import Game
from balatro.oracle import Oracle, diff, normalize

with Oracle() as o:
    r = o.send({"cmd": "start", "seed": "TESTSEED", "deck": "Red Deck", "stake": 1})
    G = Game("TESTSEED", hands_order=r["state"]["hands_order"]).start_run()
    for cmd in [{"cmd": "select_blind"}, {"cmd": "play", "cards": [0, 1, 2, 3, 4]}]:
        r = o.send(cmd)
        G.do(cmd)
        assert not diff(normalize(G.snapshot()), normalize(r["state"]))
```

Pass the oracle session's `hands_order` to the engine. Each LuaJIT process
iterates `G.GAME.hands` in its own order (see
[API reference](api-reference.md#creating-a-run)).

## Differential fuzzing

```
python -m balatro.oracle.fuzz --runs 20 --seed 1
```

The fuzzer plays random legal actions on the engine and on the original game
side by side, and compares the complete state after every action. Each run
picks a random seed, deck, stake and sometimes a challenge. Play covers
shops, packs, consumables, boss rerolls, skips, selling and reordering. To
reach later content it occasionally adds money or jokers, forces a boss,
jumps antes or wins a blind about to be lost. These helpers use no
randomness.

| Option | Default | |
|---|---|---|
| `--runs N` | 10 | number of runs |
| `--steps N` | 300 | actions per run at most |
| `--max-ante N` | 9 | stop a run beyond this ante |
| `--seed N` | 0 | the fuzzer's own RNG seed (runs are reproducible) |
| `--deck NAME`, `--stake N` | random | fix the deck or the stake |
| `--money-prob`, `--joker-prob`, `--ante-prob`, `--boss-prob`, `--challenge-prob`, `--win-prob` | 0.5, 0.3, 0.15, 0.3, 0.15, 0.7 | how often the helpers are used |
| `--sweep KIND` | | one run per item, injected at the start: `jokers`, `consumables`, `vouchers`, `bosses`, `tags` |
| `--sweep-offset`, `--sweep-step` | 0, 1 | split a sweep between processes |
| `--profile all\|fresh` | `all` | the profile |
| `--gamespeed X` | 1 | the game speed setting (0.5, 1, 2, 4) |
| `--out FILE` | | append failing runs (as JSON lines) to FILE |
| `--record FILE` | | append passing runs (commands and the game's final state) to FILE |

Each run prints `OK` or `FAIL` with the first difference.

## Replaying a failure

```
python -m balatro.oracle.replay fails.jsonl --index 0 --verbose
```

Replays a logged run on both sides, step by step, and shows where they part.
`--gamespeed` overrides the speed of the log.

## Timing scenarios

```
python tools/scenarios.py                 # all
python tools/scenarios.py dagger_juggler trading_card
```

Targeted setups for the cases where timing decides the outcome:

- Ceremonial Dagger slicing Juggler, Troubadour or Turtle Bean;
- Madness;
- Trading Card;
- Hallucination packs;
- Gros Michel going extinct, and other food jokers;
- Glass cards with Oops! All 6s;
- The Hanged Man, Immolate and Grim with Canio;
- Ankh and Hex;
- first-hand jokers (DNA, Certificate);
- Sixth Sense;
- Midas Mask with Vampire;
- Perkeo;
- bosses (The Hook, Cerulean Bell, Crimson Heart, Amber Acorn, The Ox);
- Luchador with Chicot;
- Diet Cola.

Each is played with a fixed policy on both sides and compared after every
command.

## Tests

```
python -m pytest                  # all tests (the oracle ones need LuaJIT and the game source, else they are skipped)
python -m pytest -m "not slow"    # without the slow differential fuzz run
python -m pytest -m slow          # only that run
```

| File | Checks |
|---|---|
| `test_rng.py` | the RNG, bit for bit, against vectors produced by the game's Lua code (`tests/vectors/rng.json`) |
| `test_engine.py` | known values recorded from the original game on fixed seeds |
| `test_api.py` | legal actions are playable and change nothing, determinism, `clone` (with pending events), illegal actions, game speeds, fast-forward giving the same result as frame-by-frame |
| `test_golden.py` | runs recorded from the original game (`fuzz --record`, in `tests/vectors/golden.jsonl`), replayed on the engine and compared with the game's final state. No LuaJIT needed. |
| `test_robust.py` | random runs with every kind of card injected: no exception, no card lost or duplicated |
| `test_feedback.py` | feedback recording and the hand preview change nothing; their content; the sprite data |
| `test_quick.py` | `Ante1` against full games |
| `test_oracle.py` | scripted runs against the oracle (skipped without LuaJIT and the game source) |

## Known limits

- **Frame jitter.** The real game's frame times vary. A race that the
  reference timeline decides by a frame or two can go either way in a real
  session; races decided by more than that match.
- **`pairs()` order.** To Do List, the Orbital Tag's hand and The Ox's
  tie-break depend on the session's hash order. Match it with `hands_order`.
- **Cosmetic only.** The artwork variant of some packs comes from LuaJIT's
  global random state. Both variants play the same.
- **Sort ties.** The game breaks ties between equal cards by an internal UI
  counter; the engine uses creation order. They differ only for cards whose
  suit a Tarot changed, very late in a run.
- **Not modelled.** Unlocks and discoveries during a run, the game's own
  save and continue (use `clone()`), the tutorial, and actions taken while an
  animation is still running.

## Before committing a change to the rules

1. `python -m pytest` (the golden runs catch most regressions without
   LuaJIT).
2. `python tools/scenarios.py` if the change touches events, timing,
   destruction or creation of cards.
3. A fuzz run, plus a sweep of the items concerned:
   `python -m balatro.oracle.fuzz --runs 20` and
   `--sweep jokers` (or `consumables`, ...).
