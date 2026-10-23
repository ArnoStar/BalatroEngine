"""Port of back.lua (the deck)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .lua import T, copy_table

if TYPE_CHECKING:
    from .game import Game


class Back:
    def __init__(self, G: "Game", center: T | None = None) -> None:
        self.G = G
        center = center or G.P_CENTERS["b_red"]
        self.name = center.name or "Red Deck"
        self.effect = T(center=center, config=copy_table(center.config))

    @property
    def key(self) -> str:
        return self.effect.center.key

    def trigger_effect(self, args: T) -> Any:
        G = self.G
        if not args:
            return None
        if self.name == "Anaglyph Deck" and args.context == "eval" and G.GAME.last_blind and G.GAME.last_blind.boss:
            from .tag import Tag
            G.ev(lambda: G.add_tag(Tag(G, "tag_double")))
        if self.name == "Plasma Deck" and args.context == "blind_amount":
            return None
        if self.name == "Plasma Deck" and args.context == "final_scoring_step":
            tot = args.chips + args.mult
            args.chips = G.floor(tot / 2)
            args.mult = G.floor(tot / 2)
            G.update_hand_text(T(delay=0), T(mult=args.mult, chips=args.chips))
            G.ev(None)
            G.delay(0.6)
            return args.chips, args.mult
        return None

    def apply_to_run(self) -> None:
        G = self.G
        GAME = G.GAME
        cfg = self.effect.config
        from .card import apply_to_run
        if cfg.voucher:
            GAME.used_vouchers[cfg.voucher] = True
            GAME.starting_voucher_count = (GAME.starting_voucher_count or 0) + 1
            apply_to_run(G, None, G.P_CENTERS[cfg.voucher])
        if cfg.hands:
            GAME.starting_params.hands = GAME.starting_params.hands + cfg.hands
        if cfg.consumables:
            G.delay(0.4)

            def cons() -> None:
                for v in cfg.consumables:
                    card = G.create_card("Tarot", G.consumeables, None, None, None, None, v, "deck")
                    card.add_to_deck()
                    G.consumeables.emplace(card)
            G.ev(cons)
        if cfg.dollars:
            GAME.starting_params.dollars = GAME.starting_params.dollars + cfg.dollars
        if cfg.remove_faces:
            GAME.starting_params.no_faces = True
        if cfg.spectral_rate:
            GAME.spectral_rate = cfg.spectral_rate
        if cfg.discards:
            GAME.starting_params.discards = GAME.starting_params.discards + cfg.discards
        if cfg.reroll_discount:
            GAME.starting_params.reroll_cost = GAME.starting_params.reroll_cost - cfg.reroll_discount
        if cfg.edition:
            def edition() -> None:
                i = 0
                while i < cfg.edition_count:
                    card = G.random_card_from(list(G.playing_cards), "edition_deck")
                    if not card.edition:
                        i = i + 1
                        card.set_edition(T({cfg.edition: True}), None, True)
            G.ev(edition)
        if cfg.vouchers:
            for v in cfg.vouchers:
                GAME.used_vouchers[v] = True
                GAME.starting_voucher_count = (GAME.starting_voucher_count or 0) + 1
                apply_to_run(G, None, G.P_CENTERS[v])
        if self.name == "Checkered Deck":
            def checkered() -> None:
                for v in list(G.playing_cards):
                    if v.base.suit == "Clubs":
                        v.change_suit("Spades")
                    if v.base.suit == "Diamonds":
                        v.change_suit("Hearts")
            G.ev(checkered)
        if cfg.randomize_rank_suit:
            GAME.starting_params.erratic_suits_and_ranks = True
        if cfg.joker_slot:
            GAME.starting_params.joker_slots = GAME.starting_params.joker_slots + cfg.joker_slot
        if cfg.hand_size:
            GAME.starting_params.hand_size = GAME.starting_params.hand_size + cfg.hand_size
        if cfg.ante_scaling:
            GAME.starting_params.ante_scaling = cfg.ante_scaling
        if cfg.consumable_slot:
            GAME.starting_params.consumable_slots = GAME.starting_params.consumable_slots + cfg.consumable_slot
        if cfg.no_interest:
            GAME.modifiers.no_interest = True
        if cfg.extra_hand_bonus:
            GAME.modifiers.money_per_hand = cfg.extra_hand_bonus
        if cfg.extra_discard_bonus:
            GAME.modifiers.money_per_discard = cfg.extra_discard_bonus
