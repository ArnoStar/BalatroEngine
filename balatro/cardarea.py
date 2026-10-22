"""Port of cardarea.lua (logic only; card order == on-screen left-to-right order)."""

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
    def emplace(self, card: "Card", location: str | None = None, stay_flipped: bool | None = None) -> None:
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
        if self.config.type in ("deck", "discard") and card.facing == "front":
            card.flip()  # align_cards() keeps deck/discard cards face down
        if self is G.jokers:
            joker_tally = sum(1 for c in self.cards if c.ability.set == "Joker")
            if joker_tally > G.GAME.max_jokers:
                G.GAME.max_jokers = joker_tally
        if self.config.type in ("hand", "joker", "consumeable", "title_2"):
            # align_cards keeps these ordered by x position == list order
            pass

    def remove_card(self, card: "Card | None" = None, discarded_only: bool = False) -> "Card | None":
        if self.removed:
            return None
        cards = self.cards
        if discarded_only:
            cards = [v for v in self.cards if v.ability and v.ability.discarded]
        if card is None:
            if not cards:
                return None
            if self.config.type in ("discard", "deck"):
                card = cards[-1]
            else:
                card = cards[0]
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
                    and G.STATE in (G.STATES.DRAW_TO_HAND, G.STATES.SELECTING_HAND)):
                for _ in range(abs(delta)):
                    G.draw_card(G.deck, G.hand)
                    G.add_event(lambda: self.sort())
        G.add_event(ev)

    # ------------------------------------------------------------ highlight
    def can_highlight(self, card: "Card") -> bool:
        return self.config.type in ("hand", "joker", "consumeable") or (
            self.config.type == "shop" and self.config.highlighted_limit > 0)

    def add_to_highlighted(self, card: "Card", silent: bool = False) -> None:
        if self.config.type == "shop":
            if self.highlighted:
                self.remove_from_highlighted(self.highlighted[0])
            self.highlighted.append(card)
            card.highlighted = True
        elif self.config.type in ("joker", "consumeable"):
            if len(self.highlighted) >= self.config.highlighted_limit:
                self.remove_from_highlighted(self.highlighted[0])
            self.highlighted.append(card)
            card.highlighted = True
        else:
            if len(self.highlighted) >= self.config.highlighted_limit:
                card.highlighted = False
            else:
                self.highlighted.append(card)
                card.highlighted = True

    def remove_from_highlighted(self, card: "Card", force: bool = False) -> None:
        G = self.G
        if not force and card is not None and card.ability.forced_selection and self is G.hand:
            return
        for i in range(len(self.highlighted) - 1, -1, -1):
            if self.highlighted[i] is card:
                del self.highlighted[i]
                break
        if card is not None:
            card.highlighted = False

    def unhighlight_all(self) -> None:
        G = self.G
        for i in range(len(self.highlighted) - 1, -1, -1):
            c = self.highlighted[i]
            if c.ability.forced_selection and self is G.hand:
                continue
            c.highlighted = False
            del self.highlighted[i]

    # ---------------------------------------------------------- order / rng
    def index(self, card: "Card") -> int:
        for i, c in enumerate(self.cards):
            if c is card:
                return i
        return -1

    def shuffle(self, seed: str | None = None) -> None:
        G = self.G
        self.cards.sort(key=lambda c: c.sort_id)
        G.rng.shuffle(self.cards, G.rng.pseudoseed(seed or "shuffle"))

    def sort(self, method: str | None = None) -> None:
        self.config.sort = method or self.config.sort
        m = self.config.sort
        # Lua's table.sort with a strict comparator; keys are all distinct
        # (get_nominal includes the per-card unique_val), so Python's stable
        # sort gives the same result.
        if m == "desc":
            self.cards.sort(key=lambda c: c.get_nominal(), reverse=True)
        elif m == "asc":
            self.cards.sort(key=lambda c: c.get_nominal())
        elif m == "suit desc":
            self.cards.sort(key=lambda c: c.get_nominal("suit"), reverse=True)
        elif m == "suit asc":
            self.cards.sort(key=lambda c: c.get_nominal("suit"))
        elif m == "order":
            self.cards.sort(key=lambda c: (c.config.card.order if c.config.card and c.config.card.order is not None
                                           else c.config.center.order))

    def draw_card_from(self, area: "CardArea", stay_flipped: bool | None = None, discarded_only: bool = False) -> bool:
        G = self.G
        if len(self.cards) < self.config.card_limit or self is G.deck or self is G.hand:
            card = area.remove_card(None, discarded_only)
            if card is not None:
                stay = G.GAME.blind.stay_flipped(self, card) if G.GAME.blind else None
                if self is G.hand and G.GAME.modifiers.flipped_cards:
                    if G.rng.random("flipped_card") < 1 / G.GAME.modifiers.flipped_cards:
                        stay = True
                self.emplace(card, None, stay)
                return True
        return False

    def remove(self) -> None:
        """CardArea:remove() -> every card in it is removed (Card:remove)."""
        for c in list(self.cards):
            c.remove()
        self.cards = []
        self.removed = True
