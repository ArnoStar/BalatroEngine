"""Coop: two players play one run together, in turns.

- **Shared**: the run (money, shop, vouchers, tags, consumables, hand levels,
  the blinds), the hands and the discards of a round (the hands as in the
  game, the discards doubled), and the jokers: 10 slots, 5 for each player.
  Every joker counts, whoever's it is; a player buys, sells and moves only
  their own (``owner``).
- **Each player's own**: their deck (with its hand and discard pile, the
  seats' card areas). The second player's deck is shuffled on its own random
  stream: the first player's deck goes as in the original game.
- **Turns**: the player whose turn it is plays from their deck (play, discard,
  sort, the blind's choice, consumables during the round); after each hand
  they play, the turn passes to the other player, whose own hand comes up
  (drawn the first time in the round). A round starts with the player who
  didn't play last.
- **The shop**: both buy (for themselves: a joker goes in their half, a
  playing card in their deck, a pack is theirs to open); the shop is left once
  both players have asked to leave it.
- **The blinds** grow faster: ``(1 + BLIND_GROWTH * (ante - 1))`` times the game's.
- **Each player's numbers** (``stats``): the hands they played and their
  chips, their best hand, their discards (for the players to compare).

Commands carry the player's ``seat`` (0 or 1); legal actions are a seat's
(``viewer``). Feedback has ``{"type": "turn", "seat": ...}`` when the turn
passes, and ``{"type": "shop_vote", ...}`` when a player asks to leave the shop.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ..actions import IllegalAction
from ..cardarea import CardArea
from . import Mod

if TYPE_CHECKING:
    from ..card import Card
    from ..game import Game

SEATS = 2
BLIND_GROWTH = 0.35
TURN_COMMANDS = ("play", "discard", "sort", "select_blind", "skip_blind", "reroll_boss")


class Seat:
    """A player's own card areas."""

    def __init__(self, deck: CardArea, hand: CardArea, discard: CardArea) -> None:
        self.deck = deck
        self.hand = hand
        self.discard = discard
        self.round_seen = -1  # the round its deck was last shuffled for


class Coop(Mod):
    key = "coop"

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.seats: list[Seat] = []
        self.turn = 0  # whose turn it is
        self.active = 0  # whose card areas are the game's (G.hand, G.deck, G.discard)
        self.limits = [0, 0]  # each player's joker slots
        self.shop_votes: list[int] = []  # who asked to leave the shop
        self.pack_seat: int | None = None  # who opened the pack on screen
        self.viewer: int | None = None  # whose legal actions G.legal_actions() lists (None: the turn's)
        self.stats: list[dict[str, Any]] = [new_stats() for _ in range(SEATS)]
        self._acting = 0
        self._last_score: Any = None
        self._limit_before = 0

    # ------------------------------------------------------------ set-up
    def setup(self, G: "Game") -> None:
        G.GAME.starting_params.discards = G.GAME.starting_params.discards * 2

    def start(self, G: "Game") -> None:
        sp = G.GAME.starting_params
        first = Seat(G.deck, G.hand, G.discard)
        second = Seat(CardArea(G, "deck", {"card_limit": 52, "type": "deck"}),
                      CardArea(G, "hand", {"card_limit": sp.hand_size, "type": "hand"}),
                      CardArea(G, "discard", {"card_limit": 500, "type": "discard"}))
        G.deck = second.deck
        challenge = G.data.challenge(G.challenge_id) if G.challenge_id else None
        for p in G.starting_protos(challenge):
            G.card_from_control(p)
        G.deck = first.deck
        self.seats = [first, second]
        self.limits = [sp.joker_slots, sp.joker_slots]
        G.jokers.config.card_limit = sp.joker_slots * SEATS

    # ------------------------------------------------------------ seats
    def use(self, G: "Game", seat: int) -> None:
        """The seat's card areas become the game's."""
        if seat == self.active or not self.seats:
            return
        s = self.seats[seat]
        G.deck, G.hand, G.discard = s.deck, s.hand, s.discard
        self.active = seat

    def owner(self, card: "Card") -> int | None:
        return getattr(card, "seat", None)

    def jokers_of(self, G: "Game", seat: int) -> list["Card"]:
        return [c for c in G.jokers.cards if self.owner(c) == seat]

    def has_room(self, G: "Game", seat: int, card: "Card | None" = None) -> bool:
        neg = 1 if card is not None and card.edition and card.edition.negative else 0
        return len(self.jokers_of(G, seat)) < self.limits[seat] + neg

    def own_jokers(self, G: "Game", acting: int) -> None:
        """New jokers are the acting player's (or the other's, when theirs is full); each player's together."""
        delta = G.jokers.config.card_limit - self._limit_before
        if delta:
            self.limits[acting] += delta
        changed = False
        for c in G.jokers.cards:
            if self.owner(c) is None:
                c.seat = acting if self.has_room(G, acting) or not self.has_room(G, 1 - acting) else 1 - acting
                changed = True
        if changed:
            order = {id(c): i for i, c in enumerate(G.jokers.cards)}
            G.jokers.cards.sort(key=lambda c: (self.owner(c) or 0, order[id(c)]))

    def bring_up(self, G: "Game", seat: int) -> None:
        """The seat's hand on the table, mid-round: its deck shuffled for the round the first time, its hand drawn."""
        GAME = G.GAME
        self.use(G, seat)
        G._feedback("turn", seat=seat)
        s = self.seats[seat]
        if s.round_seen != GAME.round:
            s.round_seen = GAME.round
            if not G.hand.cards:
                G.deck.shuffle("nr" + G.ante_str())
        G.settle()  # (an empty hand is drawn by the state machine, as after a hand)

    def clear_hand(self, G: "Game") -> None:
        """A hand left over when its round ended: its cards held at the end of the round, then back to the deck."""
        if not G.hand.cards and not G.discard.cards:
            return
        if G.hand.cards:
            G.end_of_round_hand()
            G.draw_from_hand_to_discard()
        G.draw_from_discard_to_deck()
        G.settle()

    # ------------------------------------------------------------ rules
    def blind_amount(self, G: "Game", ante: int, amount: float) -> float:
        if amount is None or ante < 1:
            return amount
        x = amount * (1 + BLIND_GROWTH * (ante - 1))
        if x != x or x == math.inf or x < 1000:
            return x
        step = 10 ** (math.floor(math.log10(x)) - 1)
        return x - x % step

    def hand_size_changed(self, G: "Game", area: CardArea, delta: int) -> None:
        for s in self.seats:
            if s.hand is not area:
                real = s.hand.config.real_card_limit if s.hand.config.real_card_limit is not None else s.hand.config.card_limit
                s.hand.config.real_card_limit = real + delta
                s.hand.config.card_limit = max(0, s.hand.config.real_card_limit)

    def shuffle_key(self, G: "Game", area: CardArea, key: str) -> str:
        if len(self.seats) == SEATS and area is self.seats[1].deck:
            return key + "_2"
        return key

    # ------------------------------------------------------------ commands
    def check(self, G: "Game", seat: int, cmd: dict) -> None:
        """What the seat may do now (raises IllegalAction)."""
        c = cmd.get("cmd")
        S = G.STATES
        if c in TURN_COMMANDS and seat != self.turn:
            raise IllegalAction("it is the other player's turn")
        if c == "use" and G.STATE == S.SELECTING_HAND and seat != self.turn:
            raise IllegalAction("it is the other player's turn")
        if c in ("pick", "skip_pack") and self.pack_seat is not None and seat != self.pack_seat:
            raise IllegalAction("the other player opened this pack")
        if c in ("sell", "move") and cmd.get("area") == "jokers":
            a = G.jokers.cards
            idx = [cmd.get("index")] if c == "sell" else [cmd.get("from"), cmd.get("to")]
            for i in idx:
                if not isinstance(i, int) or not 0 <= i < len(a) or self.owner(a[i]) != seat:
                    raise IllegalAction("that joker is the other player's")
        if c == "move" and cmd.get("area") == "hand" and seat != self.turn:
            raise IllegalAction("it is the other player's turn")
        if c == "buy" and cmd.get("area") == "shop_jokers" and G.shop_jokers is not None:
            i = cmd.get("index")
            if isinstance(i, int) and 0 <= i < len(G.shop_jokers.cards):
                card = G.shop_jokers.cards[i]
                if card.ability.set == "Joker" and not self.has_room(G, seat, card):
                    raise IllegalAction("your joker slots are full")

    def before_command(self, G: "Game", cmd: dict) -> None:
        seat = cmd.get("seat", 0)
        if seat not in range(SEATS):
            raise IllegalAction("seat 0 or 1")
        self.check(G, seat, cmd)
        self._acting = seat
        self._limit_before = G.jokers.config.card_limit
        self._last_score = G.last_score
        # in the shop, a player acts with their own areas (a playing card bought goes in their deck, a pack is theirs)
        if G.in_shop() and cmd.get("cmd") in ("buy", "reroll", "use", "sell"):
            self.use(G, seat)

    def command(self, G: "Game", cmd: dict) -> bool:
        if cmd.get("cmd") != "end_shop":
            return False
        G._require(G.in_shop(), "not in the shop")
        seat = cmd.get("seat", 0)
        if seat not in self.shop_votes:
            self.shop_votes.append(seat)
        G._feedback("shop_vote", seats=list(self.shop_votes))
        if len(self.shop_votes) < SEATS:
            return True  # (the other player is still shopping)
        self.shop_votes = []
        self.use(G, self.turn)
        G.act_end_shop()
        return True

    def after_command(self, G: "Game", cmd: dict) -> None:
        S = G.STATES
        c = cmd.get("cmd")
        seat = self._acting
        self.own_jokers(G, seat)
        if c == "select_blind":
            self.seats[self.active].round_seen = G.GAME.round
        self.count(G, seat, c)
        if c == "play":
            self.turn = 1 - seat  # (after each hand: a round starts with the player who didn't play last)
        if G.STATE == S.SELECTING_HAND and self.active != self.turn:
            self.bring_up(G, self.turn)
        elif G.STATE in (S.ROUND_EVAL, S.GAME_OVER) and self.seats:
            # the round is over: the other player's hand back in their deck too
            other = 1 - self.active
            if self.seats[other].hand.cards or self.seats[other].discard.cards:
                self.use(G, other)
                self.clear_hand(G)
            if self.active != self.turn:
                self.use(G, self.turn)
                G._feedback("turn", seat=self.turn)
        # a pack is its opener's until it closes; then the turn's areas again
        if G.in_pack():
            if self.pack_seat is None:
                self.pack_seat = self.active
        else:
            self.pack_seat = None
            if G.STATE in (S.SHOP, S.BLIND_SELECT, S.ROUND_EVAL) and self.active != self.turn:
                self.use(G, self.turn)
        if not G.in_shop():
            self.shop_votes = []

    def count(self, G: "Game", seat: int, c: str | None) -> None:
        """The player's numbers after their command (a hand played: its score, from the scoring)."""
        st = self.stats[seat]
        if c == "discard":
            st["discards"] += 1
        elif c == "play" and G.last_score is not None and G.last_score is not self._last_score:
            score = G.last_score.score
            st["hands"] += 1
            st["chips"] += score
            if score > st["best_hand"]:
                st["best_hand"], st["best_hand_name"] = score, G.last_score.hand

    def legal_actions(self, G: "Game", actions: list[dict]) -> list[dict]:
        seat = self.turn if self.viewer is None else self.viewer
        out = []
        for a in actions:
            if a.get("cmd") == "sell" and a.get("area") == "jokers":
                i = a.get("index")
                if not (isinstance(i, int) and i < len(G.jokers.cards) and self.owner(G.jokers.cards[i]) == seat):
                    continue
            try:
                self.check(G, seat, a)
            except IllegalAction:
                continue
            out.append(a)
        if seat in self.shop_votes:
            out = [a for a in out if a.get("cmd") != "end_shop"]
        return out

    def state(self) -> dict[str, Any]:
        return {"turn": self.turn, "limits": list(self.limits), "shop_votes": list(self.shop_votes),
                "pack_seat": self.pack_seat,
                "decks": [{"remaining": len(s.deck.cards), "hand": len(s.hand.cards)} for s in self.seats],
                "stats": [dict(st) for st in self.stats]}

    def seat_cards(self, seat: int) -> list["Card"]:
        """The seat's playing cards in its deck, hand and discard pile."""
        s = self.seats[seat]
        return [*s.deck.cards, *s.hand.cards, *s.discard.cards]


def new_stats() -> dict[str, Any]:
    return {"hands": 0, "chips": 0, "best_hand": 0, "best_hand_name": None, "discards": 0}


def owner_of(card: Any) -> int | None:
    return getattr(card, "seat", None)


__all__ = ["BLIND_GROWTH", "Coop", "SEATS", "owner_of"]
