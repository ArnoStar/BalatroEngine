"""Port of blind.lua (logic only)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .lua import T

if TYPE_CHECKING:
    from .card import Card
    from .cardarea import CardArea
    from .game import Game


class Blind:
    def __init__(self, G: "Game") -> None:
        self.G = G
        self.config = T()
        self.chips = 0
        self.name: str = ""
        self.dollars = 0
        self.debuff = T()
        self.mult = 0
        self.disabled = False
        self.discards_sub = None
        self.hands_sub = None
        self.boss = None
        self.triggered = None
        self.prepped = None
        self.hands: T | None = None
        self.only_hand: Any = None

    def __bool__(self) -> bool:  # G.GAME.blind is always a table in Lua
        return True

    def __repr__(self) -> str:
        return f"<Blind {self.name!r} chips={self.chips}>"

    def get_type(self) -> str | None:
        if self.name == "Small Blind":
            return "Small"
        if self.name == "Big Blind":
            return "Big"
        if self.name:
            return "Boss"
        return None

    def set_blind(self, blind: T | None, reset: Any = None, silent: Any = None) -> None:
        G = self.G
        GAME = G.GAME
        if not reset:
            self.config.blind = blind if blind is not None else T()
            self.name = blind.name if blind is not None and blind.name else ""
            self.dollars = blind.dollars if blind is not None and blind.dollars else 0
            if GAME.modifiers.no_blind_reward and GAME.modifiers.no_blind_reward.get(self.get_type()):
                self.dollars = 0
            self.debuff = blind.debuff if blind is not None and blind.debuff is not None else T()
            self.mult = blind.mult if blind is not None and blind.mult else 0
            self.disabled = False
            self.discards_sub = None
            self.hands_sub = None
            self.boss = bool(blind.boss) if blind is not None else None
            self.triggered = None
            self.prepped = True
            GAME.last_blind = GAME.last_blind or T()
            GAME.last_blind.boss = self.boss
            GAME.last_blind.name = self.name
            self.chips = G.get_blind_amount(GAME.round_resets.ante) * self.mult * GAME.starting_params.ante_scaling
            if blind is None:
                self.chips = 0
        name = self.name
        if name == "The Eye" and not reset:
            self.hands = T({h: False for h in G.data.handlist})
        if name == "The Mouth" and not reset:
            self.only_hand = False
        if name == "The Fish" and not reset:
            self.prepped = None
        if name == "The Water" and not reset:
            self.discards_sub = GAME.current_round.discards_left
            G.ease_discard(-self.discards_sub)
        if name == "The Needle" and not reset:
            self.hands_sub = GAME.round_resets.hands - 1
            G.ease_hands_played(-self.hands_sub)
        if name == "The Manacle" and not reset:
            G.hand.change_size(-1)
        if name == "Amber Acorn" and not reset and G.jokers.cards:
            G.jokers.unhighlight_all()
            for v in G.jokers.cards:
                v.flip()
            if len(G.jokers.cards) > 1:
                def shuffles() -> None:
                    for _ in range(3):
                        G.add_event(lambda: G.jokers.shuffle("aajk"))
                G.add_event(shuffles)
        for v in G.playing_cards:
            self.debuff_card(v)
        for v in G.jokers.cards:
            if not reset:
                self.debuff_card(v, True)

    def defeat(self, silent: Any = None) -> None:
        G = self.G
        for v in G.jokers.cards:
            if v.facing == "back":
                v.flip()
        if self.name == "The Manacle" and not self.disabled:
            G.hand.change_size(1)
        # the blind is reset ~1.2s later in a non-blockable event
        G.defer(lambda: self.set_blind(None, None, True))

    def disable(self) -> None:
        G = self.G
        GAME = G.GAME
        self.disabled = True
        for v in G.jokers.cards:
            if v.facing == "back":
                v.flip()
        name = self.name
        if name == "The Water":
            G.ease_discard(self.discards_sub)
        if name in ("The Wheel", "The House", "The Mark", "The Fish"):
            for c in G.hand.cards:
                if c.facing == "back":
                    c.flip()
            for v in G.playing_cards:
                v.ability.wheel_flipped = None
        if name == "The Needle":
            G.ease_hands_played(self.hands_sub)
        if name == "The Wall":
            self.chips = self.chips / 2
        if name == "Cerulean Bell":
            for v in G.playing_cards:
                v.ability.forced_selection = None
        if name == "The Manacle":
            G.hand.change_size(1)
            G.draw_from_deck_to_hand(1)
        if name == "Violet Vessel":
            self.chips = self.chips / 3

        def check() -> None:
            if self.boss and GAME.chips - GAME.blind.chips >= 0:
                G.STATE = G.STATES.NEW_ROUND
                G.STATE_COMPLETE = False
        G.add_event(check)
        for v in G.playing_cards:
            self.debuff_card(v)
        for v in G.jokers.cards:
            self.debuff_card(v)

    def press_play(self) -> Any:
        G = self.G
        if self.disabled:
            return None
        name = self.name
        if name == "The Hook":
            def hook() -> None:
                any_selected = None
                cards = list(G.hand.cards)
                for i in range(2):
                    if i < len(G.hand.cards):
                        # pseudorandom_element sorts by sort_id but returns the original index
                        order = sorted(range(len(cards)), key=lambda j: cards[j].sort_id)
                        pick = order[G.rng.element_index(len(order), G.rng.pseudoseed("hook"))]
                        G.hand.add_to_highlighted(cards[pick], True)
                        del cards[pick]
                        any_selected = True
                if any_selected:
                    G.discard_cards_from_highlighted(None, True)
            G.add_event(hook)
            self.triggered = True
            return True
        if name == "Crimson Heart":
            if G.jokers.cards:
                self.triggered = True
                self.prepped = True
        if name == "The Fish":
            self.prepped = True
        if name == "The Tooth":
            def tooth() -> None:
                for _ in range(len(G.play.cards)):
                    G.ease_dollars(-1)
            G.add_event(tooth)
            self.triggered = True
            return True
        return None

    def modify_hand(self, cards: list, poker_hands: Any, text: str, mult: float, hand_chips: float) -> tuple[float, float, bool]:
        import math
        if self.disabled:
            return mult, hand_chips, False
        if self.name == "The Flint":
            self.triggered = True
            return max(math.floor(mult * 0.5 + 0.5), 1), max(math.floor(hand_chips * 0.5 + 0.5), 0), True
        return mult, hand_chips, False

    def debuff_hand(self, cards: list, hand: Any, handname: str, check: Any = None) -> bool | None:
        G = self.G
        if self.disabled:
            return None
        if self.debuff is not None:
            self.triggered = False
            d = self.debuff
            if d.hand and hand[d.hand]:
                self.triggered = True
                return True
            if d.h_size_ge and len(cards) < d.h_size_ge:
                self.triggered = True
                return True
            if d.h_size_le and len(cards) > d.h_size_le:
                self.triggered = True
                return True
            if self.name == "The Eye":
                if self.hands[handname]:
                    self.triggered = True
                    return True
                if not check:
                    self.hands[handname] = True
            if self.name == "The Mouth":
                if self.only_hand and self.only_hand != handname:
                    self.triggered = True
                    return True
                if not check:
                    self.only_hand = handname
        if self.name == "The Arm":
            self.triggered = False
            if G.GAME.hands[handname].level > 1:
                self.triggered = True
                if not check:
                    G.level_up_hand(None, handname, None, -1)
        if self.name == "The Ox":
            self.triggered = False
            if handname == G.GAME.current_round.most_played_poker_hand:
                self.triggered = True
                if not check:
                    G.ease_dollars(-G.GAME.dollars, True)
        return None

    def drawn_to_hand(self) -> None:
        G = self.G
        if not self.disabled:
            if self.name == "Cerulean Bell":
                any_forced = any(v.ability.forced_selection for v in G.hand.cards)
                if not any_forced:
                    G.hand.unhighlight_all()
                    forced = G._random_card_from(G.hand.cards, "cerulean_bell")
                    forced.ability.forced_selection = True
                    G.hand.add_to_highlighted(forced)
            if self.name == "Crimson Heart" and self.prepped and G.jokers.cards:
                jokers = []
                for c in G.jokers.cards:
                    if not c.debuff or len(G.jokers.cards) < 2:
                        jokers.append(c)
                    c.set_debuff(False)
                if jokers:
                    card = G._random_card_from(jokers, "crimson_heart")
                    card.set_debuff(True)
                else:
                    # pseudorandom_element on an empty table still advances the stream
                    G.rng.pseudoseed("crimson_heart")
        self.prepped = None

    def stay_flipped(self, area: "CardArea", card: "Card") -> bool | None:
        G = self.G
        if not self.disabled:
            if area is G.hand:
                if self.name == "The Wheel" and G.rng.random(G.rng.pseudoseed("wheel")) < G.GAME.probabilities.normal / 7:
                    return True
                if self.name == "The House" and G.GAME.current_round.hands_played == 0 and G.GAME.current_round.discards_used == 0:
                    return True
                if self.name == "The Mark" and card.is_face(True):
                    return True
                if self.name == "The Fish" and self.prepped:
                    return True
        return None

    def debuff_card(self, card: "Card", from_blind: Any = None) -> None:
        G = self.G
        d = self.debuff
        if d is not None and not self.disabled and card.area is not G.jokers:
            if d.suit and card.is_suit(d.suit, True):
                card.set_debuff(True)
                return
            if d.is_face == "face" and card.is_face(True):
                card.set_debuff(True)
                return
            if self.name == "The Pillar" and card.ability.played_this_ante:
                card.set_debuff(True)
                return
            if d.value and d.value == card.base.value:
                card.set_debuff(True)
                return
            if d.nominal and d.nominal == card.base.nominal:
                card.set_debuff(True)
                return
        if self.name == "Crimson Heart" and not self.disabled and card.area is G.jokers:
            return
        if self.name == "Verdant Leaf" and not self.disabled and card.area is not G.jokers:
            card.set_debuff(True)
            return
        card.set_debuff(False)
