"""Port of functions/common_events.lua and the game-logic parts of
functions/misc_functions.lua (as methods of the Game object, the Lua ``G``).

UI helpers that only animate (attention_text, sounds, juice) are dropped, but
every *event* they queue that can hold up the queue is kept with the same
trigger, delay and flags, because those delays are part of the game's
timeline (see events.py).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable

from .card import Card
from .lua import T, copy_table, floor, lor, lua_mod, lua_pow
from .rng import lua_tostring

if TYPE_CHECKING:
    from .cardarea import CardArea
    from .game import Game

UNAVAILABLE = "UNAVAILABLE"

# G.PROFILES[...].career_stats and the high scores a run can set (game.lua:init_item_prototypes)
CAREER_STATS = ("c_round_interest_cap_streak", "c_dollars_earned", "c_shop_dollars_spent", "c_tarots_bought",
                "c_planets_bought", "c_playing_cards_bought", "c_vouchers_bought", "c_tarot_reading_used",
                "c_planetarium_used", "c_shop_rerolls", "c_cards_played", "c_cards_discarded", "c_losses", "c_wins",
                "c_rounds", "c_hands_played", "c_face_cards_played", "c_jokers_sold", "c_cards_sold",
                "c_single_hand_round_streak")
HIGH_SCORES = ("hand", "furthest_round", "furthest_ante", "most_money", "boss_streak")


def new_run_profile() -> T:
    """What a run adds to the player's profile: the parts of the game's
    ``G.PROFILES[G.SETTINGS.profile]`` that playing changes (career stats,
    high scores, joker and voucher usage), starting from a blank profile.

    The game only records these for unseeded runs that aren't challenges.
    The engine records them for every run, as an unseeded run would, and
    whoever keeps the player's profile decides which runs count.  The win
    streaks span runs, so they are left to that keeper too."""
    return T(career_stats=T({k: 0 for k in CAREER_STATS}), high_scores=T({k: 0 for k in HIGH_SCORES}),
             joker_usage=T(), voucher_usage=T())


def status_text_info(card: Any, eval_type: str, amt: Any, extra: T | None) -> dict[str, Any]:
    """What a card_eval_status_text pop-up says, as data: the card it shows on,
    the effect (chips, mult, x_mult, dollars, debuffed, swap or message) and
    its amount."""
    if extra and extra.focus:
        card = extra.focus
    info: dict[str, Any] = {"card": getattr(card, "sort_id", None)}
    if eval_type == "debuff":
        info["effect"] = "debuffed"
    elif eval_type in ("chips", "mult", "x_mult", "dollars", "swap"):
        info["effect"] = eval_type
        info["amount"] = amt
    elif eval_type == "h_mult":
        info["effect"] = "mult"
        info["amount"] = amt
        info["held"] = True
    else:  # 'extra' / 'jokers': the message a joker, seal or edition returned
        ex = extra or T()
        x = ex.Xmult_mod or ex.x_mult_mod
        if x:
            info["effect"], info["amount"] = "x_mult", x
        elif ex.mult_mod:
            info["effect"], info["amount"] = "mult", ex.mult_mod
        elif ex.chip_mod:
            info["effect"], info["amount"] = "chips", ex.chip_mod
        elif ex.dollars:
            info["effect"], info["amount"] = "dollars", ex.dollars
        else:
            info["effect"] = "message"
            if isinstance(ex.message, str) and ex.message != "msg":
                info["message"] = ex.message
        if ex.repetitions:
            info["effect"] = "again"
        if ex.edition:
            info["edition"] = True
    return info


class CommonMixin:
    # ===================================================== event shorthands
    def event(self: "Game", func: Callable[..., Any] | None = None, **kw: Any) -> None:
        """G.E_MANAGER:add_event(Event{func = func, ...}); func returns completion."""
        from .events import Event
        self.E_MANAGER.add_event(Event(self, func, **kw))

    def ev(self: "Game", fn: Callable[[], Any] | None = None, **kw: Any) -> None:
        """An event whose function runs once (the Lua ``... return true end``)."""
        from .events import Event
        if fn is None:
            self.E_MANAGER.add_event(Event(self, None, **kw))
            return

        def f() -> bool:
            fn()
            return True
        self.E_MANAGER.add_event(Event(self, f, **kw))

    def delay(self: "Game", time: float | None = None) -> None:
        from .events import Event
        self.E_MANAGER.add_event(Event(self, None, trigger="after", delay=lor(time, 1)))

    @staticmethod
    def floor(x: float) -> float:
        return floor(x)

    # ======================================================= player feedback
    def start_feedback(self: "Game") -> list[dict]:
        """Start recording what the game shows the player (status texts, the
        scoring panel, money, cards moving), in the order and at the time the
        game shows it.  Returns the list that fills up; ``t`` is the real time
        in seconds since this call.  Recording never changes the run."""
        self.feedback = []
        self._feedback_t0 = self.TIMERS["REAL"]
        return self.feedback

    def stop_feedback(self: "Game") -> list[dict]:
        fb = self.feedback or []
        self.feedback = None
        return fb

    def _feedback(self: "Game", kind: str, **data: Any) -> None:
        fb = self.feedback
        if fb is not None:
            data["type"] = kind
            data["t"] = round(self.TIMERS["REAL"] - self._feedback_t0, 4)
            fb.append(data)

    # ============================================================== easing
    def ease_chips(self: "Game", mod: float) -> None:
        G = self

        def f() -> None:
            G._feedback("round_score", chips=mod or 0)
            G.event(floor, trigger="ease", blockable=False, ref_table=G.GAME, ref_value="chips", ease_to=mod or 0,
                    delay=0.3)
        G.ev(f)

    def ease_dollars(self: "Game", mod: float, instant: Any = None) -> None:
        G = self

        def _mod() -> None:
            if not (mod or 0) < 0:
                G.inc_career_stat("c_dollars_earned", mod)
            G.GAME.dollars = G.GAME.dollars + (mod or 0)
            G.check_and_set_high_score("most_money", G.GAME.dollars)
            G._feedback("dollars", amount=mod or 0, total=G.GAME.dollars)
        if instant:
            _mod()
        else:
            G.ev(_mod)

    def ease_discard(self: "Game", mod: float, instant: Any = None, silent: Any = None) -> None:
        G = self

        def _mod() -> None:
            cr = G.GAME.current_round
            if abs(max(cr.discards_left, mod)) == 0:
                return
            m = max(-cr.discards_left, mod or 0)
            cr.discards_left = cr.discards_left + m
        if instant:
            _mod()
        else:
            G.ev(_mod)

    def ease_hands_played(self: "Game", mod: float, instant: Any = None) -> None:
        G = self

        def _mod() -> None:
            G.GAME.current_round.hands_left = G.GAME.current_round.hands_left + (mod or 0)
        if instant:
            _mod()
        else:
            G.ev(_mod)

    def ease_ante(self: "Game", mod: int) -> None:
        G = self

        def f() -> None:
            G.GAME.round_resets.ante = G.GAME.round_resets.ante + (mod or 0)
            G.check_and_set_high_score("furthest_ante", G.GAME.round_resets.ante)
        G.ev(f)

    def ease_round(self: "Game", mod: int) -> None:
        G = self

        def f() -> None:
            G.GAME.round = G.GAME.round + (mod or 0)
            G.check_and_set_high_score("furthest_round", G.GAME.round)
            G.check_and_set_high_score("furthest_ante", G.GAME.round_resets.ante)
        G.ev(f)

    # ===================================================== card movement
    def draw_card(self: "Game", from_: "CardArea | None", to: "CardArea", percent: Any = None, dir: Any = None,
                  sort: Any = None, card: Card | None = None, delay: float | None = None, mute: Any = None,
                  stay_flipped: Any = None, vol: Any = None, discarded_only: bool = False) -> None:
        G = self
        state = [card]

        def f() -> None:
            c = state[0]
            if c is not None:
                if from_ is not None:
                    c = from_.remove_card(c)
                    state[0] = c
                stay = G.GAME.blind.stay_flipped(to, c) if G.GAME and G.GAME.blind else None
                if G.GAME.modifiers.flipped_cards and to is G.hand:
                    if G.rng.random(G.rng.pseudoseed("flipped_card")) < 1 / G.GAME.modifiers.flipped_cards:
                        stay = True
                to.emplace(c, None, stay)
            else:
                to.draw_card_from(from_, stay_flipped, discarded_only)
            if sort:
                to.sort()
        G.ev(f, trigger="before", delay=lor(delay, 0.1))

    def highlight_card(self: "Game", card: Card, percent: Any = None, dir: Any = None) -> None:
        highlight = dir != "down"

        def f() -> None:
            card.highlight(highlight)
        self.ev(f, trigger="before", delay=0.1)

    def play_area_status_text(self: "Game", text: str, silent: Any = None, delay: float | None = None) -> None:
        d = lor(delay, 0.6)
        self.ev(lambda: self._feedback("status_text", text=text), trigger="immediate" if d == 0 else "before", delay=d)

    def juice_card(self: "Game", card: Card) -> None:
        # card:juice_up(0.7): the card that made an effect wiggles
        self.ev(lambda: self._feedback("card_juiced", card=card.sort_id))

    def level_up_hand(self: "Game", card: Any, hand: str, instant: Any = None, amount: int | None = None) -> None:
        G = self
        amount = lor(amount, 1)
        h = G.GAME.hands[hand]
        h.level = max(0, h.level + amount)
        h.mult = max(h.s_mult + h.l_mult * (h.level - 1), 1)
        h.chips = max(h.s_chips + h.l_chips * (h.level - 1), 0)
        if not instant:
            G.ev(None, trigger="after", delay=0.2)
            G.update_hand_text(T(delay=0), T(mult=h.mult, StatusText=True))
            G.ev(None, trigger="after", delay=0.9)
            G.update_hand_text(T(delay=0), T(chips=h.chips, StatusText=True))
            G.ev(None, trigger="after", delay=0.9)
            G.update_hand_text(T(sound="button", volume=0.7, pitch=0.9, delay=0), T(level=h.level))
            G.delay(1.3)
        G.ev(None)  # check_for_unlock

    def update_hand_text(self: "Game", config: T, vals: T) -> None:
        G = self

        def f() -> None:
            ch = G.GAME.current_round.current_hand
            if vals.chips is not None and ch.chips != vals.chips:
                ch.chips = vals.chips
            if vals.mult is not None and ch.mult != vals.mult:
                ch.mult = vals.mult
            if vals.handname is not None and ch.handname != vals.handname:
                ch.handname = vals.handname
            if vals.chip_total is not None:
                ch.chip_total = vals.chip_total
            if vals.level is not None:
                ch.hand_level = vals.level
            if G.feedback is not None:
                G._feedback("hand", **{k: vals.get(k) for k in ("handname", "level", "chips", "mult", "chip_total")
                                       if vals.get(k) is not None})
        G.ev(f, trigger="before", blockable=not config.immediate, delay=lor(config.delay, 0.8))

    def card_eval_status_text(self: "Game", card: Any, eval_type: str, amt: Any = None, percent: Any = None,
                              dir: Any = None, extra: T | None = None) -> None:
        """Only the event it queues (its delay) and playing_cards_created matter."""
        G = self
        d = 0.65
        if eval_type == "debuff":
            amt = 1
        elif eval_type == "chips":
            d = 0.6
        elif eval_type in ("extra", "jokers"):
            d = lor(extra.delay, 0.75)
            amt = 1
        d = d * 1.25
        if amt is not None and (amt > 0 or amt < 0):
            def show() -> None:
                if G.feedback is not None:
                    G._feedback("card_text", **status_text_info(card, eval_type, amt, extra))
            if extra and extra.instant:
                show()
            else:
                G.ev(show, trigger="before", delay=d)
        if extra and extra.playing_cards_created:
            G.playing_card_joker_effects(extra.playing_cards_created)

    def alert_no_space(self: "Game", card: Card, area: Any) -> None:
        G = self
        G.CONTROLLER.locks.no_space = True

        def f() -> None:
            G.CONTROLLER.locks.no_space = None
        G.ev(f, trigger="after", delay=0.5 * G.SETTINGS.GAMESPEED, blockable=False, blocking=False)

    # ===================================================== round eval rows
    def add_round_eval_row(self: "Game", config: T) -> None:
        G = self
        num_dollars = lor(config.dollars, 1)
        if config.name != "bottom":
            if config.name != "blind1":
                if not G.round_eval.divider_added:
                    G.ev(None, trigger="after", delay=0.25)
                    G.delay(0.6)
                    G.round_eval.divider_added = True
            else:
                G.delay(0.2)
            G.delay(0.2)
            G.ev(None, trigger="before", delay=0.5)
            if num_dollars > 60:
                G.ev(None, trigger="before", delay=0.38)
            else:
                d = 0.18 - (0.13 if num_dollars > 20 else 0.1 if num_dollars > 9 else 0)
                for _ in range(1, int(num_dollars) + 1) if num_dollars >= 1 else ():
                    G.ev(None, trigger="before", delay=d)
        else:
            G.delay(0.4)

            def f() -> None:
                G.GAME.current_round.dollars = config.dollars
            G.ev(f, trigger="before", delay=0.5)

    # ============================================================ shop size
    def change_shop_size(self: "Game", mod: int) -> None:
        G = self
        if not G.GAME.shop:
            return
        G.GAME.shop.joker_max = G.GAME.shop.joker_max + mod
        sj = G.shop_jokers
        if sj is not None and not sj.removed:
            if mod < 0:
                for i in range(len(sj.cards) - 1, G.GAME.shop.joker_max - 1, -1):
                    if i < len(sj.cards):
                        sj.cards[i].remove()
            sj.config.card_limit = G.GAME.shop.joker_max
            if mod > 0:
                for _ in range(G.GAME.shop.joker_max - len(sj.cards)):
                    sj.emplace(G.create_card_for_shop(sj))

    # ======================================================== misc helpers
    def stop_use(self: "Game") -> None:
        G = self
        G.GAME.STOP_USE = (G.GAME.STOP_USE or 0) + 1
        G.dec_stop_use(6)

    def dec_stop_use(self: "Game", depth: int) -> None:
        G = self
        if depth > 0:
            G.ev(lambda: G.dec_stop_use(depth - 1), blocking=False, no_delete=True)
        else:
            def f() -> None:
                G.GAME.STOP_USE = max(G.GAME.STOP_USE - 1, 0)
            G.ev(f, blocking=False, no_delete=True)

    def find_joker(self: "Game", name: str, non_debuff: Any = None) -> list[Card]:
        out: list[Card] = []
        if self.jokers is None or self.jokers.removed:
            return out
        for v in self.jokers.cards:
            if v.ability.name == name and (non_debuff or not v.debuff):
                out.append(v)
        for v in self.consumeables.cards:
            if v.ability.name == name and (non_debuff or not v.debuff):
                out.append(v)
        return out

    def get_blind_amount(self: "Game", ante: int) -> float:
        k = 0.75
        scaling = self.GAME.modifiers.scaling
        if not scaling or scaling == 1:
            amounts = (300, 800, 2000, 5000, 11000, 20000, 35000, 50000)
        elif scaling == 2:
            amounts = (300, 900, 2600, 8000, 20000, 36000, 60000, 100000)
        elif scaling == 3:
            amounts = (300, 1000, 3200, 9000, 25000, 60000, 110000, 200000)
        else:
            return None  # type: ignore[return-value]
        if ante < 1:
            return 100
        if ante <= 8:
            return amounts[ante - 1]
        a, b, c, d = amounts[7], 1.6, ante - 8, 1 + 0.2 * (ante - 8)
        amount = floor(a * lua_pow(b + lua_pow(k * c, d), c))
        # (for huge antes amount is inf and this turns it into nan, as in Lua)
        amount = amount - lua_mod(amount, lua_pow(10, floor(math.log10(amount) - 1)))
        return amount

    def refresh_all_costs(self: "Game") -> None:
        for v in list(self.I_CARD):
            v.set_cost()

    # ================================================== the player's profile
    def inc_career_stat(self: "Game", stat: str, mod: float | None = None) -> None:
        cs = self.PROFILE.career_stats
        cs[stat] = (cs.get(stat) or 0) + (mod or 0)

    def check_and_set_high_score(self: "Game", score: str, amt: Any) -> None:
        """The run's round score (shown at the end of the run) and its high
        score.  (The game also flags a new profile high score; the engine
        doesn't know the player's profile.)"""
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            return
        amt = floor(amt)
        rs = self.GAME.round_scores.get(score)
        if rs and amt > rs.amt:
            rs.amt = amt
        hs = self.PROFILE.high_scores
        if score in hs and amt > hs[score]:
            hs[score] = amt

    def set_joker_usage(self: "Game") -> None:
        u = self.PROFILE.joker_usage
        for v in self.jokers.cards:
            key = v.config.center_key
            if key and v.ability.set == "Joker":
                if u.get(key):
                    u[key].count = u[key].count + 1
                else:
                    u[key] = T(count=1, wins=T(), losses=T())

    def _joker_result(self: "Game", result: str) -> None:
        u = self.PROFILE.joker_usage
        stake = self.GAME.stake
        for v in self.jokers.cards:
            key = v.config.center_key
            if key and v.ability.set == "Joker":
                if result == "wins" and not u.get(key):
                    u[key] = T(count=1, wins=T(), losses=T())
                if u.get(key):
                    u[key][result][stake] = (u[key][result].get(stake) or 0) + 1

    def set_joker_win(self: "Game") -> None:
        self._joker_result("wins")

    def set_joker_loss(self: "Game") -> None:
        self._joker_result("losses")

    def set_voucher_usage(self: "Game", card: Card) -> None:
        key = card.config.center_key
        if key and card.ability.set == "Voucher":
            u = self.PROFILE.voucher_usage
            u[key] = (u.get(key) or 0) + 1

    def set_consumeable_usage(self: "Game", card: Card) -> None:
        G = self
        key = card.config.center_key
        if key and card.ability.consumeable:
            u = G.GAME.consumeable_usage
            if u.get(key):
                u[key].count = u[key].count + 1
            else:
                u[key] = T(count=1, order=card.config.center.order, set=card.ability.set)
            tot = G.GAME.consumeable_usage_total or T(tarot=0, planet=0, spectral=0, tarot_planet=0, all=0)
            G.GAME.consumeable_usage_total = tot
            s = card.config.center.set
            if s == "Tarot":
                tot.tarot += 1
                tot.tarot_planet += 1
            elif s == "Planet":
                tot.planet += 1
                tot.tarot_planet += 1
            elif s == "Spectral":
                tot.spectral += 1
            tot.all += 1
            if s in ("Tarot", "Planet"):
                def outer() -> None:
                    def inner() -> None:
                        G.GAME.last_tarot_planet = key
                    G.ev(inner)
                G.ev(outer)

    def set_hand_usage(self: "Game", hand: str) -> None:
        key = hand.replace(" ", "")
        u = self.GAME.hand_usage
        if u.get(key):
            u[key].count = u[key].count + 1
        else:
            u[key] = T(count=1, order=hand)

    def playing_card_joker_effects(self: "Game", cards: list[Any]) -> None:
        for j in list(self.jokers.cards):
            j.calculate_joker(T(playing_card_added=True, cards=cards))

    def card_from_control(self: "Game", control: T) -> Card:
        G = self
        G.playing_card = (G.playing_card + 1) if G.playing_card else 1
        c = Card(G, G.P_CARDS[control.s + "_" + control.r], G.P_CENTERS[control.e or "c_base"],
                 {"playing_card": G.playing_card})
        if control.d:
            c.set_edition(T({control.d: True}), True, True)
        if control.g:
            c.set_seal(control.g, True, True)
        G.deck.emplace(c)
        G.playing_cards.append(c)
        return c

    def add_joker(self: "Game", key: str, edition: str | None = None, silent: Any = None, eternal: Any = None) -> Card:
        G = self
        center = G.P_CENTERS[key]
        area = G.consumeables if center.consumeable else G.jokers
        card = Card(G, G.P_CARDS["empty"] if "empty" in G.P_CARDS else None, center,
                    {"discover": True, "bypass_discovery_center": True, "bypass_discovery_ui": True})
        card.start_materialize(None, silent)
        if area is not None:
            card.add_to_deck()
        if edition:
            card.set_edition(T({edition: True}))
        if eternal:
            card.set_eternal(True)
        if area is not None and card.ability.set == "Joker":
            area.emplace(card)
        elif G.consumeables is not None:
            G.consumeables.emplace(card)
        return card

    def add_tag(self: "Game", tag: Any) -> None:
        G = self
        for t in list(G.GAME.tags):
            t.apply_to_run(T(type="tag_add", tag=tag))
        G.GAME.tags.append(tag)

    # ================================================================ pools
    def pseudorandom_element_index(self: "Game", n: int, seed: float) -> int:
        return self.rng.element_index(n, seed)

    def random_card_from(self: "Game", cards: list[Card], seed_key: str) -> Card:
        """pseudorandom_element over a list of cards (sorted by sort_id)."""
        ordered = sorted(cards, key=lambda c: c.sort_id)
        return ordered[self.rng.element_index(len(ordered), self.rng.pseudoseed(seed_key))]

    def random_card_index(self: "Game", cards: list[Card], seed_key: str) -> int:
        """Like random_card_from, but returns the (0-based) key in ``cards``."""
        order = sorted(range(len(cards)), key=lambda i: cards[i].sort_id)
        return order[self.rng.element_index(len(order), self.rng.pseudoseed(seed_key))]

    def random_p_card(self: "Game", seed_key: str) -> T:
        keys = self.data.P_CARDS_SORTED_KEYS
        return self.P_CARDS[keys[self.rng.element_index(len(keys), self.rng.pseudoseed(seed_key))]]

    def get_current_pool(self: "Game", _type: str, _rarity: float | None = None, _legendary: Any = None,
                         _append: str | None = None) -> tuple[list[str], str]:
        G = self
        GAME = G.GAME
        ante = GAME.round_resets.ante
        if _type == "Joker":
            rarity = _rarity if _rarity is not None else G.rng.random("rarity" + lua_tostring(ante) + (_append or ""))
            rarity = 4 if _legendary else (3 if rarity > 0.95 else (2 if rarity > 0.7 else 1))
            starting_pool = G.P_JOKER_RARITY_POOLS[rarity - 1]
            pool_key = "Joker" + str(rarity) + ((_append or "") if not _legendary else "")
        else:
            starting_pool = G.P_CENTER_POOLS[_type]
            pool_key = _type + (_append or "")
        pool: list[str] = []
        size = 0
        used = GAME.used_jokers
        showman: bool | None = None
        for v in starting_pool:
            add = None
            if _type == "Enhanced":
                add = True
            elif _type == "Demo":
                if v.pos and v.config:
                    add = True
            elif _type == "Tag":
                if (not v.requires or (v.requires in G.P_CENTERS and G.is_discovered(v.requires))) and (
                        not v.min_ante or v.min_ante <= ante):
                    add = True
            else:
                if used.get(v.key) and showman is None:
                    showman = bool(G.find_joker("Showman"))
                if not (used.get(v.key) and not showman) and (G.is_unlocked(v) or v.rarity == 4):
                    if v.set == "Voucher":
                        if not GAME.used_vouchers.get(v.key):
                            include = True
                            if v.requires:
                                for vv in v.requires:
                                    if not GAME.used_vouchers.get(vv):
                                        include = False
                            if G.shop_vouchers is not None and not G.shop_vouchers.removed:
                                for vv in G.shop_vouchers.cards:
                                    if vv.config.center.key == v.key:
                                        include = False
                            if include:
                                add = True
                    elif v.set == "Planet":
                        if not v.config.softlock or GAME.hands[v.config.hand_type].played > 0:
                            add = True
                    elif v.enhancement_gate:
                        add = None
                        for vv in G.playing_cards:
                            if vv.config.center.key == v.enhancement_gate:
                                add = True
                    else:
                        add = True
                    if v.name in ("Black Hole", "The Soul"):
                        add = False
            if v.no_pool_flag and GAME.pool_flags.get(v.no_pool_flag):
                add = None
            if v.yes_pool_flag and not GAME.pool_flags.get(v.yes_pool_flag):
                add = None
            if add and not GAME.banned_keys.get(v.key):
                pool.append(v.key)
                size += 1
            else:
                pool.append(UNAVAILABLE)
        if size == 0:
            if _type in ("Tarot", "Tarot_Planet"):
                pool = ["c_strength"]
            elif _type == "Planet":
                pool = ["c_pluto"]
            elif _type == "Spectral":
                pool = ["c_incantation"]
            elif _type == "Voucher":
                pool = ["v_blank"]
            elif _type == "Tag":
                pool = ["tag_handy"]
            else:
                pool = ["j_joker"]
        return pool, pool_key + (lua_tostring(ante) if not _legendary else "")

    def pick_from_pool(self: "Game", pool: list[str], pool_key: str) -> str:
        """pseudorandom_element + the '_resample' loop used everywhere."""
        rng = self.rng
        center = pool[rng.element_index(len(pool), rng.pseudoseed(pool_key))]
        it = 1
        while center == UNAVAILABLE:
            it += 1
            center = pool[rng.element_index(len(pool), rng.pseudoseed(pool_key + "_resample" + str(it)))]
        return center

    def get_next_voucher_key(self: "Game", _from_tag: Any = None) -> str:
        pool, pool_key = self.get_current_pool("Voucher")
        if _from_tag:
            pool_key = "Voucher_fromtag"
        return self.pick_from_pool(pool, pool_key)

    def get_next_tag_key(self: "Game", append: str | None = None) -> str:
        if self.FORCE_TAG:
            return self.FORCE_TAG
        pool, pool_key = self.get_current_pool("Tag", None, None, append)
        return self.pick_from_pool(pool, pool_key)

    def poll_edition(self: "Game", _key: str | None = None, _mod: float | None = None, _no_neg: Any = None,
                     _guaranteed: Any = None) -> T | None:
        G = self
        _mod = lor(_mod, 1)
        poll = G.rng.random(G.rng.pseudoseed(_key or "edition_generic"))
        if _guaranteed:
            if poll > 1 - 0.003 * 25 and not _no_neg:
                return T(negative=True)
            elif poll > 1 - 0.006 * 25:
                return T(polychrome=True)
            elif poll > 1 - 0.02 * 25:
                return T(holo=True)
            elif poll > 1 - 0.04 * 25:
                return T(foil=True)
        else:
            rate = G.GAME.edition_rate
            if poll > 1 - 0.003 * _mod and not _no_neg:
                return T(negative=True)
            elif poll > 1 - 0.006 * rate * _mod:
                return T(polychrome=True)
            elif poll > 1 - 0.02 * rate * _mod:
                return T(holo=True)
            elif poll > 1 - 0.04 * rate * _mod:
                return T(foil=True)
        return None

    def create_card(self: "Game", _type: str, area: "CardArea | None", legendary: Any = None,
                    _rarity: float | None = None, skip_materialize: Any = None, soulable: Any = None,
                    forced_key: Any = None, key_append: str | None = None) -> Card:
        G = self
        GAME = G.GAME
        area = area if area is not None else G.jokers
        ante = lua_tostring(GAME.round_resets.ante)
        if not forced_key and soulable and not GAME.banned_keys.get("c_soul"):
            if _type in ("Tarot", "Spectral", "Tarot_Planet") and not (
                    GAME.used_jokers.get("c_soul") and not G.find_joker("Showman")):
                if G.rng.random("soul_" + _type + ante) > 0.997:
                    forced_key = "c_soul"
            if _type in ("Planet", "Spectral") and not (
                    GAME.used_jokers.get("c_black_hole") and not G.find_joker("Showman")):
                if G.rng.random("soul_" + _type + ante) > 0.997:
                    forced_key = "c_black_hole"
        if _type == "Base":
            forced_key = "c_base"
        if forced_key and not GAME.banned_keys.get(forced_key):
            center = G.P_CENTERS[forced_key]
            _type = center.set if center.set != "Default" else _type
        else:
            pool, pool_key = G.get_current_pool(_type, _rarity, legendary, key_append)
            center = G.P_CENTERS[G.pick_from_pool(pool, pool_key)]
        front = None
        if _type in ("Base", "Enhanced"):
            front = G.random_p_card("front" + (key_append or "") + ante)
        in_shop = area is G.shop_jokers or area is G.pack_cards or area is G.shop_vouchers
        card = Card(G, front, center, {
            "bypass_discovery_center": in_shop or area is G.jokers or area is G.consumeables,
            "bypass_discovery_ui": in_shop,
            "discover": area is G.jokers or area is G.consumeables,
        })
        if card.ability.consumeable and not skip_materialize:
            card.start_materialize()
        if _type == "Joker":
            if GAME.modifiers.all_eternal:
                card.set_eternal(True)
            if area is G.shop_jokers or area is G.pack_cards:
                in_pack = area is G.pack_cards
                ep = G.rng.random(("packetper" if in_pack else "etperpoll") + ante)
                if GAME.modifiers.enable_eternals_in_shop and ep > 0.7:
                    card.set_eternal(True)
                elif GAME.modifiers.enable_perishables_in_shop and 0.4 < ep <= 0.7:
                    card.set_perishable(True)
                if GAME.modifiers.enable_rentals_in_shop and G.rng.random(("packssjr" if in_pack else "ssjr") + ante) > 0.7:
                    card.set_rental(True)
            edition = G.poll_edition("edi" + (key_append or "") + ante)
            card.set_edition(edition)
        return card

    def create_playing_card(self: "Game", card_init: T | None, area: "CardArea | None", skip_materialize: Any = None,
                            silent: Any = None, colours: Any = None) -> Card:
        G = self
        card_init = card_init or T()
        card_init.front = card_init.front or G.random_p_card("front")
        card_init.center = card_init.center or G.P_CENTERS["c_base"]
        G.playing_card = (G.playing_card + 1) if G.playing_card else 1
        card = Card(G, card_init.front, card_init.center, {"playing_card": G.playing_card})
        G.playing_cards.append(card)
        card.playing_card = G.playing_card
        if area is not None:
            area.emplace(card)
        if not skip_materialize:
            card.start_materialize(colours, silent)
        return card

    def copy_card(self: "Game", other: Card, new_card: Card | None = None, card_scale: Any = None,
                  playing_card: int | None = None, strip_edition: Any = None) -> Card:
        G = self
        if new_card is None:
            new_card = Card(G, G.P_CARDS.get("empty"), G.P_CENTERS["c_base"], {"playing_card": playing_card})
        new_card.set_ability(other.config.center)
        new_card.ability.type = other.ability.type
        new_card.set_base(other.config.card)
        for k, v in list(other.ability.items()):
            new_card.ability[k] = copy_table(v)
        if not strip_edition:
            new_card.set_edition(other.edition or T(), None, True)
        new_card.set_seal(other.seal, True)
        if other.params:
            new_card.params = other.params
            new_card.params["playing_card"] = playing_card
        new_card.debuff = other.debuff
        new_card.pinned = other.pinned
        return new_card

    def get_pack(self: "Game", _key: str | None = None, _type: str | None = None) -> T:
        G = self
        GAME = G.GAME
        if not GAME.first_shop_buffoon and not GAME.banned_keys.get("p_buffoon_normal_1"):
            GAME.first_shop_buffoon = True
            # 'p_buffoon_normal_'..math.random(1, 2) on LuaJIT's global state:
            # two artworks of the same pack
            return G.P_CENTERS["p_buffoon_normal_1"]
        cume, it, center = 0, 0, None
        boosters = G.P_CENTER_POOLS["Booster"]
        for v in boosters:
            if (not _type or _type == v.kind) and not GAME.banned_keys.get(v.key):
                cume = cume + lor(v.weight, 1)
        poll = G.rng.random(G.rng.pseudoseed((_key or "pack_generic") + lua_tostring(GAME.round_resets.ante))) * cume
        for v in boosters:
            if not GAME.banned_keys.get(v.key):
                w = lor(v.weight, 1)
                if not _type or _type == v.kind:
                    it = it + w
                if it >= poll and it - w <= poll:
                    center = v
                    break
        return center

    def calculate_reroll_cost(self: "Game", skip_increment: Any = None) -> None:
        cr = self.GAME.current_round
        if cr.free_rerolls < 0:
            cr.free_rerolls = 0
        if cr.free_rerolls > 0:
            cr.reroll_cost = 0
            return
        cr.reroll_cost_increase = cr.reroll_cost_increase or 0
        if not skip_increment:
            cr.reroll_cost_increase = cr.reroll_cost_increase + 1
        rr = self.GAME.round_resets
        cr.reroll_cost = lor(rr.temp_reroll_cost, rr.reroll_cost) + cr.reroll_cost_increase

    # ======================================================= per-round cards
    def reset_idol_card(self: "Game") -> None:
        G = self
        cr = G.GAME.current_round
        cr.idol_card.rank = "Ace"
        cr.idol_card.suit = "Spades"
        valid = [v for v in G.playing_cards if v.ability.effect != "Stone Card"]
        if valid:
            c = G.random_card_from(valid, "idol" + lua_tostring(G.GAME.round_resets.ante))
            cr.idol_card.rank = c.base.value
            cr.idol_card.suit = c.base.suit
            cr.idol_card.id = c.base.id

    def reset_mail_rank(self: "Game") -> None:
        G = self
        cr = G.GAME.current_round
        cr.mail_card.rank = "Ace"
        valid = [v for v in G.playing_cards if v.ability.effect != "Stone Card"]
        if valid:
            c = G.random_card_from(valid, "mail" + lua_tostring(G.GAME.round_resets.ante))
            cr.mail_card.rank = c.base.value
            cr.mail_card.id = c.base.id

    def reset_ancient_card(self: "Game") -> None:
        G = self
        cr = G.GAME.current_round
        suits = [s for s in ("Spades", "Hearts", "Clubs", "Diamonds") if s != cr.ancient_card.suit]
        cr.ancient_card.suit = G.rng.element(suits, G.rng.pseudoseed("anc" + lua_tostring(G.GAME.round_resets.ante)))

    def reset_castle_card(self: "Game") -> None:
        G = self
        cr = G.GAME.current_round
        cr.castle_card.suit = "Spades"
        valid = [v for v in G.playing_cards if v.ability.effect != "Stone Card"]
        if valid:
            c = G.random_card_from(valid, "cas" + lua_tostring(G.GAME.round_resets.ante))
            cr.castle_card.suit = c.base.suit

    def reset_blinds(self: "Game") -> None:
        G = self
        rr = G.GAME.round_resets
        rr.blind_states = rr.blind_states or T(Small="Select", Big="Upcoming", Boss="Upcoming")
        if rr.blind_states.Boss == "Defeated":
            rr.blind_states.Small = "Upcoming"
            rr.blind_states.Big = "Upcoming"
            rr.blind_states.Boss = "Upcoming"
            G.GAME.blind_on_deck = "Small"
            rr.blind_choices.Boss = G.get_new_boss()
            rr.boss_rerolled = False

    def get_new_boss(self: "Game") -> str:
        G = self
        GAME = G.GAME
        ante = GAME.round_resets.ante
        GAME.perscribed_bosses = GAME.perscribed_bosses or T()
        if GAME.perscribed_bosses.get(ante):
            ret = GAME.perscribed_bosses.pop(ante)
            GAME.bosses_used[ret] = GAME.bosses_used[ret] + 1
            return ret
        if G.FORCE_BOSS:
            return G.FORCE_BOSS
        eligible: dict[str, Any] = {}
        win_ante = GAME.win_ante
        for k, v in G.P_BLINDS.items():
            b = v.boss
            if not b:
                continue
            if not b.showdown and (b.min <= max(1, ante) and (lua_mod(max(1, ante), win_ante) != 0 or ante < 2)):
                eligible[k] = True
            elif b.showdown and lua_mod(ante, win_ante) == 0 and ante >= 2:
                eligible[k] = True
        for k in GAME.banned_keys:
            eligible.pop(k, None)
        min_use = 100
        for k, v in GAME.bosses_used.items():
            if k in eligible:
                eligible[k] = v
                if v <= min_use:
                    min_use = v
        for k in list(eligible):
            v = eligible[k]
            if v is not True and v > min_use:
                del eligible[k]
        keys = sorted(eligible)
        boss = keys[G.rng.element_index(len(keys), G.rng.pseudoseed("boss"))]
        GAME.bosses_used[boss] = GAME.bosses_used[boss] + 1
        return boss

    # ============================================================ shop cards
    def create_card_for_shop(self: "Game", area: "CardArea") -> Card:
        G = self
        GAME = G.GAME
        forced = None
        for v in list(GAME.tags):
            if not forced:
                forced = v.apply_to_run(T(type="store_joker_create", area=area))
                if forced:
                    for vv in list(GAME.tags):
                        if vv.apply_to_run(T(type="store_joker_modify", card=forced)):
                            break
                    return forced
        GAME.spectral_rate = GAME.spectral_rate or 0
        total = GAME.joker_rate + GAME.tarot_rate + GAME.planet_rate + GAME.playing_card_rate + GAME.spectral_rate
        polled = G.rng.random(G.rng.pseudoseed("cdt" + lua_tostring(GAME.round_resets.ante))) * total
        check = 0
        base_type = "Base"
        if GAME.used_vouchers.get("v_illusion") and G.rng.random(G.rng.pseudoseed("illusion")) > 0.6:
            base_type = "Enhanced"
        for typ, val in (("Joker", GAME.joker_rate), ("Tarot", GAME.tarot_rate), ("Planet", GAME.planet_rate),
                         (base_type, GAME.playing_card_rate), ("Spectral", GAME.spectral_rate)):
            if check < polled <= check + val:
                card = G.create_card(typ, area, None, None, None, None, None, "sho")
                G.create_shop_card_ui(card)

                def modify(card: Card = card) -> None:
                    for t in list(GAME.tags):
                        if t.apply_to_run(T(type="store_joker_modify", card=card)):
                            break
                G.ev(modify)
                if typ in ("Base", "Enhanced") and GAME.used_vouchers.get("v_illusion") and G.rng.random(
                        G.rng.pseudoseed("illusion")) > 0.8:
                    poll = G.rng.random(G.rng.pseudoseed("illusion"))
                    if poll > 1 - 0.15:
                        ed = T(polychrome=True)
                    elif poll > 0.5:
                        ed = T(holo=True)
                    else:
                        ed = T(foil=True)
                    card.set_edition(ed)
                return card
            check = check + val
        return None  # type: ignore[return-value]

    def create_shop_card_ui(self: "Game", card: Card, typ: Any = None, area: Any = None) -> None:
        # a non-blocking UI event: nothing to model
        return None

