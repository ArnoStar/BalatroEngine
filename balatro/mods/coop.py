"""Coop: two players play one run together, in turns.

- **Shared**: the run (money, shop, vouchers, tags, consumables, hand levels,
  the blinds), the deck and its hand, the hands and the discards of a round
  (the hands as in the game, the discards doubled), and the jokers: 10 slots,
  5 for each player. Every joker counts, whoever's it is; a player buys,
  sells and moves only their own (``owner``).
- **Turns**: the player whose turn it is plays (play, discard, sort, the
  blind's choice, consumables during the round); after each hand they play,
  the turn passes to the other player, who goes on with the hand. A round
  starts with the player who didn't play last.
- **The shop**: both buy (for themselves: a joker goes in their half, a pack
  is theirs to open: they choose its cards, and the hand's cards it is used
  on); the shop is left once both players have asked to leave it. A player's
  ask holds until the shop is left, a pack the other opens meanwhile included.
- **Rules** (option ``rules``): ``3`` (the default) is the above; ``2``, the
  rules of engine 0.9.0, is ``votes="reset"``; ``1``, the rules until engine
  0.9.0, is also ``decks="own"`` and ``blinds="linear"`` (a run replays with
  the rules it was started with). ``decks``, ``blinds`` and ``votes`` can also
  be given on their own.
- **Votes** (option ``votes``): ``"kept"`` (rules 3) is the above;
  ``"reset"`` (rules 1 and 2): a pack opened in the shop drops the asks to
  leave it (a player who had asked must ask again).
- **Decks** (option ``decks``): ``"shared"`` (rules 2) is the above;
  ``"own"``, the rules until engine 0.9.0 (runs started with them replay with
  them): each player has their own deck, with its hand and discard pile (the
  seats' card areas), and the second player's deck is shuffled on its own
  random stream (the first player's deck goes as in the original game). On
  their turn a player plays from their own hand, drawn the first time in the
  round; a playing card bought goes in its buyer's deck, a pack deals its
  opener's hand.
- **The blinds** grow faster (two players' jokers make far bigger hands):
  ``max(1 + BLIND_GROWTH * (ante - 1), exp(BLIND_STEEPNESS * (ante - 1)²))``
  times the game's: x1.35 at ante 2, x2.46 at ante 4, x12.2 at ante 6, x134 at
  ante 8 (option ``blinds``: ``"steep"``; ``"linear"``, until engine 0.9.0:
  ``1 + BLIND_GROWTH * (ante - 1)``, x3.45 at ante 8).
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
BLIND_STEEPNESS = 0.1
TURN_COMMANDS = ("play", "discard", "sort", "select_blind", "skip_blind", "reroll_boss")
DECKS = ("shared", "own")
BLINDS = ("steep", "linear")
VOTES = ("kept", "reset")
RULES = {1: {"decks": "own", "blinds": "linear", "votes": "reset"},
         2: {"decks": "shared", "blinds": "steep", "votes": "reset"},
         3: {"decks": "shared", "blinds": "steep", "votes": "kept"}}
LATEST_RULES = 3


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
        rules = options.get("rules", LATEST_RULES)
        if rules not in RULES:
            raise ValueError(f"coop's rules are one of {', '.join(map(str, RULES))}")
        decks = options.get("decks", RULES[rules]["decks"])
        blinds = options.get("blinds", RULES[rules]["blinds"])
        votes = options.get("votes", RULES[rules]["votes"])
        if decks not in DECKS:
            raise ValueError(f"coop's decks are one of {', '.join(DECKS)}")
        if blinds not in BLINDS:
            raise ValueError(f"coop's blinds are one of {', '.join(BLINDS)}")
        if votes not in VOTES:
            raise ValueError(f"coop's votes are one of {', '.join(VOTES)}")
        self.own_decks = decks == "own"  # each player's own deck (rules 1)
        self.steep_blinds = blinds == "steep"
        self.kept_votes = votes == "kept"  # a pack opened in the shop keeps the asks to leave it (rules 3)
        self.seats: list[Seat] = []  # (own decks: each player's card areas)
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
        self.limits = [sp.joker_slots, sp.joker_slots]
        G.jokers.config.card_limit = sp.joker_slots * SEATS
        if not self.own_decks:
            return
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
        x = amount * blind_factor(ante, self.steep_blinds)
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

    def hand_seat(self, G: "Game") -> int:
        """Whose the hand is to select: the pack's opener's while it is open, else the turn's player's."""
        return self.pack_seat if G.in_pack() and self.pack_seat is not None else self.turn

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
        if c == "move" and cmd.get("area") == "hand" and seat != (self.turn if self.own_decks else self.hand_seat(G)):
            raise IllegalAction("it is the other player's turn")
        if c == "use" and not self.own_decks and G.in_pack() and seat != self.pack_seat:
            raise IllegalAction("the other player opened this pack")
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
        self.count(G, seat, c)
        if c == "play":
            self.turn = 1 - seat  # (after each hand: a round starts with the player who didn't play last)
        if self.own_decks:
            self.own_decks_after(G, c)
        elif c == "play" and G.STATE == S.SELECTING_HAND:
            G._feedback("turn", seat=self.turn)  # (the other player goes on with the hand)
        # a pack is its opener's until it closes
        if G.in_pack():
            if self.pack_seat is None:
                self.pack_seat = self.active if self.own_decks else seat
        else:
            self.pack_seat = None
            if G.STATE in (S.SHOP, S.BLIND_SELECT, S.ROUND_EVAL) and self.active != self.turn:
                self.use(G, self.turn)  # (own decks: the turn's areas again)
        if not G.in_shop() and not (self.kept_votes and G.in_pack()):
            self.shop_votes = []

    def own_decks_after(self, G: "Game", c: str | None) -> None:
        """Own decks: the turn's player's hand up, and the hands left over at a round's end back in their decks."""
        S = G.STATES
        if c == "select_blind":
            self.seats[self.active].round_seen = G.GAME.round
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
                "pack_seat": self.pack_seat, "decks_mode": "own" if self.own_decks else "shared",
                "blinds": "steep" if self.steep_blinds else "linear", "votes": "kept" if self.kept_votes else "reset",
                "decks": [{"remaining": len(s.deck.cards), "hand": len(s.hand.cards)} for s in self.seats],
                "stats": [dict(st) for st in self.stats]}

    def seat_cards(self, seat: int) -> list["Card"]:
        """The seat's playing cards in its deck, hand and discard pile."""
        s = self.seats[seat]
        return [*s.deck.cards, *s.hand.cards, *s.discard.cards]


def blind_factor(ante: int, steep: bool = True) -> float:
    """How many times the game's chips a blind of this ante asks for."""
    linear = 1 + BLIND_GROWTH * (ante - 1)
    if not steep:
        return linear
    try:
        return max(linear, math.exp(BLIND_STEEPNESS * (ante - 1) ** 2))
    except OverflowError:
        return math.inf


def new_stats() -> dict[str, Any]:
    return {"hands": 0, "chips": 0, "best_hand": 0, "best_hand_name": None, "discards": 0}


def owner_of(card: Any) -> int | None:
    return getattr(card, "seat", None)


__all__ = ["BLINDS", "BLIND_GROWTH", "BLIND_STEEPNESS", "Coop", "DECKS", "LATEST_RULES", "RULES", "SEATS",
           "blind_factor", "owner_of"]
