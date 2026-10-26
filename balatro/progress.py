"""The player's progress, changed by an unseeded run as the game changes it:
check_for_unlock, unlock_card and discover_card (common_events.lua);
set_discover_tallies, get_deck_win_stake, set_deck_win, set_deck_loss and
set_challenge_unlock (misc_functions.lua); and the unlock checks that
Game:main_menu does between runs.

A run starts from the player's :class:`Profile` and changes its own copy
(``G.profile``) where the game changes ``G.PROFILES`` and the centers'
``unlocked`` and ``discovered`` flags: what gets unlocked enters the pools for
the rest of the run.  What the run unlocked and discovered is listed in
``G.PROFILE.progress`` too.  As in the game, a seeded run (the player chose
the seed) and a challenge unlock and discover nothing.  The Steam
achievements are left out: they change nothing in a run.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from . import data as data_mod
from .lua import T

if TYPE_CHECKING:
    from .card import Card
    from .game import Game

# G.CHALLENGE_WINS (globals.lua): decks to win with before challenges unlock
CHALLENGE_WINS = 5
# the career stats that are streaks: they span runs, and are set back to 0
STREAKS = ("c_round_interest_cap_streak", "c_single_hand_round_streak")


class Profile:
    """A player's progress, as much of ``G.PROFILES[G.SETTINGS.profile]`` and
    the centers' flags as decides what a run can find and unlock.

    ``Profile.everything()`` is the seed finders' convention (everything
    unlocked and discovered, nothing else known); ``Profile.fresh()`` is a
    brand new save.  The cumulative parts (career stats, deck wins, voucher
    usage, completed challenges) are what the unlock conditions read.
    """

    def __init__(self, unlocked: set[str] | None = None, discovered: set[str] | None = None, all_: bool = True,
                 career_stats: dict[str, float] | None = None,
                 deck_usage: dict[str, dict[str, dict[int, int]]] | None = None,
                 voucher_usage: dict[str, int] | None = None,
                 challenges_completed: set[str] | None = None) -> None:
        self.all = all_
        self.unlocked = set(unlocked or ())
        self.discovered = set(discovered or ())
        self.career_stats: dict[str, float] = dict(career_stats or {})
        # deck key -> {"wins": {stake: n}, "losses": {stake: n}}
        self.deck_usage: dict[str, dict[str, dict[int, int]]] = copy.deepcopy(deck_usage or {})
        self.voucher_usage: dict[str, int] = dict(voucher_usage or {})
        self.challenges_completed = set(challenges_completed or ())

    @classmethod
    def everything(cls) -> "Profile":
        return cls(all_=True)

    @classmethod
    def fresh(cls) -> "Profile":
        d = data_mod.load()
        unlocked = {k for k, v in d.P_CENTERS.items() if v.unlocked is not False}
        discovered = {k for k, v in d.P_CENTERS.items() if v.discovered}
        discovered |= {k for k, v in d.P_TAGS.items() if v.discovered}
        return cls(unlocked, discovered, all_=False)

    def copy(self) -> "Profile":
        return Profile(self.unlocked, self.discovered, self.all, self.career_stats, self.deck_usage,
                       self.voucher_usage, self.challenges_completed)

    # ------------------------------------------------------------ the game's helpers
    def deck_win_stake(self, deck: str | None = None) -> int:
        """get_deck_win_stake(deck): the highest stake won with the deck (0: none)."""
        if self.all:
            return 8
        if deck is None:
            return max((max(u.get("wins", {}) or {0: 0}) for u in self.deck_usage.values()), default=0)
        wins = (self.deck_usage.get(deck) or {}).get("wins") or {}
        return max(wins) if wins else 0

    def max_stake(self, deck: str) -> int:
        """The highest stake the run setup offers with this deck (G.FUNCS.change_viewed_back)."""
        return 8 if self.all else min(8, self.deck_win_stake(deck) + 1)

    def challenges_unlocked(self, total: int) -> int:
        """G.PROFILES[...].challenges_unlocked, as set_challenge_unlock keeps it: none
        until CHALLENGE_WINS decks have a win, then 5 more than those completed."""
        if self.all:
            return total
        deck_wins = sum(1 for u in self.deck_usage.values() if (u.get("wins") or {}).get(1))
        if deck_wins < CHALLENGE_WINS:
            return 0
        return min(total, len(self.challenges_completed) + 5)

    def with_main_menu_unlocks(self) -> "Profile":
        """The profile once the main menu has been shown (Game:main_menu checks
        every career stat's unlocks and the blind discoveries' then: it is
        where they unlock, between runs)."""
        p = self.copy()
        if p.all:
            return p
        d = data_mod.load()
        blinds = sum(1 for k in d.P_BLINDS if k in p.discovered)
        for k, v in sorted(d.P_CENTERS.items(), key=lambda kv: kv[1].order or 0):
            uc = v.unlock_condition
            if v.unlocked is not False or k in p.unlocked or not uc or k[:2] not in ("j_", "b_", "v_"):
                continue
            if (uc.type in p.career_stats and p.career_stats[uc.type] >= uc.extra) or (
                    uc.type == "blind_discoveries" and blinds >= uc.extra):
                p.unlocked.add(k)
                if v.set == "Back":
                    p.discovered.add(k)
        return p

    def is_unlocked(self, key: str) -> bool:
        d = data_mod.load()
        c = d.P_CENTERS.get(key)
        return self.all or (c is not None and c.unlocked is not False) or key in self.unlocked

    # ------------------------------------------------------------ storage
    def to_json(self) -> dict[str, Any]:
        if self.all:
            return {"all": True}
        return {
            "unlocked": sorted(self.unlocked), "discovered": sorted(self.discovered),
            "career_stats": dict(sorted(self.career_stats.items())),
            "deck_usage": {k: {r: {str(s): n for s, n in sorted(v.get(r, {}).items())} for r in ("wins", "losses")}
                           for k, v in sorted(self.deck_usage.items())},
            "voucher_usage": dict(sorted(self.voucher_usage.items())),
            "challenges_completed": sorted(self.challenges_completed),
        }

    @classmethod
    def from_json(cls, d: dict[str, Any] | None) -> "Profile":
        if not d or d.get("all"):
            return cls.everything()
        return cls(set(d.get("unlocked") or ()), set(d.get("discovered") or ()), all_=False,
                   career_stats=d.get("career_stats"),
                   deck_usage={k: {r: {int(s): n for s, n in (v.get(r) or {}).items()} for r in ("wins", "losses")}
                               for k, v in (d.get("deck_usage") or {}).items()},
                   voucher_usage=d.get("voucher_usage"), challenges_completed=set(d.get("challenges_completed") or ()))


class ProgressMixin:
    """The game's progress functions, on the run's own profile (G.profile)."""

    # ------------------------------------------------------------ setup
    def _start_progress(self: "Game") -> None:
        """G.P_LOCKED (game.lua:init_item_prototypes): the jokers, decks and
        vouchers still locked, in order.  (Game:main_menu's checks happen
        between runs: Profile.with_main_menu_unlocks.)"""
        G = self
        G.P_LOCKED = []
        if not G.unlocking:
            return
        for k, v in G.P_CENTERS.items():
            if not G.is_unlocked(v) and k[:2] in ("j_", "b_", "v_"):
                G.P_LOCKED.append(v)
        G.P_LOCKED.sort(key=lambda v: v.order if v.order is not None else 0)

    def career_stat(self: "Game", stat: str) -> float:
        """G.PROFILES[...].career_stats[stat]: the profile's, with this run's."""
        G = self
        if stat in STREAKS:
            return G.profile.career_stats.get(stat) or 0
        return (G.profile.career_stats.get(stat) or 0) + (G.PROFILE.career_stats.get(stat) or 0)

    def set_streak(self: "Game", stat: str, value: float) -> None:
        """A career streak changes (the run's record and the profile's)."""
        G = self
        G.PROFILE.career_stats[stat] = value
        if G.unlocking:
            G.profile.career_stats[stat] = value
            G.PROFILE.progress.streaks[stat] = value

    def _record_progress(self: "Game", kind: str, key: str) -> None:
        lst = self.PROFILE.progress[kind]
        if key not in lst:
            lst.append(key)

    # ------------------------------------------------------------ unlock / discover
    def unlock_card(self: "Game", card: T) -> None:
        G = self
        if G.is_unlocked(card):
            return
        if not G.unlocking or card.wip:
            return
        G.profile.unlocked.add(card.key)
        G._record_progress("unlocked", card.key)
        if card.set == "Back":
            G.discover_card(card)
        # notify_alert: the "Unlocked!" notification (its own queue: it changes nothing in the run)
        G._feedback("card_unlocked", key=card.key, set=card.set)

    def discover_card(self: "Game", card: T | None) -> None:
        G = self
        if not G.unlocking:
            return
        if card is None or card.wip:
            return
        key = card.key
        if not key or G.is_discovered(key):
            return
        G.GAME.round_scores.new_collection.amt = G.GAME.round_scores.new_collection.amt + 1
        G.profile.discovered.add(key)
        G._record_progress("discovered", key)
        G.set_discover_tallies()
        G.ev(None)  # G:save_progress()

    def discover_object(self: "Game", card: "Card") -> None:
        """discover_card(card) called with the card itself (set_consumeable_usage):
        the game marks the card object, not its center: the collection count
        goes up and the tallies are taken again, the center stays undiscovered."""
        G = self
        if not G.unlocking or getattr(card, "_discover_marked", False):
            return
        card._discover_marked = True  # type: ignore[attr-defined]
        G.GAME.round_scores.new_collection.amt = G.GAME.round_scores.new_collection.amt + 1
        G.set_discover_tallies()
        G.ev(None)  # G:save_progress()

    def set_discover_tallies(self: "Game") -> None:
        G = self
        tally: dict[str, list[int]] = {k: [0, 0] for k in ("total", "jokers", "planets", "tarots")}

        def count(kind: str, yes: bool) -> None:
            tally[kind][1] += 1
            if yes:
                tally[kind][0] += 1
        for k, v in G.P_CENTERS.items():
            if v.omit or not v.set:
                continue
            found = G.is_discovered(k)
            if v.set in ("Joker", "Edition", "Voucher", "Back", "Booster") or v.consumeable:
                count("total", found)
            if v.consumeable and v.set == "Planet":
                count("planets", found)
            elif v.consumeable and v.set == "Tarot":
                count("tarots", found)
        for k in G.P_BLINDS:
            count("total", G.is_discovered(k))
        for k in G.P_TAGS:
            count("total", G.is_discovered(k))
        G.check_for_unlock(T(type="discover_amount", amount=tally["total"][0], planet_count=tally["planets"][0],
                             tarot_count=tally["tarots"][0]))

    # ------------------------------------------------------------ deck wins
    def get_deck_win_stake(self: "Game", deck: str | None = None) -> int:
        return self.profile.deck_win_stake(deck)

    def set_deck_win(self: "Game") -> None:
        G = self
        wins = G.profile.deck_usage.setdefault(G.GAME.selected_back_key.key, {"wins": {}, "losses": {}})["wins"]
        stake = G.GAME.stake
        wins[stake] = (wins.get(stake) or 0) + 1
        for i in range(1, stake + 1):
            wins[i] = wins.get(i) or 1

    def set_deck_loss(self: "Game") -> None:
        G = self
        losses = G.profile.deck_usage.setdefault(G.GAME.selected_back_key.key, {"wins": {}, "losses": {}})["losses"]
        losses[G.GAME.stake] = (losses.get(G.GAME.stake) or 0) + 1

    # ------------------------------------------------------------ check_for_unlock
    def check_for_unlock(self: "Game", args: T) -> None:  # noqa: C901 - mirrors the Lua
        """check_for_unlock(args) without the achievements."""
        G = self
        if not args or not G.unlocking:
            return
        P = G.profile
        t = args.type
        locked = G.P_LOCKED
        i = 0
        while i < len(locked):
            ret = False
            card = locked[i]
            uc = card.unlock_condition
            if not G.is_unlocked(card) and uc and t == "career_stat":
                if args.statname == uc.type and G.career_stat(args.statname) >= uc.extra:
                    ret = True
                    G.unlock_card(card)
            if not G.is_unlocked(card) and uc and uc.type == t:
                if t == "hand" and args.handname == uc.extra:
                    ret = True
                    G.unlock_card(card)
                if t == "min_hand_size" and G.hand is not None and G.hand.config.card_limit <= uc.extra:
                    ret = True
                    G.unlock_card(card)
                if t == "interest_streak" and uc.extra <= G.career_stat("c_round_interest_cap_streak"):
                    ret = True
                    G.unlock_card(card)
                if t == "run_card_replays":
                    for v in G.playing_cards:
                        if v.base.times_played >= uc.extra:
                            ret = True
                            G.unlock_card(card)
                            break
                if t == "play_all_hearts":
                    played = True
                    for v in list(G.deck.cards) + list(G.hand.cards):
                        if v.ability.name != "Stone Card" and v.base.suit == "Hearts":
                            played = False
                    if played:
                        ret = True
                        G.unlock_card(card)
                if t == "run_redeem":
                    if sum(1 for _ in G.GAME.used_vouchers) >= uc.extra:
                        ret = True
                        G.unlock_card(card)
                if t == "have_edition":
                    if sum(1 for v in G.jokers.cards if v.edition) >= uc.extra:
                        ret = True
                        G.unlock_card(card)
                if t == "double_gold":
                    ret = True
                    G.unlock_card(card)
                if t == "continue_game":
                    ret = True
                    G.unlock_card(card)
                if t == "blank_redeems":
                    n = (P.voucher_usage.get("v_blank") or 0) + (G.PROFILE.voucher_usage.get("v_blank") or 0)
                    if n and n >= uc.extra:
                        G.unlock_card(card)
                if t == "modify_deck":
                    ex = uc.extra
                    if ex and ex.suit:
                        if sum(1 for v in G.playing_cards if v.base.suit == ex.suit) >= ex.count:
                            ret = True
                            G.unlock_card(card)
                    if ex and ex.enhancement:
                        if sum(1 for v in G.playing_cards if v.ability.name == ex.enhancement) >= ex.count:
                            ret = True
                            G.unlock_card(card)
                    if ex and ex.tally:
                        if sum(1 for v in G.playing_cards if v.ability.set == "Enhanced") >= ex.count:
                            ret = True
                            G.unlock_card(card)
                if t == "discover_amount":
                    if uc.amount and uc.amount <= args.amount:
                        ret = True
                        G.unlock_card(card)
                    if uc.tarot_count and uc.tarot_count <= args.tarot_count:
                        ret = True
                        G.unlock_card(card)
                    if uc.planet_count and uc.planet_count <= args.planet_count:
                        ret = True
                        G.unlock_card(card)
                if t == "win_deck":
                    if uc.deck and G.get_deck_win_stake(uc.deck) > 0:
                        ret = True
                        G.unlock_card(card)
                if t == "win_stake":
                    if uc.stake and G.get_deck_win_stake() >= uc.stake:
                        ret = True
                        G.unlock_card(card)
                if t == "discover_planets":
                    if sum(1 for k, v in G.P_CENTERS.items() if v.set == "Planet" and G.is_discovered(k)) >= 9:
                        ret = True
                        G.unlock_card(card)
                if t == "blind_discoveries":
                    if sum(1 for k in G.P_BLINDS if G.is_discovered(k)) >= uc.extra:
                        ret = True
                        G.unlock_card(card)
                if t == "modify_jokers" and G.jokers is not None:
                    if uc.extra.count:
                        n = sum(1 for v in G.jokers.cards if v.ability.set == "Joker" and v.edition
                                and v.edition.polychrome and uc.extra.polychrome)
                        if n >= uc.extra.count:
                            ret = True
                            G.unlock_card(card)
                if t == "money":
                    if uc.extra <= G.GAME.dollars:
                        ret = True
                        G.unlock_card(card)
                if t == "round_win":
                    cr = G.GAME.current_round
                    if card.name == "Matador":
                        if (cr.hands_played == 1 and cr.discards_left == G.GAME.round_resets.discards
                                and G.GAME.blind.get_type() == "Boss"):
                            ret = True
                            G.unlock_card(card)
                    if card.name == "Troubadour":
                        if G.career_stat("c_single_hand_round_streak") >= uc.extra:
                            ret = True
                            G.unlock_card(card)
                    if card.name == "Hanging Chad":
                        if G.GAME.last_hand_played == uc.extra and G.GAME.blind.get_type() == "Boss":
                            ret = True
                            G.unlock_card(card)
                if t == "ante_up":
                    if uc.ante and args.ante == uc.ante:
                        ret = True
                        G.unlock_card(card)
                if t == "hand_contents":
                    if card.name == "Seeing Double":
                        if sum(1 for c in args.cards if c.get_id() == 7 and c.is_suit("Clubs")) >= 4:
                            ret = True
                            G.unlock_card(card)
                    if card.name == "Golden Ticket":
                        if sum(1 for c in args.cards if c.ability.name == "Gold Card") >= 5:
                            ret = True
                            G.unlock_card(card)
                if t == "discard_custom":
                    if card.name == "Hit the Road":
                        if sum(1 for c in args.cards if c.get_id() == 11) >= 5:
                            ret = True
                            G.unlock_card(card)
                    if card.name == "Brainstorm":
                        from .poker import evaluate_poker_hand
                        ev = evaluate_poker_hand(G, args.cards)
                        if ev["Straight Flush"]:
                            if min((c.get_id() for c in args.cards), default=10) >= 10:
                                ret = True
                                G.unlock_card(card)
                if t == "win_no_hand" and G.GAME.hands[uc.extra].played == 0:
                    ret = True
                    G.unlock_card(card)
                if t == "win_custom":
                    if card.name == "Invisible Joker" and G.GAME.max_jokers <= 4:
                        ret = True
                        G.unlock_card(card)
                    if card.name == "Blueprint":
                        ret = True
                        G.unlock_card(card)
                if t == "win":
                    if uc.n_rounds >= G.GAME.round:
                        ret = True
                        G.unlock_card(card)
                if t == "chip_score":
                    if uc.chips <= args.chips:
                        ret = True

                        def later(card: T = card) -> None:
                            G.ev(lambda: G.unlock_card(card))
                        G.ev(later)
            if ret:
                locked.pop(i)
            else:
                i += 1
