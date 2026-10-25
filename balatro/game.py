"""The Game object (the global ``G`` of the Lua source).

It owns the run state (``G.GAME``), the card areas, the event queue and the
frame loop.  :meth:`Game.frame` is a port of ``Game:update``: timers, the
event manager, the state machine, the UI motion the logic waits on, every
card's per-frame update and the controller locks, in the game's order.
Player actions (see actions.py) are applied between frames and the game is
then run frame by frame until it waits for input again.
"""

from __future__ import annotations

import copy
import math
import random
from typing import Any, Iterable

from . import data as data_mod
from .actions import ActionsMixin
from .back import Back
from .blind import Blind
from .buttons import ButtonsMixin
from .card import _UPDATE_NAMES as UPDATE_NAMES
from .card import Card
from .cardarea import CardArea
from .common import CommonMixin, new_run_profile
from .events import EventManager
from .lua import T, copy_table, to_T
from .rng import SEED_ALPHABET, PseudoRandom, lua_tostring, normalize_seed
from .state_events import StateEventsMixin
from .ui import HAND_H, ROOM_Y, TILE_H, Box, move_hand


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
PACK_STATES = (STATES.TAROT_PACK, STATES.PLANET_PACK, STATES.SPECTRAL_PACK, STATES.STANDARD_PACK, STATES.BUFFOON_PACK)

DECK_NAMES = {
    "red": "b_red", "blue": "b_blue", "yellow": "b_yellow", "green": "b_green", "black": "b_black",
    "magic": "b_magic", "nebula": "b_nebula", "ghost": "b_ghost", "abandoned": "b_abandoned",
    "checkered": "b_checkered", "zodiac": "b_zodiac", "painted": "b_painted", "anaglyph": "b_anaglyph",
    "plasma": "b_plasma", "erratic": "b_erratic", "challenge": "b_challenge",
}
STAKE_NAMES = {"white": 1, "red": 2, "green": 3, "black": 4, "blue": 5, "purple": 6, "orange": 7, "gold": 8}

# ``pairs(G.GAME.hands)`` iteration order.  It decides To Do List targets, the
# Orbital Tag hand and The Ox's tie-break (and nothing else).  LuaJIT keys
# string hashes with a per-process random seed, so in the real game this order
# changes from one launch to the next: the seed fixes *which position* is
# chosen, the session fixes which hand sits there.  Pass ``hands_order`` to
# match a particular session (the oracle reports the order it used).
DEFAULT_HANDS_ORDER = [
    "Flush Five", "Flush House", "Five of a Kind", "Straight Flush", "Four of a Kind", "Full House",
    "Flush", "Straight", "Three of a Kind", "Two Pair", "Pair", "High Card",
]


def _num(x: float) -> str:
    """A number as the game shows it (no trailing .0)."""
    return str(int(x)) if isinstance(x, float) and x.is_integer() and abs(x) < 1e15 else str(x)


class Profile:
    """Which centers are unlocked/discovered (this changes the pools).

    Seed finders assume everything is unlocked; :meth:`fresh` is a brand new
    save.  A seeded run never unlocks or discovers anything, so the profile
    stays fixed for the whole run.
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


class Controller:
    """The parts of engine/controller.lua the logic reads: the locks."""

    def __init__(self) -> None:
        self.locks = T()
        self.locked = False

    def update(self) -> None:
        # (as in the oracle: frame locks only last a frame, wipes never happen)
        self.locks.wipe = False
        self.locks.frame_set = None
        self.locks.frame = None
        self.locked = any(bool(v) for v in self.locks.values())


class Game(CommonMixin, StateEventsMixin, ButtonsMixin, ActionsMixin):
    """A Balatro run.

    ``Game(seed, deck, stake, challenge=None)`` (no seed: a random one); call
    :meth:`start_run`, then play it with the ``act_*`` methods (actions.py).
    The run behaves as a seeded run: nothing gets unlocked or discovered.
    """

    STATES = STATES

    def __init__(self, seed: str | None = None, deck: str = "b_red", stake: int | str = 1, challenge: str | None = None,
                 profile: Profile | None = None, hands_order: Iterable[str] | None = None,
                 game_speed: float = 1, normalize: bool = True, fast_forward: bool = True) -> None:
        self.data = d = data_mod.load()
        self.P_CENTERS = d.P_CENTERS
        self.P_CARDS = d.P_CARDS
        self.P_BLINDS = d.P_BLINDS
        self.P_TAGS = d.P_TAGS
        self.P_SEALS = d.P_SEALS
        self.P_CENTER_POOLS = d.P_CENTER_POOLS
        self.P_JOKER_RARITY_POOLS = d.P_JOKER_RARITY_POOLS
        self.P_CARD_KEY = d.P_CARD_KEY
        self.handlist = d.handlist
        self.profile = profile or Profile.everything()
        self.PROFILE = new_run_profile()
        self._hands_order = list(hands_order) if hands_order is not None else list(DEFAULT_HANDS_ORDER)

        if seed is None:  # like an unseeded run: a fresh random seed (8 characters)
            seed = "".join(random.SystemRandom().choice(SEED_ALPHABET) for _ in range(8))
        self.seed = normalize_seed(seed) if normalize else seed
        self.deck_key = DECK_NAMES.get(deck.lower(), deck) if isinstance(deck, str) else deck
        self.stake = STAKE_NAMES.get(stake.lower(), 1) if isinstance(stake, str) else stake
        self.challenge_id = challenge

        # engine globals
        self.SETTINGS = T(GAMESPEED=game_speed, paused=False)
        self.TIMERS = {"TOTAL": 0.0, "REAL": 0.0}
        self.FRAMES_MOVE = 0
        self.dt = 1 / 60
        # skip the work of frames in which nothing can happen (identical results)
        self.fast_forward = fast_forward
        self._idle: tuple[float, float, float, float] | None = None
        self.real_dt = self.dt
        self.ACC: float = 0
        self.ACC_state: int | None = None
        self.SPEEDFACTOR: float = 1
        self.exp_xy = 0.0
        self.move_dt = 0.0
        self.max_vel = 0.0
        self.CONTROLLER = Controller()
        self.E_MANAGER = EventManager(self)
        self.STAGE_RUN = True
        self.STATE: int = -1
        self.STATE_COMPLETE = False
        self.node_id = 0
        self.sort_id = 0
        self.tagid = 0
        self.playing_card = 0
        self.stone_id = -100
        self.I_CARD: list[Card] = []
        self.OVERLAY_MENU = None
        self.FORCE_TAG = None
        self.FORCE_BOSS = None
        self.orbital_hand = None
        self.from_boss_tag = None
        self.TAROT_INTERRUPT = None
        self.RESET_JIGGLES = None
        self.RESET_BLIND_STATES = None
        self.boss_throw_hand = None
        self.deck_preview = None
        self.last_materialized = None
        self.ARGS = T()
        # UI boxes the logic reads or writes
        self.shop: Box | None = None
        self.SHOP_SIGN: Box | None = None
        self.blind_select: Box | None = None
        self.blind_prompt_box: Box | None = None
        self.blind_select_tags: T = T()
        self.booster_pack: Box | None = None
        self.round_eval: Box | None = None
        self.hand_T_y = TILE_H - HAND_H
        # card areas
        self.shop_jokers: CardArea | None = None
        self.shop_vouchers: CardArea | None = None
        self.shop_booster: CardArea | None = None
        self.pack_cards: CardArea | None = None
        # (these six exist once start_run() has run)
        self.play: CardArea = None  # type: ignore[assignment]
        self.jokers: CardArea = None  # type: ignore[assignment]
        self.consumeables: CardArea = None  # type: ignore[assignment]
        self.hand: CardArea = None  # type: ignore[assignment]
        self.deck: CardArea = None  # type: ignore[assignment]
        self.discard: CardArea = None  # type: ignore[assignment]
        self.playing_cards: list[Card] = []
        self.GAME: T = self.init_game_object()
        self.rng = PseudoRandom(self.seed)
        self.last_score: T | None = None
        self.last_scoring: T | None = None
        self.round_eval_rows: list | None = None
        # what the game shows the player, while recording (start_feedback)
        self.feedback: list[dict] | None = None
        self._feedback_t0 = 0.0

    # ------------------------------------------------------------ helpers
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
        """The order of ``pairs(G.GAME.hands)`` (see DEFAULT_HANDS_ORDER)."""
        return self._hands_order

    def ante_str(self) -> str:
        return lua_tostring(self.GAME.round_resets.ante)

    def next_draws(self, n: int | None = None) -> list[Card]:
        """The cards the deck will deal next, in order (it deals from the end
        of ``G.deck.cards``).  The deck is reshuffled when a round starts."""
        cards = self.deck.cards[::-1] if self.deck is not None else []
        return cards if n is None else cards[:n]

    def summary(self) -> str:
        """A short human-readable description of the current situation."""
        from .analyzer import describe
        G = self
        GAME = G.GAME
        cr = GAME.current_round
        rr = GAME.round_resets
        lines = [f"{G.seed} ante {rr.ante} round {GAME.round}  {STATE_NAMES.get(G.STATE, G.STATE)}  ${_num(GAME.dollars)}"]

        def row(label: str, cards: list[Card]) -> None:
            lines.append(f"  {label}: " + (", ".join(f"{i}:{describe(c)}" for i, c in enumerate(cards)) or "-"))
        if G.STATE == STATES.BLIND_SELECT:
            tags = rr.blind_tags or T()
            lines.append(f"  on deck: {GAME.blind_on_deck}  boss: {G.data.display_name(rr.blind_choices.Boss)}  "
                         f"tags: {tags.Small} / {tags.Big}")
        if GAME.blind and GAME.blind.name:
            lines.append(f"  blind: {GAME.blind.name}  {GAME.chips:.0f} / {GAME.blind.chips:.0f} chips  "
                         f"hands {cr.hands_left}  discards {cr.discards_left}")
        if G.jokers is not None:
            row(f"jokers {len(G.jokers.cards)}/{G.jokers.config.card_limit}", G.jokers.cards)
            row(f"consumables {len(G.consumeables.cards)}/{G.consumeables.config.card_limit}", G.consumeables.cards)
        if G.hand is not None and G.hand.cards:
            row("hand", G.hand.cards)
        if G.shop is not None and not G.shop.removed:
            row("shop", G.shop_jokers.cards)
            row("vouchers", G.shop_vouchers.cards)
            row("packs", G.shop_booster.cards)
            lines.append(f"  reroll ${_num(cr.reroll_cost)}")
        if G.pack_cards is not None and not G.pack_cards.removed and G.in_pack():
            row(f"pack (choose {GAME.pack_choices})", G.pack_cards.cards)
        if GAME.tags:
            lines.append("  tags: " + ", ".join(t.key for t in GAME.tags))
        return "\n".join(lines)

    def snapshot(self) -> dict:
        """The run state as plain data (the oracle's format, see snapshot.py)."""
        from .snapshot import snapshot
        return snapshot(self)

    def clone(self) -> "Game":
        """An independent copy of the whole run (for what-if exploration).

        Static prototype tables are shared, everything else is copied, so the
        copy continues exactly like the original would."""
        memo: dict[int, Any] = {id(self.data): self.data, id(self.profile): self.profile}
        d = self.data
        for table in (d.P_CENTERS, d.P_CARDS, d.P_BLINDS, d.P_TAGS, d.P_SEALS, d.P_STAKES):
            memo[id(table)] = table
            for v in table.values():
                memo[id(v)] = v
                if isinstance(v, T) and v.config is not None:
                    memo[id(v.config)] = v.config
        for pool in d.P_CENTER_POOLS.values():
            memo[id(pool)] = pool
        memo[id(d.P_CENTER_POOLS)] = d.P_CENTER_POOLS
        for pool in d.P_JOKER_RARITY_POOLS:
            memo[id(pool)] = pool
        memo[id(d.P_JOKER_RARITY_POOLS)] = d.P_JOKER_RARITY_POOLS
        memo[id(d.P_CARD_KEY)] = d.P_CARD_KEY
        memo[id(self.handlist)] = self.handlist
        # (pending events copy the closures they hold, see Event.__deepcopy__)
        return copy.deepcopy(self, memo)

    # ------------------------------------------------------- game object
    def init_game_object(self) -> T:
        d = self.data
        bosses_used = T({k: 0 for k, v in d.P_BLINDS.items() if v.boss})
        return T(
            won=False,
            round_scores=T(furthest_ante=T(amt=0), furthest_round=T(amt=0), hand=T(amt=0), poker_hand=T(amt=0),
                           new_collection=T(amt=0), cards_played=T(amt=0), cards_discarded=T(amt=0),
                           times_rerolled=T(amt=0), cards_purchased=T(amt=0)),
            joker_usage=T(), consumeable_usage=T(), hand_usage=T(), last_tarot_planet=None, win_ante=8,
            stake=1, modifiers=T(), starting_params=to_T(copy_table(d.starting_params)), banned_keys=T(), round=0,
            probabilities=T(normal=1), bosses_used=bosses_used, pseudorandom=T(), starting_deck_size=52,
            ecto_minus=1, pack_size=2, skips=0, STOP_USE=0, edition_rate=1, joker_rate=20, tarot_rate=4,
            planet_rate=4, spectral_rate=0, playing_card_rate=0, consumeable_buffer=0, joker_buffer=0,
            discount_percent=0, interest_cap=25, interest_amount=1, inflation=0, hands_played=0,
            unused_discards=0, perishable_rounds=5, rental_rate=3, blind=None, chips=0, dollars=0,
            max_jokers=0, bankrupt_at=0, current_boss_streak=0, base_reroll_cost=5, blind_on_deck=None,
            sort="desc", previous_round=T(dollars=4), tags=[], tag_tally=0, pool_flags=T(), used_jokers=T(),
            used_vouchers=T(),
            current_round=T(
                current_hand=T(chips=0, mult=0, chip_total=0, handname="", hand_level=""),
                used_packs=T(), cards_flipped=0, round_text="Round ", idol_card=T(suit="Spades", rank="Ace"),
                mail_card=T(rank="Ace"), ancient_card=T(suit="Spades"), castle_card=T(suit="Spades"),
                hands_left=0, hands_played=0, discards_left=0, discards_used=0, dollars=0, reroll_cost=5,
                reroll_cost_increase=0, jokers_purchased=0, free_rerolls=0, round_dollars=0,
                most_played_poker_hand="High Card",
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

    # ------------------------------------------------------------- start
    def start_run(self) -> "Game":
        """Game:start_run(): set up the run, then run it until it waits for
        the first decision (the blind select screen)."""
        G = self
        GAME = G.GAME
        challenge = G.data.challenge(G.challenge_id) if G.challenge_id else None
        if challenge is not None and challenge.deck and challenge.deck.type:
            back_center = G.data.center_by_name(challenge.deck.type)
        else:
            back_center = G.P_CENTERS[G.deck_key]
        G.STATE = STATES.BLIND_SELECT
        G.STATE_COMPLETE = False
        G.SETTINGS.paused = False
        G.RESET_BLIND_STATES = True
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
        GAME.selected_back.apply_to_run()
        if challenge is not None:
            self._apply_challenge(challenge)
        sp = GAME.starting_params
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

        G.CONTROLLER.locks.load = True

        def unlock_load() -> None:
            G.CONTROLLER.locks.load = None
        G.ev(unlock_load, no_delete=True, trigger="after", blocking=False, blockable=False, delay=3.5, timer="TOTAL")

        G.consumeables = CardArea(G, "consumeables", {"card_limit": sp.consumable_slots, "type": "joker", "highlight_limit": 1})
        G.jokers = CardArea(G, "jokers", {"card_limit": sp.joker_slots, "type": "joker", "highlight_limit": 1})
        G.discard = CardArea(G, "discard", {"card_limit": 500, "type": "discard"})
        G.deck = CardArea(G, "deck", {"card_limit": 52, "type": "deck"})
        G.hand = CardArea(G, "hand", {"card_limit": sp.hand_size, "type": "hand"})
        G.play = CardArea(G, "play", {"card_limit": 5, "type": "play"})
        G.playing_cards = []
        G.hand_T_y = TILE_H - HAND_H  # set_screen_positions

        # the starting deck
        de = challenge.deck if challenge is not None and challenge.deck else None
        if de is not None and de.cards:
            protos = [T(v) for v in de.cards]
        else:
            protos = []
            keys = G.data.P_CARDS_SORTED_KEYS
            for k in G.data.P_CARDS_PAIRS_ORDER:
                if sp.erratic_suits_and_ranks:
                    k = keys[G.rng.element_index(len(keys), G.rng.pseudoseed("erratic"))]
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
                    protos.append(T(s=s, r=r, e=e, d=dd, g=g))
        if sp.extra_cards:
            for v in sp.extra_cards:
                protos.append(T(v))
        protos.sort(key=lambda p: (p.s or "") + (p.r or "") + (p.e or "") + (p.d or "") + (p.g or ""))
        for p in protos:
            G.card_from_control(p)
        GAME.starting_deck_size = len(G.playing_cards)
        G.check_and_set_high_score("most_money", GAME.dollars)

        G.delay(0.5)
        GAME.current_round.discards_left = rr.discards
        GAME.current_round.hands_left = rr.hands
        G.deck.shuffle()
        G.reset_idol_card()
        G.reset_mail_rank()
        GAME.current_round.ancient_card.suit = None
        G.reset_ancient_card()
        G.reset_castle_card()

        GAME.blind = Blind(G)
        GAME.blind.set_blind(None, None, True)
        G.reset_blinds()
        G.ev(None)  # unlock_notify
        G.settle()
        return self

    def _apply_challenge(self, ch: T) -> None:
        G = self
        GAME = G.GAME
        GAME.challenge = ch.id
        GAME.challenge_tab = ch
        from .card import apply_to_run
        if ch.jokers:
            for i, v in enumerate(ch.jokers):
                def mk(v: T = v, i: int = i) -> None:
                    j = G.add_joker(v.id, v.edition, i != 0)
                    if v.eternal:
                        j.set_eternal(True)
                    if v.pinned:
                        j.pinned = True
                G.ev(mk)
        if ch.consumeables:
            for i, v in enumerate(ch.consumeables):
                G.ev(lambda v=v, i=i: G.add_joker(v.id, None, i != 0))
        if ch.vouchers:
            for v in ch.vouchers:
                GAME.used_vouchers[v.id] = True

                def ap(v: T = v) -> None:
                    GAME.starting_voucher_count = (GAME.starting_voucher_count or 0) + 1
                    apply_to_run(G, None, G.P_CENTERS[v.id])
                G.ev(ap)
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

    # ===================================================== state functions
    def update_selecting_hand(self) -> None:
        G = self
        if not G.hand.cards and not G.deck.cards and not G.play.cards:
            G.end_round()
        if G.shop is not None:
            G.shop.remove()
            G.shop = None
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True
            if not G.hand.cards and not G.deck.cards:
                G.end_round()

    def update_shop(self) -> None:
        G = self
        GAME = G.GAME
        if not G.STATE_COMPLETE:
            G.stop_use()
            shop_exists = G.shop is not None
            if G.shop is None:
                G.shop_jokers = CardArea(G, "shop_jokers", {"card_limit": GAME.shop.joker_max, "type": "shop", "highlight_limit": 1})
                G.shop_vouchers = CardArea(G, "shop_vouchers", {"card_limit": 1, "type": "shop", "highlight_limit": 1})
                G.shop_booster = CardArea(G, "shop_booster", {"card_limit": 2, "type": "shop", "highlight_limit": 1})
                G.SHOP_SIGN = Box(G, "cm", -15)
                sign = G.SHOP_SIGN
                G.ev(lambda: setattr(sign.alignment.offset, "y", 0))
                G.shop = Box(G, "tmi", ROOM_Y + 11, moving=True)
                G.shop.areas = [G.shop_jokers, G.shop_vouchers, G.shop_booster]
            shop = G.shop

            def arrive() -> None:
                shop.alignment.offset.y = -5.3
                shop.alignment.offset.x = 0

                def fill() -> bool | None:
                    if abs(shop.T_y - shop.VT_y) < 3:
                        for t in list(GAME.tags):
                            t.apply_to_run(T(type="shop_start"))
                        if not shop_exists:
                            for _ in range(GAME.shop.joker_max - len(G.shop_jokers.cards)):
                                G.shop_jokers.emplace(G.create_card_for_shop(G.shop_jokers))
                            if GAME.current_round.voucher and GAME.current_round.voucher in G.P_CENTERS:
                                card = Card(G, G.P_CARDS.get("empty"), G.P_CENTERS[GAME.current_round.voucher],
                                            {"bypass_discovery_center": True, "bypass_discovery_ui": True})
                                card.shop_voucher = True
                                G.create_shop_card_ui(card, "Voucher", G.shop_vouchers)
                                card.start_materialize()
                                G.shop_vouchers.emplace(card)
                            for i in (1, 2):
                                cr = GAME.current_round
                                cr.used_packs = cr.used_packs or T()
                                if not cr.used_packs.get(i):
                                    cr.used_packs[i] = G.get_pack("shop_pack").key
                                if cr.used_packs[i] != "USED":
                                    card = Card(G, G.P_CARDS.get("empty"), G.P_CENTERS[cr.used_packs[i]],
                                                {"bypass_discovery_center": True, "bypass_discovery_ui": True})
                                    G.create_shop_card_ui(card, "Booster", G.shop_booster)
                                    card.ability.booster_pos = i
                                    card.start_materialize()
                                    G.shop_booster.emplace(card)
                            for t in list(GAME.tags):
                                t.apply_to_run(T(type="voucher_add"))
                            for t in list(GAME.tags):
                                t.apply_to_run(T(type="shop_final_pass"))
                        G.ev(None)  # save_run
                        return True
                    return None
                G.event(fill, trigger="after", delay=0.2, blockable=False)
            G.ev(arrive)
            G.STATE_COMPLETE = True

    def update_hand_played(self) -> None:
        G = self
        if G.shop is not None:
            G.shop.remove()
            G.shop = None
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True

            def ev() -> None:
                if G.GAME.chips - G.GAME.blind.chips >= 0 or G.GAME.current_round.hands_left < 1:
                    G.STATE = G.STATES.NEW_ROUND
                else:
                    G.STATE = G.STATES.DRAW_TO_HAND
                G.STATE_COMPLETE = False
            G.ev(ev)

    def update_draw_to_hand(self) -> None:
        G = self
        if G.shop is not None:
            G.shop.remove()
            G.shop = None
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True
            for t in list(G.GAME.tags):
                t.apply_to_run(T(type="round_start_bonus"))

            def ev() -> bool:
                if G.draw_from_deck_to_hand(None):
                    return True
                cr = G.GAME.current_round
                if cr.hands_played == 0 and cr.discards_used == 0 and G.GAME.facing_blind:
                    for j in list(G.jokers.cards):
                        j.calculate_joker(T(first_hand_drawn=True))

                def ev2() -> None:
                    G.STATE = G.STATES.SELECTING_HAND
                    G.STATE_COMPLETE = False
                    G.GAME.blind.drawn_to_hand()
                G.ev(ev2)
                return True
            G.event(ev)

    def update_new_round(self) -> None:
        G = self
        if G.shop is not None:
            G.shop.remove()
            G.shop = None
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True
            G.end_round()

    def update_blind_select(self) -> None:
        G = self
        if G.shop is not None:
            G.shop.remove()
            G.shop = None
        if not G.STATE_COMPLETE:
            G.stop_use()
            G.ev(None)  # save_run
            G.STATE_COMPLETE = True

            def outer() -> None:
                def inner() -> None:
                    G.blind_select = G.create_UIBox_blind_select()
                    for t in list(G.GAME.tags):
                        t.apply_to_run(T(type="immediate"))
                    for t in list(G.GAME.tags):
                        if t.apply_to_run(T(type="new_blind_choice")):
                            break
                G.ev(inner)
            G.ev(outer)

    def update_round_eval(self) -> None:
        G = self
        if G.shop is not None:
            G.shop.remove()
            G.shop = None
        if not G.STATE_COMPLETE:
            G.stop_use()
            G.STATE_COMPLETE = True

            def ev() -> None:
                G.GAME.facing_blind = None
                G.round_eval = Box(G, "bm", ROOM_Y + 19, moving=True)
                box = G.round_eval

                def arrive() -> bool | None:
                    if box.alignment.offset.y != -7.8:
                        box.alignment.offset.y = -7.8
                    else:
                        if abs(box.T_y - box.VT_y) < 3:
                            G.delay(0.1)
                            G.evaluate_round()
                            return True
                    return None
                G.event(arrive)
            G.ev(ev)

    def update_pack(self, draw: bool, recall_delay: bool = True) -> None:
        G = self
        if G.shop is not None:
            G.shop.alignment.offset.y = ROOM_Y + 11
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True

            def ev() -> None:
                size = G.GAME.pack_size
                G.pack_cards = CardArea(G, "pack_cards", {"card_limit": size, "type": "consumeable", "highlight_limit": 1})
                G.booster_pack = Box(G, "tmi", ROOM_Y + 9)
                G.booster_pack.areas = [G.pack_cards]
                G.booster_pack.alignment.offset.y = -2.2
                if recall_delay:
                    def inner() -> None:
                        if draw:
                            G.draw_from_deck_to_hand()
                        G.ev(None, trigger="after", delay=0.5)
                    G.ev(inner)
                else:
                    G.ev(None)
            G.ev(ev)

    def update_game_over(self) -> None:
        G = self
        if not G.STATE_COMPLETE:
            if G.GAME.round_resets.ante <= G.GAME.win_ante:
                G.inc_career_stat("c_losses", 1)
                G.set_joker_loss()
            G.SETTINGS.paused = True
            G.overlay_menu()
            G.STATE_COMPLETE = True

    # ========================================================= frame loop
    def update_state(self) -> None:
        """The state-machine part of Game:update (each check sees the state
        the previous one may have changed)."""
        G = self
        S = STATES
        if G.STATE == S.SELECTING_HAND:
            if not G.hand.cards and G.deck.cards:
                G.STATE = S.DRAW_TO_HAND
                G.STATE_COMPLETE = False
            else:
                G.update_selecting_hand()
        if G.STATE == S.SHOP:
            G.update_shop()
        if G.STATE == S.HAND_PLAYED:
            G.update_hand_played()
        if G.STATE == S.DRAW_TO_HAND:
            G.update_draw_to_hand()
        if G.STATE == S.NEW_ROUND:
            G.update_new_round()
        if G.STATE == S.BLIND_SELECT:
            G.update_blind_select()
        if G.STATE == S.ROUND_EVAL:
            G.update_round_eval()
        if G.STATE == S.TAROT_PACK:
            G.update_pack(True)
        if G.STATE == S.SPECTRAL_PACK:
            G.update_pack(True)
        if G.STATE == S.STANDARD_PACK:
            G.update_pack(False)
        if G.STATE == S.BUFFOON_PACK:
            G.update_pack(False)
        if G.STATE == S.PLANET_PACK:
            G.update_pack(False, False)
        if G.STATE == S.GAME_OVER:
            G.update_game_over()

    def _next_clock(self) -> tuple[float, float, float, float]:
        """(ACC, SPEEDFACTOR, TOTAL, REAL) after the next (unpaused) frame."""
        G = self
        S = STATES
        dt = G.dt
        acc = G.ACC if G.STATE == G.ACC_state else 0
        speed = G.SETTINGS.GAMESPEED
        if G.STATE == S.HAND_PLAYED or G.STATE == S.NEW_ROUND:
            acc = min((acc or 0) + dt * 0.2 * speed, 16)
        else:
            acc = 0
        sf = speed + max(0, abs(acc) - 2)
        return acc, sf, G.TIMERS["TOTAL"] + dt * sf, G.TIMERS["REAL"] + dt

    def _idle_thresholds(self) -> tuple[float, float, float, float] | None:
        """If the next frame can only move the clocks and the UI (the state
        machine is idle and every event the queue would handle is only waiting
        for its time), the clock values at which that stops:
        (TOTAL <, TOTAL <=, REAL <, REAL <=); otherwise None."""
        G = self
        S = STATES
        if G.SETTINGS.paused or not G.STATE_COMPLETE or not G.fast_forward:
            return None
        st = G.STATE
        if G.shop is not None and st not in (S.SHOP,) + PACK_STATES and not G.shop.removed:
            return None  # the state functions remove it
        hand = G.hand
        if hand is None:
            return None
        if st == S.SELECTING_HAND and (not hand.cards or (not G.deck.cards and not G.play.cards)):
            return None
        if G.GAME.modifiers.minus_hand_size_per_X_dollar or (not hand.highlighted and any(
                c.ability.forced_selection for c in hand.cards)):
            return None
        if G.deck.config.card_limit > len(G.playing_cards):
            return None
        inf = math.inf
        t_lt = t_le = r_lt = r_le = inf
        blocked = False
        for e in G.E_MANAGER.queue:
            if blocked and e.blockable:
                continue
            if not e.start_timer:
                return None
            trig = e.trigger
            real = e.timer != "TOTAL"
            if trig == "after" or trig == "before":
                if trig == "before" and not e.complete:
                    return None
                due = e.time + e.delay  # due once now >= due
                if real:
                    r_lt = min(r_lt, due)
                else:
                    t_lt = min(t_lt, due)
            elif trig == "ease":
                if e.ease_ref is not None or e.ease_start_time is None:
                    return None
                end = e.ease_end_time  # done once now > end
                if real:
                    r_le = min(r_le, end)
                else:
                    t_le = min(t_le, end)
            else:
                return None
            if e.blocking:
                blocked = True
        return t_lt, t_le, r_lt, r_le

    def _light_frame(self, clock: tuple[float, float, float, float]) -> None:
        """A frame in which no event fires: only the clocks and UI motion."""
        G = self
        acc, sf, total, real = clock
        G.FRAMES_MOVE += 1
        G.TIMERS["REAL"] = real
        G.real_dt = G.dt
        G.ACC = acc
        G.ACC_state = G.STATE
        G.SPEEDFACTOR = sf
        G.TIMERS["TOTAL"] = total
        em = G.E_MANAGER
        em.queue_timer = em.queue_timer + G.real_dt
        em.queue_last_processed = em.queue_last_processed + em.queue_dt
        move_hand(G)
        for box in (G.shop, G.round_eval):
            if box is not None and not box.removed:
                box.move()

    def frame(self) -> None:
        """One Game:update(dt)."""
        G = self
        if G.fast_forward:
            th = G._idle
            if th is None:
                th = G._idle = G._idle_thresholds()
            if th is not None:
                clock = G._next_clock()
                if clock[2] < th[0] and clock[2] <= th[1] and clock[3] < th[2] and clock[3] <= th[3]:
                    G._light_frame(clock)
                    return
            G._idle = None
        S = STATES
        dt = G.dt
        G.FRAMES_MOVE += 1
        G.TIMERS["REAL"] = G.TIMERS["REAL"] + dt
        G.real_dt = dt
        paused = G.SETTINGS.paused
        if paused:
            dt = 0
        if G.STATE != G.ACC_state:
            G.ACC = 0
        G.ACC_state = G.STATE
        speed = G.SETTINGS.GAMESPEED
        if G.STATE == S.HAND_PLAYED or G.STATE == S.NEW_ROUND:
            G.ACC = min((G.ACC or 0) + dt * 0.2 * speed, 16)
        else:
            G.ACC = 0
        G.SPEEDFACTOR = speed if (G.STAGE_RUN and not paused) else 1
        G.SPEEDFACTOR = G.SPEEDFACTOR + max(0, abs(G.ACC) - 2)
        G.TIMERS["TOTAL"] = G.TIMERS["TOTAL"] + dt * G.SPEEDFACTOR
        G.E_MANAGER.update(G.real_dt)
        G.update_state()
        # moveables: the hand slides, UI boxes chase their targets
        G.exp_xy = math.exp(-50 * G.real_dt)
        G.move_dt = min(1 / 20, G.real_dt)
        G.max_vel = 70 * G.move_dt
        if G.hand is not None:
            move_hand(G)
            for area in (G.jokers, G.deck, G.discard):
                area.align_cards()
        if not G.SETTINGS.paused:
            for box in (G.shop, G.round_eval):
                if box is not None and not box.removed:
                    box.move()
        # moveables: per-frame updates
        for area in (G.hand, G.deck):
            if area is not None:
                area.update()
        for c in list(G.I_CARD):
            ab = c.ability
            if ab.get("perma_debuff"):
                c.debuff = True
            if ab["name"] in UPDATE_NAMES:
                c.update()
        G.CONTROLLER.update()

    def settled(self) -> bool:
        return not self.CONTROLLER.locked and not self.E_MANAGER.busy() and self.STATE_COMPLETE

    def settle(self, max_frames: int = 100000) -> int:
        """Run frames until the game waits for the player (the same rule as
        the oracle: 4 consecutive quiet frames).  Returns the frame count."""
        G = self
        G._idle = None  # the player may have changed anything
        quiet = 0
        for n in range(1, max_frames + 1):
            # winning opens a pausing overlay: press 'Endless' like a player would
            if G.SETTINGS.paused and G.OVERLAY_MENU and G.GAME.won and G.STATE != STATES.GAME_OVER:
                G.exit_overlay_menu()
            G.frame()
            if G.STATE == STATES.GAME_OVER and G.STATE_COMPLETE:
                return n  # the run is over (the game is paused for good)
            if G.settled():
                quiet += 1
                if quiet >= 4:
                    return n
            else:
                quiet = 0
        raise RuntimeError("the game never settled")
