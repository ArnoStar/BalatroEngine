"""The Game object (``G`` in the Lua source): run state, card areas, helpers.

Gameplay functions are split over mixins (pools, flow, shop, packs) but all
operate on this object, mirroring how the Lua code uses the global ``G``.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Callable, Iterable

from . import data as data_mod
from .actions import ActionsMixin
from .back import Back
from .blind import Blind
from .card import Card
from .cardarea import CardArea
from .flow import FlowMixin
from .lua import T, copy_table, floor, to_T
from .packs import PacksMixin
from .pools import PoolsMixin
from .rng import PseudoRandom, normalize_seed
from .shop import ShopMixin


class STATES:
    SELECTING_HAND = 1
    HAND_PLAYED = 2
    DRAW_TO_HAND = 3
    GAME_OVER = 4
    SHOP = 5
    PLAY_TAROT = 6
    BLIND_SELECT = 7
    ROUND_EVAL = 8
    TAROT_PACK = 9
    PLANET_PACK = 10
    MENU = 11
    TUTORIAL = 12
    SPLASH = 13
    SANDBOX = 14
    SPECTRAL_PACK = 15
    DEMO_CTA = 16
    STANDARD_PACK = 17
    BUFFOON_PACK = 18
    NEW_ROUND = 19


STATE_NAMES = {v: k for k, v in vars(STATES).items() if not k.startswith("_")}

DECK_NAMES = {
    "red": "b_red", "blue": "b_blue", "yellow": "b_yellow", "green": "b_green", "black": "b_black",
    "magic": "b_magic", "nebula": "b_nebula", "ghost": "b_ghost", "abandoned": "b_abandoned",
    "checkered": "b_checkered", "zodiac": "b_zodiac", "painted": "b_painted", "anaglyph": "b_anaglyph",
    "plasma": "b_plasma", "erratic": "b_erratic", "challenge": "b_challenge",
}
STAKE_NAMES = {"white": 1, "red": 2, "green": 3, "black": 4, "blue": 5, "purple": 6, "orange": 7, "gold": 8}


class Profile:
    """Which centers are unlocked/discovered (affects pools).

    Seed finders assume everything is unlocked; ``Profile.fresh()`` is a brand
    new save.  Discoveries made during a *seeded* run don't count in the game,
    so the profile is static for the whole run.
    """

    def __init__(self, unlocked: set[str] | None = None, discovered: set[str] | None = None, all_: bool = True) -> None:
        self.all = all_
        self.unlocked = unlocked or set()
        self.discovered = discovered or set()

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


class Game(PoolsMixin, FlowMixin, ShopMixin, PacksMixin, ActionsMixin):
    STATES = STATES

    def __init__(self, seed: str, deck: str = "b_red", stake: int | str = 1, challenge: str | None = None,
                 profile: Profile | None = None, hands_order: Iterable[str] | None = None,
                 normalize: bool = True) -> None:
        self.data = data_mod.load()
        d = self.data
        self.P_CENTERS = d.P_CENTERS
        self.P_CARDS = d.P_CARDS
        self.P_BLINDS = d.P_BLINDS
        self.P_TAGS = d.P_TAGS
        self.P_SEALS = d.P_SEALS
        self.P_CENTER_POOLS = d.P_CENTER_POOLS
        self.P_JOKER_RARITY_POOLS = d.P_JOKER_RARITY_POOLS
        self.P_CARD_KEY = {id(v): k for k, v in d.P_CARDS.items()}
        self.handlist = d.handlist
        self.profile = profile or Profile.everything()
        self._hands_order = list(hands_order) if hands_order is not None else list(DEFAULT_HANDS_ORDER)

        self.seed = normalize_seed(seed) if normalize else seed
        self.deck_key = DECK_NAMES.get(deck.lower(), deck) if isinstance(deck, str) else deck
        self.stake = STAKE_NAMES.get(stake.lower(), 1) if isinstance(stake, str) else stake
        self.challenge_id = challenge

        # runtime bookkeeping (globals in the Lua)
        self.sort_id = 0
        self.tagid = 0
        self.playing_card = 0
        self.stone_id_counter = -100
        self.all_cards: list[Card] = []
        self.events: deque[Callable[[], Any]] = deque()
        self.deferred: list[Callable[[], Any]] = []
        self.OVERLAY_MENU = None
        self.FORCE_TAG = None
        self.FORCE_BOSS = None
        self.orbital_hand = None
        self.from_boss_tag = None
        self.ARGS = T()
        self.STATE = STATES.BLIND_SELECT
        self.STATE_COMPLETE = False
        self.TAROT_INTERRUPT = None
        self.shop = None
        self.blind_select = None
        self.booster_pack = None
        self.round_eval = None
        self.shop_jokers: CardArea | None = None
        self.shop_vouchers: CardArea | None = None
        self.shop_booster: CardArea | None = None
        self.pack_cards: CardArea | None = None
        self.play: CardArea | None = None
        self.jokers: CardArea | None = None
        self.consumeables: CardArea | None = None
        self.hand: CardArea | None = None
        self.deck: CardArea | None = None
        self.discard: CardArea | None = None
        self.playing_cards: list[Card] = []
        self.GAME: T = self.init_game_object()
        self.rng = PseudoRandom(self.seed)
        self.log: list[Any] = []

    def snapshot(self) -> dict:
        from .snapshot import snapshot
        return snapshot(self)

    def clone(self) -> "Game":
        """An independent copy of the whole run (for what-if exploration).

        Static prototype tables are shared, everything else is copied, so the
        clone continues with exactly the same RNG streams and state.
        """
        import copy
        memo: dict[int, Any] = {id(self.data): self.data, id(self.profile): self.profile}
        for table in (self.P_CENTERS, self.P_CARDS, self.P_BLINDS, self.P_TAGS, self.P_SEALS,
                      self.data.P_STAKES):
            memo[id(table)] = table
            for v in table.values():
                memo[id(v)] = v
        for pool in self.P_CENTER_POOLS.values():
            memo[id(pool)] = pool
        memo[id(self.P_CENTER_POOLS)] = self.P_CENTER_POOLS
        for pool in self.P_JOKER_RARITY_POOLS:
            memo[id(pool)] = pool
        memo[id(self.P_JOKER_RARITY_POOLS)] = self.P_JOKER_RARITY_POOLS
        memo[id(self.P_CARD_KEY)] = self.P_CARD_KEY
        memo[id(self.handlist)] = self.handlist
        return copy.deepcopy(self, memo)

    # ------------------------------------------------------------- profile
    def is_unlocked(self, center: T) -> bool:
        if self.profile.all:
            return True
        if center.unlocked is not False:
            return True
        return center.key in self.profile.unlocked

    def is_discovered(self, key: str) -> bool:
        if self.profile.all:
            return True
        return key in self.profile.discovered

    def hands_order(self) -> list[str]:
        """Iteration order of ``pairs(G.GAME.hands)`` (see DEFAULT_HANDS_ORDER)."""
        return self._hands_order

    # -------------------------------------------------------------- events
    def add_event(self, fn: Callable[[], Any], front: bool = False) -> None:
        if front:
            self.events.appendleft(fn)
        else:
            self.events.append(fn)

    def run_events(self) -> None:
        ev = self.events
        while ev:
            ev.popleft()()

    def defer(self, fn: Callable[[], Any]) -> None:
        """Non-blockable delayed events: run once the action has settled."""
        self.deferred.append(fn)

    def defer_removal(self, card: Card) -> None:
        self.defer(card.remove)

    def run_deferred_one_frame(self) -> None:
        """Fire every pending timed (non-blockable) effect; events they queue
        join the normal queue."""
        while self.deferred:
            fns, self.deferred = self.deferred, []
            for fn in fns:
                fn()

    def run_deferred(self) -> None:
        while self.deferred:
            self.run_deferred_one_frame()
            self.run_events()

    # ------------------------------------------------------------- helpers
    def find_joker(self, name: str, non_debuff: bool = False) -> list[Card]:
        out = []
        if self.jokers is None:
            return out
        for v in self.jokers.cards:
            if v.ability.name == name and (non_debuff or not v.debuff):
                out.append(v)
        for v in self.consumeables.cards:
            if v.ability.name == name and (non_debuff or not v.debuff):
                out.append(v)
        return out

    def get_blind_amount(self, ante: int) -> float:
        k = 0.75
        scaling = self.GAME.modifiers.scaling
        if not scaling or scaling == 1:
            amounts = [300, 800, 2000, 5000, 11000, 20000, 35000, 50000]
        elif scaling == 2:
            amounts = [300, 900, 2600, 8000, 20000, 36000, 60000, 100000]
        else:
            amounts = [300, 1000, 3200, 9000, 25000, 60000, 110000, 200000]
        if ante < 1:
            return 100
        if ante <= 8:
            return amounts[ante - 1]
        a, b, c, dd = amounts[7], 1.6, ante - 8, 1 + 0.2 * (ante - 8)
        amount = floor(a * (b + (k * c) ** dd) ** c)
        if amount == math.inf:
            return amount
        amount = amount - amount % (10 ** math.floor(math.log10(amount) - 1))
        return amount

    def refresh_all_costs(self) -> None:
        for c in list(self.all_cards):
            c.set_cost()

    def update_cards(self) -> None:
        """Per-frame CardArea:update + Card:update logic (Game:update -> MOVEABLES)."""
        G = self
        hand = G.hand
        if hand is not None:
            per = G.GAME.modifiers.minus_hand_size_per_X_dollar
            if per:
                last = hand.config.last_poll_size or 0
                now = math.floor(G.GAME.dollars / per)
                if now != last:
                    hand.change_size(last - now)
                    hand.config.last_poll_size = now
            for c in list(hand.cards):
                if c.ability.forced_selection and not hand.highlighted:
                    hand.add_to_highlighted(c)
        if G.deck is not None and G.deck.config.card_limit > len(G.playing_cards):
            G.deck.config.card_limit = len(G.playing_cards)
        for c in list(self.all_cards):
            if not c.removed:
                c.update()

    def ease_dollars(self, mod: float, instant: bool = False) -> None:
        def _mod() -> None:
            self.GAME.dollars = self.GAME.dollars + (mod or 0)
        if instant:
            _mod()
        else:
            self.add_event(_mod)

    def ease_discard(self, mod: float, instant: bool = False, silent: bool = False) -> None:
        def _mod() -> None:
            cr = self.GAME.current_round
            if abs(max(cr.discards_left, mod)) == 0:
                return
            m = max(-cr.discards_left, mod or 0)
            cr.discards_left = cr.discards_left + m
        if instant:
            _mod()
        else:
            self.add_event(_mod)

    def ease_hands_played(self, mod: float, instant: bool = False) -> None:
        def _mod() -> None:
            self.GAME.current_round.hands_left = self.GAME.current_round.hands_left + (mod or 0)
        if instant:
            _mod()
        else:
            self.add_event(_mod)

    def ease_ante(self, mod: int) -> None:
        def _mod() -> None:
            self.GAME.round_resets.ante = self.GAME.round_resets.ante + (mod or 0)
        self.add_event(_mod)

    def ease_round(self, mod: int) -> None:
        def _mod() -> None:
            self.GAME.round = self.GAME.round + (mod or 0)
        self.add_event(_mod)

    def ease_chips(self, mod: float) -> None:
        def _mod() -> None:
            self.GAME.chips = mod or 0
        self.add_event(_mod)

    def level_up_hand(self, card: Any, hand: str, instant: Any = None, amount: int = 1) -> None:
        h = self.GAME.hands[hand]
        h.level = max(0, h.level + amount)
        h.mult = max(h.s_mult + h.l_mult * (h.level - 1), 1)
        h.chips = max(h.s_chips + h.l_chips * (h.level - 1), 0)

    def calculate_reroll_cost(self, skip_increment: bool = False) -> None:
        cr = self.GAME.current_round
        if cr.free_rerolls < 0:
            cr.free_rerolls = 0
        if cr.free_rerolls > 0:
            cr.reroll_cost = 0
            return
        cr.reroll_cost_increase = cr.reroll_cost_increase or 0
        if not skip_increment:
            cr.reroll_cost_increase += 1
        rr = self.GAME.round_resets
        cr.reroll_cost = (rr.temp_reroll_cost if rr.temp_reroll_cost is not None else rr.reroll_cost) + cr.reroll_cost_increase

    def add_tag(self, tag: Any) -> None:
        for t in list(self.GAME.tags):
            t.apply_to_run(T(type="tag_add", tag=tag))
        self.GAME.tags.append(tag)

    def change_shop_size(self, mod: int) -> None:
        G = self
        if not G.GAME.shop:
            return
        G.GAME.shop.joker_max = G.GAME.shop.joker_max + mod
        if G.shop_jokers is not None and not G.shop_jokers.removed:
            if mod < 0:
                for i in range(len(G.shop_jokers.cards) - 1, G.GAME.shop.joker_max - 1, -1):
                    if i < len(G.shop_jokers.cards):
                        G.shop_jokers.cards[i].remove()
            G.shop_jokers.config.card_limit = G.GAME.shop.joker_max
            if mod > 0:
                for _ in range(G.GAME.shop.joker_max - len(G.shop_jokers.cards)):
                    G.shop_jokers.emplace(G.create_card_for_shop(G.shop_jokers))

    def playing_card_joker_effects(self, cards: list[Any]) -> None:
        for j in list(self.jokers.cards):
            j.calculate_joker(T(playing_card_added=True, cards=cards))

    def draw_card(self, from_: CardArea | None, to: CardArea, card: Card | None = None, sort: bool = False,
                  stay_flipped: Any = None, discarded_only: bool = False) -> None:
        """draw_card() from common_events.lua: the move happens in an event."""
        G = self

        def ev() -> None:
            c = card
            if c is not None:
                if from_ is not None:
                    c = from_.remove_card(c)
                stay = G.GAME.blind.stay_flipped(to, c) if G.GAME and G.GAME.blind else None
                if G.GAME.modifiers.flipped_cards and to is G.hand:
                    if G.rng.random("flipped_card") < 1 / G.GAME.modifiers.flipped_cards:
                        stay = True
                to.emplace(c, None, stay)
            else:
                to.draw_card_from(from_, stay_flipped, discarded_only)
            if sort:
                to.sort()
        G.add_event(ev)

    # ------------------------------------------------------- game object
    def init_game_object(self) -> T:
        d = self.data
        bosses_used = T({k: 0 for k, v in d.P_BLINDS.items() if v.boss})
        g = T(
            won=False,
            round_scores=T(new_collection=T(amt=0), cards_played=T(amt=0), cards_discarded=T(amt=0),
                           times_rerolled=T(amt=0), cards_purchased=T(amt=0), hand=T(amt=0)),
            joker_usage=T(), consumeable_usage=T(), hand_usage=T(), last_tarot_planet=None, win_ante=8,
            stake=1, modifiers=T(), starting_params=to_T(dict(d.starting_params)), banned_keys=T(), round=0,
            probabilities=T(normal=1), bosses_used=bosses_used, pseudorandom=T(), starting_deck_size=52,
            ecto_minus=1, pack_size=2, skips=0, STOP_USE=0, edition_rate=1, joker_rate=20, tarot_rate=4,
            planet_rate=4, spectral_rate=0, playing_card_rate=0, consumeable_buffer=0, joker_buffer=0,
            discount_percent=0, interest_cap=25, interest_amount=1, inflation=0, hands_played=0,
            unused_discards=0, perishable_rounds=5, rental_rate=3, blind=None, chips=0, dollars=0,
            max_jokers=0, bankrupt_at=0, current_boss_streak=0, base_reroll_cost=5, blind_on_deck=None,
            sort="desc", previous_round=T(dollars=4), tags=[], tag_tally=0, pool_flags=T(), used_jokers=T(),
            used_vouchers=T(),
            current_round=T(
                current_hand=T(chips=0, mult=0, chip_total=0, handname=""),
                used_packs=T(), cards_flipped=0, idol_card=T(suit="Spades", rank="Ace"), mail_card=T(rank="Ace"),
                ancient_card=T(suit="Spades"), castle_card=T(suit="Spades"), hands_left=0, hands_played=0,
                discards_left=0, discards_used=0, dollars=0, reroll_cost=5, reroll_cost_increase=0,
                jokers_purchased=0, free_rerolls=0, round_dollars=0, most_played_poker_hand="High Card",
            ),
            round_resets=T(hands=1, discards=1, reroll_cost=1, temp_reroll_cost=None, temp_handsize=None, ante=1,
                           blind_ante=1, blind_states=T(Small="Select", Big="Upcoming", Boss="Upcoming"),
                           blind_choices=T(Small="bl_small", Big="bl_big"), boss_rerolled=False),
            round_bonus=T(next_hands=0, discards=0),
            shop=T(joker_max=2),
            cards_played=T({r: T(suits=T(), total=0) for r in
                            ("Ace", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Jack", "Queen", "King")}),
            hands=to_T(copy_table(d.hands_proto)),
        )
        return g

    # -------------------------------------------------------------- start
    def start_run(self) -> "Game":
        G = self
        GAME = G.GAME
        challenge = G.data.challenge(G.challenge_id) if G.challenge_id else None
        if challenge is not None and challenge.deck and challenge.deck.type:
            back_center = G.data.center_by_name(challenge.deck.type)
        else:
            back_center = G.P_CENTERS[G.deck_key]
        GAME.stake = G.stake
        GAME.STOP_USE = 0
        GAME.selected_back = Back(G, back_center)
        GAME.selected_back_key = back_center
        if GAME.stake >= 2:
            GAME.modifiers.no_blind_reward = GAME.modifiers.no_blind_reward or T()
            GAME.modifiers.no_blind_reward.Small = True
        if GAME.stake >= 3:
            GAME.modifiers.scaling = 2
        if GAME.stake >= 4:
            GAME.modifiers.enable_eternals_in_shop = True
        if GAME.stake >= 5:
            GAME.starting_params.discards = GAME.starting_params.discards - 1
        if GAME.stake >= 6:
            GAME.modifiers.scaling = 3
        if GAME.stake >= 7:
            GAME.modifiers.enable_perishables_in_shop = True
        if GAME.stake >= 8:
            GAME.modifiers.enable_rentals_in_shop = True

        # card areas exist before any event runs
        sp = GAME.starting_params
        G.consumeables = CardArea(G, "consumeables", {"card_limit": sp.consumable_slots, "type": "joker", "highlight_limit": 1})
        G.jokers = CardArea(G, "jokers", {"card_limit": sp.joker_slots, "type": "joker", "highlight_limit": 1})
        G.discard = CardArea(G, "discard", {"card_limit": 500, "type": "discard"})
        G.deck = CardArea(G, "deck", {"card_limit": 52, "type": "deck"})
        G.hand = CardArea(G, "hand", {"card_limit": sp.hand_size, "type": "hand"})
        G.play = CardArea(G, "play", {"card_limit": 5, "type": "play"})
        GAME.blind = Blind(G)

        GAME.selected_back.apply_to_run()

        if challenge is not None:
            self._apply_challenge(challenge)
            sp = GAME.starting_params

        # CardAreas above were created with the *pre*-deck starting params in
        # the Lua as well?  No: start_run builds areas after apply_to_run.
        G.consumeables.config.card_limit = sp.consumable_slots
        G.consumeables.config.temp_limit = sp.consumable_slots
        G.jokers.config.card_limit = sp.joker_slots
        G.jokers.config.temp_limit = sp.joker_slots
        G.hand.config.card_limit = sp.hand_size
        G.hand.config.temp_limit = sp.hand_size

        rr = GAME.round_resets
        rr.hands = sp.hands
        rr.discards = sp.discards
        rr.reroll_cost = sp.reroll_cost
        GAME.dollars = sp.dollars
        GAME.base_reroll_cost = sp.reroll_cost
        rr.reroll_cost = GAME.base_reroll_cost
        GAME.current_round.reroll_cost = GAME.base_reroll_cost

        GAME.seeded = True
        GAME.pseudorandom = G.rng.state
        rr.blind_tags = rr.blind_tags or T()
        rr.blind_choices.Boss = G.get_new_boss()
        GAME.current_round.voucher = G.get_next_voucher_key()
        rr.blind_tags.Small = G.get_next_tag_key()
        rr.blind_tags.Big = G.get_next_tag_key()

        # starting deck
        card_protos: list[T] = []
        de = challenge.deck if challenge is not None and challenge.deck else None
        if de is not None and de.cards:
            card_protos = [T(v) for v in de.cards]
        else:
            # pairs() order over P_CARDS is irrelevant: every pass is either
            # unconditional (52 erratic draws) or the result gets sorted below
            for k in G.data.P_CARDS_SORTED_KEYS:
                if sp.erratic_suits_and_ranks:
                    k = G.data.P_CARDS_SORTED_KEYS[G.rng.element_index(52, G.rng.pseudoseed("erratic"))]
                r, s = k[2], k[0]
                keep, e, dd, g = True, None, None, None
                if de is not None:
                    if de.yes_ranks and not de.yes_ranks.get(r):
                        keep = False
                    if de.no_ranks and de.no_ranks.get(r):
                        keep = False
                    if de.yes_suits and not de.yes_suits.get(s):
                        keep = False
                    if de.no_suits and de.no_suits.get(s):
                        keep = False
                    e, dd, g = de.enhancement, de.edition, de.gold_seal
                if sp.no_faces and r in ("K", "Q", "J"):
                    keep = False
                if keep:
                    card_protos.append(T(s=s, r=r, e=e, d=dd, g=g))
        if sp.extra_cards:
            for v in sp.extra_cards:
                card_protos.append(T(v))
        card_protos.sort(key=lambda p: (p.s or "") + (p.r or "") + (p.e or "") + (p.d or "") + (p.g or ""))
        for p in card_protos:
            G.card_from_control(p)
        GAME.starting_deck_size = len(G.playing_cards)

        GAME.current_round.discards_left = rr.discards
        GAME.current_round.hands_left = rr.hands
        G.deck.shuffle()
        G.reset_idol_card()
        G.reset_mail_rank()
        GAME.current_round.ancient_card.suit = None
        G.reset_ancient_card()
        G.reset_castle_card()

        GAME.blind.set_blind(None, None, True)
        G.reset_blinds()
        G.STATE = STATES.BLIND_SELECT
        G.STATE_COMPLETE = False
        G.advance()
        return self

    def card_from_control(self, control: T) -> Card:
        G = self
        G.playing_card = (G.playing_card + 1) if G.playing_card else 1
        card = Card(G, G.P_CARDS[control.s + "_" + control.r], G.P_CENTERS[control.e or "c_base"],
                    {"playing_card": G.playing_card})
        if control.d:
            card.set_edition(T({control.d: True}), True, True)
        if control.g:
            card.set_seal(control.g, True, True)
        G.deck.emplace(card)
        G.playing_cards.append(card)
        return card

    def _apply_challenge(self, ch: T) -> None:
        G = self
        GAME = G.GAME
        GAME.challenge = ch.id
        GAME.challenge_tab = ch
        if ch.jokers:
            for i, v in enumerate(ch.jokers):
                def mk(v: T = v) -> None:
                    j = G.add_joker(v.id, v.edition)
                    if v.eternal:
                        j.set_eternal(True)
                    if v.pinned:
                        j.pinned = True
                G.add_event(mk)
        if ch.consumeables:
            for v in ch.consumeables:
                G.add_event(lambda v=v: G.add_joker(v.id, None))
        if ch.vouchers:
            from .vouchers import apply_to_run
            for v in ch.vouchers:
                GAME.used_vouchers[v.id] = True

                def ap(v: T = v) -> None:
                    GAME.starting_voucher_count = (GAME.starting_voucher_count or 0) + 1
                    apply_to_run(G, None, G.P_CENTERS[v.id])
                G.add_event(ap)
        rules = ch.rules
        if rules:
            for v in rules.modifiers or []:
                GAME.starting_params[v.id] = v.value
            for v in rules.custom or []:
                if v.id == "no_reward":
                    GAME.modifiers.no_blind_reward = GAME.modifiers.no_blind_reward or T()
                    GAME.modifiers.no_blind_reward.Small = True
                    GAME.modifiers.no_blind_reward.Big = True
                    GAME.modifiers.no_blind_reward.Boss = True
                elif v.id == "no_reward_specific":
                    GAME.modifiers.no_blind_reward = GAME.modifiers.no_blind_reward or T()
                    GAME.modifiers.no_blind_reward[v.value] = True
                elif v.value is not None:
                    GAME.modifiers[v.id] = v.value
                elif v.id == "no_shop_jokers":
                    GAME.joker_rate = 0
                else:
                    GAME.modifiers[v.id] = True
        res = ch.restrictions
        if res:
            for v in res.banned_cards or []:
                GAME.banned_keys[v.id] = True
                for vv in v.ids or []:
                    GAME.banned_keys[vv] = True
            for v in res.banned_tags or []:
                GAME.banned_keys[v.id] = True
            for v in res.banned_other or []:
                GAME.banned_keys[v.id] = True

    def add_joker(self, key: str, edition: str | None = None, silent: Any = None, eternal: Any = None) -> Card:
        G = self
        center = G.P_CENTERS[key]
        area = G.consumeables if center.consumeable else G.jokers
        card = Card(G, None, center, {"discover": True, "bypass_discovery_center": True})
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


# ``pairs(G.GAME.hands)`` iteration order.  It decides To Do List targets, the
# Orbital Tag hand and The Ox's tie-break (and nothing else).  In LuaJIT 2.1
# (LOVE 11.4+/Balatro) the order depends on string hashes that are keyed with
# a random per-process seed ("Redesign and harden string interning", 2020), so
# it changes from one game launch to the next: the seed fixes *which position*
# is chosen, the session fixes which hand sits at that position.  The default
# is simply the constructor's source order; pass ``hands_order`` to match a
# particular session (the oracle reports the order it used).
DEFAULT_HANDS_ORDER = [
    "Flush Five", "Flush House", "Five of a Kind", "Straight Flush", "Four of a Kind", "Full House",
    "Flush", "Straight", "Three of a Kind", "Two Pair", "Pair", "High Card",
]
