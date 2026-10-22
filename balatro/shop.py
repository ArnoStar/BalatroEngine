"""Shop and card-use actions (button_callbacks.lua + Game:update_shop)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .card import Card
from .cardarea import CardArea
from .lua import T

if TYPE_CHECKING:
    from .game import Game


class ShopMixin:
    # -------------------------------------------------------------- update
    def update_shop(self: "Game") -> None:
        G = self
        if G.STATE_COMPLETE:
            return
        shop_exists = G.shop is not None
        if G.shop is None:
            G.shop = True
            G.shop_jokers = CardArea(G, "shop_jokers", {"card_limit": G.GAME.shop.joker_max, "type": "shop", "highlight_limit": 1})
            G.shop_vouchers = CardArea(G, "shop_vouchers", {"card_limit": 1, "type": "shop", "highlight_limit": 1})
            G.shop_booster = CardArea(G, "shop_booster", {"card_limit": 2, "type": "shop", "highlight_limit": 1})

        def ev() -> None:
            def ev2() -> None:
                GAME = G.GAME
                for t in list(GAME.tags):
                    t.apply_to_run(T(type="shop_start"))
                if not shop_exists:
                    for _ in range(GAME.shop.joker_max - len(G.shop_jokers.cards)):
                        G.shop_jokers.emplace(G.create_card_for_shop(G.shop_jokers))
                    if GAME.current_round.voucher and GAME.current_round.voucher in G.P_CENTERS:
                        card = Card(G, None, G.P_CENTERS[GAME.current_round.voucher], {"bypass_discovery_center": True})
                        card.shop_voucher = True
                        G.shop_vouchers.emplace(card)
                    GAME.current_round.used_packs = GAME.current_round.used_packs or T()
                    for i in (1, 2):
                        if not GAME.current_round.used_packs.get(i):
                            GAME.current_round.used_packs[i] = G.get_pack("shop_pack").key
                        if GAME.current_round.used_packs[i] != "USED":
                            card = Card(G, None, G.P_CENTERS[GAME.current_round.used_packs[i]], {"bypass_discovery_center": True})
                            card.ability.booster_pos = i
                            G.shop_booster.emplace(card)
                    for t in list(GAME.tags):
                        t.apply_to_run(T(type="voucher_add"))
                    for t in list(GAME.tags):
                        t.apply_to_run(T(type="shop_final_pass"))
            G.add_event(ev2)
        G.add_event(ev)
        G.STATE_COMPLETE = True

    def remove_shop(self: "Game") -> None:
        """G.shop:remove(): unbought shop cards are removed (frees used_jokers)."""
        G = self
        if G.shop is None:
            return
        for area in (G.shop_jokers, G.shop_vouchers, G.shop_booster):
            if area is not None:
                area.remove()
        G.shop = None

    # ------------------------------------------------------------- actions
    def reroll_shop(self: "Game") -> None:
        G = self
        GAME = G.GAME
        assert G.STATE == G.STATES.SHOP, "not in the shop"
        cr = GAME.current_round
        if (GAME.dollars - GAME.bankrupt_at) - cr.reroll_cost < 0 and cr.reroll_cost != 0:
            raise ValueError("can't afford reroll")
        if cr.reroll_cost > 0:
            G.ease_dollars(-cr.reroll_cost)

        def ev() -> None:
            final_free = cr.free_rerolls > 0
            cr.free_rerolls = max(cr.free_rerolls - 1, 0)
            GAME.round_scores.times_rerolled.amt += 1
            G.calculate_reroll_cost(final_free)
            for i in range(len(G.shop_jokers.cards) - 1, -1, -1):
                c = G.shop_jokers.remove_card(G.shop_jokers.cards[i])
                c.remove()
            for _ in range(GAME.shop.joker_max - len(G.shop_jokers.cards)):
                G.shop_jokers.emplace(G.create_card_for_shop(G.shop_jokers))
        G.add_event(ev)

        def ev2() -> None:
            def ev3() -> None:
                for j in list(G.jokers.cards):
                    j.calculate_joker(T(reroll_shop=True))
            G.add_event(ev3)
        G.add_event(ev2)
        G.advance()

    @staticmethod
    def check_for_buy_space(G: "Game", card: Card) -> bool:
        s = card.ability.set
        if (s not in ("Voucher", "Enhanced", "Default")
                and not (s == "Joker" and len(G.jokers.cards) < G.jokers.config.card_limit + (1 if card.edition and card.edition.negative else 0))
                and not (card.ability.consumeable and len(G.consumeables.cards) < G.consumeables.config.card_limit + (1 if card.edition and card.edition.negative else 0))):
            return False
        return True

    def can_afford(self: "Game", card: Card) -> bool:
        return not (card.cost > self.GAME.dollars - self.GAME.bankrupt_at and card.cost > 0)

    def buy_from_shop(self: "Game", card: Card, buy_and_use: bool = False) -> None:
        G = self
        GAME = G.GAME
        assert G.STATE == G.STATES.SHOP, "not in the shop"
        if not G.can_afford(card):
            raise ValueError("can't afford this card")
        if buy_and_use:
            if not card.can_use_consumeable():
                raise ValueError("this card can't be used right now")
        elif not ShopMixin.check_for_buy_space(G, card):
            raise ValueError("no space for this card")

        def ev() -> None:
            card.area.remove_card(card)
            card.add_to_deck()
            if card.ability.set in ("Default", "Enhanced"):
                G.playing_card = (G.playing_card + 1) if G.playing_card else 1
                G.deck.emplace(card)
                card.playing_card = G.playing_card
                G.playing_card_joker_effects([card])
                G.playing_cards.append(card)
            elif not buy_and_use:
                if card.ability.consumeable:
                    G.consumeables.emplace(card)
                else:
                    G.jokers.emplace(card)
                G.add_event(lambda: card.calculate_joker(T(buying_card=True, card=card)))
            GAME.round_scores.cards_purchased.amt += 1
            if card.ability.set == "Joker":
                GAME.current_round.jokers_purchased += 1
            for j in list(G.jokers.cards):
                j.calculate_joker(T(buying_card=True, card=card))
            if GAME.modifiers.inflation:
                GAME.inflation += 1
                G.add_event(G.refresh_all_costs)
            if card.cost != 0:
                G.ease_dollars(-card.cost)
            if buy_and_use:
                G.use_card(card, True)
        G.add_event(ev)
        G.advance()

    def toggle_shop(self: "Game") -> None:
        """'Next Round' button."""
        G = self
        assert G.STATE == G.STATES.SHOP and G.shop is not None, "not in the shop"
        for j in list(G.jokers.cards):
            j.calculate_joker(T(ending_shop=True))

        def ev() -> None:
            G.remove_shop()
            G.STATE_COMPLETE = False
            G.STATE = G.STATES.BLIND_SELECT
        G.add_event(ev)
        G.advance()

    def sell_card(self: "Game", card: Card) -> None:
        G = self
        if not card.can_sell_card():
            raise ValueError("this card can't be sold")
        card.sell_card()
        for j in list(G.jokers.cards):
            if j is not card:
                j.calculate_joker(T(selling_card=True, card=card))
        G.advance()

    # ------------------------------------------------------------ use_card
    def use_card(self: "Game", card: Card, mute: Any = None, nosave: Any = None) -> None:
        """G.FUNCS.use_card: consumables, boosters, vouchers and pack picks."""
        G = self
        S = G.STATES
        GAME = G.GAME
        area = card.area
        prev_state = G.STATE
        dont_dissolve = None
        delay_fac = 1
        if card.check_use():
            return
        G.TAROT_INTERRUPT = G.STATE
        if card.ability.set == "Booster":
            GAME.PACK_INTERRUPT = G.STATE
        if G.STATE not in (S.TAROT_PACK, S.PLANET_PACK, S.SPECTRAL_PACK, S.STANDARD_PACK, S.BUFFOON_PACK):
            G.STATE = S.PLAY_TAROT
        if card.area is not None:
            card.area.remove_card(card)
        s = card.ability.set
        if card.ability.consumeable:
            if G.STATE not in (S.TAROT_PACK, S.PLANET_PACK, S.SPECTRAL_PACK):
                G.draw_card(G.hand, G.play, card)
            card.use_consumeable(area)
            for j in list(G.jokers.cards):
                j.calculate_joker(T(using_consumeable=True, consumeable=card))
        elif s in ("Enhanced", "Default"):
            G.playing_card = (G.playing_card + 1) if G.playing_card else 1
            G.deck.emplace(card)
            card.playing_card = G.playing_card
            G.playing_card_joker_effects([card])
            card.add_to_deck()
            G.playing_cards.append(card)
            dont_dissolve = True
            delay_fac = 0.2
        elif s == "Joker":
            card.add_to_deck()
            G.jokers.emplace(card)
            dont_dissolve = True
            delay_fac = 0.2
        elif s == "Booster":
            if card.ability.booster_pos:
                GAME.current_round.used_packs[card.ability.booster_pos] = "USED"
            G.draw_card(G.hand, G.play, card)
            if not card.from_tag:
                GAME.round_scores.cards_purchased.amt += 1
            card.open()
        elif s == "Voucher":
            G.draw_card(G.hand, G.play, card)
            GAME.round_scores.cards_purchased.amt += 1
            card.redeem()
        if s == "Booster":
            G.TAROT_INTERRUPT = None
            return

        def ev() -> None:
            if not dont_dissolve:
                card.start_dissolve()

            def ev2() -> None:
                G.STATE = prev_state
                G.TAROT_INTERRUPT = None
                if prev_state in (S.TAROT_PACK, S.PLANET_PACK, S.SPECTRAL_PACK, S.STANDARD_PACK, S.BUFFOON_PACK) and G.booster_pack:
                    if area is G.consumeables:
                        pass
                    elif GAME.pack_choices and GAME.pack_choices > 1:
                        GAME.pack_choices = GAME.pack_choices - 1
                    else:
                        G.end_consumeable(None, delay_fac)
            G.add_event(ev2)
        G.add_event(ev)
