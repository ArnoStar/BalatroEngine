# Front-end hooks

A user interface needs a few things the game only shows on screen: what
happens during an action, which hand a selection makes, the cash-out rows,
and where each card is drawn. The engine provides them as data. **None of
them changes the run**: a run recorded with feedback, or previewed at every
step, is identical to one played without them (tested in
`tests/test_feedback.py`).

## Feedback: what the player sees happen

```python
fb = G.start_feedback()        # start recording; fb fills up as the game runs
G.act_play([0, 1, 2, 3, 4])
G.stop_feedback()              # stop (returns the same list)
for e in fb:
    print(e)
```

```
{'type': 'card_moved', 'card': 35, 'to': 'play', 't': 0.55}
...
{'type': 'hand', 'handname': 'Pair', 'level': 1, 'mult': 2, 'chips': 10, 't': 1.15}
{'type': 'hand', 'chips': 19, 't': 2.1833}
{'type': 'card_text', 'card': 47, 'effect': 'chips', 'amount': 9, 't': 2.2}
{'type': 'hand', 'chips': 28, 't': 2.9667}
{'type': 'card_text', 'card': 8, 'effect': 'chips', 'amount': 9, 't': 2.9833}
{'type': 'hand_scored', 'hand': 'Pair', 'chips': 28, 'mult': 2, 'score': 56, 'round_score': 56, 't': 4.7}
{'type': 'card_moved', 'card': 35, 'to': 'discard', 't': 6.4167}
{'type': 'card_flipped', 'card': 35, 'facing': 'back', 't': 6.4167}
...
```

Each entry has a `type` and `t`, the real time in seconds since
`start_feedback()` at which the game shows it, at 60 frames per second and
the run's game speed. `card` is the card's `sort_id`.

| `type` | Fields | Recorded when |
|---|---|---|
| `hand` | `handname`, `level`, `chips`, `mult`, `chip_total` (only those set) | the scoring panel updates (`update_hand_text`). `""` clears a value; `"?"`/`"????"` hide it (face-down selection). |
| `card_text` | `card`, `effect`, `amount`, `message`, `held`, `edition` | a pop-up over a card (`card_eval_status_text`) |
| `hand_scored` | `hand`, `chips`, `mult`, `score`, `round_score` | the hand's total is shown |
| `round_score` | `chips` | the round score is set (`ease_chips`, at cash out) |
| `dollars` | `amount`, `total` | money changes (`ease_dollars`) |
| `status_text` | `text` | text over the play area (`Not Allowed!`) |
| `card_moved` | `card`, `to` (area name) | a card is put in an area (`CardArea:emplace`) |
| `card_flipped` | `card`, `facing` (`front`/`back`) | a card turns over (`Card:flip`) |
| `card_removed` | `card`, `area` | a card leaves the game (`Card:remove`) |

`card_text.effect`:

| `effect` | From | `amount` |
|---|---|---|
| `chips` | `+N` chips | chips |
| `mult` | `+N Mult` (`held: True` for a held-in-hand effect) | mult |
| `x_mult` | `XN Mult` | the factor |
| `dollars` | `$N` | dollars |
| `again` | a retrigger (`Again!`) | |
| `debuffed` | a debuffed card | |
| `swap` | chips and mult swapped | |
| `message` | any other joker, seal or edition message. `message` holds a key when the engine knows it (`plus_planet`, `plus_tarot`, `boss_disabled`, `disabled`, `remaining`, `edition`), else it is absent. | |

`edition: True` marks the pop-ups of a card's edition.

### How it works

Each record is made inside the event the game already queues to show it (for
example the `trigger="before"` event of `card_eval_status_text`). So `t` is
the time the game shows it, and recording adds no event and moves nothing in
the timeline. While not recording (`G.feedback is None`), nothing is kept.

The game's texts are localized strings built at display time. The engine
records their meaning (effect and amount), not the text.

## Hand preview

```python
G.preview_hand([0, 1, 2, 3, 4])
# {'selected': [0, 1, 2, 3, 4], 'hand': 'Pair', 'display': 'Pair', 'level': 1, 'chips': 10, 'mult': 2,
#  'scoring': [3, 4], 'not_allowed': False, 'hidden': False}
```

This is what the game shows above the hand while cards are selected
(`CardArea:parse_highlighted`), computed on a hypothetical selection:

| Key | |
|---|---|
| `selected` | the selection's hand positions, a forced card (Cerulean Bell) included |
| `hand` | the poker hand, or `None` if nothing is selected or the hand is hidden |
| `display` | the name shown (`Royal Flush` for an ace-high straight flush) |
| `level`, `chips`, `mult` | the hand's level and base values |
| `scoring` | positions of the cards that would score |
| `not_allowed` | the boss blind forbids it (`Blind:debuff_hand` in check mode) |
| `hidden` | a face-down card is selected; the game shows `????` |

It raises `IllegalAction` outside `SELECTING_HAND`, for a position not in
the hand, a card given twice, or more than 5 cards. The blind's `triggered`
flag, which the check sets as in the game, is restored afterwards.

## Cash-out rows

After a blind is beaten, `G.round_eval_rows` lists the rows of the cash-out
screen as `(label, dollars)`:

| Label | |
|---|---|
| `blind` | the blind's reward (0 if the stake removes it) |
| `hands` | `$1` (or the deck's rate) per hand left |
| `discards` | per discard left (Green Deck) |
| `joker:<key>` | a joker's end-of-round money (Golden Joker, Cloud 9, Rocket...) |
| `tag:<key>` | a tag's money (Investment Tag) |
| `interest` | interest |

`act_cash_out()` adds their sum to the money.

## Sprites

`balatro.data.sprites()` returns where the game draws each item in its sprite
sheets, generated from the game's source by `tools/lua/extract_sprites.lua`
into `balatro/data/sprites.json`:

```python
from balatro.data import sprites
s = sprites()
s["atlases"]["Joker"]          # {'file': 'Jokers.png', 'px': 71, 'py': 95}
s["centers"]["j_hologram"]     # {'atlas': 'Joker', 'pos': {'x': 4, 'y': 12}, 'soul_pos': {'x': 2, 'y': 9}}
s["cards"]["H_A"]              # {'atlas': 'cards_1', 'atlas_high_contrast': 'cards_2', 'pos': {'x': 12, 'y': 0}}
```

| Key | |
|---|---|
| `atlases` | each sheet: `file` (in the game's `resources/textures/1x/`, and `2x/`), cell size `px` × `py`, `frames` for animated sheets |
| `centers` | every center: `atlas`, `pos`, `soul_pos` (a second layer, for legendary jokers and Hologram) |
| `cards` | the 52 card fronts |
| `blinds` | blind chips (`blind_chips`, animated) and their `colour` |
| `tags`, `seals`, `stakes` | |
| `stickers` | `eternal`, `perishable`, `rental`, and the `debuff` overlay |

`pos` is in cells: the pixel rectangle is `(x·px, y·py, px, py)` at 1x. The
atlas choice follows the game's `Card:set_sprites`. Planet and Spectral cards
use the Tarot sheet (`Planet` and `Spectral` are aliases of it).
