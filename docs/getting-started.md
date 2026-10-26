# Getting started

## Install

The engine needs Python 3.12 or later and nothing else.

```
pip install git+https://github.com/ArnoStar/BalatroEngine.git@v0.5.0
# or, from a checkout:
pip install .            # or: uv pip install .
```

The package is `balatro`. To work on the engine itself, use `uv sync` to get
the dev tools (pytest, ruff, mypy).

## Start a run

```python
from balatro import Game

G = Game("TESTSEED", deck="red", stake="white").start_run()
```

- **`seed`**: up to 8 letters or digits, as typed in the game. It is
  upper-cased and `0` becomes `O`. `Game()` with no seed picks a random one.
- **`deck`**: a short name (`"red"`, `"plasma"`...) or a key (`"b_red"`).
- **`stake`**: a name (`"white"` ... `"gold"`) or a level 1-8.
- **`challenge`**: a challenge id (`"c_omelette_1"`), which sets the deck.

`start_run()` sets the run up and runs it to the first decision. It returns
the game, so it can be chained. The run is now at the blind select screen:

```python
G.STATE == G.STATES.BLIND_SELECT                  # True
G.GAME.round_resets.blind_choices.Boss            # 'bl_head'
G.GAME.round_resets.blind_tags                    # {'Small': 'tag_economy', 'Big': 'tag_investment'}
G.GAME.dollars                                    # 4
```

## Play

```python
G.act_select_blind()
[c.label() for c in G.hand.cards]                 # ['AH', 'KH', 'QD', '9S', '9C', '5C', '5D', '4C']

G.act_play([0, 1, 2, 3, 4])                       # A K Q 9 9: a pair of nines
G.GAME.chips                                      # 56 = (10 + 9 + 9) x 2
G.last_score                                      # {'chips': 28, 'mult': 2, 'score': 56, 'hand': 'Pair'}
G.GAME.current_round.hands_left                   # 3
```

Each `act_*` method is one player action. It raises `balatro.IllegalAction`
if the game doesn't allow it then (the run is unchanged), and returns once
the game waits for the player again. Card positions are 0-based, left to
right, as on screen.

| Screen (`G.STATE`) | Actions |
|---|---|
| `BLIND_SELECT` | `act_select_blind()`, `act_skip_blind()`, `act_reroll_boss()` |
| `SELECTING_HAND` | `act_play(cards)`, `act_discard(cards)`, `act_sort("rank" \| "suit")` |
| `ROUND_EVAL` | `act_cash_out()` |
| `SHOP` | `act_buy(area, i, use=False)`, `act_reroll()`, `act_end_shop()` |
| a booster pack | `act_pick(i, targets=None)`, `act_skip_pack()` |
| most of the time | `act_use(i, targets=None)`, `act_sell(area, i)`, `act_move(area, from, to)` |

What each one does, and when it is allowed, is in the
[API reference](api-reference.md). The sequence of screens is in
[Game flow](game-flow.md).

## Look around

```python
print(G.summary())
# TESTSEED ante 1 round 1  SELECTING_HAND  $4
#   blind: Small Blind  56 / 300 chips  hands 3  discards 4
#   jokers 0/5: -
#   consumables 0/2: -
#   hand: 0:AS, 1:QC, 2:TC, 3:8C, 4:7H, 5:5C, 6:5D, 7:4C

G.legal_actions()          # [{'cmd': 'play', 'n': 8}, {'cmd': 'discard', 'n': 8}, {'cmd': 'sort', 'mode': 'rank'}, ...]
[c.label() for c in G.next_draws(3)]   # ['AD', 'TD', '2D']: the next cards the deck deals
```

`G.GAME` holds the run state with the field names of the Lua source:
`dollars`, `round_resets.ante`, `current_round.hands_left`, `hands`, `tags`,
`used_vouchers`... See the [State reference](state-reference.md).

## Play with plain commands

The same actions exist as dicts, which is convenient for bots and for storing
runs:

```python
R = Game("TESTSEED").start_run()
for cmd in [{"cmd": "select_blind"}, {"cmd": "discard", "cards": [0, 3]}, {"cmd": "play", "cards": [0, 1, 2]}]:
    R.do(cmd)
```

A run is fully determined by its settings and its list of commands. Replaying
them on a new `Game` gives exactly the same run.

## Branch

```python
H = G.clone()                  # an independent copy (G has just played its first hand)
H.act_discard([0])
len(G.discard.cards), len(H.discard.cards)    # (5, 6): the original is untouched
```

`clone()` copies everything, including events that are still pending, so the
copy continues exactly as the original would.

## A whole run

`examples/greedy_bot.py` plays complete runs with a simple strategy:

```
python examples/greedy_bot.py TESTSEED --deck red --stake 1
```

The core loop of any bot is:

```python
while not G.is_game_over():
    st = G.STATE
    if st == G.STATES.BLIND_SELECT:
        G.act_select_blind()
    elif st == G.STATES.SELECTING_HAND:
        G.act_play(choose_cards(G))
    elif st == G.STATES.ROUND_EVAL:
        G.act_cash_out()
    elif st == G.STATES.SHOP:
        G.act_end_shop()
    elif G.in_pack():
        G.act_skip_pack()
```

## Analyze a seed

```python
from balatro.analyzer import analyze
print(analyze("TESTSEED", antes=1, rerolls=0).to_text())
# == Ante 1 ==  Boss: The Head   Voucher: Crystal Ball
#   Small Small Blind              300 chips  skip tag: Economy Tag
#         first hand: AH KH QD 9S 9C 5C 5D 4C
#   ...
#   Shop after Small:
#     cards:    Raised Fist, Pareidolia
#     pack:     Buffoon Pack: Abstract Joker, Astronomer
```

For searching many seeds, `balatro.quick.Ante1` computes the ante-1 boss,
voucher, tags and first hand without building a game, at about 10,000 seeds
per second:

```python
from balatro.quick import Ante1
a = Ante1("TESTSEED")
a.boss, a.voucher, a.tags        # ('bl_head', 'v_crystal_ball', ('tag_economy', 'tag_investment'))
```

`examples/find_royal_flush.py` uses it.
