"""Port of cardarea.lua (game logic only).

Cards are kept in their on-screen left-to-right order, which is what the
game's ``align_cards`` (sorting by x position every frame) maintains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .lua import T

if TYPE_CHECKING:
    from .card import Card
    from .game import Game


class CardArea:
    def __init__(self, G: "Game", name: str, config: dict[str, Any]) -> None:
        self.G = G
        self.name = name
        self.cards: list[Card] = []
        self.highlighted: list[Card] = []
        self.config = T(config)
        self.config.highlighted_limit = config.get("highlight_limit", 5)
        self.config.card_limit = config.get("card_limit", 52)
        self.config.temp_limit = self.config.card_limit
        self.config.card_count = 0
        self.config.type = config.get("type", "deck")
        self.config.sort = config.get("sort", "desc")
        self.removed = False

    def __repr__(self) -> str:
        return f"<CardArea {self.name} {self.cards}>"

    # ----------------------------------------------------------------- core
    def emplace(self, card: "Card", location: str | None = None, stay_flipped: Any = None) -> None:
        G = self.G
        if location == "front" or self.config.type == "deck":
            self.cards.insert(0, card)
        else:
            self.cards.append(card)
        if card.facing == "back" and self.config.type not in ("discard", "deck") and not stay_flipped:
            card.flip()
        if self is G.hand and stay_flipped:
            card.ability.wheel_flipped = True
        if len(self.cards) > self.config.card_limit:
            if self is G.deck:
                self.config.card_limit = len(self.cards)
        card.area = self
        self.align_cards()
        if self is G.jokers:
            tally = sum(1 for c in self.cards if c.ability.set == "Joker")
            if tally > G.GAME.max_jokers:
                G.GAME.max_jokers = tally

    def remove_card(self, card: "Card | None" = None, discarded_only: bool = False) -> "Card | None":
        if self.removed:
            return None
        cards = self.cards
        if discarded_only:
            cards = [v for v in self.cards if v.ability and v.ability.discarded]
        if self.config.type in ("discard", "deck"):
            card = card or (cards[-1] if cards else None)
        else:
            card = card or (cards[0] if cards else None)
        for i in range(len(self.cards) - 1, -1, -1):
            if self.cards[i] is card:
                card.area = None
                del self.cards[i]
                self.remove_from_highlighted(card, True)
                break
        return card

    def change_size(self, delta: int) -> None:
        G = self.G
        if delta == 0:
            return

        def ev() -> None:
            real = self.config.real_card_limit if self.config.real_card_limit is not None else self.config.card_limit
            self.config.real_card_limit = real + delta
            self.config.card_limit = max(0, self.config.real_card_limit)
            if (delta > 0 and self.config.real_card_limit > 1 and self is G.hand and self.cards
                    and (G.STATE == G.STATES.DRAW_TO_HAND or G.STATE == G.STATES.SELECTING_HAND)):
                for _ in range(abs(delta)):
                    G.draw_card(G.deck, G.hand, None, None, None, None, 0.07)
                    G.ev(self.sort)
        G.ev(ev)

    # ------------------------------------------------------------ highlight
    def add_to_highlighted(self, card: "Card", silent: Any = None) -> None:
        G = self.G
        t = self.config.type
        if t == "shop":
            if self.highlighted:
                self.remove_from_highlighted(self.highlighted[0])
            self.highlighted.append(card)
            card.highlight(True)
        elif t in ("joker", "consumeable"):
            if len(self.highlighted) >= self.config.highlighted_limit:
                self.remove_from_highlighted(self.highlighted[0])
            self.highlighted.append(card)
            card.highlight(True)
        else:
            if len(self.highlighted) >= self.config.highlighted_limit:
                card.highlight(False)
            else:
                self.highlighted.append(card)
                card.highlight(True)
            if self is G.hand and G.STATE == G.STATES.SELECTING_HAND:
                self.parse_highlighted()

    def parse_highlighted(self) -> None:
        """Previews the hand: queues the hand-text update (an event, and the
        hand name it shows decides a delay in evaluate_play) and lets the
        blind set its 'triggered' flag."""
        G = self.G
        G.boss_throw_hand = None
        text, disp_text, poker_hands, _s, _n = G.get_poker_hand_info(self.highlighted)
        if text == "NULL":
            G.update_hand_text(T(immediate=True, nopulse=True, delay=0), T(mult=0, chips=0, level="", handname=""))
        else:
            if G.GAME.blind and G.GAME.blind.debuff_hand(self.highlighted, poker_hands, text, True):
                G.boss_throw_hand = True
            if any(v.facing == "back" for v in self.highlighted):
                G.update_hand_text(T(immediate=True, delay=0), T(handname="????", level="?", mult="?", chips="?"))
            else:
                h = G.GAME.hands[text]
                G.update_hand_text(T(immediate=True, delay=0),
                                   T(handname=disp_text, level=h.level, mult=h.mult, chips=h.chips))

    def remove_from_highlighted(self, card: "Card", force: Any = None) -> None:
        G = self.G
        if not force and card is not None and card.ability.forced_selection and self is G.hand:
            return
        for i in range(len(self.highlighted) - 1, -1, -1):
            if self.highlighted[i] is card:
                del self.highlighted[i]
                break
        card.highlight(False)
        if self is G.hand and G.STATE == G.STATES.SELECTING_HAND:
            self.parse_highlighted()

    def unhighlight_all(self) -> None:
        G = self.G
        for i in range(len(self.highlighted) - 1, -1, -1):
            c = self.highlighted[i]
            if c.ability.forced_selection and self is G.hand:
                continue
            c.highlight(False)
            del self.highlighted[i]
        if self is G.hand and G.STATE == G.STATES.SELECTING_HAND:
            self.parse_highlighted()

    # ---------------------------------------------------------- order / rng
    def index(self, card: "Card") -> int:
        for i, c in enumerate(self.cards):
            if c is card:
                return i
        return -1

    def align_cards(self) -> None:
        """The logic in align_cards: deck and discard cards lie face down,
        and of the re-sorts by x position only the joker area's 'pinned
        first' rule can change an order."""
        t = self.config.type
        if t == "deck" or t == "discard":
            for c in self.cards:
                if c.facing == "front":
                    c.flip()
        elif t == "joker" and any(c.pinned for c in self.cards):
            order = {id(c): i for i, c in enumerate(self.cards)}
            self.cards.sort(key=lambda c: (0, -c.sort_id) if c.pinned else (1, order[id(c)]))

    def shuffle(self, seed: str | None = None) -> None:
        G = self.G
        cards = self.cards
        if cards and cards[0].sort_id is not None:
            cards.sort(key=lambda c: c.sort_id)
        G.rng.shuffle(cards, G.rng.pseudoseed(seed or "shuffle"))

    def sort(self, method: str | None = None) -> None:
        self.config.sort = method or self.config.sort
        m = self.config.sort
        # keys are distinct (get_nominal includes the per-card unique_val), so
        # Python's sort matches Lua's table.sort
        if m == "desc":
            self.cards.sort(key=lambda c: c.get_nominal(), reverse=True)
        elif m == "asc":
            self.cards.sort(key=lambda c: c.get_nominal())
        elif m == "suit desc":
            self.cards.sort(key=lambda c: c.get_nominal("suit"), reverse=True)
        elif m == "suit asc":
            self.cards.sort(key=lambda c: c.get_nominal("suit"))
        elif m == "order":
            self.cards.sort(key=lambda c: c.config.card.order if c.config.card.order is not None else c.config.center.order)

    def draw_card_from(self, area: "CardArea", stay_flipped: Any = None, discarded_only: bool = False) -> bool:
        G = self.G
        if len(self.cards) < self.config.card_limit or self is G.deck or self is G.hand:
            card = area.remove_card(None, discarded_only)
            if card is not None:
                stay = G.GAME.blind.stay_flipped(self, card) if G.GAME and G.GAME.blind else None
                if self is G.hand and G.GAME.modifiers.flipped_cards:
                    if G.rng.random(G.rng.pseudoseed("flipped_card")) < 1 / G.GAME.modifiers.flipped_cards:
                        stay = True
                self.emplace(card, None, stay)
                return True
        return False

    # ------------------------------------------------------------ per frame
    def update(self) -> None:
        G = self.G
        if self is G.hand:
            per = G.GAME.modifiers.minus_hand_size_per_X_dollar
            if per:
                self.config.last_poll_size = self.config.last_poll_size or 0
                now = G.floor(G.GAME.dollars / per)
                if now != self.config.last_poll_size:
                    self.change_size(self.config.last_poll_size - now)
                    self.config.last_poll_size = now
            for v in list(self.cards):
                if v.ability.forced_selection and not self.highlighted:
                    self.add_to_highlighted(v)
        if self is G.deck and self.config.card_limit > len(G.playing_cards):
            self.config.card_limit = len(G.playing_cards)
        self.config.temp_limit = max(len(self.cards), self.config.card_limit)
        self.config.card_count = len(self.cards)

    def remove(self) -> None:
        """CardArea:remove(): every card in it is removed too."""
        cards = self.cards
        for i in range(len(cards) - 1, -1, -1):
            if i < len(cards):
                v = cards.pop(i)
                v.remove()
        self.cards = []
        self.removed = True
