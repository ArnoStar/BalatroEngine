"""A plain-data dump of the run state (the format of tools/lua/oracle.lua's
``dump()``, so the engine can be compared with the original game)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .card import Card
    from .cardarea import CardArea
    from .game import Game

JOKER_ABILITY_KEYS = ("mult", "x_mult", "extra_value", "caino_xmult", "yorick_discards", "invis_rounds",
                      "to_do_poker_hand", "loyalty_remaining", "perish_tally")


def fmt(x: Any) -> Any:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return x
    return "%.17g" % x


def card_desc(c: "Card") -> dict:
    d: dict[str, Any] = {"key": c.config.center.key, "sort_id": c.sort_id}
    ab = c.ability
    if ab.set in ("Default", "Enhanced"):
        d["card"] = c.config.card_key
        if ab.perma_bonus and ab.perma_bonus != 0:
            d["perma_bonus"] = ab.perma_bonus
    if c.edition:
        d["edition"] = c.edition.type
    if c.seal:
        d["seal"] = c.seal
    if c.debuff:
        d["debuff"] = True
    if c.facing == "back":
        d["facing"] = "back"
    if ab.eternal:
        d["eternal"] = True
    if ab.perishable:
        d["perishable"] = ab.perish_tally
    if ab.rental:
        d["rental"] = True
    if ab.forced_selection:
        d["forced"] = True
    if c.highlighted:
        d["highlighted"] = True
    d["cost"] = c.cost
    d["sell_cost"] = c.sell_cost
    if ab.set == "Joker":
        a: dict[str, Any] = {}
        for k in JOKER_ABILITY_KEYS:
            if ab.get(k) is not None:
                a[k] = fmt(ab[k])
        if isinstance(ab.extra, dict):
            for k, v in ab.extra.items():
                if not isinstance(v, (dict, list)):
                    a["extra." + k] = fmt(v)
        elif ab.extra is not None:
            a["extra"] = fmt(ab.extra)
        d["ability"] = a
    return d


def area_desc(area: "CardArea | None") -> list | None:
    if area is None or area.removed:
        return None
    return [card_desc(c) for c in area.cards]


def snapshot(G: "Game") -> dict:
    GAME = G.GAME
    cr = GAME.current_round
    shop = G.shop is not None and not G.shop.removed
    return {
        "state": G.STATE,
        "state_complete": G.STATE_COMPLETE,
        "ante": GAME.round_resets.ante,
        "round": GAME.round,
        "dollars": GAME.dollars,
        "chips": fmt(GAME.chips),
        "hands_left": cr.hands_left,
        "discards_left": cr.discards_left,
        "hand_size": G.hand.config.card_limit if G.hand is not None else None,
        "joker_slots": G.jokers.config.card_limit if G.jokers is not None else None,
        "consumable_slots": G.consumeables.config.card_limit if G.consumeables is not None else None,
        "reroll_cost": cr.reroll_cost,
        "blind": ({"name": GAME.blind.name, "chips": fmt(GAME.blind.chips), "disabled": GAME.blind.disabled}
                  if GAME.blind else None),
        "blind_on_deck": GAME.blind_on_deck,
        "boss": GAME.round_resets.blind_choices.Boss,
        "voucher": cr.voucher,
        "blind_tags": dict(GAME.round_resets.blind_tags or {}),
        "blind_states": dict(GAME.round_resets.blind_states),
        "tags": [t.key for t in GAME.tags],
        "deck": area_desc(G.deck),
        "hand": area_desc(G.hand),
        "discard": area_desc(G.discard),
        "play": area_desc(G.play),
        "jokers": area_desc(G.jokers),
        "consumeables": area_desc(G.consumeables),
        "shop_jokers": area_desc(G.shop_jokers) if shop else None,
        "shop_vouchers": area_desc(G.shop_vouchers) if shop else None,
        "shop_booster": area_desc(G.shop_booster) if shop else None,
        "pack_cards": area_desc(G.pack_cards),
        "pack_choices": GAME.pack_choices,
        "hands": {k: {"level": v.level, "played": v.played, "chips": v.chips, "mult": v.mult, "visible": v.visible}
                  for k, v in GAME.hands.items()},
        "used_jokers": sorted(k for k, v in GAME.used_jokers.items() if v),
        "used_vouchers": sorted(k for k, v in GAME.used_vouchers.items() if v),
        "pool_flags": sorted(k for k, v in GAME.pool_flags.items() if v),
        "current_round": {
            "idol": f"{cr.idol_card.suit}:{cr.idol_card.rank}" if cr.idol_card else None,
            "mail": cr.mail_card.rank if cr.mail_card else None,
            "ancient": cr.ancient_card.suit if cr.ancient_card else None,
            "castle": cr.castle_card.suit if cr.castle_card else None,
            "most_played": cr.most_played_poker_hand,
            "dollars": cr.dollars,
        },
        "rng": {k: fmt(v) for k, v in G.rng.state.items()},
        "hands_order": list(G.hands_order()),
        "round_scores": {k: fmt(v.amt) for k, v in GAME.round_scores.items()},
        "profile": profile_desc(G.PROFILE),
    }


def profile_desc(p: Any) -> dict:
    """What the run added to the player's profile (Game.PROFILE)."""
    return {
        "career_stats": dict(p.career_stats),
        "high_scores": {k: fmt(v) for k, v in p.high_scores.items()},
        "joker_usage": {k: {"count": v.count, "wins": {str(s): n for s, n in v.wins.items()},
                            "losses": {str(s): n for s, n in v.losses.items()}}
                        for k, v in p.joker_usage.items()},
        "voucher_usage": dict(p.voucher_usage),
    }
