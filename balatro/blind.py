"""Port of blind.lua (game logic and the events it queues)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .lua import T, lor, nonempty

if TYPE_CHECKING:
    from .card import Card
    from .game import Game

HAND_NAMES = ("Flush Five", "Flush House", "Five of a Kind", "Straight Flush", "Four of a Kind", "Full House",
              "Flush", "Straight", "Three of a Kind", "Two Pair", "Pair", "High Card")


class Blind:
    def __init__(self, G: "Game") -> None:
        self.G = G
        self.config = T()
        self.chips = 0
        self.name: str | None = None
        self.dollars = 0
        self.debuff: T | None = None
        self.sound_pings: int | None = None
        self.blind_set = False
        self.mult = 0
        self.disabled = False
        self.boss = None
        self.triggered = None
        self.prepped = None
        self.discards_sub = None
        self.hands_sub = None
        self.hands: T | None = None
        self.only_hand = None
        self.block_play = None
        self.loc_debuff_text = ""
        self.dissolve = None

    def __repr__(self) -> str:
        return f"<Blind {self.name}>"

    # -------------------------------------------------------- set_blind
    def set_blind(self, blind: T | None = None, reset: Any = None, silent: Any = None) -> None:
        G = self.G
        GAME = G.GAME
        if not reset:
            self.config.blind = blind or T()
            self.name = blind.name if blind else ""
            self.dollars = blind.dollars if blind else 0
            self.sound_pings = self.dollars + 2
            if GAME.modifiers.no_blind_reward and GAME.modifiers.no_blind_reward.get(self.get_type()):
                self.dollars = 0
            self.debuff = (blind.debuff if blind else None) or T()
            self.mult = (blind.mult if blind else None) or 0
            self.disabled = False
            self.discards_sub = None
            self.hands_sub = None
            self.boss = bool(blind and blind.boss)
            self.blind_set = False
            self.triggered = None
            self.prepped = True
            self.set_text()
            GAME.last_blind = GAME.last_blind or T()
            GAME.last_blind.boss = self.boss
            GAME.last_blind.name = self.name
            self.chips = G.get_blind_amount(GAME.round_resets.ante) * self.mult * GAME.starting_params.ante_scaling
            if not blind:
                self.chips = 0
            if blind and blind.name and blind.name != "":
                self.alert_debuff(True)

                def show() -> bool:
                    def show2() -> None:
                        self.blind_set = True
                    G.ev(show2, trigger="after", delay=0.15, blockable=False)
                    return True
                G.event(show, trigger="after", delay=0.05, blockable=False)
        name = self.name
        if name == "The Eye" and not reset:
            self.hands = T({h: False for h in HAND_NAMES})
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
                    G.ev(lambda: G.jokers.shuffle("aajk"))
                    G.delay(0.15)
                    G.ev(lambda: G.jokers.shuffle("aajk"))
                    G.delay(0.15)
                    G.ev(lambda: G.jokers.shuffle("aajk"))
                    G.delay(0.5)
                G.ev(shuffles, trigger="after", delay=0.2)
        for v in list(G.playing_cards):
            self.debuff_card(v)
        for v in list(G.jokers.cards):
            if not reset:
                self.debuff_card(v, True)

    def set_text(self) -> None:
        """Only whether the debuff text is empty matters (it starts
        alert_debuff): every boss has a description, Small/Big have none."""
        if self.config.blind is not None:
            if self.disabled:
                self.loc_debuff_text = ""
            else:
                self.loc_debuff_text = "x" if self.config.blind.boss else ""

    def alert_debuff(self, first: Any = None) -> None:
        G = self.G
        if self.loc_debuff_text and self.loc_debuff_text != "":
            self.block_play = True

            def wait() -> bool | None:
                if self.disabled:
                    self.block_play = None
                    return True
                if G.STATE == G.STATES.SELECTING_HAND:
                    def alert() -> None:
                        for i in range(1, 5):
                            G.ev(None, blockable=False, trigger="after", delay=G.SETTINGS.GAMESPEED * (0.1 * (i - 1)))

                        def unblock() -> None:
                            self.block_play = None
                        G.ev(unblock, trigger="after", delay=1, blocking=False, blockable=False)
                    G.ev(alert, trigger="after", delay=G.SETTINGS.GAMESPEED * 0.05, blockable=False)
                    return True
                return None
            G.event(wait, blockable=False, blocking=False)

    # ------------------------------------------------------------ defeat
    def defeat(self, silent: Any = None) -> None:
        G = self.G
        dissolve_time = 1.3
        self.dissolve = 0
        G.ev(None, trigger="after", blockable=False, delay=0.5 * dissolve_time)
        if not silent:
            pings = lor(self.sound_pings, 3)
            for i in range(1, min(pings, 7) + 1):
                G.ev(None, blockable=False, trigger="after", delay=(0.15 - 0.01 * pings) * i * dissolve_time)
        G.ev(None, trigger="ease", blockable=False, delay=0.7 * dissolve_time)
        G.ev(None, trigger="after", blockable=False, delay=0.8 * dissolve_time)

        def finish() -> None:
            self.dissolve = None
            self.set_blind(None, None, True)
        G.ev(finish, trigger="after", blockable=False, delay=0.95 * dissolve_time)
        for v in G.jokers.cards:
            if v.facing == "back":
                v.flip()
        if self.name == "The Manacle" and not self.disabled:
            G.hand.change_size(1)

    def get_type(self) -> str | None:
        if self.name == "Small Blind":
            return "Small"
        if self.name == "Big Blind":
            return "Big"
        if self.name and self.name != "":
            return "Boss"
        return None

    def disable(self) -> None:
        G = self.G
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
            if self.boss and G.GAME.chips - G.GAME.blind.chips >= 0:
                G.STATE = G.STATES.NEW_ROUND
                G.STATE_COMPLETE = False
        G.ev(check)
        for v in list(G.playing_cards):
            self.debuff_card(v)
        for v in list(G.jokers.cards):
            self.debuff_card(v)
        self.set_text()
        self.wiggle()

    def wiggle(self) -> None:
        pass  # a non-blocking sound event

    # ------------------------------------------------------------ playing
    def press_play(self) -> bool | None:
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
                        k = G.random_card_index(cards, "hook")
                        selected = cards[k]
                        G.hand.add_to_highlighted(selected, True)
                        del cards[k]
                        any_selected = True
                if any_selected:
                    G.discard_cards_from_highlighted(None, True)
            G.ev(hook)
            self.triggered = True
            G.delay(0.7)
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
                    G.ev(None)
                    G.ease_dollars(-1)
                    G.delay(0.23)
            G.ev(tooth, trigger="after", delay=0.2)
            self.triggered = True
            return True
        return None

    def modify_hand(self, cards: list["Card"], poker_hands: T, text: str, mult: float, hand_chips: float
                    ) -> tuple[float, float, bool]:
        if self.disabled:
            return mult, hand_chips, False
        if self.name == "The Flint":
            self.triggered = True
            G = self.G
            return max(G.floor(mult * 0.5 + 0.5), 1), max(G.floor(hand_chips * 0.5 + 0.5), 0), True
        return mult, hand_chips, False

    def debuff_hand(self, cards: list["Card"], hand: T, handname: str, check: Any = None) -> bool | None:
        G = self.G
        if self.disabled:
            return None
        if self.debuff is not None:
            self.triggered = False
            d = self.debuff
            if d.hand and nonempty(hand[d.hand]):
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
                    self.wiggle()
        if self.name == "The Ox":
            self.triggered = False
            if handname == G.GAME.current_round.most_played_poker_hand:
                self.triggered = True
                if not check:
                    G.ease_dollars(-G.GAME.dollars, True)
                    self.wiggle()
        return None

    def drawn_to_hand(self) -> None:
        G = self.G
        if not self.disabled:
            if self.name == "Cerulean Bell":
                if not any(v.ability.forced_selection for v in G.hand.cards):
                    G.hand.unhighlight_all()
                    forced = G.random_card_from(list(G.hand.cards), "cerulean_bell")
                    forced.ability.forced_selection = True
                    G.hand.add_to_highlighted(forced)
            if self.name == "Crimson Heart" and self.prepped and G.jokers.cards:
                jokers = []
                n = len(G.jokers.cards)
                for c in list(G.jokers.cards):
                    if not c.debuff or n < 2:
                        jokers.append(c)
                    c.set_debuff(False)
                if jokers:
                    card = G.random_card_from(jokers, "crimson_heart")
                    card.set_debuff(True)
                    self.wiggle()
                else:
                    G.rng.pseudoseed("crimson_heart")
        self.prepped = None

    def stay_flipped(self, area: Any, card: "Card") -> bool | None:
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
