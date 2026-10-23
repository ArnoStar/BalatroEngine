# BalatroEngine documentation

BalatroEngine is a Python library that reproduces the game logic of
**Balatro 1.0.1o** exactly. Give it a seed, a deck and a stake, then play by
calling methods. For the same seed and the same choices, the engine produces
what the original game produces: every draw, shop, pack, score and dollar.

| Document | Read it to |
|---|---|
| [Getting started](getting-started.md) | install it, play a run, branch it, analyze a seed |
| [Game flow](game-flow.md) | know the run's states, what can be done in each, and what each action sets off |
| [API reference](api-reference.md) | look up every public class, method and function |
| [State reference](state-reference.md) | read the run state: `G.GAME`, card areas, cards, blinds, tags, `snapshot()` |
| [Front-end hooks](frontend-hooks.md) | build a user interface: feedback events, hand preview, sprites |
| [Internals](internals.md) | understand or change the engine: module map, event queue, frames, RNG, data |
| [Verification](verification.md) | check the engine against the original game: oracle, fuzzing, scenarios, tests |

[BalatroWebAPI](https://github.com/ArnoStar/BalatroWebAPI) serves the engine
over HTTP for front ends.

## The model in one page

```python
from balatro import Game

G = Game("TESTSEED", deck="red", stake="white").start_run()   # waits at the blind select screen
G.act_select_blind()                                           # deals the hand
G.act_play([0, 1, 2, 3, 4])                                    # plays hand cards by position
print(G.GAME.chips, G.last_score)                              # 56  {'chips': 28, 'mult': 2, ...}
```

- **`Game` is the Lua `G`.** It holds the whole run: `G.GAME` (the run
  state), the card areas (`G.hand`, `G.jokers`...), the state machine
  (`G.STATE`) and the event queue.
- **The run waits for one decision at a time.** `G.STATE` says which screen
  it is on: blind select, selecting a hand, round evaluation, shop, a booster
  pack, or game over.
- **Every `act_*` method is one player action.** It checks that the game
  allows it, applies it like a button press, then runs the game frame by frame
  until it waits for the player again. An action the game doesn't allow
  raises `IllegalAction` and changes nothing.
- **Cards are chosen by position**, 0-based, left to right as on screen.
- **`legal_actions()`** lists what is possible now. **`do(command)`** applies
  an action given as a plain dict.
- **`clone()`** copies a run, so you can explore alternatives.
  **`snapshot()`** dumps it as plain data.
