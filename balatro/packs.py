"""Booster packs: Card:open(), the pack states and end_consumeable."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cardarea import CardArea
from .lua import T
from .rng import lua_tostring

if TYPE_CHECKING:
    from .card import Card
    from .game import Game


def open_booster(card: "Card") -> None:
    G = card.G
    GAME = G.GAME
    S = G.STATES
    if card.ability.set != "Booster":
        return
    G.STATE_COMPLETE = False
    card.opening = True
    name = card.ability.name
    if "Arcana" in name:
        G.STATE = S.TAROT_PACK
    elif "Celestial" in name:
        G.STATE = S.PLANET_PACK
    elif "Spectral" in name:
        G.STATE = S.SPECTRAL_PACK
    elif "Standard" in name:
        G.STATE = S.STANDARD_PACK
    elif "Buffoon" in name:
        G.STATE = S.BUFFOON_PACK
    GAME.pack_size = card.ability.extra
    GAME.pack_choices = card.config.center.config.choose or 1
    if card.cost > 0:
        G.ease_dollars(-card.cost)
    # create_UIBox_*_pack() makes G.pack_cards before the cards are generated
    G.pack_cards = CardArea(G, "pack_cards", {"card_limit": GAME.pack_size, "type": "consumeable", "highlight_limit": 1})
    G.booster_pack = True

    def ev() -> None:
        # Card:explode() queues blocking-but-unblockable events that hold back
        # every blockable event for ~1.95s, while the (unblockable) pack
        # generation fires at 1.3s.  So the pack is generated before anything
        # the open_booster jokers queue (e.g. Hallucination's tarot), and the
        # booster card itself is removed (Card:remove at 1.95s) right after.
        G.generate_pack_cards(card)
        G.defer_removal(card)
        for j in list(G.jokers.cards):
            j.calculate_joker(T(open_booster=True, card=card))
        if GAME.modifiers.inflation:
            GAME.inflation += 1
            G.add_event(G.refresh_all_costs)
    G.add_event(ev)


class PacksMixin:
    def generate_pack_cards(self: "Game", booster: "Card") -> None:
        G = self
        GAME = G.GAME
        # generation runs >=1.7s after the pack was opened: every timed effect
        # still pending from before (e.g. a tarot used in the previous pack of
        # a Double+Charm tag chain finishing its 0.7s dissolve) has fired.
        G.run_deferred_one_frame()
        ante = lua_tostring(GAME.round_resets.ante)
        name = booster.ability.name
        cards = []
        for i in range(booster.ability.extra):
            card = None
            if "Arcana" in name:
                if GAME.used_vouchers.get("v_omen_globe") and G.rng.random("omen_globe") > 0.8:
                    card = G.create_card("Spectral", G.pack_cards, None, None, True, True, None, "ar2")
                else:
                    card = G.create_card("Tarot", G.pack_cards, None, None, True, True, None, "ar1")
            elif "Celestial" in name:
                if GAME.used_vouchers.get("v_telescope") and i == 0:
                    planet, hand, tally = None, None, 0
                    for v in G.handlist:
                        if GAME.hands[v].visible and GAME.hands[v].played > tally:
                            hand = v
                            tally = GAME.hands[v].played
                    if hand:
                        for v in G.P_CENTER_POOLS["Planet"]:
                            if v.config.hand_type == hand:
                                planet = v.key
                    card = G.create_card("Planet", G.pack_cards, None, None, True, True, planet, "pl1")
                else:
                    card = G.create_card("Planet", G.pack_cards, None, None, True, True, None, "pl1")
            elif "Spectral" in name:
                card = G.create_card("Spectral", G.pack_cards, None, None, True, True, None, "spe")
            elif "Standard" in name:
                typ = "Enhanced" if G.rng.random(G.rng.pseudoseed("stdset" + ante)) > 0.6 else "Base"
                card = G.create_card(typ, G.pack_cards, None, None, None, True, None, "sta")
                edition = G.poll_edition("standard_edition" + ante, 2, True)
                card.set_edition(edition)
                seal_poll = G.rng.random(G.rng.pseudoseed("stdseal" + ante))
                if seal_poll > 1 - 0.02 * 10:
                    seal_type = G.rng.random(G.rng.pseudoseed("stdsealtype" + ante))
                    if seal_type > 0.75:
                        card.set_seal("Red")
                    elif seal_type > 0.5:
                        card.set_seal("Blue")
                    elif seal_type > 0.25:
                        card.set_seal("Gold")
                    else:
                        card.set_seal("Purple")
            elif "Buffoon" in name:
                card = G.create_card("Joker", G.pack_cards, None, None, True, True, None, "buf")
            cards.append(card)

        def emplace() -> None:
            if G.pack_cards is not None and not G.pack_cards.removed:
                for c in cards:
                    G.pack_cards.emplace(c)
        G.add_event(emplace)

    def update_pack(self: "Game") -> None:
        G = self
        S = G.STATES
        if G.STATE_COMPLETE:
            return
        G.STATE_COMPLETE = True
        if G.STATE in (S.TAROT_PACK, S.SPECTRAL_PACK):
            def ev() -> None:
                G.add_event(lambda: G.draw_from_deck_to_hand())
            G.add_event(ev)

    def end_consumeable(self: "Game", e: object = None, delayfac: float = 1) -> None:
        G = self
        GAME = G.GAME
        if G.booster_pack:
            def remove_pack() -> None:
                if G.pack_cards is not None:
                    G.pack_cards.remove()
                G.booster_pack = None
            G.add_event(remove_pack)

        def ev() -> None:
            G.draw_from_hand_to_deck()

            def ev2() -> None:
                G.STATE = GAME.PACK_INTERRUPT
                GAME.PACK_INTERRUPT = None
            G.add_event(ev2)
            for t in list(GAME.tags):
                if t.apply_to_run(T(type="new_blind_choice")):
                    break
        G.add_event(ev)

    # ------------------------------------------------------------- actions
    def skip_booster(self: "Game") -> None:
        G = self
        assert G.in_pack(), "no booster pack is open"
        for j in list(G.jokers.cards):
            j.calculate_joker(T(skipping_booster=True))
        G.end_consumeable(None)
        G.advance()

    def in_pack(self: "Game") -> bool:
        S = self.STATES
        return self.STATE in (S.TAROT_PACK, S.PLANET_PACK, S.SPECTRAL_PACK, S.STANDARD_PACK, S.BUFFOON_PACK)

    def can_select_pack_card(self: "Game", card: "Card") -> bool:
        G = self
        if card.ability.consumeable:
            return card.can_use_consumeable()
        return (card.ability.set != "Joker" or bool(card.edition and card.edition.negative)
                or len(G.jokers.cards) < G.jokers.config.card_limit)
