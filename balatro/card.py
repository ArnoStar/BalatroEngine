"""Port of card.lua.

Everything that changes the game state is ported, including the timed
events the game uses for its animations (they decide *when* things happen):
editions/seals popping, cards dissolving or shattering (the card is removed
when the animation ends), cards materializing, booster packs opening.
Drawing, sprites, sounds and the hover UI are left out.

``calculate_joker`` lives in jokers.py, ``use_consumeable`` and
``can_use_consumeable`` in consumables.py.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .lua import T, copy_table, lor
from .rng import lua_tostring

if TYPE_CHECKING:
    from .cardarea import CardArea
    from .game import Game

RANKS = {
    "2": (2, 0.0, 2), "3": (3, 0.0, 3), "4": (4, 0.0, 4), "5": (5, 0.0, 5), "6": (6, 0.0, 6),
    "7": (7, 0.0, 7), "8": (8, 0.0, 8), "9": (9, 0.0, 9), "10": (10, 0.0, 10),
    "Jack": (10, 0.1, 11), "Queen": (10, 0.2, 12), "King": (10, 0.3, 13), "Ace": (11, 0.4, 14),
}
SUITS = {"Diamonds": (0.01, 0.001), "Clubs": (0.02, 0.002), "Hearts": (0.03, 0.003), "Spades": (0.04, 0.004)}
VALUE_TO_CHAR = {"Ace": "A", "King": "K", "Queen": "Q", "Jack": "J", "10": "T"}
ID_TO_CHAR = {10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}
SUIT_CODE = {"Diamonds": "D_", "Spades": "S_", "Clubs": "C_", "Hearts": "H_"}


class Card:
    """A card object: playing card, joker, consumable, voucher or booster pack."""

    def __init__(self, G: "Game", card: T | None, center: T, params: dict | None = None) -> None:
        self.G = G
        self.params = params if isinstance(params, dict) else {}
        G.node_id += 1
        self.ID = G.node_id
        self.config: T = T(card=card if card is not None else T(), center=center)
        self.playing_card: int | None = self.params.get("playing_card")
        G.sort_id += 1
        self.sort_id: int = G.sort_id
        self.back = "viewed_back" if self.params.get("viewed_back") else "selected_back"
        self.bypass_discovery_center = self.params.get("bypass_discovery_center")
        self.base_cost: float = 0
        self.extra_cost: float = 0
        self.cost: float = 0
        self.sell_cost: float = 0
        self.unique_val = 1 - self.ID / 1603301
        self.edition: T | None = None
        self.seal: str | None = None
        self.ability: T = None  # type: ignore[assignment]
        self.base: T = None  # type: ignore[assignment]
        self.area: "CardArea | None" = None
        self.removed = False
        self.REMOVED = False
        # transient flags used by the game code
        self.getting_sliced: bool | None = None
        self.shattered: bool | None = None
        self.destroyed: bool | None = None
        self.lucky_trigger: bool | None = None
        self.vampired: bool | None = None
        self.opening: bool | None = None
        self.from_tag: bool | None = None
        self.shop_voucher: bool | None = None
        self.temp_edition: bool | None = None
        self.pinned: bool | None = None
        self.dissolve: float | None = None
        self.eligible_strength_jokers: list[Card] = []
        self.eligible_editionless_jokers: list[Card] = []
        self.set_ability(center, True)
        self.set_base(card, True)
        self.facing: str = "front"
        self.highlighted: bool = False
        self.debuff: bool = False
        self.added_to_deck: bool | None = None
        self.set_cost()
        G.I_CARD.append(self)

    # ------------------------------------------------------------- display
    def __repr__(self) -> str:
        return f"<Card {self.label()}#{self.sort_id}>"

    def label(self) -> str:
        if self.ability.set in ("Default", "Enhanced"):
            s = card_label(self)
        else:
            s = self.config.center.key or "?"
        if self.edition:
            s += f"[{self.edition.type}]"
        return s

    @property
    def key(self) -> str:
        return self.config.center.key

    # ------------------------------------------------------------- set_base
    def set_base(self, card: T | None, initial: bool = False) -> None:
        G = self.G
        card = card if card is not None else T()
        self.config.card = card
        self.config.card_key = G.P_CARD_KEY.get(id(card))
        snno = None
        if self.base is not None and self.base.suit_nominal_original:
            snno = self.base.suit_nominal_original
        self.base = T(name=card.name, suit=card.suit, value=card.value, nominal=0, suit_nominal=0, face_nominal=0,
                      times_played=0)
        r = RANKS.get(card.value)
        if r is not None:
            self.base.nominal, self.base.face_nominal, self.base.id = r
        if initial:
            self.base.original_value = self.base.value
        s = SUITS.get(card.suit)
        if s is not None:
            self.base.suit_nominal = s[0]
            self.base.suit_nominal_original = snno or s[1]
        if not initial:
            G.GAME.blind.debuff_card(self)

    # ---------------------------------------------------------- set_ability
    def set_ability(self, center: T, initial: bool = False, delay_sprites: bool = False) -> None:
        G = self.G
        self.config.center = center
        self.config.center_key = center.key
        if delay_sprites:
            G.ev(lambda: None)
        cfg = center.config
        old = self.ability
        self.ability = T(
            name=center.name, effect=center.effect, set=center.set,
            mult=cfg.mult or 0, h_mult=cfg.h_mult or 0, h_x_mult=cfg.h_x_mult or 0, h_dollars=cfg.h_dollars or 0,
            p_dollars=cfg.p_dollars or 0, t_mult=cfg.t_mult or 0, t_chips=cfg.t_chips or 0,
            x_mult=lor(cfg.Xmult, 1), h_size=cfg.h_size or 0, d_size=cfg.d_size or 0,
            extra=copy_table(cfg.extra), extra_value=0, type=cfg.type or "", order=center.order,
            forced_selection=old.forced_selection if old is not None else None,
            perma_bonus=(old.perma_bonus or 0) if old is not None else 0,
        )
        # (self.ability.bonus is read from the new table, so it starts at 0)
        self.ability.bonus = cfg.bonus or 0
        if center.consumeable:
            self.ability.consumeable = cfg  # a reference, as in the game
        ab = self.ability
        name = ab.name
        if name == "Invisible Joker":
            ab.invis_rounds = 0
        if name == "To Do List":
            hands = [k for k in G.hands_order() if G.GAME.hands[k].visible]
            old_hand = ab.to_do_poker_hand
            ab.to_do_poker_hand = None
            title = self.area is not None and self.area.config.type == "title"
            while ab.to_do_poker_hand is None:
                ab.to_do_poker_hand = G.rng.element(hands, G.rng.pseudoseed("false_to_do" if title else "to_do"))
                if ab.to_do_poker_hand == old_hand:
                    ab.to_do_poker_hand = None
        if name == "Caino":
            ab.caino_xmult = 1
        if name == "Yorick":
            ab.yorick_discards = ab.extra.discards
        if name == "Loyalty Card":
            ab.burnt_hand = 0
            ab.loyalty_remaining = ab.extra.every
        self.base_cost = lor(center.cost, 1)
        ab.hands_played_at_create = G.GAME.hands_played if G.GAME else 0
        if not G.OVERLAY_MENU:
            for k in G.data.by_name.get(name, ()):
                G.GAME.used_jokers[k] = True
        if not initial:
            G.GAME.blind.debuff_card(self)

    # ------------------------------------------------------------- set_cost
    def set_cost(self) -> None:
        G = self.G
        GAME = G.GAME
        self.extra_cost = 0 + GAME.inflation
        e = self.edition
        if e:
            self.extra_cost = self.extra_cost + (3 if e.holo else 0) + (2 if e.foil else 0) + (
                5 if e.polychrome else 0) + (5 if e.negative else 0)
        self.cost = max(1, math.floor((self.base_cost + self.extra_cost + 0.5) * (100 - GAME.discount_percent) / 100))
        ab = self.ability
        if ab.set == "Booster" and GAME.modifiers.booster_ante_scaling:
            self.cost = self.cost + GAME.round_resets.ante - 1
        if (ab.set == "Planet" or (ab.set == "Booster" and "Celestial" in ab.name)) and G.find_joker("Astronomer"):
            self.cost = 0
        if ab.rental:
            self.cost = 1
        self.sell_cost = max(1, math.floor(self.cost / 2)) + (ab.extra_value or 0)
        if self.area is not None and ab.couponed and (self.area is G.shop_jokers or self.area is G.shop_booster):
            self.cost = 0

    # ---------------------------------------------------------- set_edition
    def set_edition(self, edition: Any, immediate: Any = None, silent: Any = None) -> None:
        G = self.G
        self.edition = None
        if not edition:
            return
        P = G.P_CENTERS
        if edition.get("holo"):
            self.edition = T(mult=P["e_holo"].config.extra, holo=True, type="holo")
        elif edition.get("foil"):
            self.edition = T(chips=P["e_foil"].config.extra, foil=True, type="foil")
        elif edition.get("polychrome"):
            self.edition = T(x_mult=P["e_polychrome"].config.extra, polychrome=True, type="polychrome")
        elif edition.get("negative"):
            # self.edition was just cleared, so an added card always gains a slot
            if self.added_to_deck:
                if self.ability.consumeable:
                    G.consumeables.config.card_limit += 1
                else:
                    G.jokers.config.card_limit += 1
            self.edition = T(negative=True, type="negative")
        if self.edition and not silent:
            G.CONTROLLER.locks.edition = True
            G.ev(None, trigger="after", delay=0.2 if not immediate else 0, blockable=not immediate)

            def unlock() -> None:
                G.CONTROLLER.locks.edition = False
            G.ev(unlock, trigger="after", delay=0.1)
        self.set_cost()

    # ------------------------------------------------------------- set_seal
    def set_seal(self, seal: str | None, silent: Any = None, immediate: Any = None) -> None:
        G = self.G
        self.seal = None
        if seal:
            self.seal = seal
            if not silent:
                G.CONTROLLER.locks.seal = True
                if immediate:
                    G.CONTROLLER.locks.seal = False
                else:
                    G.ev(None, trigger="after", delay=0.3)

                    def unlock() -> None:
                        G.CONTROLLER.locks.seal = False
                    G.ev(unlock, trigger="after", delay=0.15)
        self.set_cost()

    def get_seal(self, bypass_debuff: bool = False) -> str | None:
        if self.debuff and not bypass_debuff:
            return None
        return self.seal

    def set_eternal(self, eternal: Any) -> None:
        self.ability.eternal = None
        if self.config.center.eternal_compat and not self.ability.perishable:
            self.ability.eternal = eternal

    def set_perishable(self, perishable: Any) -> None:
        self.ability.perishable = None
        if self.config.center.perishable_compat and not self.ability.eternal:
            self.ability.perishable = True
            self.ability.perish_tally = self.G.GAME.perishable_rounds

    def set_rental(self, rental: Any) -> None:
        self.ability.rental = rental
        self.set_cost()

    def set_debuff(self, should_debuff: Any = None) -> None:
        G = self.G
        if self.ability.perishable and self.ability.perish_tally <= 0:
            if not self.debuff:
                self.debuff = True
                if self.area is G.jokers:
                    self.remove_from_deck(True)
            return
        if should_debuff != self.debuff:
            if self.area is G.jokers:
                if should_debuff:
                    self.remove_from_deck(True)
                else:
                    self.add_to_deck(True)
            self.debuff = should_debuff

    def change_suit(self, new_suit: str) -> None:
        G = self.G
        val = VALUE_TO_CHAR.get(self.base.value, self.base.value)
        self.set_base(G.P_CARDS[SUIT_CODE[new_suit] + val])
        G.GAME.blind.debuff_card(self)

    # ---------------------------------------------------------- deck in/out
    def add_to_deck(self, from_debuff: bool = False) -> None:
        G = self.G
        if self.added_to_deck:
            return
        self.added_to_deck = True
        ab = self.ability
        if ab.set in ("Enhanced", "Default"):
            return
        name = ab.name
        GAME = G.GAME
        if ab.h_size != 0:
            G.hand.change_size(ab.h_size)
        if ab.d_size > 0:
            GAME.round_resets.discards = GAME.round_resets.discards + ab.d_size
            G.ease_discard(ab.d_size)
        if name == "Credit Card":
            GAME.bankrupt_at = GAME.bankrupt_at - ab.extra
        if name == "Chicot" and GAME.blind and GAME.blind.boss and not GAME.blind.disabled:
            GAME.blind.disable()
            G.card_eval_status_text(self, "extra", None, None, None, T(message="boss_disabled"))
        if name == "Chaos the Clown":
            GAME.current_round.free_rerolls = GAME.current_round.free_rerolls + 1
            G.calculate_reroll_cost(True)
        if name == "Turtle Bean":
            G.hand.change_size(ab.extra.h_size)
        if name == "Oops! All 6s":
            for k in list(GAME.probabilities):
                GAME.probabilities[k] = GAME.probabilities[k] * 2
        if name == "To the Moon":
            GAME.interest_amount = GAME.interest_amount + ab.extra
        if name == "Astronomer":
            G.ev(G.refresh_all_costs)
        if name == "Troubadour":
            G.hand.change_size(ab.extra.h_size)
            GAME.round_resets.hands = GAME.round_resets.hands + ab.extra.h_plays
        if name == "Stuntman":
            G.hand.change_size(-ab.extra.h_size)
        if self.edition and self.edition.negative:
            if from_debuff:
                ab.queue_negative_removal = None
            else:
                if ab.consumeable:
                    G.consumeables.config.card_limit += 1
                else:
                    G.jokers.config.card_limit += 1
        if GAME.blind:
            G.ev(lambda: GAME.blind.set_blind(None, True, None))

    def remove_from_deck(self, from_debuff: bool = False) -> None:
        G = self.G
        if not self.added_to_deck:
            return
        self.added_to_deck = False
        ab = self.ability
        name = ab.name
        GAME = G.GAME
        if ab.h_size != 0:
            G.hand.change_size(-ab.h_size)
        if ab.d_size > 0:
            GAME.round_resets.discards = GAME.round_resets.discards - ab.d_size
            G.ease_discard(-ab.d_size)
        if name == "Credit Card":
            GAME.bankrupt_at = GAME.bankrupt_at + ab.extra
        if name == "Chaos the Clown":
            GAME.current_round.free_rerolls = GAME.current_round.free_rerolls - 1
            G.calculate_reroll_cost(True)
        if name == "Turtle Bean":
            G.hand.change_size(-ab.extra.h_size)
        if name == "Oops! All 6s":
            for k in list(GAME.probabilities):
                GAME.probabilities[k] = GAME.probabilities[k] / 2
        if name == "To the Moon":
            GAME.interest_amount = GAME.interest_amount - ab.extra
        if name == "Astronomer":
            G.ev(G.refresh_all_costs)
        if name == "Troubadour":
            G.hand.change_size(-ab.extra.h_size)
            GAME.round_resets.hands = GAME.round_resets.hands - ab.extra.h_plays
        if name == "Stuntman":
            G.hand.change_size(ab.extra.h_size)
        if self.edition and self.edition.negative and G.jokers is not None:
            if from_debuff:
                ab.queue_negative_removal = True
            else:
                if ab.consumeable:
                    G.consumeables.config.card_limit -= 1
                else:
                    G.jokers.config.card_limit -= 1
        if GAME.blind:
            G.ev(lambda: GAME.blind.set_blind(None, True, None))

    # --------------------------------------------------------------- getters
    def get_nominal(self, mod: str | None = None) -> float:
        mult = 1
        if mod == "suit":
            mult = 1000
        if self.ability.effect == "Stone Card":
            mult = -1000
        b = self.base
        return (b.nominal + b.suit_nominal * mult + (b.suit_nominal_original or 0) * 0.0001 * mult
                + b.face_nominal + 0.000001 * self.unique_val)

    def get_id(self) -> int:
        if self.ability.effect == "Stone Card" and not self.vampired:
            # -math.random(100, 1000000) on LuaJIT's global state: only its
            # uniqueness matters (stone cards never pair up)
            self.G.stone_id -= 1
            return self.G.stone_id
        return self.base.id

    def is_face(self, from_boss: Any = None) -> bool | None:
        if self.debuff and not from_boss:
            return None
        i = self.get_id()
        if i == 11 or i == 12 or i == 13 or self.G.find_joker("Pareidolia"):
            return True
        return None

    def get_original_rank(self) -> str:
        return self.base.original_value

    def get_chip_bonus(self) -> float:
        if self.debuff:
            return 0
        if self.ability.effect == "Stone Card":
            return self.ability.bonus + (self.ability.perma_bonus or 0)
        return self.base.nominal + self.ability.bonus + (self.ability.perma_bonus or 0)

    def get_chip_mult(self) -> float:
        G = self.G
        if self.debuff:
            return 0
        if self.ability.set == "Joker":
            return 0
        if self.ability.effect == "Lucky Card":
            if G.rng.random("lucky_mult") < G.GAME.probabilities.normal / 5:
                self.lucky_trigger = True
                return self.ability.mult
            return 0
        return self.ability.mult

    def get_chip_x_mult(self, context: Any = None) -> float:
        if self.debuff:
            return 0
        if self.ability.set == "Joker":
            return 0
        if self.ability.x_mult <= 1:
            return 0
        return self.ability.x_mult

    def get_chip_h_mult(self) -> float:
        if self.debuff:
            return 0
        return self.ability.h_mult

    def get_chip_h_x_mult(self) -> float:
        if self.debuff:
            return 0
        return self.ability.h_x_mult

    def get_edition(self, context: Any = None) -> T | None:
        if self.debuff:
            return None
        if self.edition:
            ret = T(card=self)
            if self.edition.x_mult:
                ret.x_mult_mod = self.edition.x_mult
            if self.edition.mult:
                ret.mult_mod = self.edition.mult
            if self.edition.chips:
                ret.chip_mod = self.edition.chips
            return ret
        return None

    def get_end_of_round_effect(self, context: Any = None) -> T:
        G = self.G
        if self.debuff:
            return T()
        ret = T()
        if self.ability.h_dollars > 0:
            ret.h_dollars = self.ability.h_dollars
            ret.card = self
        if self.seal == "Blue" and len(G.consumeables.cards) + G.GAME.consumeable_buffer < G.consumeables.config.card_limit:
            G.GAME.consumeable_buffer = G.GAME.consumeable_buffer + 1

            def planet() -> None:
                if G.GAME.last_hand_played:
                    _planet = 0
                    for v in G.P_CENTER_POOLS["Planet"]:
                        if v.config.hand_type == G.GAME.last_hand_played:
                            _planet = v.key
                    card = G.create_card("Planet", G.consumeables, None, None, None, None, _planet, "blusl")
                    card.add_to_deck()
                    G.consumeables.emplace(card)
                    G.GAME.consumeable_buffer = 0
            G.ev(planet, trigger="before", delay=0.0)
            G.card_eval_status_text(self, "extra", None, None, None, T(message="plus_planet"))
            ret.effect = True
        return ret

    def get_p_dollars(self) -> float:
        G = self.G
        if self.debuff:
            return 0
        ret = 0
        if self.seal == "Gold":
            ret = ret + 3
        if self.ability.p_dollars > 0:
            if self.ability.effect == "Lucky Card":
                if G.rng.random("lucky_money") < G.GAME.probabilities.normal / 15:
                    self.lucky_trigger = True
                    ret = ret + self.ability.p_dollars
            else:
                ret = ret + self.ability.p_dollars
        if ret > 0:
            G.GAME.dollar_buffer = (G.GAME.dollar_buffer or 0) + ret

            def clear() -> None:
                G.GAME.dollar_buffer = 0
            G.ev(clear)
        return ret

    def is_suit(self, suit: str, bypass_debuff: Any = None, flush_calc: Any = None) -> bool | None:
        G = self.G
        if flush_calc:
            if self.ability.effect == "Stone Card":
                return False
            if self.ability.name == "Wild Card" and not self.debuff:
                return True
            if G.find_joker("Smeared Joker") and (self.base.suit in ("Hearts", "Diamonds")) == (suit in ("Hearts", "Diamonds")):
                return True
            return self.base.suit == suit
        if self.debuff and not bypass_debuff:
            return None
        if self.ability.effect == "Stone Card":
            return False
        if self.ability.name == "Wild Card":
            return True
        if G.find_joker("Smeared Joker") and (self.base.suit in ("Hearts", "Diamonds")) == (suit in ("Hearts", "Diamonds")):
            return True
        return self.base.suit == suit

    # ------------------------------------------------------------ seals etc
    def calculate_seal(self, context: T) -> T | None:
        G = self.G
        if self.debuff:
            return None
        if context.repetition:
            if self.seal == "Red":
                return T(message="again", repetitions=1, card=self)
        if context.discard:
            if self.seal == "Purple" and len(G.consumeables.cards) + G.GAME.consumeable_buffer < G.consumeables.config.card_limit:
                G.GAME.consumeable_buffer = G.GAME.consumeable_buffer + 1

                def tarot() -> None:
                    card = G.create_card("Tarot", G.consumeables, None, None, None, None, None, "8ba")
                    card.add_to_deck()
                    G.consumeables.emplace(card)
                    G.GAME.consumeable_buffer = 0
                G.ev(tarot, trigger="before", delay=0.0)
                G.card_eval_status_text(self, "extra", None, None, None, T(message="plus_tarot"))
        return None

    def calculate_rental(self) -> None:
        G = self.G
        if self.ability.rental:
            G.ease_dollars(-G.GAME.rental_rate)
            G.card_eval_status_text(self, "dollars", -G.GAME.rental_rate)

    def calculate_perishable(self) -> None:
        G = self.G
        ab = self.ability
        if ab.perishable and ab.perish_tally > 0:
            if ab.perish_tally == 1:
                ab.perish_tally = 0
                G.card_eval_status_text(self, "extra", None, None, None, T(message="disabled", delay=0.45))
                self.set_debuff()
            else:
                ab.perish_tally = ab.perish_tally - 1
                G.card_eval_status_text(self, "extra", None, None, None, T(message="remaining", delay=0.45))

    def calculate_dollar_bonus(self) -> float | None:
        G = self.G
        if self.debuff:
            return None
        ab = self.ability
        if ab.set == "Joker":
            name = ab.name
            if name == "Golden Joker":
                return ab.extra
            if name == "Cloud 9" and ab.nine_tally and ab.nine_tally > 0:
                return ab.extra * ab.nine_tally
            if name == "Rocket":
                return ab.extra.dollars
            if name == "Satellite":
                planets_used = sum(1 for v in G.GAME.consumeable_usage.values() if v.set == "Planet")
                if planets_used == 0:
                    return None
                return ab.extra * planets_used
            if name == "Delayed Gratification" and G.GAME.current_round.discards_used == 0 and G.GAME.current_round.discards_left > 0:
                return G.GAME.current_round.discards_left * ab.extra
        return None

    def calculate_joker(self, context: T) -> Any:
        from .jokers import calculate_joker
        return calculate_joker(self, context)

    # ------------------------------------------------------------ consumables
    def use_consumeable(self, area: Any, copier: "Card | None" = None) -> None:
        from .consumables import use_consumeable
        use_consumeable(self, area, copier)

    def can_use_consumeable(self, any_state: Any = None, skip_check: Any = None) -> bool:
        from .consumables import can_use_consumeable
        return can_use_consumeable(self, any_state, skip_check)

    def check_use(self) -> bool | None:
        G = self.G
        if self.ability.name == "Ankh":
            if len(G.jokers.cards) >= G.jokers.config.card_limit:
                G.alert_no_space(self, G.jokers)
                return True
        return None

    def sell_card(self) -> None:
        G = self.G
        G.CONTROLLER.locks.selling_card = True
        G.stop_use()
        self.calculate_joker(T(selling_self=True))
        G.ev(None, trigger="after", delay=0.2)
        G.delay(0.2)

        def sell() -> None:
            G.ease_dollars(self.sell_cost)
            self.start_dissolve()
            G.delay(0.3)
            G.inc_career_stat("c_cards_sold", 1)
            if self.ability.set == "Joker":
                G.inc_career_stat("c_jokers_sold", 1)
            if self.ability.set == "Joker" and G.GAME.blind and G.GAME.blind.name == "Verdant Leaf":
                G.ev(G.GAME.blind.disable)

            def release() -> bool:
                def r2() -> bool:
                    def r3() -> None:
                        G.CONTROLLER.locks.selling_card = None
                    G.ev(r3)
                    return True
                G.event(r2)
                return True
            G.event(release, trigger="after", delay=0.3, blocking=False)
        G.ev(sell)

    def can_sell_card(self, context: Any = None) -> bool:
        G = self.G
        if (G.play is not None and G.play.cards) or G.CONTROLLER.locked or (G.GAME.STOP_USE and G.GAME.STOP_USE > 0):
            return False
        if self.area is not None and self.area.config.type == "joker" and not self.ability.eternal:
            return True
        return False

    # ------------------------------------------------------------ boosters
    def open(self) -> None:
        G = self.G
        if self.ability.set != "Booster":
            return
        GAME = G.GAME
        S = G.STATES
        G.stop_use()
        G.STATE_COMPLETE = False
        self.opening = True
        name = self.ability.name
        if "Arcana" in name:
            G.STATE = S.TAROT_PACK
        elif "Celestial" in name:
            G.STATE = S.PLANET_PACK
        elif "Spectral" in name:
            G.STATE = S.SPECTRAL_PACK
        elif "Standard" in name:
            G.STATE = S.STANDARD_PACK
        elif "Buffoon" in name:
            G.STATE = S.BUFFOON_PACK
        GAME.pack_size = self.ability.extra
        GAME.pack_choices = self.config.center.config.choose or 1
        if self.cost > 0:
            G.ev(lambda: G.inc_career_stat("c_shop_dollars_spent", self.cost), trigger="after", delay=0.2)
            G.ease_dollars(-self.cost)
        else:
            G.delay(0.2)

        def opening() -> None:
            self.explode()
            pack_cards: list[Card] = []
            speed = G.SETTINGS.GAMESPEED

            def fill() -> None:
                ante = lua_tostring(GAME.round_resets.ante)
                for i in range(1, self.ability.extra + 1):
                    card = None
                    if "Arcana" in name:
                        if GAME.used_vouchers.v_omen_globe and G.rng.random("omen_globe") > 0.8:
                            card = G.create_card("Spectral", G.pack_cards, None, None, True, True, None, "ar2")
                        else:
                            card = G.create_card("Tarot", G.pack_cards, None, None, True, True, None, "ar1")
                    elif "Celestial" in name:
                        if GAME.used_vouchers.v_telescope and i == 1:
                            _planet, _hand, _tally = None, None, 0
                            for v in G.handlist:
                                if GAME.hands[v].visible and GAME.hands[v].played > _tally:
                                    _hand = v
                                    _tally = GAME.hands[v].played
                            if _hand:
                                for v in G.P_CENTER_POOLS["Planet"]:
                                    if v.config.hand_type == _hand:
                                        _planet = v.key
                            card = G.create_card("Planet", G.pack_cards, None, None, True, True, _planet, "pl1")
                        else:
                            card = G.create_card("Planet", G.pack_cards, None, None, True, True, None, "pl1")
                    elif "Spectral" in name:
                        card = G.create_card("Spectral", G.pack_cards, None, None, True, True, None, "spe")
                    elif "Standard" in name:
                        typ = "Enhanced" if G.rng.random(G.rng.pseudoseed("stdset" + ante)) > 0.6 else "Base"
                        card = G.create_card(typ, G.pack_cards, None, None, None, True, None, "sta")
                        edition = G.poll_edition("standard_edition" + ante, 2, True)
                        card.set_edition(edition)
                        seal_poll = G.rng.random(G.rng.pseudoseed("stdseal" + ante))
                        if seal_poll > 1 - 0.02 * 10:
                            seal_type = G.rng.random(G.rng.pseudoseed("stdsealtype" + ante))
                            if seal_type > 0.75:
                                card.set_seal("Red")
                            elif seal_type > 0.5:
                                card.set_seal("Blue")
                            elif seal_type > 0.25:
                                card.set_seal("Gold")
                            else:
                                card.set_seal("Purple")
                    elif "Buffoon" in name:
                        card = G.create_card("Joker", G.pack_cards, None, None, True, True, None, "buf")
                    card.start_materialize(None, None, 1.5 * speed)
                    pack_cards.append(card)
            G.ev(fill, trigger="after", delay=1.3 * math.sqrt(speed), blockable=False, blocking=False)

            def emplace() -> bool | None:
                # waits for G.pack_cards.VT.y < G.ROOM.T.h: the booster UI has
                # long arrived by now (it takes ~7 frames, this fires 1.3s in)
                if G.pack_cards is not None and not G.pack_cards.removed:
                    for v in pack_cards:
                        G.pack_cards.emplace(v)
                    return True
                return None
            G.event(emplace, trigger="after", delay=1.3 * math.sqrt(speed), blockable=False, blocking=False)
            for j in list(G.jokers.cards):
                j.calculate_joker(T(open_booster=True, card=self))
            if GAME.modifiers.inflation:
                GAME.inflation = GAME.inflation + 1
                G.ev(G.refresh_all_costs)
        G.ev(opening, trigger="after", delay=0.4)

    # ------------------------------------------------------------ vouchers
    def redeem(self) -> None:
        G = self.G
        if self.ability.set != "Voucher":
            return
        GAME = G.GAME
        G.stop_use()
        if self.shop_voucher:
            GAME.current_round.voucher = None
        GAME.used_vouchers[self.config.center_key] = True
        G.ev(None, trigger="after", delay=0.4)
        G.ease_dollars(-self.cost)
        G.inc_career_stat("c_shop_dollars_spent", self.cost)
        G.inc_career_stat("c_vouchers_bought", 1)
        G.set_voucher_usage(self)
        GAME.current_round.voucher = None
        self.apply_to_run()
        G.delay(0.6)
        for j in list(G.jokers.cards):
            j.calculate_joker(T(buying_card=True, card=self))
        if GAME.modifiers.inflation:
            GAME.inflation = GAME.inflation + 1
            G.ev(G.refresh_all_costs)
        G.ev(None, trigger="after", delay=2.6)
        G.ev(None, trigger="after", delay=0.5)

    def apply_to_run(self, center: T | None = None) -> None:
        apply_to_run(self.G, self, center)

    # ------------------------------------------------------------ animations
    def explode(self, dissolve_colours: Any = None, explode_time_fac: float | None = None) -> None:
        G = self.G
        explode_time = 1.3 * (explode_time_fac or 1) * math.sqrt(G.SETTINGS.GAMESPEED)
        self.dissolve = 0
        start_time = G.TIMERS["TOTAL"]

        def juice() -> bool | None:
            if G.TIMERS["TOTAL"] - start_time > 1.5 * explode_time:
                return True
            return None
        G.event(juice, blockable=False)
        G.event(None, trigger="ease", blockable=False, delay=0.9 * explode_time)

        def burst() -> bool:
            G.event(None, trigger="ease", blockable=False, delay=0.1 * explode_time)
            return True
        G.event(burst, trigger="after", blockable=False, delay=0.9 * explode_time)
        G.event(None, trigger="after", blockable=False, delay=1.4 * explode_time)  # (only queues a visual ease)
        G.event(self.remove_true, trigger="after", blockable=False, delay=1.5 * explode_time)

    def remove_true(self) -> bool:
        self.remove()
        return True

    def shatter(self) -> None:
        G = self.G
        dissolve_time = 0.7
        self.shattered = True
        self.dissolve = 0
        G.event(None, trigger="after", blockable=False, delay=0.5 * dissolve_time)
        G.event(None, blockable=False)
        G.event(None, trigger="ease", blockable=False, delay=0.5 * dissolve_time)
        G.event(self.remove_true, trigger="after", blockable=False, delay=0.55 * dissolve_time)
        G.event(None, trigger="after", blockable=False, delay=0.51 * dissolve_time)

    def start_dissolve(self, dissolve_colours: Any = None, silent: Any = None, dissolve_time_fac: float | None = None,
                       no_juice: Any = None) -> None:
        G = self.G
        dissolve_time = 0.7 * (dissolve_time_fac or 1)
        self.dissolve = 0
        G.event(None, trigger="after", blockable=False, delay=0.7 * dissolve_time)
        if not silent:
            G.event(None, blockable=False)
        G.event(None, trigger="ease", blockable=False, delay=1 * dissolve_time)
        G.event(self.remove_true, trigger="after", blockable=False, delay=1.05 * dissolve_time)
        G.event(None, trigger="after", blockable=False, delay=1.051 * dissolve_time)

    def start_materialize(self, dissolve_colours: Any = None, silent: Any = None, timefac: float | None = None) -> None:
        G = self.G
        dissolve_time = 0.6 * (timefac or 1)
        self.dissolve = 1
        if not silent:
            now = G.TIMERS["REAL"]
            if G.last_materialized is None or G.last_materialized + 0.01 < now or G.last_materialized > now:
                G.last_materialized = now
                G.event(None, blockable=False)
        G.event(None, trigger="after", blockable=False, delay=0.5 * dissolve_time)
        G.event(None, trigger="ease", blockable=False, delay=1 * dissolve_time)
        G.event(None, trigger="after", blockable=False, delay=1.05 * dissolve_time)

    # ----------------------------------------------------------- per frame
    def update(self) -> None:
        """The game-logic part of Card:update (runs for every card, every frame)."""
        G = self.G
        ab = self.ability
        cons = ab.consumeable
        if cons and cons.max_highlighted:
            cons.mod_num = min(5, cons.max_highlighted)
        if ab.perma_debuff:
            self.debuff = True
        name = ab.name
        if name not in _UPDATE_NAMES:
            return
        if name == "Temperance":
            money = 0
            for c in G.jokers.cards:
                if c.ability.set == "Joker":
                    money = money + c.sell_cost
            ab.money = min(money, ab.extra)
        elif name == "Throwback":
            ab.x_mult = 1 + G.GAME.skips * ab.extra
        elif name == "Driver's License":
            base = G.P_CENTERS["c_base"]
            ab.driver_tally = sum(1 for v in G.playing_cards if v.config.center is not base)
        elif name == "Steel Joker":
            steel = G.P_CENTERS["m_steel"]
            ab.steel_tally = sum(1 for v in G.playing_cards if v.config.center is steel)
        elif name == "Cloud 9":
            ab.nine_tally = sum(1 for v in G.playing_cards if v.get_id() == 9)
        elif name == "Stone Joker":
            stone = G.P_CENTERS["m_stone"]
            ab.stone_tally = sum(1 for v in G.playing_cards if v.config.center is stone)
        elif name == "Joker Stencil":
            x = G.jokers.config.card_limit - len(G.jokers.cards)
            for c in G.jokers.cards:
                if c.ability.name == "Joker Stencil":
                    x = x + 1
            ab.x_mult = x
        elif name == "The Wheel of Fortune":
            self.eligible_strength_jokers = [v for v in G.jokers.cards if v.ability.set == "Joker" and not v.edition]
        elif name in ("Ectoplasm", "Hex"):
            self.eligible_editionless_jokers = [v for v in G.jokers.cards if v.ability.set == "Joker" and not v.edition]
        elif name in ("Blueprint", "Brainstorm"):
            other = None
            cards = G.jokers.cards
            if name == "Brainstorm":
                other = cards[0] if cards else None
            else:
                for i, c in enumerate(cards):
                    if c is self:
                        other = cards[i + 1] if i + 1 < len(cards) else None
            if other is not None and other is not self and other.config.center.blueprint_compat:
                ab.blueprint_compat = "compatible"
            else:
                ab.blueprint_compat = "incompatible"
        elif name == "Swashbuckler":
            sell_cost = 0
            for c in G.jokers.cards:
                if c is not self and c.area is G.jokers:
                    sell_cost = sell_cost + c.sell_cost
            ab.mult = sell_cost

    def flip(self) -> None:
        if self.facing == "front":
            self.facing = "back"
        elif self.facing == "back":
            self.ability.wheel_flipped = None
            self.facing = "front"
        if self.G.feedback is not None:
            self.G._feedback("card_flipped", card=self.sort_id, facing=self.facing)

    def highlight(self, is_highlighted: bool) -> None:
        G = self.G
        self.highlighted = is_highlighted
        ab = self.ability
        if ab.consumeable or ab.set == "Joker":
            if not self.highlighted and self.area is not None and self.area.config.type == "joker" and (
                    len(G.jokers.cards) >= G.jokers.config.card_limit or (self.edition and self.edition.negative)):
                if G.shop_jokers is not None:
                    G.shop_jokers.unhighlight_all()

    # --------------------------------------------------------------- removal
    def remove(self) -> None:
        G = self.G
        self.removed = True
        self.REMOVED = True
        if G.feedback is not None and self.area is not None:
            G._feedback("card_removed", card=self.sort_id, area=self.area.name)
        if self.area is not None:
            self.area.remove_card(self)
        self.remove_from_deck()
        if self.ability.queue_negative_removal:
            if self.ability.consumeable:
                G.consumeables.config.card_limit -= 1
            else:
                G.jokers.config.card_limit -= 1
        if not G.OVERLAY_MENU:
            keys = G.data.by_name.get(self.ability.name, ())
            if keys and not G.find_joker(self.ability.name, True):
                for k in keys:
                    G.GAME.used_jokers.pop(k, None)
        if G.playing_cards is not None:
            pc = G.playing_cards
            for i, v in enumerate(pc):
                if v is self:
                    del pc[i]
                    break
            for i, v in enumerate(pc):
                v.playing_card = i + 1
        try:
            G.I_CARD.remove(self)
        except ValueError:
            pass


_UPDATE_NAMES = frozenset(("Temperance", "Throwback", "Driver's License", "Steel Joker", "Cloud 9", "Stone Joker",
                           "Joker Stencil", "The Wheel of Fortune", "Ectoplasm", "Hex", "Blueprint", "Brainstorm",
                           "Swashbuckler"))


def apply_to_run(G: "Game", self: Card | None, center: T | None = None) -> None:
    """Card:apply_to_run (also called as Card.apply_to_run(nil, center))."""
    GAME = G.GAME
    name = center.name if center is not None else self.ability.name
    extra = center.config.extra if center is not None else self.ability.extra
    if name in ("Overstock", "Overstock Plus"):
        G.ev(lambda: G.change_shop_size(1))
    if name in ("Tarot Merchant", "Tarot Tycoon"):
        def f() -> None:
            GAME.tarot_rate = 4 * extra
        G.ev(f)
    if name in ("Planet Merchant", "Planet Tycoon"):
        def f2() -> None:
            GAME.planet_rate = 4 * extra
        G.ev(f2)
    if name in ("Hone", "Glow Up"):
        def f3() -> None:
            GAME.edition_rate = extra
        G.ev(f3)
    if name in ("Magic Trick", "Illusion"):
        def f4() -> None:
            GAME.playing_card_rate = extra
        G.ev(f4)
    if name == "Crystal Ball":
        def f5() -> None:
            G.consumeables.config.card_limit = G.consumeables.config.card_limit + 1
        G.ev(f5)
    if name in ("Clearance Sale", "Liquidation"):
        def f6() -> None:
            GAME.discount_percent = extra
            G.refresh_all_costs()
        G.ev(f6)
    if name in ("Reroll Surplus", "Reroll Glut"):
        def f7() -> None:
            # the Lua reads self.ability.extra here (self is the voucher card,
            # or nil when applied from a deck/challenge, which would error)
            ex = self.ability.extra
            GAME.round_resets.reroll_cost = GAME.round_resets.reroll_cost - ex
            GAME.current_round.reroll_cost = max(0, GAME.current_round.reroll_cost - ex)
        G.ev(f7)
    if name in ("Seed Money", "Money Tree"):
        def f8() -> None:
            GAME.interest_cap = extra
        G.ev(f8)
    if name in ("Grabber", "Nacho Tong"):
        GAME.round_resets.hands = GAME.round_resets.hands + extra
        G.ease_hands_played(extra)
    if name in ("Paint Brush", "Palette"):
        G.hand.change_size(1)
    if name in ("Wasteful", "Recyclomancy"):
        GAME.round_resets.discards = GAME.round_resets.discards + extra
        G.ease_discard(extra)
    if name == "Antimatter":
        def f9() -> None:
            if G.jokers is not None:
                G.jokers.config.card_limit = G.jokers.config.card_limit + 1
        G.ev(f9)
    if name in ("Hieroglyph", "Petroglyph"):
        G.ease_ante(-extra)
        GAME.round_resets.blind_ante = lor(GAME.round_resets.blind_ante, GAME.round_resets.ante)
        GAME.round_resets.blind_ante = GAME.round_resets.blind_ante - extra
        if name == "Hieroglyph":
            GAME.round_resets.hands = GAME.round_resets.hands - extra
            G.ease_hands_played(-extra)
        if name == "Petroglyph":
            GAME.round_resets.discards = GAME.round_resets.discards - extra
            G.ease_discard(-extra)


def card_label(card: Card) -> str:
    """Short text for a playing card, e.g. 'AS' (+enhancement, *seal)."""
    b = card.base
    rank = VALUE_TO_CHAR.get(b.value, b.value or "?")
    s = f"{rank}{(b.suit or '?')[0]}"
    if card.ability.set == "Enhanced":
        s += "+" + (card.ability.name or "").replace(" Card", "").lower()
    if card.seal:
        s += "*" + card.seal.lower()
    return s
