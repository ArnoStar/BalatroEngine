"""evaluate_poker_hand & friends (misc_functions.lua) and get_poker_hand_info."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .lua import T

if TYPE_CHECKING:
    from .card import Card
    from .game import Game

HANDS_ORDER = ["Flush Five", "Flush House", "Five of a Kind", "Straight Flush", "Four of a Kind", "Full House",
               "Flush", "Straight", "Three of a Kind", "Two Pair", "Pair", "High Card"]


def get_flush(G: "Game", hand: list["Card"]) -> list[list["Card"]]:
    four_fingers = bool(G.find_joker("Four Fingers"))
    need = 5 - (1 if four_fingers else 0)
    if len(hand) > 5 or len(hand) < need:
        return []
    for suit in ("Spades", "Hearts", "Clubs", "Diamonds"):
        t = [c for c in hand if c.is_suit(suit, None, True)]
        if len(t) >= need:
            return [t]
    return []


def get_straight(G: "Game", hand: list["Card"]) -> list[list["Card"]]:
    four_fingers = bool(G.find_joker("Four Fingers"))
    need = 5 - (1 if four_fingers else 0)
    if len(hand) > 5 or len(hand) < need:
        return []
    t: list[Card] = []
    ids: dict[int, list[Card]] = {}
    for c in hand:
        cid = c.get_id()
        if 1 < cid < 15:
            ids.setdefault(cid, []).append(c)
    straight_length = 0
    straight = False
    can_skip = bool(G.find_joker("Shortcut"))
    skipped_rank = False
    for j in range(1, 15):
        key = 14 if j == 1 else j
        if key in ids:
            straight_length += 1
            skipped_rank = False
            t.extend(ids[key])
        elif can_skip and not skipped_rank and j != 14:
            skipped_rank = True
        else:
            straight_length = 0
            skipped_rank = False
            if not straight:
                t = []
            if straight:
                break
        if straight_length >= need:
            straight = True
    if not straight:
        return []
    return [t]


def get_X_same(num: int, hand: list["Card"]) -> list[list["Card"]]:
    vals: dict[int, list[Card]] = {}
    ids = [c.get_id() for c in hand]  # note: Stone cards get unique negative ids
    for i in range(len(hand) - 1, -1, -1):
        curr = [hand[i]]
        for j in range(len(hand)):
            if ids[i] == ids[j] and i != j:
                curr.append(hand[j])
        if len(curr) == num:
            vals[ids[i]] = curr
    ret = []
    for i in range(14, 0, -1):
        if vals.get(i):
            ret.append(vals[i])
    return ret


def get_highest(hand: list["Card"]) -> list[list["Card"]]:
    highest = None
    for c in hand:
        if highest is None or c.get_nominal() > highest.get_nominal():
            highest = c
    return [[highest]] if hand else []


def evaluate_poker_hand(G: "Game", hand: list["Card"]) -> T:
    results = T({h: [] for h in HANDS_ORDER})
    p5 = get_X_same(5, hand)
    p4 = get_X_same(4, hand)
    p3 = get_X_same(3, hand)
    p2 = get_X_same(2, hand)
    flush = get_flush(G, hand)
    straight = get_straight(G, hand)
    highest = get_highest(hand)
    top = None

    if p5 and flush:
        results["Flush Five"] = p5
        top = top or results["Flush Five"]
    if p3 and p2 and flush:
        results["Flush House"].append(list(p3[0]) + list(p2[0]))
        top = top or results["Flush House"]
    if p5:
        results["Five of a Kind"] = p5
        top = top or results["Five of a Kind"]
    if flush and straight:
        ret = list(flush[0])
        for v in straight[0]:
            if not any(vv is v for vv in flush[0]):
                ret.append(v)
        results["Straight Flush"] = [ret]
        top = top or results["Straight Flush"]
    if p4:
        results["Four of a Kind"] = p4
        top = top or results["Four of a Kind"]
    if p3 and p2:
        results["Full House"].append(list(p3[0]) + list(p2[0]))
        top = top or results["Full House"]
    if flush:
        results["Flush"] = flush
        top = top or results["Flush"]
    if straight:
        results["Straight"] = straight
        top = top or results["Straight"]
    if p3:
        results["Three of a Kind"] = p3
        top = top or results["Three of a Kind"]
    if len(p2) == 2 or (len(p3) == 1 and len(p2) == 1):
        a = p2[0]
        b = p2[1] if len(p2) > 1 else p3[0]
        results["Two Pair"].append(list(a) + list(b))
        top = top or results["Two Pair"]
    if p2:
        results["Pair"] = p2
        top = top or results["Pair"]
    if highest:
        results["High Card"] = highest
        top = top or results["High Card"]

    # these keep at most 4/3/2 groups of the larger set (Lua builds sparse lists)
    if results["Five of a Kind"]:
        results["Four of a Kind"] = [g for g in results["Five of a Kind"][:4]]
    if results["Four of a Kind"]:
        results["Three of a Kind"] = [g for g in results["Four of a Kind"][:3]]
    if results["Three of a Kind"]:
        results["Pair"] = [g for g in results["Three of a Kind"][:2]]
    results.top = top
    return results


def get_poker_hand_info(G: "Game", cards: list["Card"]) -> tuple[str, str, T, list["Card"], str]:
    poker_hands = evaluate_poker_hand(G, cards)
    scoring_hand: list[Card] = []
    text = "NULL"
    for h in HANDS_ORDER:
        if poker_hands[h]:
            text = h
            scoring_hand = list(poker_hands[h][0])
            break
    disp_text = text
    if text == "Straight Flush":
        mn = 10
        for c in scoring_hand:
            cid = c.get_id()
            if cid < mn:
                mn = cid
        if mn >= 10:
            disp_text = "Royal Flush"
    return text, disp_text, poker_hands, scoring_hand, disp_text
