# State reference

The run state, where to find it, and what its fields mean. The engine keeps
the Lua source's names (`G.GAME.round_resets.blind_choices`, `consumeables`,
`ability.extra`), so the game's code is the full reference for any field not
listed here.

Tables are `balatro.lua.T` objects: dicts that also allow attribute access.
A missing key reads as `None`, like `nil` in Lua: `G.GAME.modifiers.no_interest`
is `None` unless a challenge sets it.

## The `Game` object

| Attribute | |
|---|---|
| `GAME` | the run state (below) |
| `STATE`, `STATE_COMPLETE` | the state machine (see [Game flow](game-flow.md)) |
| `deck`, `hand`, `play`, `discard` | playing card areas |
| `jokers`, `consumeables` | the joker and consumable areas |
| `shop_jokers`, `shop_vouchers`, `shop_booster` | the shop's areas while it is open |
| `pack_cards` | the open booster pack |
| `playing_cards` | every playing card the run owns, wherever it is |
| `rng` | the RNG streams (`rng.state`: `{key: float}`, the Lua `G.GAME.pseudorandom`) |
| `data`, `P_CENTERS`, `P_CARDS`, `P_BLINDS`, `P_TAGS`, `P_SEALS`, `P_CENTER_POOLS` | static data |
| `seed`, `deck_key`, `stake`, `challenge_id` | the settings |
| `last_score`, `round_eval_rows` | the last hand's result, the last cash-out rows |
| `TIMERS`, `E_MANAGER`, `SETTINGS`, `CONTROLLER` | the engine's clocks, event queue, settings (game speed) and locks |

## `G.GAME`

The run state (`Game:init_game_object()`). The fields most used:

### Money, score and progress

| Field | |
|---|---|
| `dollars` | money |
| `chips` | this round's score |
| `round` | rounds started |
| `round_resets.ante` | the ante |
| `won` | the ante-8 boss has been beaten (the run goes on in endless mode) |
| `win_ante` | 8 |
| `stake` | 1-8 |
| `bankrupt_at` | how low money may go (0; −20 with Credit Card) |
| `interest_amount`, `interest_cap` | $ per $5 of interest, the money counted at most |
| `discount_percent` | shop discount (vouchers) |
| `inflation` | price increase per purchase (a challenge rule) |
| `skips`, `hands_played`, `unused_discards` | counters some jokers and tags read |
| `probabilities.normal` | the numerator of every "1 in N" chance (doubled by Oops! All 6s) |
| `last_tarot_planet` | the last Tarot or Planet used (The Fool) |
| `selected_back` | the deck (`Back`), with `selected_back_key` its center |
| `modifiers` | stake and challenge rules (`no_blind_reward`, `scaling`, `enable_eternals_in_shop`, `no_interest`, `debuff_played_cards`, `flipped_cards`, ...) |
| `starting_params` | hands, discards, hand size, slots and ante scaling at the start |

### The current round: `GAME.current_round`

| Field | |
|---|---|
| `hands_left`, `discards_left` | |
| `hands_played`, `discards_used` | this round |
| `reroll_cost`, `free_rerolls` | the shop's next reroll |
| `current_hand` | the scoring panel: `handname`, `hand_level`, `chips`, `mult`, `chip_total` |
| `idol_card` (`rank`, `suit`), `mail_card.rank`, `ancient_card.suit`, `castle_card.suit` | this round's targets of The Idol, Mail-In Rebate, Ancient Joker, Castle |
| `most_played_poker_hand` | The Ox's hand |
| `voucher` | the ante's voucher key |
| `dollars` | the cash-out total |

### Blinds: `GAME.round_resets` and `GAME.blind`

| Field | |
|---|---|
| `round_resets.blind_choices` | `{Small, Big, Boss}`: blind keys of the ante |
| `round_resets.blind_states` | `{Small, Big, Boss}`: `Select`, `Upcoming`, `Current`, `Defeated`, `Skipped`, `Hide` |
| `round_resets.blind_tags` | `{Small, Big}`: tag keys for skipping |
| `round_resets.blind_ante` | the ante the blinds belong to |
| `round_resets.hands`, `round_resets.discards` | hands and discards each round starts with |
| `round_resets.boss_rerolled` | the boss was rerolled this ante (Director's Cut) |
| `blind_on_deck` | `Small`, `Big` or `Boss` |
| `blind` | the current `Blind` (below) |
| `bosses_used` | how often each boss appeared (boss choice avoids repeats) |
| `orbital_choices` | `{ante: {Small, Big, Boss}}`: the hands Orbital Tags would level |

### Poker hands: `GAME.hands`

`GAME.hands["Flush"]` holds `level`, `chips`, `mult` (at the current level),
`played`, `played_this_round`, `visible`, `s_chips`/`s_mult` (level 1) and
`l_chips`/`l_mult` (per level).

### Collections

| Field | |
|---|---|
| `tags` | the tags held (`Tag` objects), oldest first |
| `used_vouchers` | `{key: True}` for redeemed vouchers |
| `used_jokers` | `{key: True}` for jokers currently owned or seen (pool exclusion, as in the game) |
| `pool_flags` | flags that open or close pools (`gros_michel_extinct`, ...) |
| `cards_played` | `{rank: {total, suits}}` |
| `pack_choices` | cards left to take in the open pack |
| `shop.joker_max` | the shop's card slots |
| `consumeable_usage`, `hand_usage`, `joker_usage` | usage counters |
| `challenge` | the challenge id, if any |

## Card areas (`CardArea`)

| Member | |
|---|---|
| `name` | `deck`, `hand`, `play`, `discard`, `jokers`, `consumeables`, `shop_jokers`, `shop_vouchers`, `shop_booster`, `pack_cards` |
| `cards` | left to right as on screen. **The deck deals from the end**: `next_draws()` reads it reversed. |
| `highlighted` | the selected cards |
| `config.card_limit` | the area's size: hand size, joker slots, consumable slots |
| `config.highlighted_limit` | 5 for the hand |
| `index(card)` | the card's position |
| `removed` | the area is gone (a closed shop or pack) |

## Cards (`Card`)

| Member | |
|---|---|
| `sort_id` | the card's id: unique in the run, stable for its whole life |
| `key` | its center key: `j_joker`, `c_fool`, `v_overstock_norm`, `p_buffoon_normal_1`, `m_glass`, `c_base` |
| `label()` | a short label: `AH` for a playing card, the key for other cards |
| `config.center` | the prototype (`P_CENTERS[key]`): `name`, `set`, `cost`, `rarity`, `config`... |
| `config.card_key` | playing cards: `H_A`, `S_T`, ... |
| `base` | playing cards: `suit`, `value` (`"Ace"`, `"10"`), `id` (2-14), `nominal` (chips) |
| `ability` | the card's live state: `set` (`Default`, `Enhanced`, `Joker`, `Tarot`, `Planet`, `Spectral`, `Voucher`, `Booster`), `name`, `effect`, `extra`, `mult`, `x_mult`, `perma_bonus`, `eternal`, `perishable`, `perish_tally`, `rental`, `forced_selection`, `consumeable` |
| `edition` | `None` or a table with `type` (`foil`, `holo`, `polychrome`, `negative`) and its bonus (`chips`, `mult`, `x_mult`) |
| `seal` | `None`, `Gold`, `Red`, `Blue`, `Purple` |
| `debuff` | debuffed |
| `facing` | `front` or `back` (face down) |
| `highlighted` | selected |
| `cost`, `sell_cost` | buy and sell prices |
| `area` | the `CardArea` it is in |
| `get_id()`, `is_face()`, `is_suit(suit)`, `get_chip_bonus()` | the game's own helpers |

## `Blind`

`G.GAME.blind`:

| Member | |
|---|---|
| `name` | `Small Blind`, `The Hook`, ... |
| `config.blind` | the prototype (`P_BLINDS[key]`, with `key`) |
| `chips` | the score needed |
| `dollars` | the reward |
| `mult` | multiple of the ante's base score |
| `boss`, `disabled`, `triggered` | |
| `debuff` | the boss's debuff rules (`suit`, `is_face`, `h_size_ge`, ...) |
| `get_type()` | `Small`, `Big` or `Boss` |

## `Tag`

| Member | |
|---|---|
| `key`, `name` | |
| `ability.orbital_hand` | an Orbital Tag's hand |
| `ID` | creation counter |

## What a run adds to the profile (`G.PROFILE`)

The game keeps a profile per player (`G.PROFILES[G.SETTINGS.profile]`):
career stats, high scores, and how often each joker and voucher was used.
`G.PROFILE` is the part of it this run adds, starting from a blank profile,
written by the game's own functions at the same places (`inc_career_stat`,
`check_and_set_high_score`, `set_joker_usage`, `set_joker_win`,
`set_joker_loss`, `set_voucher_usage`). Nothing in the game reads it.

| Field | |
|---|---|
| `career_stats` | `{c_cards_played: n, c_dollars_earned: n, ...}`: the game's 20 career stats (`balatro.common.CAREER_STATS`). The two streaks (`c_single_hand_round_streak`, `c_round_interest_cap_streak`) span runs in the game; here they start at 0 |
| `high_scores` | `{hand, furthest_round, furthest_ante, most_money, boss_streak}`: the run's best |
| `joker_usage` | `{key: {count, wins: {stake: n}, losses: {stake: n}}}`: `count` = won rounds the joker was held in; wins and losses = copies held when the run was won or lost |
| `voucher_usage` | `{key: times redeemed}` |

The game only records these for an unseeded run that isn't a challenge. The
engine's runs all behave as seeded runs (nothing is unlocked), but `PROFILE` is
recorded as for an unseeded run, every time: whoever keeps the player's profile
decides which runs count. For the same reason `GAME.current_boss_streak` counts
as in an unseeded run. The win streaks, which span runs, are left to that keeper.
`check_and_set_high_score` also raises `GAME.round_scores` (as the game does,
seeded or not). The oracle records the same (`profile` in its dump, with the
game's "seeded" checks around the stats skipped), so it is verified like the
rest of the state.

## Snapshot

`G.snapshot()` returns the state as plain JSON-able data. It is the format of
the oracle's dump (`tools/lua/oracle.lua`), which is how the engine and the
original game are compared. Numbers are strings in `%.17g` format, so floats
compare exactly.

| Key | |
|---|---|
| `state`, `state_complete` | |
| `ante`, `round`, `dollars`, `chips`, `hands_left`, `discards_left` | |
| `hand_size`, `joker_slots`, `consumable_slots`, `reroll_cost` | |
| `blind` | `{name, chips, disabled}` |
| `blind_on_deck`, `boss`, `voucher`, `blind_tags`, `blind_states`, `tags` | |
| `deck`, `hand`, `discard`, `play`, `jokers`, `consumeables` | lists of cards (below), in area order (the deck in deal order, last first) |
| `shop_jokers`, `shop_vouchers`, `shop_booster`, `pack_cards` | the same, or `null` when closed |
| `pack_choices` | |
| `hands` | `{name: {level, played, chips, mult, visible}}` |
| `used_jokers`, `used_vouchers`, `pool_flags` | sorted key lists |
| `current_round` | `{idol, mail, ancient, castle, most_played, dollars}` |
| `rng` | every RNG stream: `{key: value}` |
| `hands_order` | the `pairs(G.GAME.hands)` order in use |
| `round_scores` | `{name: amt}`: the run's scores the game shows when it ends (best hand, cards played, ...) |
| `profile` | `G.PROFILE` (below): `{career_stats, high_scores, joker_usage: {key: {count, wins, losses}}, voucher_usage}` |

A card is `{key, sort_id, card?, perma_bonus?, edition?, seal?, debuff?,
facing?, eternal?, perishable?, rental?, forced?, highlighted?, cost,
sell_cost, ability?}`. Optional keys appear only when set. `ability` (jokers)
has the counters (`mult`, `x_mult`, `extra_value`, `caino_xmult`, ...) and
`extra.*` values.

The snapshot includes hidden information (the deck's order, the RNG). It is a
debugging and verification tool, not a player view; BalatroWebAPI's views
hide those.
