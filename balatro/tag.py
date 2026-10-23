"""Port of tag.lua."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .card import Card
from .lua import T, copy_table

if TYPE_CHECKING:
    from .game import Game

PLACEHOLDER_HAND = "[Poker Hand]"


class Tag:
    def __init__(self, G: "Game", key: str, for_collection: Any = None, blind_type: str | None = None) -> None:
        self.G = G
        self.key = key
        proto = G.P_TAGS[key]
        self.config = copy_table(proto.config)
        self.name = proto.name
        self.tally = G.GAME.tag_tally or 0
        self.triggered = False
        self.ID = G.tagid
        G.tagid = G.tagid + 1
        self.ability = T(orbital_hand=PLACEHOLDER_HAND, blind_type=blind_type)
        G.GAME.tag_tally = (G.GAME.tag_tally + 1) if G.GAME.tag_tally is not None else 1
        if not for_collection:
            self.set_ability()

    def __repr__(self) -> str:
        return f"<Tag {self.key}#{self.ID}>"

    # ------------------------------------------------------------ animation
    def nope(self) -> None:
        G = self.G
        G.ev(None, delay=0.2, trigger="after")
        G.ev(None, trigger="after", delay=0.1)
        G.ev(self.remove, trigger="after", delay=0.5)

    def yep(self, message: str, colour: Any, func: Any) -> None:
        G = self.G
        G.stop_use()
        G.ev(None, delay=0.4, trigger="after")
        G.ev(None)
        G.event(func)
        G.ev(self.remove, trigger="after", delay=0.7)

    def set_ability(self) -> None:
        G = self.G
        if self.name == "Orbital Tag":
            if G.orbital_hand:
                self.ability.orbital_hand = G.orbital_hand
            elif self.ability.blind_type:
                oc = G.GAME.orbital_choices
                if oc and oc[G.GAME.round_resets.ante][self.ability.blind_type]:
                    self.ability.orbital_hand = oc[G.GAME.round_resets.ante][self.ability.blind_type]

    # ----------------------------------------------------------- the effect
    def apply_to_run(self, ctx: T) -> Any:
        G = self.G
        GAME = G.GAME
        if self.triggered or self.config.type != ctx.type:
            return None
        name = self.name
        typ = ctx.type
        locks = G.CONTROLLER.locks
        if typ == "eval":
            if name == "Investment Tag" and GAME.last_blind and GAME.last_blind.boss:
                self.yep("+", None, lambda: True)
                self.triggered = True
                return T(dollars=self.config.dollars, tag=self)
        elif typ == "immediate":
            lock = self.ID
            locks[lock] = True

            def unlock() -> bool:
                locks[lock] = None
                return True
            if name == "Top-up Tag":
                def topup() -> bool:
                    for _ in range(self.config.spawn_jokers):
                        if G.jokers is not None and len(G.jokers.cards) < G.jokers.config.card_limit:
                            card = G.create_card("Joker", G.jokers, None, 0, None, None, None, "top")
                            card.add_to_deck()
                            G.jokers.emplace(card)
                    locks[lock] = None
                    return True
                self.yep("+", None, topup)
                self.triggered = True
                return True
            if name == "Skip Tag":
                self.yep("+", None, unlock)
                G.ease_dollars((GAME.skips or 0) * self.config.skip_bonus)
                self.triggered = True
                return True
            if name == "Garbage Tag":
                self.yep("+", None, unlock)
                G.ease_dollars((GAME.unused_discards or 0) * self.config.dollars_per_discard)
                self.triggered = True
                return True
            if name == "Handy Tag":
                self.yep("+", None, unlock)
                G.ease_dollars((GAME.hands_played or 0) * self.config.dollars_per_hand)
                self.triggered = True
                return True
            if name == "Economy Tag":
                self.yep("+", None, unlock)

                def econ() -> None:
                    G.ease_dollars(min(self.config.max, max(0, GAME.dollars)), True)
                G.ev(econ)
                self.triggered = True
                return True
            if name == "Orbital Tag":
                hand = self.ability.orbital_hand
                h = GAME.hands[hand]
                G.update_hand_text(T(sound="button", volume=0.7, pitch=0.8, delay=0.3),
                                   T(handname=hand, chips=h.chips, mult=h.mult, level=h.level))
                G.level_up_hand(self, hand, None, self.config.levels)
                G.update_hand_text(T(sound="button", volume=0.7, pitch=1.1, delay=0),
                                   T(mult=0, chips=0, handname="", level=""))
                self.yep("+", None, unlock)
                self.triggered = True
                return True
        elif typ == "new_blind_choice":
            lock = self.ID
            locks[lock] = True
            packs = {"Charm Tag": "p_arcana_mega_1", "Meteor Tag": "p_celestial_mega_1",
                     "Ethereal Tag": "p_spectral_normal_1", "Standard Tag": "p_standard_mega_1",
                     "Buffoon Tag": "p_buffoon_mega_1"}
            if name in packs:
                # Charm/Meteor pick the artwork variant (_1/_2) with math.random
                # on LuaJIT's global state; both packs are identical
                key = packs[name]

                def open_pack() -> bool:
                    card = Card(G, G.P_CARDS.get("empty"), G.P_CENTERS[key],
                                {"bypass_discovery_center": True, "bypass_discovery_ui": True})
                    card.cost = 0
                    card.from_tag = True
                    G.use_card(card)
                    card.start_materialize()
                    locks[lock] = None
                    return True
                self.yep("+", None, open_pack)
                self.triggered = True
                return True
            if name == "Boss Tag":
                locks[lock] = True

                def boss() -> bool:
                    G.from_boss_tag = True
                    G.reroll_boss()

                    def l1() -> bool:
                        def l2() -> bool:
                            locks[lock] = None
                            return True
                        G.event(l2)
                        return True
                    G.event(l1)
                    return True
                self.yep("+", None, boss)
                self.triggered = True
                return True
        elif typ == "voucher_add":
            if name == "Voucher Tag":
                def voucher() -> bool:
                    G.ARGS.voucher_tag = G.ARGS.voucher_tag or T()
                    vkey = G.get_next_voucher_key(True)
                    G.ARGS.voucher_tag[vkey] = True
                    G.shop_vouchers.config.card_limit = G.shop_vouchers.config.card_limit + 1
                    card = Card(G, G.P_CARDS.get("empty"), G.P_CENTERS[vkey],
                                {"bypass_discovery_center": True, "bypass_discovery_ui": True})
                    G.create_shop_card_ui(card, "Voucher", G.shop_vouchers)
                    card.start_materialize()
                    G.shop_vouchers.emplace(card)
                    G.ARGS.voucher_tag = None
                    return True
                self.yep("+", None, voucher)
                self.triggered = True
        elif typ == "tag_add":
            if name == "Double Tag" and ctx.tag.key != "tag_double":
                lock = self.ID
                locks[lock] = True
                other = ctx.tag

                def double() -> bool:
                    if other.ability and other.ability.orbital_hand:
                        G.orbital_hand = other.ability.orbital_hand
                    G.add_tag(Tag(G, other.key))
                    G.orbital_hand = None
                    locks[lock] = None
                    return True
                self.yep("+", None, double)
                self.triggered = True
        elif typ == "round_start_bonus":
            if name == "Juggle Tag":
                self.yep("+", None, lambda: True)
                G.hand.change_size(self.config.h_size)
                GAME.round_resets.temp_handsize = (GAME.round_resets.temp_handsize or 0) + self.config.h_size
                self.triggered = True
                return True
        elif typ == "store_joker_create":
            card = None
            if name == "Rare Tag":
                rares = {}
                count = 0
                for v in G.jokers.cards:
                    if v.config.center.rarity == 3 and v.config.center.key not in rares:
                        count += 1
                        rares[v.config.center.key] = True
                if len(G.P_JOKER_RARITY_POOLS[2]) > count:
                    card = G.create_card("Joker", ctx.area, None, 1, None, None, None, "rta")
                    G.create_shop_card_ui(card, "Joker", ctx.area)
                    self.yep("+", None, self._coupon(card))
                else:
                    self.nope()
                self.triggered = True
            elif name == "Uncommon Tag":
                card = G.create_card("Joker", ctx.area, None, 0.9, None, None, None, "uta")
                G.create_shop_card_ui(card, "Joker", ctx.area)
                self.yep("+", None, self._coupon(card))
            self.triggered = True
            return card
        elif typ == "shop_start":
            if name == "D6 Tag" and not GAME.shop_d6ed:
                GAME.shop_d6ed = True

                def d6() -> bool:
                    GAME.round_resets.temp_reroll_cost = 0
                    G.calculate_reroll_cost(True)
                    return True
                self.yep("+", None, d6)
                self.triggered = True
                return True
        elif typ == "store_joker_modify":
            applied = None
            card = ctx.card
            if not card.edition and not card.temp_edition and card.ability.set == "Joker":
                lock = self.ID
                locks[lock] = True
                editions = {"Foil Tag": "foil", "Holographic Tag": "holo", "Polychrome Tag": "polychrome",
                            "Negative Tag": "negative"}
                if name in editions:
                    ed = editions[name]
                    card.temp_edition = True

                    def apply() -> bool:
                        card.temp_edition = None
                        card.set_edition(T({ed: True}), True)
                        card.ability.couponed = True
                        card.set_cost()
                        locks[lock] = None
                        return True
                    self.yep("+", None, apply)
                    applied = True
                self.triggered = True
            return applied
        elif typ == "shop_final_pass":
            if name == "Coupon Tag" and (G.shop is not None and not GAME.shop_free):
                GAME.shop_free = True

                def coupon() -> bool:
                    if G.shop_jokers is not None and G.shop_booster is not None:
                        for v in list(G.shop_jokers.cards):
                            v.ability.couponed = True
                            v.set_cost()
                        for v in list(G.shop_booster.cards):
                            v.ability.couponed = True
                            v.set_cost()
                    return True
                self.yep("+", None, coupon)
                self.triggered = True
                return True
        return None

    @staticmethod
    def _coupon(card: Card) -> Any:
        def f() -> bool:
            card.start_materialize()
            card.ability.couponed = True
            card.set_cost()
            return True
        return f

    # ---------------------------------------------------------------- removal
    def remove_from_game(self) -> None:
        tags = self.G.GAME.tags
        key = None
        for i, v in enumerate(tags):
            if v is self:
                key = i
        if key is None:
            # table.remove(t, nil) removes the last element
            if tags:
                tags.pop()
        else:
            del tags[key]

    def remove(self) -> None:
        self.remove_from_game()
