"""Port of card.lua (everything except calculate_joker, which lives in jokers.py)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .lua import T, copy_table

if TYPE_CHECKING:
    from .cardarea import CardArea
    from .game import Game

RANK_NOMINALS = {
    "2": (2, 0.0, 2), "3": (3, 0.0, 3), "4": (4, 0.0, 4), "5": (5, 0.0, 5), "6": (6, 0.0, 6),
    "7": (7, 0.0, 7), "8": (8, 0.0, 8), "9": (9, 0.0, 9), "10": (10, 0.0, 10),
    "Jack": (10, 0.1, 11), "Queen": (10, 0.2, 12), "King": (10, 0.3, 13), "Ace": (11, 0.4, 14),
}
SUIT_NOMINALS = {"Diamonds": (0.01, 0.001), "Clubs": (0.02, 0.002), "Hearts": (0.03, 0.003), "Spades": (0.04, 0.004)}
ID_TO_RANK_CHAR = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "T",
                   11: "J", 12: "Q", 13: "K", 14: "A"}
VALUE_TO_RANK_CHAR = {"Ace": "A", "King": "K", "Queen": "Q", "Jack": "J", "10": "T"}
SUIT_PREFIX = {"Diamonds": "D_", "Spades": "S_", "Clubs": "C_", "Hearts": "H_"}


class Card:
    """A card object: playing card, joker, consumable, voucher or booster."""

    def __init__(self, G: "Game", card: T | None, center: T, params: dict | None = None) -> None:
        self.G = G
        self.params = params or {}
        self.config = T(card=card if card is not None else T(), center=center)
        self.playing_card = self.params.get("playing_card")
        G.sort_id += 1
        self.sort_id = G.sort_id
        self.ID = self.sort_id
        self.back = "viewed_back" if self.params.get("viewed_back") else "selected_back"
        self.bypass_discovery_center = self.params.get("bypass_discovery_center")
        self.base_cost = 0
        self.extra_cost = 0
        self.cost = 0
        self.sell_cost = 0
        self.unique_val = 1 - self.ID / 1603301
        self.edition: T | None = None
        self.seal: str | None = None
        self.ability: T = None  # type: ignore[assignment]  # set by set_ability()
        self.base: T = T()
        self.area: CardArea | None = None
        self.facing = "front"
        self.highlighted = False
        self.debuff = False
        self.added_to_deck: bool | None = None
        self.removed = False
        # transient flags used by the game logic
        self.getting_sliced = None
        self.shattered = None
        self.destroyed = None
        self.lucky_trigger = None
        self.vampired = None
        self.opening = None
        self.from_tag = None
        self.shop_voucher = None
        self.temp_edition = None
        self.pinned = None
        self.eligible_strength_jokers: list[Card] = []
        self.eligible_editionless_jokers: list[Card] = []
        self.set_ability(center, True)
        self.set_base(card, True)
        self.set_cost()
        G.all_cards.append(self)

    # ------------------------------------------------------------------ repr
    def __repr__(self) -> str:
        return f"<Card {self.short()}#{self.sort_id}>"

    def short(self) -> str:
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
        suit_base_nominal_original = None
        if self.base and self.base.suit_nominal_original is not None:
            suit_base_nominal_original = self.base.suit_nominal_original
        times_played = 0
        self.base = T(name=card.name, suit=card.suit, value=card.value, nominal=0, suit_nominal=0,
                      face_nominal=0, times_played=times_played)
        if card.value in RANK_NOMINALS:
            nominal, face, rid = RANK_NOMINALS[card.value]
            self.base.nominal = nominal
            self.base.face_nominal = face
            self.base.id = rid
        if initial:
            self.base.original_value = self.base.value
        if card.suit in SUIT_NOMINALS:
            sn, sno = SUIT_NOMINALS[card.suit]
            self.base.suit_nominal = sn
            self.base.suit_nominal_original = suit_base_nominal_original if suit_base_nominal_original is not None else sno
        if not initial:
            G.GAME.blind.debuff_card(self)

    # ---------------------------------------------------------- set_ability
    def set_ability(self, center: T, initial: bool = False, delay_sprites: bool = False) -> None:
        G = self.G
        self.config.center = center
        self.config.center_key = center.key
        # (the Lua subtracts the old enhancement bonus from the *old* ability
        # table right before replacing it - a no-op)
        old = self.ability
        cfg = center.config or T()
        self.ability = T(
            name=center.name,
            effect=center.effect,
            set=center.set,
            mult=cfg.mult or 0,
            h_mult=cfg.h_mult or 0,
            h_x_mult=cfg.h_x_mult or 0,
            h_dollars=cfg.h_dollars or 0,
            p_dollars=cfg.p_dollars or 0,
            t_mult=cfg.t_mult or 0,
            t_chips=cfg.t_chips or 0,
            x_mult=cfg.Xmult if cfg.Xmult is not None else 1,
            h_size=cfg.h_size or 0,
            d_size=cfg.d_size or 0,
            extra=copy_table(cfg.extra) if cfg.extra is not None else None,
            extra_value=0,
            type=cfg.type or "",
            order=center.order,
            forced_selection=old.forced_selection if old is not None else None,
            perma_bonus=(old.perma_bonus if old is not None and old.perma_bonus is not None else 0),
        )
        # the Lua reads self.ability.bonus from the *new* table (always nil),
        # so any previous enhancement bonus is dropped
        self.ability.bonus = cfg.bonus or 0
        if center.consumeable:
            self.ability.consumeable = copy_table(cfg)
        name = self.ability.name
        if name == "Invisible Joker":
            self.ability.invis_rounds = 0
        if name == "To Do List":
            poker_hands = [k for k in G.hands_order() if G.GAME.hands[k].visible]
            old_hand = self.ability.to_do_poker_hand
            self.ability.to_do_poker_hand = None
            area_is_title = self.area is not None and self.area.config.type == "title"
            while self.ability.to_do_poker_hand is None:
                choice = G.rng.element(poker_hands, G.rng.pseudoseed("false_to_do" if area_is_title else "to_do"))
                self.ability.to_do_poker_hand = choice
                if choice == old_hand:
                    self.ability.to_do_poker_hand = None
        if name == "Caino":
            self.ability.caino_xmult = 1
        if name == "Yorick":
            self.ability.yorick_discards = self.ability.extra.discards
        if name == "Loyalty Card":
            self.ability.burnt_hand = 0
            self.ability.loyalty_remaining = self.ability.extra.every
        self.base_cost = center.cost if center.cost is not None else 1
        self.ability.hands_played_at_create = G.GAME.hands_played if G.GAME else 0
        if not G.OVERLAY_MENU:
            for k in G.data.by_name.get(name, ()):
                G.GAME.used_jokers[k] = True
        if not initial:
            G.GAME.blind.debuff_card(self)

    # ------------------------------------------------------------- set_cost
    def set_cost(self) -> None:
        G = self.G
        self.extra_cost = 0 + G.GAME.inflation
        if self.edition:
            e = self.edition
            self.extra_cost += (3 if e.holo else 0) + (2 if e.foil else 0) + (5 if e.polychrome else 0) + (5 if e.negative else 0)
        self.cost = max(1, math.floor((self.base_cost + self.extra_cost + 0.5) * (100 - G.GAME.discount_percent) / 100))
        if self.ability.set == "Booster" and G.GAME.modifiers.booster_ante_scaling:
            self.cost = self.cost + G.GAME.round_resets.ante - 1
        if (self.ability.set == "Planet" or (self.ability.set == "Booster" and "Celestial" in self.ability.name)) and G.find_joker("Astronomer"):
            self.cost = 0
        if self.ability.rental:
            self.cost = 1
        self.sell_cost = max(1, math.floor(self.cost / 2)) + (self.ability.extra_value or 0)
        if self.area is not None and self.ability.couponed and (self.area is G.shop_jokers or self.area is G.shop_booster):
            self.cost = 0

    # ---------------------------------------------------------- set_edition
    def set_edition(self, edition: Any, immediate: bool = False, silent: bool = False) -> None:
        G = self.G
        self.edition = None
        if edition is None or edition is False:
            return  # Lua returns before set_cost() here
        P = G.P_CENTERS
        if edition.get("holo"):
            self.edition = T(mult=P["e_holo"].config.extra, holo=True, type="holo")
        elif edition.get("foil"):
            self.edition = T(chips=P["e_foil"].config.extra, foil=True, type="foil")
        elif edition.get("polychrome"):
            self.edition = T(x_mult=P["e_polychrome"].config.extra, polychrome=True, type="polychrome")
        elif edition.get("negative"):
            # self.edition was reset to nil above, so this always fires for an
            # existing card (matches the Lua, which also checks `not self.edition`)
            if self.added_to_deck:
                if self.ability.consumeable:
                    G.consumeables.config.card_limit += 1
                else:
                    G.jokers.config.card_limit += 1
            self.edition = T(negative=True, type="negative")
        self.set_cost()

    # ------------------------------------------------------------- set_seal
    def set_seal(self, seal: str | None, silent: bool = False, immediate: bool = False) -> None:
        self.seal = seal if seal else None
        self.set_cost()

    def get_seal(self, bypass_debuff: bool = False) -> str | None:
        if self.debuff and not bypass_debuff:
            return None
        return self.seal

    def set_eternal(self, eternal: Any) -> None:
        self.ability.eternal = None
        if self.config.center.eternal_compat and not self.ability.perishable:
            self.ability.eternal = eternal if eternal else None

    def set_perishable(self, perishable: Any) -> None:
        self.ability.perishable = None
        if self.config.center.perishable_compat and not self.ability.eternal:
            self.ability.perishable = True
            self.ability.perish_tally = self.G.GAME.perishable_rounds

    def set_rental(self, rental: Any) -> None:
        self.ability.rental = rental if rental else None
        self.set_cost()

    def set_debuff(self, should_debuff: Any = None) -> None:
        G = self.G
        should_debuff = bool(should_debuff)
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
        new_val = VALUE_TO_RANK_CHAR.get(self.base.value, self.base.value)
        self.set_base(G.P_CARDS[SUIT_PREFIX[new_suit] + new_val])
        G.GAME.blind.debuff_card(self)

    # ---------------------------------------------------------- deck in/out
    def add_to_deck(self, from_debuff: bool = False) -> None:
        G = self.G
        if self.added_to_deck:
            return
        self.added_to_deck = True
        if self.ability.set in ("Enhanced", "Default"):
            return
        ab = self.ability
        name = ab.name
        if ab.h_size != 0:
            G.hand.change_size(ab.h_size)
        if ab.d_size > 0:
            G.GAME.round_resets.discards += ab.d_size
            G.ease_discard(ab.d_size)
        if name == "Credit Card":
            G.GAME.bankrupt_at = G.GAME.bankrupt_at - ab.extra
        if name == "Chicot" and G.GAME.blind and G.GAME.blind.boss and not G.GAME.blind.disabled:
            G.GAME.blind.disable()
        if name == "Chaos the Clown":
            G.GAME.current_round.free_rerolls += 1
            G.calculate_reroll_cost(True)
        if name == "Turtle Bean":
            G.hand.change_size(ab.extra.h_size)
        if name == "Oops! All 6s":
            for k in list(G.GAME.probabilities):
                G.GAME.probabilities[k] = G.GAME.probabilities[k] * 2
        if name == "To the Moon":
            G.GAME.interest_amount += ab.extra
        if name == "Astronomer":
            G.add_event(G.refresh_all_costs)
        if name == "Troubadour":
            G.hand.change_size(ab.extra.h_size)
            G.GAME.round_resets.hands += ab.extra.h_plays
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
        if G.GAME.blind:
            G.add_event(lambda: G.GAME.blind.set_blind(None, True, None))

    def remove_from_deck(self, from_debuff: bool = False) -> None:
        G = self.G
        if not self.added_to_deck:
            return
        self.added_to_deck = False
        ab = self.ability
        name = ab.name
        if ab.h_size != 0:
            G.hand.change_size(-ab.h_size)
        if ab.d_size > 0:
            G.GAME.round_resets.discards -= ab.d_size
            G.ease_discard(-ab.d_size)
        if name == "Credit Card":
            G.GAME.bankrupt_at = G.GAME.bankrupt_at + ab.extra
        if name == "Chaos the Clown":
            G.GAME.current_round.free_rerolls -= 1
            G.calculate_reroll_cost(True)
        if name == "Turtle Bean":
            G.hand.change_size(-ab.extra.h_size)
        if name == "Oops! All 6s":
            for k in list(G.GAME.probabilities):
                G.GAME.probabilities[k] = G.GAME.probabilities[k] / 2
        if name == "To the Moon":
            G.GAME.interest_amount -= ab.extra
        if name == "Astronomer":
            G.add_event(G.refresh_all_costs)
        if name == "Troubadour":
            G.hand.change_size(-ab.extra.h_size)
            G.GAME.round_resets.hands -= ab.extra.h_plays
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
        if G.GAME.blind:
            G.add_event(lambda: G.GAME.blind.set_blind(None, True, None))

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
            # the game returns -math.random(100, 1000000) from the *global*
            # LuaJIT state; only uniqueness matters, so use a unique negative id
            self.G.stone_id_counter -= 1
            return self.G.stone_id_counter
        return self.base.id

    def is_face(self, from_boss: bool = False) -> bool | None:
        if self.debuff and not from_boss:
            return None
        rid = self.get_id()
        if rid in (11, 12, 13) or self.G.find_joker("Pareidolia"):
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
            G.GAME.consumeable_buffer += 1

            def make_planet() -> None:
                if G.GAME.last_hand_played:
                    planet = 0
                    for v in G.P_CENTER_POOLS["Planet"]:
                        if v.config.hand_type == G.GAME.last_hand_played:
                            planet = v.key
                    card = G.create_card("Planet", G.consumeables, None, None, None, None, planet, "blusl")
                    card.add_to_deck()
                    G.consumeables.emplace(card)
                    G.GAME.consumeable_buffer = 0
            G.add_event(make_planet)
            ret.effect = True
        return ret

    def get_p_dollars(self) -> float:
        G = self.G
        if self.debuff:
            return 0
        ret = 0
        if self.seal == "Gold":
            ret += 3
        if self.ability.p_dollars > 0:
            if self.ability.effect == "Lucky Card":
                if G.rng.random("lucky_money") < G.GAME.probabilities.normal / 15:
                    self.lucky_trigger = True
                    ret += self.ability.p_dollars
            else:
                ret += self.ability.p_dollars
        if ret > 0:
            G.GAME.dollar_buffer = (G.GAME.dollar_buffer or 0) + ret
            G.add_event(lambda: setattr(G.GAME, "dollar_buffer", 0))
        return ret

    def is_suit(self, suit: str, bypass_debuff: bool = False, flush_calc: bool = False) -> bool | None:
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
                return T(message="Again!", repetitions=1, card=self)
        if context.discard:
            if self.seal == "Purple" and len(G.consumeables.cards) + G.GAME.consumeable_buffer < G.consumeables.config.card_limit:
                G.GAME.consumeable_buffer += 1

                def make_tarot() -> None:
                    card = G.create_card("Tarot", G.consumeables, None, None, None, None, None, "8ba")
                    card.add_to_deck()
                    G.consumeables.emplace(card)
                    G.GAME.consumeable_buffer = 0
                G.add_event(make_tarot)
        return None

    def calculate_rental(self) -> None:
        G = self.G
        if self.ability.rental:
            G.ease_dollars(-G.GAME.rental_rate)

    def calculate_perishable(self) -> None:
        if self.ability.perishable and self.ability.perish_tally > 0:
            if self.ability.perish_tally == 1:
                self.ability.perish_tally = 0
                self.set_debuff()
            else:
                self.ability.perish_tally = self.ability.perish_tally - 1

    def calculate_dollar_bonus(self) -> float | None:
        G = self.G
        if self.debuff:
            return None
        if self.ability.set == "Joker":
            name = self.ability.name
            if name == "Golden Joker":
                return self.ability.extra
            if name == "Cloud 9" and self.ability.nine_tally and self.ability.nine_tally > 0:
                return self.ability.extra * self.ability.nine_tally
            if name == "Rocket":
                return self.ability.extra.dollars
            if name == "Satellite":
                planets_used = sum(1 for v in G.GAME.consumeable_usage.values() if v.set == "Planet")
                if planets_used == 0:
                    return None
                return self.ability.extra * planets_used
            if name == "Delayed Gratification" and G.GAME.current_round.discards_used == 0 and G.GAME.current_round.discards_left > 0:
                return G.GAME.current_round.discards_left * self.ability.extra
        return None

    def calculate_joker(self, context: T) -> Any:
        from .jokers import calculate_joker
        return calculate_joker(self, context)

    # ----------------------------------------------------------- per frame
    def update(self) -> None:
        """Card:update logic that matters for the game (runs every frame in Lua)."""
        G = self.G
        ab = self.ability
        if ab.consumeable and ab.consumeable.max_highlighted:
            ab.consumeable.mod_num = min(5, ab.consumeable.max_highlighted)
        if ab.perma_debuff:
            self.debuff = True
        name = ab.name
        if name == "Temperance":
            money = 0
            for c in G.jokers.cards:
                if c.ability.set == "Joker":
                    money += c.sell_cost
            ab.money = min(money, ab.extra)
        elif name == "Throwback":
            ab.x_mult = 1 + G.GAME.skips * ab.extra
        elif name == "Driver's License":
            ab.driver_tally = sum(1 for v in G.playing_cards if v.config.center is not G.P_CENTERS["c_base"])
        elif name == "Steel Joker":
            ab.steel_tally = sum(1 for v in G.playing_cards if v.config.center is G.P_CENTERS["m_steel"])
        elif name == "Cloud 9":
            ab.nine_tally = sum(1 for v in G.playing_cards if v.get_id() == 9)
        elif name == "Stone Joker":
            ab.stone_tally = sum(1 for v in G.playing_cards if v.config.center is G.P_CENTERS["m_stone"])
        elif name == "Joker Stencil":
            x = G.jokers.config.card_limit - len(G.jokers.cards)
            for c in G.jokers.cards:
                if c.ability.name == "Joker Stencil":
                    x += 1
            ab.x_mult = x
        elif name == "The Wheel of Fortune":
            self.eligible_strength_jokers = [v for v in G.jokers.cards if v.ability.set == "Joker" and not v.edition]
        elif name in ("Ectoplasm", "Hex"):
            self.eligible_editionless_jokers = [v for v in G.jokers.cards if v.ability.set == "Joker" and not v.edition]
        elif name in ("Blueprint", "Brainstorm"):
            other = None
            if name == "Brainstorm":
                other = G.jokers.cards[0] if G.jokers.cards else None
            else:
                cards = G.jokers.cards
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
                    sell_cost += c.sell_cost
            ab.mult = sell_cost

    def flip(self) -> None:
        if self.facing == "front":
            self.facing = "back"
        elif self.facing == "back":
            self.ability.wheel_flipped = None
            self.facing = "front"

    # --------------------------------------------------------------- removal
    def remove(self) -> None:
        """Card:remove()"""
        G = self.G
        if self.removed:
            return
        self.removed = True
        if self.area is not None:
            self.area.remove_card(self)
        self.remove_from_deck()
        if self.ability.queue_negative_removal:
            if self.ability.consumeable:
                G.consumeables.config.card_limit -= 1
            else:
                G.jokers.config.card_limit -= 1
        if not G.OVERLAY_MENU:
            name = self.ability.name
            keys = G.data.by_name.get(name, ())
            if keys and not G.find_joker(name, True):
                for k in keys:
                    G.GAME.used_jokers.pop(k, None)
        if G.playing_cards is not None:
            for i, v in enumerate(G.playing_cards):
                if v is self:
                    del G.playing_cards[i]
                    break
            for i, v in enumerate(G.playing_cards):
                v.playing_card = i + 1
        try:
            G.all_cards.remove(self)
        except ValueError:
            pass

    def start_dissolve(self, *args: Any, **kwargs: Any) -> None:
        # visual dissolve; the actual removal happens ~0.7s later in
        # non-blockable events -> modelled as end-of-action deferred removal
        self.G.defer_removal(self)

    def shatter(self) -> None:
        self.shattered = True
        self.G.defer_removal(self)

    # ----------------------------------------------------------- consumables
    def use_consumeable(self, area: Any, copier: "Card | None" = None) -> None:
        from .consumables import use_consumeable
        use_consumeable(self, area, copier)

    def can_use_consumeable(self, any_state: bool = False, skip_check: bool = False) -> bool:
        from .consumables import can_use_consumeable
        return can_use_consumeable(self, any_state, skip_check)

    def check_use(self) -> bool | None:
        G = self.G
        if self.ability.name == "Ankh":
            if len(G.jokers.cards) >= G.jokers.config.card_limit:
                return True
        return None

    def sell_card(self) -> None:
        G = self.G
        self.calculate_joker(T(selling_self=True))

        def finish() -> None:
            G.ease_dollars(self.sell_cost)
            self.start_dissolve()
            if self.ability.set == "Joker" and G.GAME.blind and G.GAME.blind.name == "Verdant Leaf":
                G.add_event(G.GAME.blind.disable)
        G.add_event(finish)

    def can_sell_card(self, context: Any = None) -> bool:
        G = self.G
        if (G.play is not None and G.play.cards) or (G.GAME.STOP_USE and G.GAME.STOP_USE > 0):
            return False
        if self.area is not None and self.area.config.type == "joker" and not self.ability.eternal:
            return True
        return False

    def open(self) -> None:
        from .packs import open_booster
        open_booster(self)

    def redeem(self) -> None:
        from .vouchers import redeem
        redeem(self)

    def apply_to_run(self, center: T | None = None) -> None:
        from .vouchers import apply_to_run
        apply_to_run(self.G, self, center)


def card_label(card: Card) -> str:
    """Short text for a playing card: e.g. 'AS' (+enhancement/seal)."""
    b = card.base
    rank = VALUE_TO_RANK_CHAR.get(b.value, b.value or "?")
    s = f"{rank}{(b.suit or '?')[0]}"
    if card.ability.set == "Enhanced":
        s += "+" + (card.ability.name or "").replace(" Card", "").lower()
    if card.seal:
        s += "*" + card.seal.lower()
    return s
