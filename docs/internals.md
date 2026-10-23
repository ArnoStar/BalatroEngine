# Internals

How the engine is built, for those who change it. The guiding rule: **port the
game, don't approximate it.** Each Python function mirrors a Lua function,
branch for branch, with the same names, the same order of checks (some
consume randomness), and the same events with the same triggers, delays and
flags.

## Module map

`Game` is assembled from mixins, one per Lua file, so `G.ease_dollars(...)`
reads as in the Lua source.

| Module | Lua source | Contents |
|---|---|---|
| `game.py` | `game.lua` | `Game`: settings, `init_game_object`, `start_run`, the state functions (`update_selecting_hand`, `update_shop`, `update_round_eval`, `update_hand_played`, `update_draw_to_hand`, `update_new_round`, `update_blind_select`, `update_pack`, `update_game_over`), `update_state`, `frame` (`Game:update`), `settle`, fast-forward, `clone`, `snapshot`, `summary`, `next_draws`. Also `Profile`, `Controller` (the locks), `STATES`. |
| `actions.py` | button checks in `button_callbacks.lua` and `UI_definitions.lua` | `ActionsMixin`: the `act_*` methods, the `can_*` checks, `legal_actions`, `do`, `preview_hand` |
| `state_events.py` | `functions/state_events.lua` | `win_game`, `end_round`, `new_round`, the `draw_from_*` moves, `discard_cards_from_highlighted`, `play_cards_from_highlighted`, `evaluate_play` (scoring), `evaluate_round` (cash-out rows), `get_poker_hand_info`; `eval_card`, `mod_chips`, `mod_mult` |
| `common.py` | `functions/common_events.lua`, `functions/misc_functions.lua` | event shorthands (`ev`, `event`, `delay`); `ease_dollars`, `ease_chips`, `ease_discard`, `ease_hands_played`, `ease_ante`, `ease_round`; `draw_card`, `highlight_card`, `level_up_hand`, `update_hand_text`, `card_eval_status_text`, `play_area_status_text`, `juice_card`, `add_round_eval_row`; `get_blind_amount`, `get_current_pool`, `pick_from_pool`, `create_card`, `create_playing_card`, `copy_card`, `poll_edition`, `get_pack`, `get_next_voucher_key`, `get_next_tag_key`, `get_new_boss`, `reset_blinds`, `reset_idol_card` and the other round targets, `create_card_for_shop`, `calculate_reroll_cost`, `refresh_all_costs`, `change_shop_size`, `add_joker`, `add_tag`, `find_joker`, `stop_use`; the feedback recorder |
| `buttons.py` | `functions/button_callbacks.lua` | `G.FUNCS` callbacks: `select_blind`, `skip_blind`, `reroll_boss`, `use_card`, `sell_card`, `buy_from_shop`, `check_for_buy_space`, `reroll_shop`, `toggle_shop`, `skip_booster`, `end_consumeable`, `cash_out`, `sort_hand_value`, `sort_hand_suit`, overlays; the logic of `create_UIBox_blind_select`/`_choice` |
| `card.py` | `card.lua` | `Card`: `set_base`, `set_ability`, `set_cost`, `set_edition`, `set_seal`, stickers, `set_debuff`, `add_to_deck`/`remove_from_deck`, chip and mult getters, `calculate_seal`, `calculate_dollar_bonus`, `get_end_of_round_effect`, `open` (packs), `redeem`/`apply_to_run` (vouchers), `use_consumeable`, `can_sell_card`, `start_dissolve`, `shatter`, `flip`, `highlight`, `remove`, `update` |
| `jokers.py` | `Card:calculate_joker` in `card.lua` | every joker, branch for branch |
| `consumables.py` | `Card:use_consumeable`, `Card:can_use_consumeable` | every Tarot, Planet and Spectral card |
| `cardarea.py` | `cardarea.lua` | `CardArea`: `emplace`, `remove_card`, `change_size`, highlighting and `parse_highlighted`, `align_cards`, `shuffle`, `sort`, `draw_card_from` |
| `blind.py` | `blind.lua` | `Blind`: `set_blind`, `defeat`, `disable`, `press_play`, `modify_hand`, `debuff_hand`, `drawn_to_hand`, `stay_flipped`, `debuff_card` |
| `tag.py` | `tag.lua` | `Tag`: `set_ability`, `apply_to_run` (every tag's trigger), `yep`/`nope` (their events) |
| `back.py` | `back.lua` | `Back` (the deck): `apply_to_run`, `trigger_effect` (Plasma, Anaglyph...) |
| `poker.py` | `evaluate_poker_hand` and helpers in `misc_functions.lua` | `get_flush`, `get_straight`, `get_X_same`, `get_highest`, `evaluate_poker_hand`, `get_poker_hand_info` |
| `events.py` | `engine/event.lua` | `Event`, `EventManager` |
| `ui.py` | parts of `engine/moveable.lua`, `engine/ui.lua` | the UI geometry the logic waits for: `Box` (alignment and motion of the shop and round evaluation panels), `move_hand` |
| `rng.py` | `pseudohash`, `pseudoseed`, `pseudorandom`... in `misc_functions.lua`; LuaJIT's `lib_math.c` | `PseudoRandom`, `LuaJITRandom`, `pseudohash` |
| `lua.py` | | `T` (Lua tables), Lua truthiness and number operations |
| `data.py` | | loads `data/game_data.json` and `data/sprites.json` |
| `snapshot.py` | `tools/lua/oracle.lua` `dump()` | the comparison format |
| `analyzer.py`, `quick.py` | | seed analysis tools |
| `oracle/` | | the bridge to the original game, fuzzer and replayer |

## The event queue and frames

Balatro runs its logic through an event queue (`engine/event.lua`). Each
event has:

- a **trigger**: `immediate`, `after` (run once `delay` seconds have passed),
  `before` (run now, then hold the queue for `delay`), `ease` (animate a
  value), or `condition` (run until the function returns true);
- **flags**: `blocking` (later events wait for it) and `blockable` (it waits
  for blocking events);
- a **timer**: game time `TOTAL`, scaled by the game speed, or `REAL`.

`events.py` is an exact port. `EventManager.update` handles the queue as the
game does, one blocking event per frame.

Many effects happen in events that only exist for animation: a card
dissolving, an eaten joker disappearing, a pack filling up. **When** they land
relative to the rest of the queue decides what happens. Can Ceremonial Dagger
slice a joker before the hand is drawn? Is a Trading Card's destroyed card
still in hand when replacements are counted? The engine therefore keeps every
event the game queues, including those whose only role is a delay, and runs
the game frame by frame.

**`Game.frame()`** is `Game:update(dt)`, in the same order:

1. Advance the timers. The game speed and the scoring speed-up (`G.ACC`
   during long hands) make `SPEEDFACTOR`.
2. Run the event queue (`E_MANAGER:update`).
3. Run the state function (`update_selecting_hand`...), which starts
   transitions once `STATE_COMPLETE` is false.
4. Move the hand and the UI panels the logic waits for (the shop and the
   round evaluation slide in).
5. Update the card areas and the cards whose `update` has game effects.
6. Clear the frame's locks (`Controller.update`).

The frame time is 1/60 s.

**`settle()`** runs frames until the game waits for the player: four quiet
frames in a row. A quiet frame has no busy event, no lock, and its state
function complete. This is the rule the oracle uses on the original game. The
player is assumed to act once the screen is idle.

### Fast-forward

Running every frame is slow when the queue is just waiting: a delay of 1.3 s
is 78 frames. With `fast_forward=True` (the default), the engine detects
frames in which nothing can happen. It computes, from the queue
(`_idle_thresholds`), the clock values at which the next event could fire.
Until then it only advances the clocks and the moving panels
(`_light_frame`), exactly as a full frame would. The result is identical to
frame-by-frame execution, which the tests check. It reaches about 50,000
frames per second.

## Randomness

All of Balatro's randomness goes through `pseudoseed(key)`. Each kind of
decision has its own stream, a float in `G.GAME.pseudorandom[key]` keyed by
names like `'boss'`, `'Joker1sho1'` or `'soul_Tarot1'`. A stream advances
only when it is used.

`pseudorandom(seed)` re-seeds LuaJIT's `math.random`, a Tausworthe generator,
and draws from it. `rng.py` reproduces all of this bit for bit:

- the IEEE double arithmetic and the `%.13f` rounding of `pseudoseed`;
- LuaJIT's generator;
- the sorting `pseudorandom_element` does on keys, and `pseudoshuffle`;
- the NaN stream that some seeds hash to.

Order matters as much as the algorithm:

- **Pools** (`P_CENTER_POOLS`) are kept in the game's order.
- **Conditions that consume randomness** keep Lua's short-circuit order:
  `is_face() and pseudorandom('business')`.
- **The `pairs()` order of `G.GAME.hands`** is the one thing the game itself
  doesn't fix (see `hands_order` in the [API reference](api-reference.md)).

## Cloning

`Game.clone()` is a `copy.deepcopy`. The static prototype tables are shared,
through the deepcopy memo. Pending events hold closures over game objects,
and Python's deepcopy treats functions as atomic. So `Event.__deepcopy__`
rebuilds each closure with copied cells (`copy_function`), and the copy's
events act on the copy's objects.

## Static data

`tools/lua/extract_data.lua` boots the original game headlessly
(`tools/lua/boot.lua`, a stubbed `love`) and dumps its tables into
`balatro/data/game_data.json`: centers, cards, blinds, tags, seals, stakes,
pools *with their order*, poker hands, challenges, starting parameters.
Visual fields are left out. `tools/lua/extract_sprites.lua` writes those
separately into `sprites.json`. To support another game version, regenerate
both:

```
luajit tools/lua/extract_data.lua
luajit tools/lua/extract_sprites.lua
```

(set `BALATRO_SRC` to the game's extracted Lua source if it isn't in
`../balatro_src`).

## Porting rules

- **Keep the Lua structure and names**, so any rule can be checked against
  the source side by side.
- **Keep every event**: its trigger, delay, `blocking`/`blockable` flags and
  timer, even when it does nothing but wait.
- **Keep the order of checks** that consume randomness or change state.
- **Keep Lua semantics**: `nil` and `false` are the only falsy values (`0` is
  true: `lor`), 1-based indices in shuffles, Lua number formatting in RNG keys
  (`lua_tostring`), `math.floor` and `%` on negatives and infinities.
- **UI code is dropped** unless the logic reads it: positions that order
  cards (`align_cards`), panels whose motion the queue waits for.
- **Verify every change against the original game** (see
  [Verification](verification.md)).
