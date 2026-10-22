"""Port of tag.lua."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .card import Card
from .lua import T, copy_table

if TYPE_CHECKING:
    from .game import Game


class Tag:
    def __init__(self, G: "Game", key: str, for_collection: bool = False, blind_type: str | None = None) -> None:
        self.G = G
        self.key = key
        proto = G.P_TAGS[key]
        self.config = copy_table(proto.config)
        self.name = proto.name
        self.tally = G.GAME.tag_tally or 0
        self.triggered = False
        G.tagid += 1
        self.ID = G.tagid
        self.ability = T(orbital_hand="[Poker Hand]", blind_type=blind_type)
        G.GAME.tag_tally = (G.GAME.tag_tally + 1) if G.GAME.tag_tally else 1
        if not for_collection:
            self.set_ability()

    def __repr__(self) -> str:
        return f"<Tag {self.key}>"

    def set_ability(self) -> None:
        G = self.G
        if self.name == "Orbital Tag":
            if G.orbital_hand:
                self.ability.orbital_hand = G.orbital_hand
            elif self.ability.blind_type:
                oc = G.GAME.orbital_choices
                if oc and oc.get(G.GAME.round_resets.ante) and oc[G.GAME.round_resets.ante].get(self.ability.blind_type):
                    self.ability.orbital_hand = oc[G.GAME.round_resets.ante][self.ability.blind_type]

    def remove(self) -> None:
        G = self.G
        try:
            G.GAME.tags.remove(self)
        except ValueError:
            pass

    def _yep(self, func: Any = None) -> None:
        """Tag:yep(): the tag's effect runs in an event, then the tag is removed."""
        G = self.G
        if func is not None:
            G.add_event(func)
        G.add_event(self.remove)

    def _nope(self) -> None:
        self.G.add_event(self.remove)

    def apply_to_run(self, context: T) -> Any:
        G = self.G
        if self.triggered or self.config.type != context.type:
            return None
        t = context.type
        name = self.name
        if t == "eval":
            if name == "Investment Tag" and G.GAME.last_blind and G.GAME.last_blind.boss:
                self._yep()
                self.triggered = True
                return T(dollars=self.config.dollars, condition="Defeat the Boss", tag=self)
        elif t == "immediate":
            if name == "Top-up Tag":
                def topup() -> None:
                    for _ in range(self.config.spawn_jokers):
                        if G.jokers is not None and len(G.jokers.cards) < G.jokers.config.card_limit:
                            card = G.create_card("Joker", G.jokers, None, 0, None, None, None, "top")
                            card.add_to_deck()
                            G.jokers.emplace(card)
                self._yep(topup)
                self.triggered = True
                return True
            if name == "Skip Tag":
                self._yep()
                G.ease_dollars((G.GAME.skips or 0) * self.config.skip_bonus)
                self.triggered = True
                return True
            if name == "Garbage Tag":
                self._yep()
                G.ease_dollars((G.GAME.unused_discards or 0) * self.config.dollars_per_discard)
                self.triggered = True
                return True
            if name == "Handy Tag":
                self._yep()
                G.ease_dollars((G.GAME.hands_played or 0) * self.config.dollars_per_hand)
                self.triggered = True
                return True
            if name == "Economy Tag":
                self._yep()
                G.add_event(lambda: G.ease_dollars(min(self.config.max, max(0, G.GAME.dollars)), True))
                self.triggered = True
                return True
            if name == "Orbital Tag":
                G.level_up_hand(self, self.ability.orbital_hand, None, self.config.levels)
                self._yep()
                self.triggered = True
                return True
        elif t == "new_blind_choice":
            pack = None
            if name == "Charm Tag":
                pack = "p_arcana_mega_1"  # _1/_2 picked with global math.random: art only
            elif name == "Meteor Tag":
                pack = "p_celestial_mega_1"
            elif name == "Ethereal Tag":
                pack = "p_spectral_normal_1"
            elif name == "Standard Tag":
                pack = "p_standard_mega_1"
            elif name == "Buffoon Tag":
                pack = "p_buffoon_mega_1"
            if pack is not None:
                def open_pack(pack: str = pack) -> None:
                    card = Card(G, None, G.P_CENTERS[pack], {"bypass_discovery_center": True})
                    card.cost = 0
                    card.from_tag = True
                    G.use_card(card)
                self._yep(open_pack)
                self.triggered = True
                return True
            if name == "Boss Tag":
                def reroll() -> None:
                    G.from_boss_tag = True
                    G.reroll_boss()
                self._yep(reroll)
                self.triggered = True
                return True
        elif t == "voucher_add":
            if name == "Voucher Tag":
                def add_voucher() -> None:
                    G.ARGS.voucher_tag = G.ARGS.voucher_tag or T()
                    voucher_key = G.get_next_voucher_key(True)
                    G.ARGS.voucher_tag[voucher_key] = True
                    G.shop_vouchers.config.card_limit += 1
                    card = Card(G, None, G.P_CENTERS[voucher_key], {"bypass_discovery_center": True})
                    G.shop_vouchers.emplace(card)
                    G.ARGS.voucher_tag = None
                self._yep(add_voucher)
                self.triggered = True
        elif t == "tag_add":
            if name == "Double Tag" and context.tag.key != "tag_double":
                def double() -> None:
                    if context.tag.ability and context.tag.ability.orbital_hand:
                        G.orbital_hand = context.tag.ability.orbital_hand
                    G.add_tag(Tag(G, context.tag.key))
                    G.orbital_hand = None
                self._yep(double)
                self.triggered = True
        elif t == "round_start_bonus":
            if name == "Juggle Tag":
                self._yep()
                G.hand.change_size(self.config.h_size)
                G.GAME.round_resets.temp_handsize = (G.GAME.round_resets.temp_handsize or 0) + self.config.h_size
                self.triggered = True
                return True
        elif t == "store_joker_create":
            card = None
            if name == "Rare Tag":
                rares = set()
                for v in G.jokers.cards:
                    if v.config.center.rarity == 3:
                        rares.add(v.config.center.key)
                if len(G.P_JOKER_RARITY_POOLS[2]) > len(rares):
                    card = G.create_card("Joker", context.area, None, 1, None, None, None, "rta")

                    def coupon(card: Card = card) -> None:
                        card.ability.couponed = True
                        card.set_cost()
                    self._yep(coupon)
                else:
                    self._nope()
                self.triggered = True
            elif name == "Uncommon Tag":
                card = G.create_card("Joker", context.area, None, 0.9, None, None, None, "uta")

                def coupon2(card: Card = card) -> None:
                    card.ability.couponed = True
                    card.set_cost()
                self._yep(coupon2)
            self.triggered = True
            return card
        elif t == "shop_start":
            if name == "D6 Tag" and not G.GAME.shop_d6ed:
                G.GAME.shop_d6ed = True

                def d6() -> None:
                    G.GAME.round_resets.temp_reroll_cost = 0
                    G.calculate_reroll_cost(True)
                self._yep(d6)
                self.triggered = True
                return True
        elif t == "store_joker_modify":
            applied = None
            card = context.card
            if not card.edition and not card.temp_edition and card.ability.set == "Joker":
                ed = {"Foil Tag": "foil", "Holographic Tag": "holo", "Polychrome Tag": "polychrome",
                      "Negative Tag": "negative"}.get(name)
                if ed is not None:
                    card.temp_edition = True

                    def apply_ed(card: Card = card, ed: str = ed) -> None:
                        card.temp_edition = None
                        card.set_edition(T({ed: True}), True)
                        card.ability.couponed = True
                        card.set_cost()
                    self._yep(apply_ed)
                    applied = True
                self.triggered = True
            return applied
        elif t == "shop_final_pass":
            if name == "Coupon Tag" and (G.shop is not None and not G.GAME.shop_free):
                G.GAME.shop_free = True

                def free() -> None:
                    if G.shop_jokers is not None and G.shop_booster is not None:
                        for v in G.shop_jokers.cards:
                            v.ability.couponed = True
                            v.set_cost()
                        for v in G.shop_booster.cards:
                            v.ability.couponed = True
                            v.set_cost()
                self._yep(free)
                self.triggered = True
                return True
        return None
