"""Creative mode: a content mod with ``"creative": true`` lets the player change
the run as they like, to try out the game's mechanics and other mods' items.

    G.do({"cmd": "creative", "op": "add", "key": "j_blueprint", "edition": "foil"})

Every change goes through the game's own functions (``add_joker``,
``set_edition``, ``change_size``, ``level_up_hand`` ...), so the game goes on
by its rules afterwards, and the change is a command like any other: a replay
of the run makes it again, exactly.  A change triggers no joker (adding a
card isn't Hologram's "a card is added to your deck"): it edits the run.

Operations (``op``):

==============  ==================================================================
``set``         ``what`` (money, hands, discards, hand_size, joker_slots,
                consumable_slots, ante, round_chips, reroll_cost, interest_cap)
                to ``value``
``level``       the ``hand``'s level to ``value`` (1 or more)
``add``         the center ``key``: a joker or consumable (``edition``,
                ``eternal``, ``perishable``, ``rental``), a voucher (redeemed for
                free) or a tag
``add_card``    a playing card (``rank``, ``suit``, ``enhancement``, ``edition``,
                ``seal``) ``to`` the hand (in a round) or the deck
``edit``        the card ``index`` of ``area`` (jokers, consumeables, hand):
                ``edition`` ("none" removes it), ``seal``, ``enhancement``,
                ``rank``, ``suit``, ``eternal``, ``perishable``, ``rental``
``remove``      the card ``index`` of ``area``
``boss``        the ante's boss blind becomes ``key`` (at the blind select)
``win``         the round is won now (playing a round)
==============  ==================================================================
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..actions import IllegalAction
from ..lua import T
from . import spec as S

if TYPE_CHECKING:
    from ..game import Game

SETTABLE = ("money", "hands", "discards", "hand_size", "joker_slots", "consumable_slots", "ante", "round_chips",
            "reroll_cost", "interest_cap")
AREAS = ("jokers", "consumeables", "hand")
OPS = ("set", "level", "add", "add_card", "edit", "remove", "boss", "win")
MAX_VALUE = 1e12


def _require(cond: Any, msg: str) -> None:
    if not cond:
        raise IllegalAction(msg)


def _number(cmd: dict[str, Any], lo: float, hi: float = MAX_VALUE) -> int:
    v = cmd.get("value")
    _require(isinstance(v, (int, float)) and not isinstance(v, bool) and v == v, "value: a number")
    _require(lo <= v <= hi, f"value: from {lo:g} to {hi:g}")
    return int(v)


def _in_round(G: "Game") -> bool:
    S_ = G.STATES
    return G.STATE in (S_.SELECTING_HAND, S_.HAND_PLAYED, S_.DRAW_TO_HAND)


def _card(G: "Game", cmd: dict[str, Any]) -> Any:
    area_name = cmd.get("area")
    _require(area_name in AREAS, f"area: one of {', '.join(AREAS)}")
    area = getattr(G, area_name)
    _require(area is not None and not area.removed, f"no {area_name} right now")
    i = cmd.get("index")
    _require(isinstance(i, int) and 0 <= i < len(area.cards), "index: a card of the area")
    return area.cards[i]


def creative(G: "Game", cmd: dict[str, Any]) -> None:  # noqa: C901
    """Play a creative command (IllegalAction if it can't be done now)."""
    GAME = G.GAME
    op = cmd.get("op")
    _require(op in OPS, f"op: one of {', '.join(OPS)}")
    _require(G.STATE != G.STATES.GAME_OVER, "the run is over")
    if op == "set":
        what = cmd.get("what")
        _require(what in SETTABLE, f"what: one of {', '.join(SETTABLE)}")
        if what == "money":
            v = _number(cmd, -MAX_VALUE)
            G.ease_dollars(v - GAME.dollars, True)
        elif what == "hands":
            v = _number(cmd, 0, 1000)
            if _in_round(G):
                G.ease_hands_played(v - GAME.current_round.hands_left, True)
            else:
                GAME.round_resets.hands = max(1, v)
        elif what == "discards":
            v = _number(cmd, 0, 1000)
            if _in_round(G):
                G.ease_discard(v - GAME.current_round.discards_left, True)
            else:
                GAME.round_resets.discards = v
        elif what == "hand_size":
            v = _number(cmd, 1, 100)
            G.hand.change_size(v - G.hand.config.card_limit)
        elif what == "joker_slots":
            G.jokers.config.card_limit = _number(cmd, 0, 100)
        elif what == "consumable_slots":
            G.consumeables.config.card_limit = _number(cmd, 0, 100)
        elif what == "ante":
            v = _number(cmd, -100, 1000)
            GAME.round_resets.ante = v
            GAME.round_resets.blind_ante = v
        elif what == "round_chips":
            _require(_in_round(G), "only during a round")
            GAME.chips = _number(cmd, 0)
        elif what == "reroll_cost":
            v = _number(cmd, 0, 1000)
            GAME.current_round.reroll_cost = v
            GAME.round_resets.reroll_cost = v
        elif what == "interest_cap":
            GAME.interest_cap = _number(cmd, 0, 100000)
    elif op == "level":
        hand = cmd.get("hand")
        _require(hand in GAME.hands, "hand: a poker hand")
        v = _number(cmd, 1, 10000)
        if v != GAME.hands[hand].level:
            G.level_up_hand(None, hand, True, v - GAME.hands[hand].level)
    elif op == "add":
        key = cmd.get("key")
        if isinstance(key, str) and key in G.P_TAGS:
            from ..tag import Tag
            if key == "tag_orbital":
                G.orbital_hand = cmd.get("hand") if cmd.get("hand") in GAME.hands else "High Card"
            G.add_tag(Tag(G, key))
            G.orbital_hand = None
        else:
            _require(isinstance(key, str) and key in G.P_CENTERS, "key: a card of the game or of a mod")
            center = G.P_CENTERS[key]
            if center.set == "Voucher":
                from ..card import Card
                _require(not GAME.used_vouchers.get(key), "this voucher is already redeemed")
                GAME.used_vouchers[key] = True
                card = Card(G, None, center)
                card.apply_to_run()
                card.remove()
            else:
                _require(center.set == "Joker" or center.consumeable, "key: a joker, consumable, voucher or tag")
                edition = cmd.get("edition")
                _require(edition in (None,) + S.EDITIONS, f"edition: one of {', '.join(S.EDITIONS)}")
                card = G.add_joker(key, edition)
                if cmd.get("eternal"):
                    card.set_eternal(True)
                if cmd.get("perishable"):
                    card.set_perishable(True)
                if cmd.get("rental"):
                    card.set_rental(True)
    elif op == "add_card":
        rank, suit = cmd.get("rank"), cmd.get("suit")
        _require(rank in S.RANKS, "rank: 2 .. 10, Jack, Queen, King, Ace")
        _require(suit in S.SUITS, f"suit: one of {', '.join(S.SUITS)}")
        enh = cmd.get("enhancement")
        _require(enh in (None,) + S.ENHANCEMENTS, "enhancement: m_bonus, m_mult ...")
        to_hand = cmd.get("to", "hand" if G.STATE == G.STATES.SELECTING_HAND else "deck") == "hand"
        _require(not to_hand or G.STATE == G.STATES.SELECTING_HAND, "cards go to the hand only during a round")
        front = G.P_CARDS[suit[0] + "_" + S.RANKS[rank]]
        card = G.create_playing_card(T(front=front, center=G.P_CENTERS[enh or "c_base"]),
                                     G.hand if to_hand else G.deck)
        G.deck.config.card_limit = G.deck.config.card_limit + 1
        if cmd.get("edition"):
            _require(cmd["edition"] in ("foil", "holo", "polychrome"), "edition: foil, holo or polychrome")
            card.set_edition(T({cmd["edition"]: True}), True, True)
        if cmd.get("seal"):
            _require(cmd["seal"] in S.SEALS, f"seal: one of {', '.join(S.SEALS)}")
            card.set_seal(cmd["seal"], True)
        card.add_to_deck()
        if GAME.blind:
            GAME.blind.debuff_card(card)
        if to_hand:
            G.hand.sort()
    elif op == "edit":
        from .content import _change_card
        card = _card(G, cmd)
        changes = {k: cmd[k] for k in ("enhancement", "seal", "suit", "rank") if k in cmd}
        if "enhancement" in changes:
            _require(changes["enhancement"] in S.ENHANCEMENTS + ("none",), "enhancement: m_bonus ... or none")
        if "seal" in changes:
            _require(changes["seal"] in S.SEALS + ("none",), "seal: Gold, Red, Blue, Purple or none")
        if "suit" in changes:
            _require(changes["suit"] in S.SUITS, "suit: Spades, Hearts, Clubs or Diamonds")
        if "rank" in changes:
            _require(changes["rank"] in tuple(S.RANKS) + ("up", "down"), "rank: 2 .. Ace, up or down")
        if "edition" in cmd:
            e = cmd["edition"]
            _require(e in S.EDITIONS + ("none",), "edition: foil, holo, polychrome, negative or none")
            _require(e != "negative" or card.ability.set == "Joker" or card.ability.consumeable,
                     "only jokers and consumables are negative")
            if card.added_to_deck and card.edition and card.edition.negative and e != "negative":
                # (the slot a negative card brings goes with its edition, as when it leaves)
                area = G.consumeables if card.ability.consumeable else G.jokers
                area.config.card_limit = area.config.card_limit - 1
            if not (e == "negative" and card.edition and card.edition.negative):
                card.set_edition(None if e == "none" else T({e: True}), True)
        if changes:
            _change_card(G, card, changes, None)
        if "eternal" in cmd:
            card.set_eternal(True if cmd["eternal"] else None)
        if "perishable" in cmd:
            if cmd["perishable"]:
                card.set_perishable(True)
            else:
                card.ability.perishable = None
        if "rental" in cmd:
            card.set_rental(True if cmd["rental"] else None)
    elif op == "remove":
        card = _card(G, cmd)
        if cmd["area"] == "hand":
            card.highlighted = False
            if card in G.hand.highlighted:
                G.hand.remove_from_highlighted(card)
        card.start_dissolve()
    elif op == "boss":
        key = cmd.get("key")
        _require(key in G.P_BLINDS and G.P_BLINDS[key].boss, "key: a boss blind")
        _require(G.STATE == G.STATES.BLIND_SELECT, "only at the blind select")
        GAME.round_resets.blind_choices.Boss = key
        GAME.bosses_used[key] = (GAME.bosses_used.get(key) or 0) + 1
    elif op == "win":
        _require(G.STATE == G.STATES.SELECTING_HAND, "only while playing a round")
        GAME.chips = max(GAME.chips, GAME.blind.chips)
        G.STATE = G.STATES.NEW_ROUND
        G.STATE_COMPLETE = False
    G.settle()
