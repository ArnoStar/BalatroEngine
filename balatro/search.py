"""Seed search helpers (importable so multiprocessing workers can use them)."""

from __future__ import annotations

from .quick import Ante1


def check_seed(args: tuple) -> str | None:
    """Ante-1 conditions: skip tags, boss, voucher, cards in the first hand."""
    seed, deck, stake, tags, boss, voucher, hand_has = args
    a = Ante1(seed, deck)
    if tags and list(a.tags) != list(tags):
        return None
    if boss and a.boss != boss:
        return None
    if voucher and a.voucher != voucher:
        return None
    if hand_has:
        hand = a.first_hand()
        for card in hand_has:
            if card not in hand:
                return None
    return seed
