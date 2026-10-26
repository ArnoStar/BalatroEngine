"""The gameplay callbacks of functions/button_callbacks.lua (G.FUNCS.*)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .lua import T
from .ui import ROOM_Y, Box

if TYPE_CHECKING:
    from .card import Card
    from .game import Game


class ButtonsMixin:
    # ================================================================ menus
    def overlay_menu(self: "Game") -> None:
        G = self
        G.CONTROLLER.locks.frame_set = True
        G.CONTROLLER.locks.frame = True
        G.OVERLAY_MENU = True

    def exit_overlay_menu(self: "Game") -> None:
        G = self
        if not G.OVERLAY_MENU:
            return
        G.CONTROLLER.locks.frame_set = True
        G.CONTROLLER.locks.frame = True
        G.OVERLAY_MENU = None
        G.SETTINGS.paused = False

    # ================================================================= hand
    def sort_hand_suit(self: "Game") -> None:
        self.hand.sort("suit desc")

    def sort_hand_value(self: "Game") -> None:
        self.hand.sort("desc")

    # ============================================================= use_card
    def use_card(self: "Game", card: "Card", mute: Any = None, nosave: Any = None, buy_and_use: bool = False) -> None:
        G = self
        S = G.STATES
        area = card.area
        prev_state = G.STATE
        dont_dissolve = None
        delay_fac = 1
        if card.check_use():
            G.ev(None)
            return
        G.TAROT_INTERRUPT = G.STATE
        if card.ability.set == "Booster":
            G.GAME.PACK_INTERRUPT = G.STATE
        if G.STATE not in (S.TAROT_PACK, S.PLANET_PACK, S.SPECTRAL_PACK, S.STANDARD_PACK, S.BUFFOON_PACK):
            G.STATE = S.PLAY_TAROT
        G.CONTROLLER.locks.use = True
        bp = G.booster_pack
        if bp is not None and not bp.removed and bp.alignment.offset.py is None and (
                card.ability.consumeable or not (G.GAME.pack_choices and G.GAME.pack_choices > 1)):
            bp.alignment.offset.py = bp.alignment.offset.y
            bp.alignment.offset.y = ROOM_Y + 29
        for box, off in ((G.shop, 29), (G.blind_select, 39), (G.round_eval, 29)):
            if box is not None and not box.removed and box.alignment.offset.py is None:
                box.alignment.offset.py = box.alignment.offset.y
                box.alignment.offset.y = ROOM_Y + off
        if card.area is not None:
            card.area.remove_card(card)
        if card.ability.consumeable:
            if G.STATE in (S.TAROT_PACK, S.PLANET_PACK, S.SPECTRAL_PACK):
                G.discover_card(card.config.center)
            else:
                G.draw_card(G.hand, G.play, 1, "up", True, card, None, mute)
            G.delay(0.2)
            card.use_consumeable(area)
            for j in list(G.jokers.cards):
                j.calculate_joker(T(using_consumeable=True, consumeable=card))
        elif card.ability.set in ("Enhanced", "Default"):
            G.playing_card = (G.playing_card + 1) if G.playing_card else 1
            G.deck.emplace(card)
            card.playing_card = G.playing_card
            G.playing_card_joker_effects([card])
            card.add_to_deck()
            G.playing_cards.append(card)
            dont_dissolve = True
            delay_fac = 0.2
        elif card.ability.set == "Joker":
            card.add_to_deck()
            G.jokers.emplace(card)
            dont_dissolve = True
            delay_fac = 0.2
        elif card.ability.set == "Booster":
            G.delay(0.1)
            if card.ability.booster_pos:
                G.GAME.current_round.used_packs[card.ability.booster_pos] = "USED"
            G.draw_card(G.hand, G.play, 1, "up", True, card, None, True)
            if not card.from_tag:
                G.GAME.round_scores.cards_purchased.amt = G.GAME.round_scores.cards_purchased.amt + 1
            card.open()
        elif card.ability.set == "Voucher":
            G.delay(0.1)
            G.draw_card(G.hand, G.play, 1, "up", True, card, None, True)
            G.GAME.round_scores.cards_purchased.amt = G.GAME.round_scores.cards_purchased.amt + 1
            card.redeem()
        if card.ability.set == "Booster":
            G.CONTROLLER.locks.use = False
            G.TAROT_INTERRUPT = None
        else:
            def after() -> None:
                if not dont_dissolve:
                    card.start_dissolve()

                def after2() -> None:
                    G.STATE = prev_state
                    G.TAROT_INTERRUPT = None
                    G.CONTROLLER.locks.use = False
                    if prev_state in (S.TAROT_PACK, S.PLANET_PACK, S.SPECTRAL_PACK, S.STANDARD_PACK,
                                      S.BUFFOON_PACK) and G.booster_pack is not None and not G.booster_pack.removed:
                        bpo = G.booster_pack.alignment.offset
                        if area is G.consumeables:
                            bpo.y = bpo.py
                            bpo.py = None
                        elif G.GAME.pack_choices and G.GAME.pack_choices > 1:
                            if bpo.py is not None:
                                bpo.y = bpo.py
                                bpo.py = None
                            G.GAME.pack_choices = G.GAME.pack_choices - 1
                        else:
                            if prev_state == S.TAROT_PACK:
                                G.inc_career_stat("c_tarot_reading_used", 1)
                            if prev_state == S.PLANET_PACK:
                                G.inc_career_stat("c_planetarium_used", 1)
                            G.end_consumeable(None, delay_fac)
                    else:
                        for box in (G.shop, G.blind_select, G.round_eval):
                            if box is not None and not box.removed:
                                box.alignment.offset.y = box.alignment.offset.py
                                box.alignment.offset.py = None
                        if area is not None and area.cards:
                            def f1() -> None:
                                G.ev(None)
                            G.ev(f1)
                G.ev(after2, trigger="after", delay=0.1)
            G.ev(after, trigger="after", delay=0.2)

    def sell_card(self: "Game", card: "Card") -> None:
        G = self
        card.sell_card()
        for j in list(G.jokers.cards):
            if j is not card:
                j.calculate_joker(T(selling_card=True, card=card))

    # ================================================================= shop
    def check_for_buy_space(self: "Game", card: "Card") -> bool:
        G = self
        ab = card.ability
        neg = 1 if card.edition and card.edition.negative else 0
        if (ab.set != "Voucher" and ab.set != "Enhanced" and ab.set != "Default"
                and not (ab.set == "Joker" and len(G.jokers.cards) < G.jokers.config.card_limit + neg)
                and not (ab.consumeable and len(G.consumeables.cards) < G.consumeables.config.card_limit + neg)):
            G.alert_no_space(card, G.consumeables if ab.consumeable else G.jokers)
            return False
        return True

    def buy_from_shop(self: "Game", c1: "Card", buy_and_use: bool = False) -> bool | None:
        G = self
        if not buy_and_use:
            if not G.check_for_buy_space(c1):
                return False

        def buy() -> None:
            c1.area.remove_card(c1)
            c1.add_to_deck()
            if c1.ability.set in ("Default", "Enhanced"):
                G.inc_career_stat("c_playing_cards_bought", 1)
                G.playing_card = (G.playing_card + 1) if G.playing_card else 1
                G.deck.emplace(c1)
                c1.playing_card = G.playing_card
                G.playing_card_joker_effects([c1])
                G.playing_cards.append(c1)
            elif not buy_and_use:
                if c1.ability.consumeable:
                    G.consumeables.emplace(c1)
                else:
                    G.jokers.emplace(c1)
                G.ev(lambda: c1.calculate_joker(T(buying_card=True, card=c1)))
            G.GAME.round_scores.cards_purchased.amt = G.GAME.round_scores.cards_purchased.amt + 1
            if c1.ability.consumeable:
                if c1.config.center.set == "Planet":
                    G.inc_career_stat("c_planets_bought", 1)
                elif c1.config.center.set == "Tarot":
                    G.inc_career_stat("c_tarots_bought", 1)
            elif c1.ability.set == "Joker":
                G.GAME.current_round.jokers_purchased = G.GAME.current_round.jokers_purchased + 1
            for j in list(G.jokers.cards):
                j.calculate_joker(T(buying_card=True, card=c1))
            if G.GAME.modifiers.inflation:
                G.GAME.inflation = G.GAME.inflation + 1
                G.ev(G.refresh_all_costs)
            G.inc_career_stat("c_shop_dollars_spent", c1.cost)
            if c1.cost != 0:
                G.ease_dollars(-c1.cost)
            if buy_and_use:
                G.use_card(c1, True)
        G.ev(buy, trigger="after", delay=0.1)
        return None

    def toggle_shop(self: "Game") -> None:
        G = self
        G.stop_use()
        G.CONTROLLER.locks.toggle_shop = True
        if G.shop is not None:
            for j in list(G.jokers.cards):
                j.calculate_joker(T(ending_shop=True))
            shop = G.shop

            def slide() -> None:
                shop.alignment.offset.y = ROOM_Y + 29
            G.ev(slide)

            def close() -> None:
                if G.shop is not None:
                    G.shop.remove()
                G.shop = None
                G.STATE_COMPLETE = False
                G.STATE = G.STATES.BLIND_SELECT
                G.CONTROLLER.locks.toggle_shop = None
            G.ev(close, trigger="after", delay=0.5)

    def reroll_shop(self: "Game") -> None:
        G = self
        GAME = G.GAME
        G.stop_use()
        G.CONTROLLER.locks.shop_reroll = True
        if GAME.current_round.reroll_cost > 0:
            G.inc_career_stat("c_shop_dollars_spent", GAME.current_round.reroll_cost)
            G.inc_career_stat("c_shop_rerolls", 1)
            G.ease_dollars(-GAME.current_round.reroll_cost)

        def reroll() -> None:
            final_free = GAME.current_round.free_rerolls > 0
            GAME.current_round.free_rerolls = max(GAME.current_round.free_rerolls - 1, 0)
            GAME.round_scores.times_rerolled.amt = GAME.round_scores.times_rerolled.amt + 1
            G.calculate_reroll_cost(final_free)
            sj = G.shop_jokers
            for i in range(len(sj.cards) - 1, -1, -1):
                c = sj.remove_card(sj.cards[i])
                c.remove()
            for _ in range(GAME.shop.joker_max - len(sj.cards)):
                sj.emplace(G.create_card_for_shop(sj))
        G.ev(reroll)

        def after() -> None:
            def f() -> None:
                G.CONTROLLER.locks.shop_reroll = False
                for j in list(G.jokers.cards):
                    j.calculate_joker(T(reroll_shop=True))
            G.ev(f)
        G.ev(after, trigger="after", delay=0.3)
        G.ev(None)  # save_run

    # ================================================================ blinds
    def select_blind(self: "Game") -> None:
        G = self
        GAME = G.GAME
        G.stop_use()
        if G.blind_select is not None:
            GAME.facing_blind = True
            blind = G.P_BLINDS[GAME.round_resets.blind_choices[GAME.blind_on_deck]]

            def slide() -> None:
                G.blind_select.alignment.offset.y = 40
            G.ev(slide, trigger="before", delay=0.2)

            def go() -> None:
                G.ease_round(1)
                G.inc_career_stat("c_rounds", 1)
                GAME.round_resets.blind = blind
                GAME.round_resets.blind_states[GAME.blind_on_deck] = "Current"
                G.blind_select.remove()
                G.blind_select = None
                G.blind_select_tags = T()
                G.delay(0.2)
            G.ev(go)
            G.ev(G.new_round)

    def skip_blind(self: "Game") -> None:
        G = self
        GAME = G.GAME
        G.stop_use()
        G.CONTROLLER.locks.skip_blind = True

        def unlock() -> None:
            G.CONTROLLER.locks.skip_blind = None
        G.ev(unlock, no_delete=True, trigger="after", blocking=False, blockable=False, delay=2.5, timer="TOTAL")
        tag = G.blind_select_tags.get(GAME.blind_on_deck) if G.blind_select_tags else None
        GAME.skips = (GAME.skips or 0) + 1
        if tag is not None:
            G.add_tag(tag)
            skipped = GAME.blind_on_deck or "Small"
            skip_to = "Big" if GAME.blind_on_deck == "Small" else "Boss"
            GAME.round_resets.blind_states[skipped] = "Skipped"
            GAME.round_resets.blind_states[skip_to] = "Select"
            GAME.blind_on_deck = skip_to

            def after() -> None:
                G.delay(0.3)
                for j in list(G.jokers.cards):
                    j.calculate_joker(T(skip_blind=True))
                for t in list(GAME.tags):
                    t.apply_to_run(T(type="immediate"))
                for t in list(GAME.tags):
                    if t.apply_to_run(T(type="new_blind_choice")):
                        break
            G.ev(after)

    def can_reroll_boss(self: "Game") -> bool:
        GAME = self.GAME
        return ((GAME.dollars - GAME.bankrupt_at) - 10 >= 0) and bool(
            GAME.used_vouchers.get("v_retcon")
            or (GAME.used_vouchers.get("v_directors_cut") and not GAME.round_resets.boss_rerolled))

    def reroll_boss(self: "Game") -> None:
        G = self
        GAME = G.GAME
        G.stop_use()
        GAME.round_resets.boss_rerolled = True
        if not G.from_boss_tag:
            G.ease_dollars(-10)
        G.from_boss_tag = None
        G.CONTROLLER.locks.boss_reroll = True
        G.ev(None)

        def reroll() -> None:
            GAME.round_resets.blind_choices.Boss = G.get_new_boss()
            G.create_UIBox_blind_choice("Boss")

            def unlock() -> None:
                G.CONTROLLER.locks.boss_reroll = None
            G.ev(unlock, blocking=False, trigger="after", delay=0.5)
            for t in list(GAME.tags):
                if t.apply_to_run(T(type="new_blind_choice")):
                    break
        G.ev(reroll, trigger="after", delay=0.3)

    # ================================================================ packs
    def skip_booster(self: "Game") -> None:
        G = self
        for j in list(G.jokers.cards):
            j.calculate_joker(T(skipping_booster=True))
        G.end_consumeable(None)

    def end_consumeable(self: "Game", e: Any = None, delayfac: float | None = None) -> None:
        G = self
        delayfac = delayfac or 1
        G.stop_use()
        if G.booster_pack is not None and not G.booster_pack.removed:
            G.booster_pack.alignment.offset.y = ROOM_Y + 9
            bp = G.booster_pack

            def rm() -> None:
                bp.remove()
                if G.booster_pack is bp:
                    G.booster_pack = None
            G.ev(rm, trigger="after", delay=0.2 * delayfac, blocking=False, blockable=False)
        G.delay(0.2 * delayfac)

        def ev() -> None:
            G.draw_from_hand_to_deck()

            def ev2() -> None:
                for box in (G.shop, G.blind_select, G.round_eval):
                    if box is not None and not box.removed and box.alignment.offset.py is not None:
                        box.alignment.offset.y = box.alignment.offset.py
                        box.alignment.offset.py = None
                G.ev(None)
                G.STATE = G.GAME.PACK_INTERRUPT
                G.GAME.PACK_INTERRUPT = None
            G.ev(ev2, trigger="after", delay=0.2 * delayfac)
            for t in list(G.GAME.tags):
                if t.apply_to_run(T(type="new_blind_choice")):
                    break
            G.ev(None, trigger="after", delay=0.2 * delayfac)  # save_run
        G.ev(ev, trigger="after", delay=0.2 * delayfac)

    # ============================================================= cash out
    def cash_out(self: "Game") -> None:
        G = self
        GAME = G.GAME
        G.stop_use()
        if G.round_eval is not None:
            G.round_eval.alignment.offset.y = ROOM_Y + 15
            G.deck.shuffle("cashout" + G.ante_str())
            G.delay(0.3)

            def ev() -> None:
                if G.round_eval is not None:
                    G.round_eval.remove()
                    G.round_eval = None
                cr = GAME.current_round
                cr.jokers_purchased = 0
                cr.discards_left = max(0, GAME.round_resets.discards + GAME.round_bonus.discards)
                cr.hands_left = max(1, GAME.round_resets.hands + GAME.round_bonus.next_hands)
                G.STATE = G.STATES.SHOP
                GAME.shop_free = None
                GAME.shop_d6ed = None
                G.STATE_COMPLETE = False
            G.ev(ev)
            G.ease_dollars(GAME.current_round.dollars)

            def ev2() -> None:
                GAME.previous_round.dollars = GAME.dollars
            G.ev(ev2)
        G.ease_chips(0)
        if GAME.round_resets.blind_states.Boss == "Defeated":
            GAME.round_resets.blind_ante = GAME.round_resets.ante
            GAME.round_resets.blind_tags.Small = G.get_next_tag_key()
            GAME.round_resets.blind_tags.Big = G.get_next_tag_key()
        G.reset_blinds()
        G.delay(0.6)

    # ======================================================= blind select UI
    def create_UIBox_blind_select(self: "Game") -> Box:
        """create_UIBox_blind_select(): its logic (blind on deck, orbital
        choices, the skip tags)."""
        G = self
        GAME = G.GAME
        G.blind_prompt_box = Box(G, "cm", -15)
        G.ev(lambda: setattr(G.blind_prompt_box.alignment.offset, "y", 0))
        bs = GAME.round_resets.blind_states
        GAME.blind_on_deck = ("Small" if bs.Small not in ("Defeated", "Skipped", "Hide") else
                              "Big" if bs.Big not in ("Defeated", "Skipped", "Hide") else "Boss")
        G.blind_select_tags = T()
        for typ in ("Small", "Big", "Boss"):
            if bs[typ] != "Hide":
                G.create_UIBox_blind_choice(typ)
        return Box(G, "bmi", ROOM_Y + 29)

    def create_UIBox_blind_choice(self: "Game", typ: str, run_info: Any = None) -> None:
        from .tag import Tag
        G = self
        GAME = G.GAME
        if not GAME.blind_on_deck:
            GAME.blind_on_deck = "Small"
        if not run_info:
            GAME.round_resets.blind_states[GAME.blind_on_deck] = "Select"
        ante = GAME.round_resets.ante
        GAME.orbital_choices = GAME.orbital_choices or T()
        GAME.orbital_choices[ante] = GAME.orbital_choices.get(ante) or T()
        if not GAME.orbital_choices[ante].get(typ):
            hands = [k for k in G.hands_order() if GAME.hands[k].visible]
            GAME.orbital_choices[ante][typ] = G.rng.element(hands, G.rng.pseudoseed("orbital"))
        if typ in ("Small", "Big"):
            GAME.round_resets.blind_tags = GAME.round_resets.blind_tags or T()
            key = GAME.round_resets.blind_tags.get(typ)
            if key:
                G.blind_select_tags[typ] = Tag(G, key, None, typ)
