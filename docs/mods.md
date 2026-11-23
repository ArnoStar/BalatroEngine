# Mods and game modes

There are two kinds of mods:

- **Content mods** are data: a JSON package that adds jokers, consumables,
  vouchers, decks, boss blinds and rules, or turns on creative mode. Anyone
  can write one, it runs safely on a server (it is never code), and a visual
  editor can make one. See [Content mods](#content-mods) below.
- **Game modes** (PvP, coop) are Python classes in the engine that hook into
  its code.

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
- **Coop**: the deck deals as in the original game, and the shop, bosses and
  tags keep the original's random streams (until what the second player does
  changes them).

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
| `shuffle_key(G, area, key)` | `CardArea.shuffle` | the random stream's key |
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

## Coop (`"coop"`)

Two players play one run together, in turns (`balatro.mods.coop`).

- **Shared**: the run (money, shop, vouchers, tags, consumables, hand
  levels, blinds), the deck and its hand, a round's hands (as in the game)
  and discards (doubled), and the jokers: 10 slots, 5 for each player
  (`limits`). Every joker counts; a player buys, sells and moves only their
  own (a joker's `seat`).
- **Turns** (`turn`): the player whose turn it is plays: play, discard, sort,
  choose the blind, use consumables during the round. After each hand they
  play, the turn passes and the other player goes on with the hand. A round
  starts with the player who didn't play the last hand.
- **The shop**: both players buy for themselves (a joker in their half, a
  pack they open: `pack_seat`; while it is open its cards, the hand's cards
  and the consumables are theirs to use). The shop is left once both have
  sent `end_shop` (`shop_votes`).
- **Blinds** grow faster: `max(1 + BLIND_GROWTH * (ante - 1),
  exp(BLIND_STEEPNESS * (ante - 1)²))` times the game's (`blind_factor`:
  ante 2 x1.35, ante 4 x2.46, ante 6 x12.2, ante 8 x134).

**Rules** (option `rules`, default 2, `LATEST_RULES`): a run replays with the
rules it started with, so keep the number with the run. Rules 1 (until engine
0.9.0) are `decks="own"` and `blinds="linear"`; the two options can also be
given on their own (`{"key": "coop", "decks": "own"}`):

- `decks="own"`: each player has their own deck, with its hand and discard
  pile (the `seats`' card areas; `G.hand`, `G.deck`, `G.discard` are the
  active seat's), the second player's shuffled on its own random streams
  (`..._2`). On their turn a player plays from their own hand (their deck
  shuffled for the round and their hand drawn the first time); a playing card
  bought goes in its buyer's deck, a pack deals its opener's hand.
- `blinds="linear"`: `1 + BLIND_GROWTH * (ante - 1)` times the game's (0.35:
  ante 4 x2.05, ante 8 x3.45).

Every command carries its player's `seat` (0 or 1); one the rules don't
allow raises `IllegalAction`. `legal_actions()` lists the `viewer` seat's.
Feedback adds `{"type": "turn", "seat"}` when the turn passes and
`{"type": "shop_vote", "seats"}` when a player asks to leave the shop.
`state()` gives the turn, the joker slots, the shop votes, the pack's
opener, `decks_mode` (`"shared"` or `"own"`) and `blinds`, each seat's deck
and hand sizes (`decks`: own decks only), and each player's `stats` (hands
played, their chips, the best one and its name, discards).

## Content mods

A content mod is a package: plain JSON, format 1. Pass it to `Game` like any
mod (with other mods, game modes included):

```python
import json
from balatro import Game
from balatro.mods import examples

pkg = json.load(open("my_mod.json"))
G = Game("SEED", deck="b_my_mod_gold", mods=[pkg, examples()["creative"]]).start_run()
```

`balatro.mods.spec.validate(pkg)` lists what is wrong with a package, each
error with its place in it (`jokers[0].effects[1].if: unknown name 'cardd'`);
`Game` raises `balatro.mods.content.ModError` (with `.errors`) for a package
that isn't valid, or that names a card no mod of the run has. A package
without its images is `spec.logic(pkg)`: that is all the engine needs.

**Nothing in a package is code.** Effects are a trigger, a condition and
actions; conditions and amounts are expressions in a small language (below)
that can only read the game and call a fixed set of functions. An expression
never fails a run: a mismatch (a number plus a string, a field of nothing) is
`nil`.

**A run with content mods** unlocks and discovers nothing, and its items are
always unlocked. A run without content mods is the original game: the mods
add their items to a copy of the game's tables (`G.data`), never to the
original ones. Same seed, same mods, same commands: the same run (replays,
clones and `G.snapshot()` work as without mods).

Three examples come with the engine (`balatro.mods.examples()`, files in
`balatro/mods/examples/`):

- `fruit_stand`: six jokers with their own art (scoring on cards, chances,
  values that grow, retriggers, money at cash out, passive changes, new
  cards). `tools/example_art.py` draws the art.
- `wild_rules`: two decks, three boss blinds, Tarot/Spectral/Planet cards,
  two vouchers and a house rule.
- `creative`: creative mode.

### The package

| Field | | |
|---|---|---|
| `format` | required | `1` |
| `id` | required | 3 to 32 of `a-z 0-9 _`, starting with a letter; the items' keys start with it. Not `pvp` or `coop` |
| `name` | required | 1 to 60 characters |
| `version` | required | `major.minor.patch` (`1.0.0`) |
| `author`, `description` | | up to 60 / 2000 characters |
| `tags` | | up to 8 words (`jokers`, `example` ...) |
| `loc` | | translations of `name` and `description`: `{"ru": {"name": ..., "description": ...}}` |
| `rules` | | run modifiers applied when a run starts (every run with the mod) |
| `creative` | | `true`: creative mode (below) |
| `jokers`, `consumables`, `vouchers`, `decks`, `blinds` | | the items, up to 100 of each |
| `assets` | | images: `{"name": "data:image/png;base64,..."}`, PNG, up to 256 kB each, 64 of them |

A package is at most 1.5 MB.

### Every item

| Field | |
|---|---|
| `key` | 1 to 32 of `a-z 0-9 _`; unique among the package's items of its kind. The game's key is `j_<id>_<key>` (jokers), `c_` (consumables), `v_` (vouchers), `b_` (decks), `bl_` (blinds) |
| `name` | the English name, 1 to 40 characters |
| `text` | the description, up to 8 lines, in the game's markup: `{C:mult}+#1#{} Mult`, `{X:mult,C:white} X#1# {}`, `{C:inactive}(Currently ...)`, `{C:attention,T:m_lucky}Lucky{}` (a tooltip) |
| `vars` | up to 8 expressions, the description's `#1#`, `#2#` ...; they may not draw random numbers |
| `loc` | translations: `{"fr": {"name": ..., "text": [...]}}` |
| `sprite` | an asset's name, or a cell of the game's art: `{"atlas": "Joker", "x": 0, "y": 0}` (atlases `Joker`, `Tarot`, `Planet`, `Spectral`, `Voucher`, `centers` for decks); a blind: `{"blind": "bl_hook"}` (that blind's chip) |

An asset is one card, at the game's 2x size (142x190; 71x95 works too).

### Jokers

| Field | Default | |
|---|---|---|
| `rarity` | 1 | 1 common, 2 uncommon, 3 rare, 4 legendary (only made by The Soul, or by name) |
| `cost` | 5 | |
| `config` | `{}` | the joker's values (numbers, strings, true/false; up to 32): each copy keeps its own, read as `self.<name>` and changed by `set` |
| `blueprint_compat`, `eternal_compat`, `perishable_compat` | true | |
| `in_shop` | true | false: only made by name (a deck, a `create`, creative mode) |
| `passive` | | run modifiers while the joker is in play (undone when it leaves or is debuffed): `hand_size`, `discards`, `hands` (per round, from the next round), `joker_slots`, `consumable_slots`, `interest_cap`, `probability_mult` |
| `effects` | `[]` | up to 32: `{"on": trigger, "if": expression, "do": [actions], "else": [actions]}` |

An effect's actions run when its trigger comes and its condition (if any)
holds; `else` runs when the condition doesn't hold. The effects of one
trigger add up (two `mult` actions give both). A Blueprint or Brainstorm
copying the joker runs its effects too (unless `blueprint_compat` is false),
except `set` and `destroy_self`.

**Triggers** (in the order of `calculate_joker`), and what they can read
besides `self`, `joker`, `game` and the card lists:

| Trigger | When | Reads |
|---|---|---|
| `hand_played` | a hand is played, before scoring | `hand`, `scoring`, `played`, `has_hand()` |
| `card_scored` | each scored card (and each retrigger) | `card`, the hand |
| `card_held` | each card held in hand while scoring | `card`, the hand |
| `retrigger_scored` / `retrigger_held` | may retrigger that card | `card`, the hand |
| `score` | the joker's own turn in scoring | the hand |
| `other_joker` | after each other joker scores | `other`, the hand |
| `hand_finished` | after the hand scored | the hand |
| `card_destroy` | each scored card, after scoring: the card is destroyed if the condition holds | `card`, the hand |
| `hand_not_allowed` | the boss blind forbids the hand | the hand |
| `discard_start` | a discard, once | `discarded` |
| `discard` | each discarded card | `card`, `discarded` |
| `round_end` | the round ends | |
| `cash_out` | the round's earnings: its `dollars` are the joker's row | |
| `blind_selected` | a blind is selected | `blind` |
| `first_hand_drawn` | the first hand of a round is drawn | |
| `shop_reroll`, `shop_exit` | in the shop | |
| `blind_skipped`, `pack_opened`, `pack_skipped` | | |
| `card_bought`, `card_sold` | a card bought or sold | `other` |
| `sold` | this joker is sold | |
| `consumable_used` | a consumable is used | `other` |
| `cards_added` | playing cards added to the deck | `event.count` |
| `cards_destroyed` | playing cards destroyed | `event.count`, `event.faces`, `event.glass` |

**Actions** (each is an object with one field):

| Action | | Where |
|---|---|---|
| `{"chips": e}`, `{"mult": e}`, `{"xmult": e}` | score | `card_scored`, `score`, `other_joker` (all three); `card_held` (`mult`, `xmult`) |
| `{"dollars": e}` | money (negative: lose it) | anywhere; in `cash_out`, the round's earnings |
| `{"retrigger": e}` | retrigger the card `e` times | `retrigger_scored`, `retrigger_held` |
| `{"set": {"name": e, ...}}` | change the joker's values (all computed first) | jokers |
| `{"message": "k_upgrade_ex"}` | the text over the card: a key of the game's texts (`k_upgrade_ex`, `k_safe_ex`, `k_eaten_ex`, `k_plus_planet` ...) or your own words | anywhere |
| `{"level_up": e}` | level up the played hand `e` times | `hand_played`, `score`, `hand_finished`, consumables |
| `{"level_up": {"hand": e, "levels": e}}` | level up a named hand (`"'Flush'"`) | anywhere |
| `{"create": {"set": "Tarot", "key": ..., "rarity": 2, "edition": "negative"}}` | a new Tarot / Planet / Spectral / Joker (if there is room; `key`: that card; `rarity`: jokers) | anywhere |
| `{"destroy_self": true}` | the joker is destroyed (eaten) | jokers |
| `{"destroy_card": true}` | the discarded card is destroyed | `discard` |
| `{"hands": e}`, `{"discards": e}` | hands / discards this round | anywhere |
| `{"modify_run": {modifier: e}}` | change the run for good (run modifiers) | anywhere |
| `{"modify": {...}}` | change cards (below) | anywhere |
| `{"add_tag": "tag_double"}` | get a tag | anywhere |
| `{"disable_boss": true}` | disable the boss blind | anywhere |

`modify` changes cards: `target` (`card`: the trigger's card, the default for
jokers; `scoring`, `played`, `held`; `selected`: a consumable's, its default),
`where` (an expression about `card`: only those), and what changes:
`enhancement` (`m_gold` ..., `none`), `seal` (`Gold` ..., `none`), `edition`
(`foil`, `holo`, `polychrome`, `none`), `suit`, `rank` (`Ace` ..., `up`,
`down`), `chips` (permanent bonus chips, as Hiker), `destroy` (`selected`
only, as The Hanged Man).

### Consumables

| Field | | |
|---|---|---|
| `set` | required | `Tarot`, `Planet` or `Spectral` |
| `cost` | 3 (Spectral 4) | |
| `config` | | values its expressions read as `self.<name>` |
| `hand` | | a Planet card: the poker hand it levels up (the game's own planet; no `use`) |
| `targets` | | `{"min": 1, "max": 2}`: hand cards to select first |
| `can_use` | | an expression: when it can be used (no random numbers) |
| `use` | | the actions (as a joker's; `modify` changes the selected cards) |

### Vouchers

`cost` (10), `config`, `requires` (voucher keys that must be redeemed first,
the game's or a mod's: `v_<id>_<key>`), `redeem` (actions).

### Decks

`start` (run modifiers), `jokers`, `consumables`, `vouchers` (keys the run
starts with), `cards` (the deck: `ranks` / `no_ranks` (`2` ... `10`, `Jack`,
`Queen`, `King`, `Ace`), `suits` / `no_suits`, and every card's
`enhancement`, `edition`, `seal`).

### Boss blinds

| Field | Default | |
|---|---|---|
| `mult` | 2 | the blind's size, times the ante's base |
| `dollars` | 5 | its reward |
| `min_ante`, `max_ante` | 1, 10 | the antes it can come in (as the game's bosses) |
| `showdown` | false | a final boss (every `win_ante`th ante) |
| `colour` | | `#rrggbb` |
| `debuff_card` | | an expression about `card`: it is debuffed |
| `debuff_hand` | | an expression about the `hand` (`hand.count`, `has_hand('Pair')`): the hand is not allowed |
| `on_set` | | when the blind is set: `hands`, `discards`, `hand_size` (all undone if it is disabled; the hand size when it is beaten too), `dollars`, `message` |
| `on_hand` | | each hand played and allowed: `dollars`, `message` |

### Run modifiers

`rules`, a deck's `start`, a joker's `passive` and `modify_run` share these
(amounts are added; `probability_mult` and `blind_scale` multiply):
`dollars`, `hands`, `discards` (per round), `hand_size`, `joker_slots`,
`consumable_slots`, `interest_cap` (25 is $5 of interest), `reroll_cost`,
`shop_slots`, `discount_percent`, `probability_mult` (2: Oops! All 6s),
`win_ante` and `blind_scale` (start only).

### Expressions

```
card.rank == 7 and is_suit(card, 'Hearts')
self.mult + 2 * count_face(scoring)
if(game.money > 20, 3, 1)
```

Numbers, `'strings'`, `true`, `false`, `nil`; `+ - * / % ^`, `== != < <= > >=`,
`and or not`, parentheses. As in Lua, only `false` and `nil` are false (`0`
is true: write `self.count > 0`) and `a or b` gives `a` unless it is false.
Up to 500 characters.

| Name | |
|---|---|
| `self.<name>` | the item's `config` values (a joker: this copy's) |
| `joker.position`, `.sell_value`, `.edition` | the joker itself (1 is the leftmost) |
| `card.<field>`, `other.<field>` | a card: `rank` (2 .. 14, Ace 14), `rank_name` (`Ace`), `suit`, `face`, `chips`, `enhancement` (`m_gold` or nil), `seal`, `edition`, `debuffed`, `key`, `set`, `rarity`, `sell_value`, `cost` |
| `hand.<field>` | the played hand: `name`, `level`, `played`, `played_this_round`, `count` (cards played), `scoring_count`, `chips`, `mult` |
| `game.<field>` | `money`, `ante`, `round`, `hands_left`, `discards_left`, `hands_played`, `discards_used`, `hand_size`, `deck_count`, `full_deck_count`, `joker_count`, `joker_slots`, `consumable_count`, `consumable_slots`, `probability` (1, 2 with Oops! All 6s), `blind_boss`, `blind_chips`, `round_chips`, `skips`, `rerolls`, `interest_cap`, `stake`, `hands_per_round`, `discards_per_round` |
| `blind.<field>` | `blind_selected`: `boss`, `key`, `chips`, `mult`, `dollars` |
| `event.<field>` | `cards_added`, `cards_destroyed` |
| card lists | `scoring`, `played`, `held`, `deck` (left to draw), `full_deck`, `jokers`, `consumables`, `discarded`, `selected` |

Functions: `min`, `max`, `floor`, `ceil`, `abs`, `round`, `clamp(x, lo, hi)`,
`if(c, a, b)`; `is_suit(card, s)` (Wild Cards and Smeared Joker count),
`is_rank(card, 7 or 'Ace')`, `is_face(card)`, `count(list)`,
`count_suit(list, s)`, `count_rank(list, r)`, `count_face(list)`,
`count_enhancement(list, 'm_gold')`, `count_seal(list, 'Red')`,
`count_edition(list, 'foil')`, `count_key(list, key)`, `hand_level(name)`,
`times_played(name)`, `has_joker(key)`, `has_voucher(key)`,
`has_hand(name)` (the played hand contains it). Random:
`chance(n, d)` (n in d, times `game.probability`, as the game's "1 in 4"),
`random(lo, hi)` (a whole number); a third argument names a separate random
stream. Each item draws from its own streams, so a mod's chances don't move
the game's.

The game's front end evaluates `vars` with a twin of `balatro/mods/expr.py`:
keep both in step.

### Creative mode

A package with `"creative": true` (the `creative` example) lets the player
change the run with the command `{"cmd": "creative", "op": ...}`
(`balatro/mods/creative.py` documents each one): `set` money, hands,
discards, hand size, slots, ante, the round's chips, the reroll cost or the
interest cap; `level` a poker hand; `add` any joker, consumable, voucher or
tag (other mods' too); `add_card` a playing card to the hand or the deck;
`edit` a card (edition, seal, enhancement, rank, suit, stickers); `remove`
one; choose the `boss`; `win` the round. Each goes through the game's own
functions, so the game goes on by its rules from there, and it is a command
in the run's history like any other: replays make it again. `legal_actions()`
has `{"cmd": "creative"}` while it can be used.
