"""Card:redeem() and Card:apply_to_run() from card.lua."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .lua import T

if TYPE_CHECKING:
    from .card import Card
    from .game import Game


def redeem(card: "Card") -> None:
    G = card.G
    if card.ability.set != "Voucher":
        return
    if card.shop_voucher:
        G.GAME.current_round.voucher = None
    G.GAME.used_vouchers[card.config.center_key] = True
    G.ease_dollars(-card.cost)
    G.GAME.current_round.voucher = None
    apply_to_run(G, card, None)
    for j in list(G.jokers.cards):
        j.calculate_joker(T(buying_card=True, card=card))
    if G.GAME.modifiers.inflation:
        G.GAME.inflation += 1
        G.add_event(G.refresh_all_costs)


def apply_to_run(G: "Game", card: "Card | None", center: T | None) -> None:
    name = center.name if center is not None else (card.ability.name if card is not None else None)
    extra = None
    if center is not None and center.config.extra is not None:
        extra = center.config.extra
    elif card is not None:
        extra = card.ability.extra
    GAME = G.GAME

    if name in ("Overstock", "Overstock Plus"):
        G.add_event(lambda: G.change_shop_size(1))
    if name in ("Tarot Merchant", "Tarot Tycoon"):
        G.add_event(lambda: setattr(GAME, "tarot_rate", 4 * extra))
    if name in ("Planet Merchant", "Planet Tycoon"):
        G.add_event(lambda: setattr(GAME, "planet_rate", 4 * extra))
    if name in ("Hone", "Glow Up"):
        G.add_event(lambda: setattr(GAME, "edition_rate", extra))
    if name in ("Magic Trick", "Illusion"):
        G.add_event(lambda: setattr(GAME, "playing_card_rate", extra))
    if name == "Crystal Ball":
        def cb() -> None:
            G.consumeables.config.card_limit += 1
        G.add_event(cb)
    if name in ("Clearance Sale", "Liquidation"):
        def cs() -> None:
            GAME.discount_percent = extra
            G.refresh_all_costs()
        G.add_event(cs)
    if name in ("Reroll Surplus", "Reroll Glut"):
        amount = card.ability.extra if card is not None else extra

        def rr() -> None:
            GAME.round_resets.reroll_cost = GAME.round_resets.reroll_cost - amount
            GAME.current_round.reroll_cost = max(0, GAME.current_round.reroll_cost - amount)
        G.add_event(rr)
    if name in ("Seed Money", "Money Tree"):
        G.add_event(lambda: setattr(GAME, "interest_cap", extra))
    if name in ("Grabber", "Nacho Tong"):
        GAME.round_resets.hands += extra
        G.ease_hands_played(extra)
    if name in ("Paint Brush", "Palette"):
        G.hand.change_size(1)
    if name in ("Wasteful", "Recyclomancy"):
        GAME.round_resets.discards += extra
        G.ease_discard(extra)
    if name == "Antimatter":
        def am() -> None:
            if G.jokers is not None:
                G.jokers.config.card_limit += 1
        G.add_event(am)
    if name in ("Hieroglyph", "Petroglyph"):
        G.ease_ante(-extra)
        rr_ = GAME.round_resets
        rr_.blind_ante = rr_.blind_ante if rr_.blind_ante is not None else rr_.ante
        rr_.blind_ante = rr_.blind_ante - extra
        if name == "Hieroglyph":
            rr_.hands -= extra
            G.ease_hands_played(-extra)
        if name == "Petroglyph":
            rr_.discards -= extra
            G.ease_discard(-extra)
