# Mods and game modes

A **mod** changes the game's rules for a game mode the original game doesn't
have. Mods are passed to `Game`:

```python
from balatro import Game

G = Game("TESTSEED", mods=["pvp"]).start_run()
G.mod("pvp").blinds          # what the mod keeps (here: every blind the run resolved)
```

`mods` takes keys (`"pvp"`), specs (`{"key": "pvp"}`) or `Mod` objects
(`balatro.make_mod` makes one from a key or a spec, and `Mod.spec()` gives it
back as plain data).

## A run without mods is the original game

A mod is an object whose hooks the engine calls at fixed places of the game's
code. Every hook does nothing by default, and a game without mods never calls
one, so the oracle tests and golden vectors still hold. A mod keeps to the
original wherever its mode allows (`tests/test_mods.py` checks it):

- **PvP** is the original game until a round is lost.

## Hooks

Subclass `balatro.mods.Mod` and add it to `registry()` in
`balatro/mods/__init__.py`. The mod's state lives on the mod object, which
`Game.clone()` copies with the game.

| Hook | Called | Returns |
|---|---|---|
| `setup(G)` | in `start_run`, once the deck, stake and challenge are applied, before the starting deck is made | |
| `start(G)` | in `start_run`, once the starting deck is made | |
| `blind_amount(G, ante, amount)` | `get_blind_amount` | the blind's base chips |
| `round_lost(G)` | `end_round`, the round lost and no joker saved it | True: the run goes on (no blind reward, as with Mr. Bones) |
| `round_ended(G, lost, saved)` | `end_round`, before the ante goes up | |
| `out_of_hands(G)` | after a hand, the game's "no hands left" | True/False, or None for the game's rule |
| `out_of_cards(G)` | selecting a hand with no cards left | True/False, or None |
| `hand_size_changed(G, area, delta)` | `CardArea.change_size` on the hand | |
| `before_command(G, cmd)` / `after_command(G, cmd)` | around every `G.do(cmd)` | |
| `command(G, cmd)` | before the game's own commands | True: the mod played it |
| `legal_actions(G, actions)` | `G.legal_actions()` | the list |
| `state()` | by front ends | the mod's state as plain data |

## PvP (`"pvp"`)

Two players race on the same seed, each with their own run. A lost round
doesn't end the run: it ends as when Mr. Bones saves it (no blind reward,
then the shop), so both runs go through the same blinds in step. The mod
records every blind the run resolves, played or skipped, in `blinds`:
`ante`, `round`, `slot` (Small/Big/Boss), `blind`, `chips` (the round's
score), `target`, `lost`, `saved` (a joker saved it), `skipped`.

The match's rules are in `balatro.mods.pvp`:

- `match_state([blinds_a, blinds_b])` gives both players' hit points after the
  blinds both have finished, round by round, and whether the match is over
  and who won.
- Each player starts with `START_HP` (50). Once both have finished a blind,
  each loses `floor(other's chips / own chips)` hit points, from ante
  `SAFE_ANTES + 1` (4) on. A player who lost the round loses `LOSS_DAMAGE` (10)
  instead, at any ante. A skipped blind (both players skip it, or neither
  does) hurts nobody.
- The match is over when a player has no hit points left: the other wins
  (both at once: the one with more left; as many: a draw).

Commands added by the mod:

| Command | When | What |
|---|---|---|
| `{"cmd": "forfeit_round"}` | playing a round | the round is lost now (the timer ran out) |

`G.mod("pvp").timeout_command(G)` gives the command that moves a late player
on in the current state: `forfeit_round` in a round, `cash_out`, `skip_pack`
(or the first card that can be taken), `end_shop`; None at the blind select,
which the match decides.
