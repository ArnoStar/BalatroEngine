"""Port of back.lua (deck effects)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .lua import T, copy_table

if TYPE_CHECKING:
    from .game import Game


class Back:
    def __init__(self, G: "Game", center: T | None) -> None:
        self.G = G
        if center is None:
            center = G.P_CENTERS["b_red"]
        self.name = center.name or "Red Deck"
        self.effect = T(center=center, config=copy_table(center.config))
        self.key = center.key

    def trigger_effect(self, args: T) -> Any:
        G = self.G
        if not args:
            return None
        if self.name == "Anaglyph Deck" and args.context == "eval" and G.GAME.last_blind and G.GAME.last_blind.boss:
            from .tag import Tag
            G.add_event(lambda: G.add_tag(Tag(G, "tag_double")))
        if self.name == "Plasma Deck" and args.context == "blind_amount":
            return None
        if self.name == "Plasma Deck" and args.context == "final_scoring_step":
            tot = args.chips + args.mult
            args.chips = math.floor(tot / 2)
            args.mult = math.floor(tot / 2)
            return args.chips, args.mult
        return None

    def apply_to_run(self) -> None:
        G = self.G
        cfg = self.effect.config
        sp = G.GAME.starting_params
        from .vouchers import apply_to_run
        if cfg.voucher:
            G.GAME.used_vouchers[cfg.voucher] = True
            G.GAME.starting_voucher_count = (G.GAME.starting_voucher_count or 0) + 1
            apply_to_run(G, None, G.P_CENTERS[cfg.voucher])
        if cfg.hands:
            sp.hands = sp.hands + cfg.hands
        if cfg.consumables:
            def make() -> None:
                for v in cfg.consumables:
                    card = G.create_card("Tarot", G.consumeables, None, None, None, None, v, "deck")
                    card.add_to_deck()
                    G.consumeables.emplace(card)
            G.add_event(make)
        if cfg.dollars:
            sp.dollars = sp.dollars + cfg.dollars
        if cfg.remove_faces:
            sp.no_faces = True
        if cfg.spectral_rate:
            G.GAME.spectral_rate = cfg.spectral_rate
        if cfg.discards:
            sp.discards = sp.discards + cfg.discards
        if cfg.reroll_discount:
            sp.reroll_cost = sp.reroll_cost - cfg.reroll_discount
        if cfg.edition:
            def editions() -> None:
                i = 0
                while i < cfg.edition_count:
                    card = G._random_card_from(G.playing_cards, "edition_deck")
                    if not card.edition:
                        i += 1
                        card.set_edition(T({cfg.edition: True}), None, True)
            G.add_event(editions)
        if cfg.vouchers:
            for v in cfg.vouchers:
                G.GAME.used_vouchers[v] = True
                G.GAME.starting_voucher_count = (G.GAME.starting_voucher_count or 0) + 1
                apply_to_run(G, None, G.P_CENTERS[v])
        if self.name == "Checkered Deck":
            def checker() -> None:
                for v in G.playing_cards:
                    if v.base.suit == "Clubs":
                        v.change_suit("Spades")
                    if v.base.suit == "Diamonds":
                        v.change_suit("Hearts")
            G.add_event(checker)
        if cfg.randomize_rank_suit:
            sp.erratic_suits_and_ranks = True
        if cfg.joker_slot:
            sp.joker_slots = sp.joker_slots + cfg.joker_slot
        if cfg.hand_size:
            sp.hand_size = sp.hand_size + cfg.hand_size
        if cfg.ante_scaling:
            sp.ante_scaling = cfg.ante_scaling
        if cfg.consumable_slot:
            sp.consumable_slots = sp.consumable_slots + cfg.consumable_slot
        if cfg.no_interest:
            G.GAME.modifiers.no_interest = True
        if cfg.extra_hand_bonus:
            G.GAME.modifiers.money_per_hand = cfg.extra_hand_bonus
        if cfg.extra_discard_bonus:
            G.GAME.modifiers.money_per_discard = cfg.extra_discard_bonus
