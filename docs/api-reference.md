# API reference

Everything a user of the engine calls. Internal functions (the ports of the
game's Lua functions) are listed in [Internals](internals.md).

Contents:

- [`balatro`](#the-balatro-package): `Game`, `Profile`, `IllegalAction`, constants
- [`Game`](#game): [creating](#creating-a-run) · [actions](#actions) ·
  [checks](#checks) · [`legal_actions`](#legal_actions) · [`do`](#do-commands) ·
  [inspecting](#inspecting) · [branching](#branching) ·
  [front-end hooks](#front-end-hooks) · [running frames](#running-frames)
- [`balatro.data`](#balatrodata) · [`balatro.analyzer`](#balatroanalyzer) ·
  [`balatro.quick`](#balatroquick) · [`balatro.poker`](#balatropoker) ·
  [`balatro.rng`](#balatrorng) · [`balatro.snapshot`](#balatrosnapshot) ·
  [`balatro.oracle`](#balatrooracle) · [`balatro.lua`](#balatrolua)

---

## The `balatro` package

```python
from balatro import Game, Profile, IllegalAction, STATES, STATE_NAMES, DECK_NAMES, STAKE_NAMES
```

| Name | |
|---|---|
| `Game` | a run (the Lua `G`) |
| `Profile` | which items are unlocked and discovered |
| `IllegalAction` | raised by an action the game doesn't allow now (a `ValueError`) |
| `STATES` | the game states: `STATES.SELECTING_HAND == 1`, `STATES.SHOP == 5`, ... (see [Game flow](game-flow.md)) |
| `STATE_NAMES` | state value → name (`{1: 'SELECTING_HAND', ...}`) |
| `DECK_NAMES` | short deck names → keys: `{'red': 'b_red', ..., 'erratic': 'b_erratic', 'challenge': 'b_challenge'}` |
| `STAKE_NAMES` | stake names → levels: `{'white': 1, 'red': 2, 'green': 3, 'black': 4, 'blue': 5, 'purple': 6, 'orange': 7, 'gold': 8}` |
| `__version__` | the engine version (`"0.4.2"`) |

### `Profile`

What the player has unlocked and discovered. A seeded run never unlocks or
discovers anything, so the profile is fixed for the whole run. It matters
because locked items are left out of the shop and pack pools.

| | |
|---|---|
| `Profile.everything()` | everything unlocked and discovered (the default, and the seed finders' convention) |
| `Profile.fresh()` | a new save: only what the game unlocks from the start |
| `Profile(unlocked=set_of_keys, discovered=set_of_keys, all_=False)` | a specific save |

---

## `Game`

### Creating a run

```python
Game(seed=None, deck="b_red", stake=1, challenge=None, profile=None, hands_order=None,
     game_speed=1, normalize=True, fast_forward=True)
```

| Parameter | | |
|---|---|---|
| `seed` | `str \| None` | up to 8 characters. `None` picks a random seed from the game's alphabet, like an unseeded run (it is still played as a seeded run). |
| `deck` | `str` | a key (`"b_plasma"`) or a short name (`"plasma"`) |
| `stake` | `int \| str` | 1-8, or a name (`"gold"`) |
| `challenge` | `str \| None` | a challenge id (`"c_omelette_1"`). The challenge's deck replaces `deck`. Challenges are played on stake 1. |
| `profile` | `Profile \| None` | default `Profile.everything()` |
| `hands_order` | list of the 12 hand names | the order of `pairs(G.GAME.hands)` in the game session to match (see below) |
| `game_speed` | `float` | the game's speed setting: 0.5, 1, 2 or 4 |
| `normalize` | `bool` | upper-case the seed and turn `0` into `O`, as the game does with typed seeds |
| `fast_forward` | `bool` | skip the work of frames in which nothing can happen. Gives identical results, much faster. |

**`hands_order`.** To Do List targets, the Orbital Tag's hand and The Ox's
tie-break iterate over `pairs(G.GAME.hands)`. In LuaJIT that order follows
string hashes salted per process, so it changes each time the game is
launched. The seed decides which *position* is picked; the session decides
which hand is there. The default is `DEFAULT_HANDS_ORDER` (`balatro.game`).

**`start_run() -> Game`** sets the run up (`Game:start_run`) and plays it to
the first decision, the blind select screen. It returns `self`.

Attributes set at creation: `seed`, `deck_key`, `stake`, `challenge_id`,
`data` (the [`GameData`](#balatrodata)), `profile`, `PROFILE` (what the run adds to the player's profile, see [state reference](state-reference.md#what-a-run-adds-to-the-profile-gprofile)), `SETTINGS.GAMESPEED`.

### Actions

Each action checks that it is allowed, applies it, and runs the game until it
waits for the player ([`settle`](#running-frames)). It returns `None`, and
raises `IllegalAction` with a message when the game doesn't allow it. In that
case the run is unchanged: the checks come before any change.

Card positions are 0-based indices into an area's `cards`, left to right.

#### Blind select

| Method | Allowed when | Does |
|---|---|---|
| `act_select_blind()` | `BLIND_SELECT` | plays the blind on deck (`G.FUNCS.select_blind`) |
| `act_skip_blind()` | `BLIND_SELECT`, Small or Big on deck | skips it and takes its tag (`G.FUNCS.skip_blind`) |
| `act_reroll_boss()` | `BLIND_SELECT`, $10 available, Director's Cut (once per ante) or Retcon | rerolls the boss (`G.FUNCS.reroll_boss`) |

#### Playing a hand

| Method | Allowed when | Does |
|---|---|---|
| `act_play(idxs)` | `SELECTING_HAND`, 1 to 5 cards counting a forced card | selects the hand cards at `idxs` (a forced card stays selected), lets the game settle, presses *Play Hand* |
| `act_discard(idxs)` | `SELECTING_HAND`, a discard left, 1 to 5 cards | the same with *Discard* |
| `act_sort(mode="rank")` | a hand exists | the hand's *Rank* or *Suit* sort button (`mode="suit"`); the choice sticks for later draws |
| `act_move(area, frm, to)` | `area` is `"jokers"`, `"consumeables"` or `"hand"` | drags card `frm` to position `to` |

#### Rounds and shop

| Method | Allowed when | Does |
|---|---|---|
| `act_cash_out()` | `ROUND_EVAL` | *Cash Out*: collects the round's money, opens the shop |
| `act_buy(area, index, use=False)` | `SHOP`, affordable | `area="shop_jokers"`: buys the card (it needs room). `use=True`: buys a consumable and uses it at once (it must be usable). `"shop_vouchers"`: redeems the voucher. `"shop_booster"`: opens the pack. |
| `act_reroll()` | `SHOP`, the reroll affordable (or free) | rerolls the shop's card slots |
| `act_end_shop()` | `SHOP` | *Next Round* |

#### Consumables and jokers

| Method | Allowed when | Does |
|---|---|---|
| `act_use(index, targets=None)` | consumable `index` can be used now | `targets`: hand positions to select first (Tarot and Spectral cards that need a selection). Then uses the card (`G.FUNCS.use_card`). |
| `act_sell(area, index)` | `area` is `"jokers"` or `"consumeables"`, the card can be sold (not Eternal, nothing being played) | sells it (`G.FUNCS.sell_card`) |

#### Booster packs

| Method | Allowed when | Does |
|---|---|---|
| `act_pick(index, targets=None)` | a pack is open; a joker needs a slot (or is Negative); a consumable must be usable with `targets` | takes the card, or uses it |
| `act_skip_pack()` | a pack is open, and its hand is dealt for Arcana and Spectral packs | skips the rest of the pack |

Use the game's spelling `consumeables` for area names: these are the Lua
area names.

### Checks

These answer without changing anything:

| Method | Returns |
|---|---|
| `can_select_blind()` | at the blind select screen |
| `can_skip_blind()` | the blind on deck can be skipped (Small or Big) |
| `can_reroll_boss()` | the boss can be rerolled (voucher and money) |
| `can_play(idxs)` / `can_discard(idxs)` | these hand positions can be played / discarded |
| `can_afford(card)` | the card's cost is within the money (and Credit Card's debt) |
| `check_space(card)` | buying the card leaves it room (`G.FUNCS.check_for_buy_space`, without its alert) |
| `can_reroll_shop()` | the reroll is affordable or free |
| `can_use(index, targets=None)` | consumable `index` can be used, with those hand positions selected |
| `can_select_pack_card(card, targets=None)` | a pack card can be taken or used |
| `can_skip_pack()` | the pack can be skipped |
| `in_shop()` | the shop is open |
| `in_pack()` | a booster pack is open |
| `is_game_over()` | the run is lost |
| `ready()` | the game waits for the player (or the run is over) |

### `legal_actions`

**`legal_actions() -> list[dict]`** lists what can be done now, as command
dicts for [`do`](#do-commands). It doesn't change the game. Card choices are
left open:

| Entry | Meaning |
|---|---|
| `{"cmd": "select_blind"}`, `{"cmd": "skip_blind"}`, `{"cmd": "reroll_boss"}` | blind select |
| `{"cmd": "play", "n": 8}`, `{"cmd": "discard", "n": 8}` | play or discard any 1-5 of the `n` hand cards |
| `{"cmd": "sort", "mode": "rank"}`, `{"cmd": "sort", "mode": "suit"}` | |
| `{"cmd": "cash_out"}` | |
| `{"cmd": "buy", "area": "shop_jokers", "index": 0}` | an affordable card that has room |
| `{"cmd": "buy", "area": "shop_jokers", "index": 0, "use": True}` | an affordable consumable usable now |
| `{"cmd": "buy", "area": "shop_vouchers" \| "shop_booster", "index": i}` | |
| `{"cmd": "reroll"}`, `{"cmd": "end_shop"}` | |
| `{"cmd": "pick", "index": i}` | a pack card that can be taken |
| `{"cmd": "pick", "index": i, "min": 1, "max": 2}` | a pack consumable that needs 1-2 hand cards selected |
| `{"cmd": "skip_pack"}` | |
| `{"cmd": "use", "index": i}` | a consumable usable now |
| `{"cmd": "use", "index": i, "min": 1, "max": 3}` | a consumable that needs hand cards selected; whether a given selection fits is checked when it is used |
| `{"cmd": "sell", "area": "jokers" \| "consumeables", "index": i}` | |

`move` is never listed. Any card of a non-empty area can be moved.

### `do` (commands)

**`do(cmd: dict) -> None`** applies an action given as a dict. These are the
formats `legal_actions()` lists, with the open choices filled in:

| `cmd` | Other keys | Same as |
|---|---|---|
| `select_blind`, `skip_blind`, `reroll_boss` | | `act_select_blind()` ... |
| `play`, `discard` | `cards`: list of hand positions | `act_play(cards)` |
| `sort` | `mode` (default `"rank"`) | `act_sort(mode)` |
| `move` | `area`, `from`, `to` | `act_move(area, from, to)` |
| `cash_out`, `reroll`, `end_shop`, `skip_pack` | | |
| `buy` | `area`, `index`, `use` (optional) | `act_buy(...)` |
| `use` | `index`, `targets` (optional) | `act_use(...)` |
| `sell` | `area`, `index` | `act_sell(...)` |
| `pick` | `index`, `targets` (optional) | `act_pick(...)` |
| `state` | | nothing (a no-op, for tools) |

An unknown `cmd` raises `IllegalAction`.

**Test helpers.** These commands are not player actions. They exist to reach
any situation in tests, and none of them uses randomness, so a run that uses
them still replays exactly:

| Command | Effect |
|---|---|
| `{"cmd": "cheat", "dollars": 100}` | set the money |
| `{"cmd": "cheat", "ante": 8}` | set the ante (and the blinds' ante) |
| `{"cmd": "cheat", "boss": "bl_hook"}` | set this ante's boss |
| `{"cmd": "cheat", "win": True}` | beat the current blind now, as if a hand had scored enough (in `SELECTING_HAND`) |
| `{"cmd": "add_joker", "key": "j_blueprint", "edition": "negative"}` | add a joker or a consumable (`add_joker` in the game's debug tools). `edition` is optional: `foil`, `holo`, `polychrome`, `negative`. |
| `{"cmd": "add_tag", "key": "tag_charm"}` | add a tag. An Orbital Tag takes `orbital_hand` (default `"High Card"`). |
| `{"cmd": "add_voucher", "key": "v_retcon"}` | redeem a voucher for free |

A run is fully described by its settings and its list of commands:

```python
G = Game(seed, deck=deck, stake=stake).start_run()
for cmd in commands:
    G.do(cmd)
```

### Inspecting

| Member | |
|---|---|
| `GAME` | the run state, with the Lua field names (see [State reference](state-reference.md)) |
| `STATE` | the current state (`STATES`) |
| `deck`, `hand`, `play`, `discard`, `jokers`, `consumeables` | the card areas (`CardArea`, with `.cards` left to right) |
| `shop_jokers`, `shop_vouchers`, `shop_booster`, `pack_cards` | the shop's and the pack's areas (`None`, or `.removed`, when closed) |
| `playing_cards` | every playing card the run owns |
| `last_score` | the last hand played: `{'chips', 'mult', 'score', 'hand'}`, or `None` |
| `round_eval_rows` | the last cash-out rows: `[(label, dollars)]` with labels `blind`, `hands`, `discards`, `joker:<key>`, `tag:<key>`, `interest` |
| `blind_select_tags` | the tags offered on the blind select screen (`Tag` objects) |
| `rng` | the RNG state ([`PseudoRandom`](#balatrorng)) |
| `summary() -> str` | a short readable description: ante, money, blind, jokers, consumables, hand, shop or pack |
| `snapshot() -> dict` | the whole state as plain data ([format](state-reference.md#snapshot)) |
| `next_draws(n=None) -> list[Card]` | the next `n` cards the deck will deal, in order (all of them if `n` is None). The deck is reshuffled when each round starts. |
| `hands_order() -> list[str]` | the `pairs(G.GAME.hands)` order in use |
| `get_blind_amount(ante) -> float` | the base score of an ante (`get_blind_amount`), before the blind's multiplier |
| `get_poker_hand_info(cards) -> tuple` | the poker hand cards make: `(name, display_name, poker_hands, scoring_cards, display_name)` |
| `find_joker(name, non_debuff=None) -> list[Card]` | the jokers with this name (`find_joker`) |
| `is_unlocked(center)`, `is_discovered(key)` | per the profile |

### Branching

**`clone() -> Game`** returns an independent copy of the run. The static
prototype tables are shared; everything else is copied, including pending
events and the closures they hold. The copy continues exactly as the
original would. It takes a few milliseconds.

```python
best = max(candidates, key=lambda play: score_after(G.clone(), play))
```

### Front-end hooks

Described in detail in [Front-end hooks](frontend-hooks.md).

| Method | |
|---|---|
| `preview_hand(idxs) -> dict` | what the game shows while these hand cards are selected: `selected`, `hand`, `display`, `level`, `chips`, `mult`, `scoring` (hand positions), `not_allowed`, `hidden`. Changes nothing. Raises `IllegalAction` outside `SELECTING_HAND`, or for a bad selection. |
| `start_feedback() -> list[dict]` | start recording what the player sees happen; returns the list that fills up |
| `stop_feedback() -> list[dict]` | stop recording; returns the list |

### Running frames

The `act_*` methods call these; tools may call them directly.

| Method | |
|---|---|
| `settle(max_frames=100000) -> int` | runs frames until the game waits for the player (four quiet frames in a row: the event queue idle, no lock, the state function done), or until game over. Returns the number of frames. When the run is won, it presses *Endless mode* on the win screen. |
| `settled() -> bool` | the current frame is quiet |
| `frame()` | one `Game:update(dt)`: timers, the event queue, the state function, card areas and UI motion. With `fast_forward`, a frame in which nothing can happen only moves the clocks. |

`TIMERS` (`{'TOTAL', 'REAL'}`), `FRAMES_MOVE` and `E_MANAGER` (the event
queue) expose the timeline. See [Internals](internals.md).

---

## `balatro.data`

The static game data, extracted from the original game by
`tools/lua/extract_data.lua` into `balatro/data/game_data.json`.

**`load(path=None) -> GameData`** (cached) loads it. Its attributes:

| Attribute | |
|---|---|
| `version` | the game version (`"1.0.1o-FULL"`) |
| `P_CENTERS` | every center by key: jokers, consumables, vouchers, boosters, decks, enhancements, editions |
| `P_CARDS` | the 52 playing cards (`"H_A"`: name, suit, value) |
| `P_BLINDS`, `P_TAGS`, `P_SEALS`, `P_STAKES` | |
| `P_CENTER_POOLS` | the pools by set (`"Joker"`, `"Tarot"`, `"Voucher"`, ...), **in the game's order**, which the RNG depends on |
| `P_JOKER_RARITY_POOLS` | jokers by rarity |
| `handlist`, `hands_proto`, `poker_hand_names` | poker hands: order, base values, display names |
| `starting_params` | the starting hands, discards, slots... |
| `challenges` | the 20 challenges |
| `center_by_name(name)`, `challenge(id)`, `display_name(key)` | lookups |

Each entry is a `T` (a dict with attribute access): `P_CENTERS["j_joker"].config.mult == 4`.

**`sprites() -> dict`** (cached) loads `balatro/data/sprites.json`: where the
game draws each item. See [Front-end hooks](frontend-hooks.md#sprites).

---

## `balatro.analyzer`

Seed analysis, following the seed finders' convention: select and win every
blind without playing a hand, open and skip both packs in every shop, reroll
the shop `rerolls` times, buy nothing.

**`analyze(seed, deck="b_red", stake=1, antes=8, rerolls=2, open_packs=True, **kw) -> SeedReport`**.
`kw` is passed to `Analyzer` (`challenge`, `profile`, `hands_order`).

| Class | Fields |
|---|---|
| `SeedReport` | `seed`, `deck`, `stake`, `starting_deck`, `antes: list[AnteInfo]`; `to_text()` |
| `AnteInfo` | `ante`, `boss`, `boss_name`, `voucher`, `voucher_name`, `blinds: list[BlindInfo]`, `shops: list[ShopInfo]` |
| `BlindInfo` | `kind` (Small/Big/Boss), `key`, `name`, `chips`, `tag`, `tag_name`, `orbital_hand`, `first_hand` |
| `ShopInfo` | `blind` (the blind just beaten), `cards` (the shop queue: 2, plus 2 per reroll), `vouchers`, `packs` |
| `PackInfo` | `key`, `name`, `contents: list[CardInfo]` |
| `CardInfo` | `key`, `name`, `set`, `edition`, `seal`, `card`, `eternal`, `perishable`, `rental`, `cost` |

`describe(card) -> str` is a short label for a card (`"TH+steel*red"`,
`"Smeared Joker (Holo)"`).

---

## `balatro.quick`

**`Ante1(seed, deck="b_red", normalize=True)`**: what is known at the first
blind select, computed directly from the RNG without a `Game`. It is fast
enough for seed searching (about 10,000 seeds per second).

| Member | |
|---|---|
| `boss` | the ante-1 boss key |
| `voucher` | the ante-1 voucher key |
| `tags` | `(small_tag, big_tag)` |
| `starting_deck()` | the deck's card keys in creation order |
| `first_hand()` | the cards drawn for the Small Blind (8; 10 for Painted Deck), in draw order |

`ante1(seed, deck)` is a shortcut.

---

## `balatro.poker`

| Function | |
|---|---|
| `evaluate_poker_hand(G, cards) -> T` | every poker hand the cards contain (`evaluate_poker_hand`), honouring Four Fingers, Shortcut and Smeared Joker |
| `get_poker_hand_info(G, cards)` | `(name, display_name, poker_hands, scoring_cards, display_name)`: the best hand and the cards that score. `display_name` is `"Royal Flush"` for an ace-high straight flush. |
| `get_flush`, `get_straight`, `get_X_same`, `get_highest` | the building blocks, as in the game |

---

## `balatro.rng`

Balatro's randomness, bit for bit.

**`PseudoRandom(seed, state=None)`** is the `G.GAME.pseudorandom` table and the
functions that use it. `G.rng` is one.

| Method | Lua | |
|---|---|---|
| `pseudoseed(key) -> float` | `pseudoseed(key)` | advances stream `key` and returns its seed |
| `peek(key) -> float` | | the value `pseudoseed(key)` would return, without advancing |
| `random(key_or_seed) -> float` | `pseudorandom(x)` | a float in [0, 1) |
| `randint(key_or_seed, lo, hi) -> int` | `pseudorandom(x, lo, hi)` | |
| `element(items, seed)` | `pseudorandom_element` | an element of a list already in the game's sort order |
| `element_index(n, seed) -> int` | | the 0-based index `pseudorandom_element` picks among `n` |
| `shuffle(items, seed)` | `pseudoshuffle` | in place |
| `copy()` | | |
| `state` | | the streams: `{key: float}` |

| Function | |
|---|---|
| `pseudohash(s) -> float` | `pseudohash` |
| `seeded_random(seed) -> float` | `math.randomseed(seed); math.random()` |
| `predict_pseudoseed(key, seed) -> float` | the first value of a stream for a run seed, without state |
| `random_string(length, seed) -> str` | `random_string` (how the game makes seeds) |
| `normalize_seed(seed) -> str` | upper-case, `0` → `O` |
| `LuaJITRandom` | LuaJIT 2.1's `math.random` (Tausworthe): `seed(x)`, `random()`, `randint(lo, hi)` |
| `SEED_ALPHABET` | `"123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"` |

---

## `balatro.snapshot`

`snapshot(G) -> dict` is `Game.snapshot()`: the state in the format of the
oracle's dump, so the engine can be compared with the original game. The
format is in [State reference](state-reference.md#snapshot).

---

## `balatro.oracle`

Runs the **original** game headlessly as a reference. It needs `luajit` and
the game's Lua source (see [Verification](verification.md)).

| | |
|---|---|
| `Oracle(src=None, profile="all", gamespeed=1, dt=1/60)` | starts `tools/lua/oracle.lua`. `src`: the game source directory (default `$BALATRO_SRC` or `../balatro_src`). Use it as a context manager. |
| `Oracle.send(cmd) -> dict` | sends a command (`{"cmd": "start", "seed", "deck", "stake"}` or any `do` command) and returns the reply, whose `state` is the game's snapshot. Raises `OracleError` on a game error. |
| `Oracle.close()` | |
| `normalize(state) -> dict` | prepares a snapshot for comparison |
| `diff(a, b) -> list[str]` | the differences between two snapshots, as paths |

Command-line tools: `python -m balatro.oracle.fuzz` and
`python -m balatro.oracle.replay` (see [Verification](verification.md)).

---

## `balatro.lua`

Helpers that give Python the semantics of Lua tables and numbers, used
throughout the engine:

| | |
|---|---|
| `T` | a dict with attribute access, where missing keys read as `None` (a Lua table) |
| `to_T(obj)`, `copy_table(obj)` | convert / deep-copy nested data |
| `lor(x, y)` | Lua's `x or y` (only `None` and `False` are falsy) |
| `truthy(v)`, `nonempty(t)` | Lua truthiness, a non-empty table |
| `floor`, `lua_mod`, `lua_pow`, `lua_div` | Lua's number operations, NaN and infinity included |
