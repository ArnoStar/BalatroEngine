"""Port of functions/state_events.lua: drawing, discarding, playing and
scoring a hand, ending a round, the cash-out evaluation."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .lua import T, nonempty
from .poker import get_poker_hand_info
from .rng import lua_tostring

if TYPE_CHECKING:
    from .card import Card
    from .game import Game


def eval_card(G: "Game", card: "Card", context: T) -> T:
    """eval_card() from common_events.lua."""
    ret = T()
    if context.repetition_only:
        seals = card.calculate_seal(context)
        if seals:
            ret.seals = seals
        return ret
    if context.cardarea is G.play:
        chips = card.get_chip_bonus()
        if chips > 0:
            ret.chips = chips
        mult = card.get_chip_mult()
        if mult > 0:
            ret.mult = mult
        x_mult = card.get_chip_x_mult(context)
        if x_mult > 0:
            ret.x_mult = x_mult
        p_dollars = card.get_p_dollars()
        if p_dollars > 0:
            ret.p_dollars = p_dollars
        jokers = card.calculate_joker(context)
        if jokers:
            ret.jokers = jokers
        edition = card.get_edition(context)
        if edition:
            ret.edition = edition
    if context.cardarea is G.hand:
        h_mult = card.get_chip_h_mult()
        if h_mult > 0:
            ret.h_mult = h_mult
        h_x_mult = card.get_chip_h_x_mult()
        if h_x_mult > 0:
            ret.x_mult = h_x_mult
        jokers = card.calculate_joker(context)
        if jokers:
            ret.jokers = jokers
    if context.cardarea is G.jokers or context.card is G.consumeables:
        if context.edition:
            jokers = card.get_edition(context)
        elif context.other_joker:
            jokers = context.other_joker.calculate_joker(context)
        else:
            jokers = card.calculate_joker(context)
        if jokers:
            ret.jokers = jokers
    return ret


def mod_chips(G: "Game", chips: float) -> float:
    if G.GAME.modifiers.chips_dollar_cap:
        chips = min(chips, max(G.GAME.dollars, 0))
    return chips


def mod_mult(mult: float) -> float:
    return mult


class StateEventsMixin:
    def get_poker_hand_info(self: "Game", cards: list["Card"]) -> tuple:
        return get_poker_hand_info(self, cards)

    # =============================================================== win
    def win_game(self: "Game") -> None:
        G = self
        G.set_joker_win()
        G.inc_career_stat("c_wins", 1)

        def pause() -> None:
            G.SETTINGS.paused = True
            G.overlay_menu()
        G.ev(pause)

        def endless() -> bool | None:
            if not G.SETTINGS.paused:
                G.GAME.current_round.round_text = "Endless Round "
                return True
            return None
        G.event(endless)

    # ========================================================= end round
    def end_round(self: "Game") -> None:
        G = self
        GAME = G.GAME

        def ev() -> None:
            game_over = True
            game_won = False
            G.RESET_BLIND_STATES = True
            G.RESET_JIGGLES = True
            if GAME.chips - GAME.blind.chips >= 0:
                game_over = False
            for j in list(G.jokers.cards):
                e = j.calculate_joker(T(end_of_round=True, game_over=game_over))
                if e:
                    if e.saved:
                        game_over = False
                    G.card_eval_status_text(j, "jokers", None, None, None, e)
                j.calculate_rental()
                j.calculate_perishable()
            if GAME.round_resets.ante == GAME.win_ante and GAME.blind.get_type() == "Boss":
                game_won = True
                GAME.won = True
            if game_over:
                G.STATE = G.STATES.GAME_OVER
                G.STATE_COMPLETE = False
                return
            GAME.unused_discards = (GAME.unused_discards or 0) + GAME.current_round.discards_left
            if GAME.blind.get_type() == "Boss":
                handname, played, order = "High Card", -1, 100
                for k in G.hands_order():
                    v = GAME.hands[k]
                    if v.played > played or (v.played == played and order > v.order):
                        played = v.played
                        handname = k
                GAME.current_round.most_played_poker_hand = handname
            if GAME.blind.get_type() == "Boss":
                GAME.current_boss_streak = GAME.current_boss_streak + 1
                G.check_and_set_high_score("boss_streak", GAME.current_boss_streak)
            if GAME.current_round.hands_played == 1:
                G.inc_career_stat("c_single_hand_round_streak", 1)
            else:
                G.PROFILE.career_stats.c_single_hand_round_streak = 0
            G.set_joker_usage()
            if game_won and not GAME.win_notified:
                GAME.win_notified = True

                def win() -> bool | None:
                    if G.STATE == G.STATES.ROUND_EVAL:
                        G.win_game()
                        GAME.won = True
                        return True
                    return None
                G.event(win, blocking=False, blockable=False)
            hand = G.hand.cards
            for i in range(len(hand)):
                reps: list[Any] = [1]
                rep = 0
                while rep < len(reps):
                    if reps[rep] != 1:
                        r = reps[rep].jokers or reps[rep].seals
                        G.card_eval_status_text(r.card, "jokers", None, None, None, r)
                    effects = [G.hand.cards[i].get_end_of_round_effect()]
                    for jk in list(G.jokers.cards):
                        e = jk.calculate_joker(T(cardarea=G.hand, other_card=G.hand.cards[i], individual=True, end_of_round=True))
                        if e:
                            effects.append(e)
                    if reps[rep] == 1:
                        e = eval_card(G, G.hand.cards[i], T(end_of_round=True, cardarea=G.hand, repetition=True, repetition_only=True))
                        if nonempty(e) and (nonempty(effects[0]) or len(effects) > 1):
                            for _ in range(e.seals.repetitions):
                                reps.append(e)
                        for jk in list(G.jokers.cards):
                            e = eval_card(G, jk, T(cardarea=G.hand, other_card=G.hand.cards[i], repetition=True,
                                                   end_of_round=True, card_effects=effects))
                            if nonempty(e):
                                for _ in range(e.jokers.repetitions):
                                    reps.append(e)
                    for eff in effects:
                        if eff.card:
                            G.juice_card(eff.card)
                        if eff.h_dollars:
                            G.ease_dollars(eff.h_dollars)
                            G.card_eval_status_text(G.hand.cards[i], "dollars", eff.h_dollars)
                        if eff.extra:
                            G.card_eval_status_text(G.hand.cards[i], "extra", None, None, None, eff.extra)
                    rep += 1
            G.delay(0.3)
            G.draw_from_hand_to_discard()
            if GAME.blind.get_type() == "Boss":
                GAME.voucher_restock = None
                if GAME.modifiers.set_eternal_ante and GAME.round_resets.ante == GAME.modifiers.set_eternal_ante:
                    for v in G.jokers.cards:
                        v.set_eternal(True)
                if GAME.modifiers.set_joker_slots_ante and GAME.round_resets.ante == GAME.modifiers.set_joker_slots_ante:
                    G.jokers.config.card_limit = 0
                G.delay(0.4)
                G.ease_ante(1)
                G.delay(0.4)
            G.draw_from_discard_to_deck()

            def ev2() -> None:
                G.STATE = G.STATES.ROUND_EVAL
                G.STATE_COMPLETE = False
                rr = GAME.round_resets
                if rr.blind is G.P_BLINDS["bl_small"]:
                    rr.blind_states.Small = "Defeated"
                elif rr.blind is G.P_BLINDS["bl_big"]:
                    rr.blind_states.Big = "Defeated"
                else:
                    GAME.current_round.voucher = G.get_next_voucher_key()
                    rr.blind_states.Boss = "Defeated"
                    for v in G.playing_cards:
                        v.ability.played_this_ante = None
                if rr.temp_handsize is not None:
                    G.hand.change_size(-rr.temp_handsize)
                    rr.temp_handsize = None
                if rr.temp_reroll_cost is not None:  # 0 (D6 Tag) is truthy in Lua
                    rr.temp_reroll_cost = None
                    G.calculate_reroll_cost(True)
                G.reset_idol_card()
                G.reset_mail_rank()
                G.reset_ancient_card()
                G.reset_castle_card()
                for v in G.playing_cards:
                    v.ability.discarded = None
                    v.ability.forced_selection = None
            G.ev(ev2, trigger="after", delay=0.3)
        G.ev(ev, trigger="after", delay=0.2)

    # ========================================================= new round
    def new_round(self: "Game") -> None:
        G = self
        GAME = G.GAME
        G.RESET_JIGGLES = None
        G.delay(0.4)

        def ev() -> None:
            cr = GAME.current_round
            rr = GAME.round_resets
            cr.discards_left = max(0, rr.discards + GAME.round_bonus.discards)
            cr.hands_left = max(1, rr.hands + GAME.round_bonus.next_hands)
            cr.hands_played = 0
            cr.discards_used = 0
            cr.reroll_cost_increase = 0
            cr.used_packs = T()
            for h in GAME.hands.values():
                h.played_this_round = 0
            for v in G.playing_cards:
                v.ability.wheel_flipped = None
            cr.free_rerolls = len(G.find_joker("Chaos the Clown"))
            G.calculate_reroll_cost(True)
            GAME.round_bonus.next_hands = 0
            GAME.round_bonus.discards = 0
            if rr.blind is G.P_BLINDS["bl_small"]:
                rr.blind_states.Small = "Current"
                GAME.current_boss_streak = 0
                blhash = "S"
            elif rr.blind is G.P_BLINDS["bl_big"]:
                rr.blind_states.Big = "Current"
                GAME.current_boss_streak = 0
                blhash = "B"
            else:
                rr.blind_states.Boss = "Current"
                blhash = "L"
            GAME.subhash = lua_tostring(rr.ante) + blhash
            GAME.blind.set_blind(rr.blind)
            for j in list(G.jokers.cards):
                j.calculate_joker(T(setting_blind=True, blind=rr.blind))
            G.delay(0.4)

            def ev2() -> None:
                G.STATE = G.STATES.DRAW_TO_HAND
                G.deck.shuffle("nr" + lua_tostring(rr.ante))
                G.STATE_COMPLETE = False
            G.ev(ev2)
        G.ev(ev)

    # ======================================================= draw / discard
    def draw_from_deck_to_hand(self: "Game", e: int | None = None) -> bool | None:
        G = self
        S = G.STATES
        if not (G.STATE == S.TAROT_PACK or G.STATE == S.SPECTRAL_PACK) and G.hand.config.card_limit <= 0 and not G.hand.cards:
            G.STATE = S.GAME_OVER
            G.STATE_COMPLETE = False
            return True
        hand_space = e if e is not None else min(len(G.deck.cards), G.hand.config.card_limit - len(G.hand.cards))
        bl = G.GAME.blind
        cr = G.GAME.current_round
        if bl.name == "The Serpent" and not bl.disabled and (cr.hands_played > 0 or cr.discards_used > 0):
            hand_space = min(len(G.deck.cards), 3)
        G.delay(0.3)
        for i in range(1, hand_space + 1):
            G.draw_card(G.deck, G.hand, i * 100 / hand_space, "up", True)
        return None

    def discard_cards_from_highlighted(self: "Game", e: Any = None, hook: Any = None) -> None:
        G = self
        GAME = G.GAME
        G.stop_use()
        for v in G.playing_cards:
            v.ability.forced_selection = None
        count = min(len(G.hand.highlighted), G.discard.config.card_limit - len(G.play.cards))
        if count > 0:
            G.update_hand_text(T(immediate=True, nopulse=True, delay=0), T(mult=0, chips=0, level="", handname=""))
            G.hand.highlighted.sort(key=lambda c: G.hand.index(c))
            G.inc_career_stat("c_cards_discarded", count)
            hl = G.hand.highlighted
            for j in list(G.jokers.cards):
                j.calculate_joker(T(pre_discard=True, full_hand=hl, hook=hook))
            cards = []
            destroyed = []
            for i in range(count):
                c = hl[i]
                c.calculate_seal(T(discard=True))
                removed = False
                for j in list(G.jokers.cards):
                    ev = j.calculate_joker(T(discard=True, other_card=c, full_hand=hl))
                    if ev:
                        if ev.remove:
                            removed = True
                        G.card_eval_status_text(j, "jokers", None, 1, None, ev)
                cards.append(c)
                if removed:
                    destroyed.append(c)
                    if c.ability.name == "Glass Card":
                        c.shatter()
                    else:
                        c.start_dissolve()
                else:
                    c.ability.discarded = True
                    G.draw_card(G.hand, G.discard, (i + 1) * 100 / count, "down", False, c)
            if destroyed:
                for j in list(G.jokers.cards):
                    eval_card(G, j, T(cardarea=G.jokers, remove_playing_cards=True, removed=destroyed))
            GAME.round_scores.cards_discarded.amt = GAME.round_scores.cards_discarded.amt + len(cards)
            if not hook:
                if GAME.modifiers.discard_cost:
                    G.ease_dollars(-GAME.modifiers.discard_cost)
                G.ease_discard(-1)
                GAME.current_round.discards_used = GAME.current_round.discards_used + 1
                G.STATE = G.STATES.DRAW_TO_HAND

                def ev2() -> None:
                    G.STATE_COMPLETE = False
                G.ev(ev2)

    def play_cards_from_highlighted(self: "Game", e: Any = None) -> None:
        G = self
        GAME = G.GAME
        if G.play is not None and G.play.cards:
            return
        G.stop_use()
        GAME.blind.triggered = False
        for v in G.playing_cards:
            v.ability.forced_selection = None
        G.hand.highlighted.sort(key=lambda c: G.hand.index(c))

        def ev0() -> None:
            G.STATE = G.STATES.HAND_PLAYED
            G.STATE_COMPLETE = True
        G.ev(ev0)
        G.inc_career_stat("c_cards_played", len(G.hand.highlighted))
        G.inc_career_stat("c_hands_played", 1)
        G.ease_hands_played(-1)
        G.delay(0.4)
        hl = G.hand.highlighted
        n = len(hl)
        for i in range(n):
            c = hl[i]
            if c.is_face():
                G.inc_career_stat("c_face_cards_played", 1)
            c.base.times_played = c.base.times_played + 1
            c.ability.played_this_ante = True
            GAME.round_scores.cards_played.amt = GAME.round_scores.cards_played.amt + 1
            G.draw_card(G.hand, G.play, (i + 1) * 100 / n, "up", None, c)
        if GAME.blind.press_play():
            G.ev(None)
            G.delay(0.4)

        def ev1() -> None:
            G.ev(G.evaluate_play)

            def ev2() -> None:
                G.draw_from_play_to_discard()
                GAME.hands_played = GAME.hands_played + 1
                GAME.current_round.hands_played = GAME.current_round.hands_played + 1
            G.ev(ev2, trigger="after", delay=0.1)

            def ev3() -> None:
                G.STATE_COMPLETE = False
            G.ev(ev3)
        G.ev(ev1)

    def draw_from_play_to_discard(self: "Game") -> None:
        G = self
        count = len(G.play.cards)
        it = 1
        for v in list(G.play.cards):
            if not v.shattered and not v.destroyed:
                G.draw_card(G.play, G.discard, it * 100 / count, "down", False, v)
                it += 1

    def draw_from_play_to_hand(self: "Game", cards: list["Card"]) -> None:
        G = self
        n = len(cards)
        for i, c in enumerate(cards):
            if not c.shattered and not c.destroyed:
                G.draw_card(G.play, G.hand, (i + 1) * 100 / n, "up", True, c)

    def draw_from_discard_to_deck(self: "Game") -> None:
        G = self

        def ev() -> None:
            count = len(G.discard.cards)
            for i in range(1, count + 1):
                G.draw_card(G.discard, G.deck, i * 100 / count, "up", None, None, 0.005, i % 2 == 0, None,
                            max((21 - i) / 20, 0.7))
        G.ev(ev)

    def draw_from_hand_to_deck(self: "Game") -> None:
        G = self
        count = len(G.hand.cards)
        for i in range(1, count + 1):
            G.draw_card(G.hand, G.deck, i * 100 / count, "down", None, None, 0.08)

    def draw_from_hand_to_discard(self: "Game") -> None:
        G = self
        count = len(G.hand.cards)
        for i in range(1, count + 1):
            G.draw_card(G.hand, G.discard, i * 100 / count, "down", None, None, 0.07)

    # ============================================================= scoring
    def evaluate_play(self: "Game") -> None:  # noqa: C901 - mirrors the Lua
        G = self
        GAME = G.GAME
        text, disp_text, poker_hands, scoring_hand, non_loc = G.get_poker_hand_info(G.play.cards)
        hand = GAME.hands[text]
        hand.played = hand.played + 1
        hand.played_this_round = hand.played_this_round + 1
        GAME.last_hand_played = text
        G.set_hand_usage(text)
        hand.visible = True

        splash = bool(G.find_joker("Splash"))
        pures = []
        for i, c in enumerate(G.play.cards):
            if splash:
                if i < len(scoring_hand):
                    scoring_hand[i] = c
                else:
                    scoring_hand.append(c)
            elif c.ability.effect == "Stone Card":
                if not any(s is c for s in scoring_hand):
                    pures.append(c)
        scoring_hand.extend(pures)
        scoring_hand.sort(key=lambda c: G.play.index(c))
        G.delay(0.2)
        for i, c in enumerate(scoring_hand):
            G.highlight_card(c, (i + 1 - 0.999) / 5, "up")
        G.last_scoring = T(text=text, disp_text=disp_text, scoring=list(scoring_hand))

        ch = GAME.current_round.current_hand
        if ch.handname != disp_text:
            G.delay(0.3)
        G.update_hand_text(T(immediate=True, delay=0.4 if ch.handname != disp_text else 0),
                           T(handname=disp_text, level=hand.level, mult=hand.mult, chips=hand.chips))

        base = dict(full_hand=G.play.cards, scoring_hand=scoring_hand, scoring_name=text, poker_hands=poker_hands)
        status = G.card_eval_status_text
        uht = G.update_hand_text
        D0 = T(delay=0)
        mult = 0.0
        hand_chips = 0.0
        if not GAME.blind.debuff_hand(G.play.cards, poker_hands, text):
            mult = mod_mult(hand.mult)
            hand_chips = mod_chips(G, hand.chips)
            G.delay(0.4)
            if GAME.first_used_hand_level and GAME.first_used_hand_level > 0:
                G.level_up_hand(G.deck.cards[0] if G.deck.cards else None, text, None, GAME.first_used_hand_level)
                GAME.first_used_hand_level = None
            for j in list(G.jokers.cards):
                eff = eval_card(G, j, T(cardarea=G.jokers, before=True, **base))
                if eff.jokers:
                    status(j, "jokers", None, None, None, eff.jokers)
                    if eff.jokers.level_up:
                        G.level_up_hand(j, text)
            mult = mod_mult(hand.mult)
            hand_chips = mod_chips(G, hand.chips)
            mult, hand_chips, modded = GAME.blind.modify_hand(G.play.cards, poker_hands, text, mult, hand_chips)
            mult, hand_chips = mod_mult(mult), mod_chips(G, hand_chips)
            if modded:
                uht(T(sound="chips2", modded=modded), T(chips=hand_chips, mult=mult))

            # ------------------------------------------------ played cards
            for c in scoring_hand:
                if c.ability.effect != "Stone Card":
                    cp = GAME.cards_played[c.base.value]
                    cp.total = cp.total + 1
                    cp.suits[c.base.suit] = True
                if c.debuff:
                    GAME.blind.triggered = True
                    G.ev(None)
                    status(c, "debuff")
                    continue
                reps: list[Any] = [1]
                e = eval_card(G, c, T(repetition_only=True, cardarea=G.play, repetition=True, **base))
                if nonempty(e):
                    for _ in range(e.seals.repetitions):
                        reps.append(e)
                for j in list(G.jokers.cards):
                    e = eval_card(G, j, T(cardarea=G.play, other_card=c, repetition=True, **base))
                    if nonempty(e) and e.jokers:
                        for _ in range(e.jokers.repetitions):
                            reps.append(e)
                for r in reps:
                    if r != 1:
                        rr = r.jokers or r.seals
                        status(rr.card, "jokers", None, None, None, rr)
                    effects = [eval_card(G, c, T(cardarea=G.play, full_hand=G.play.cards, scoring_hand=scoring_hand,
                                                 poker_hand=text))]
                    for j in list(G.jokers.cards):
                        e = j.calculate_joker(T(cardarea=G.play, other_card=c, individual=True, **base))
                        if e:
                            effects.append(e)
                    c.lucky_trigger = None
                    for eff in effects:
                        if eff.chips:
                            if eff.card:
                                G.juice_card(eff.card)
                            hand_chips = mod_chips(G, hand_chips + eff.chips)
                            uht(D0, T(chips=hand_chips))
                            status(c, "chips", eff.chips)
                        if eff.mult:
                            if eff.card:
                                G.juice_card(eff.card)
                            mult = mod_mult(mult + eff.mult)
                            uht(D0, T(mult=mult))
                            status(c, "mult", eff.mult)
                        if eff.p_dollars:
                            if eff.card:
                                G.juice_card(eff.card)
                            G.ease_dollars(eff.p_dollars)
                            status(c, "dollars", eff.p_dollars)
                        if eff.dollars:
                            if eff.card:
                                G.juice_card(eff.card)
                            G.ease_dollars(eff.dollars)
                            status(c, "dollars", eff.dollars)
                        if eff.extra:
                            if eff.card:
                                G.juice_card(eff.card)
                            ex = eff.extra
                            ext_m = ext_c = False
                            if ex.mult_mod:
                                mult = mod_mult(mult + ex.mult_mod)
                                ext_m = True
                            if ex.chip_mod:
                                hand_chips = mod_chips(G, hand_chips + ex.chip_mod)
                                ext_c = True
                            if ex.swap:
                                old_mult = mult
                                mult = mod_mult(hand_chips)
                                hand_chips = mod_chips(G, old_mult)
                                ext_c = ext_m = True
                            if ex.func:
                                ex.func()
                            uht(D0, T(chips=hand_chips if ext_c else None, mult=mult if ext_m else None))
                            status(c, "extra", None, None, None, ex)
                        if eff.x_mult:
                            if eff.card:
                                G.juice_card(eff.card)
                            mult = mod_mult(mult * eff.x_mult)
                            uht(D0, T(mult=mult))
                            status(c, "x_mult", eff.x_mult)
                        if eff.edition:
                            ed = eff.edition
                            hand_chips = mod_chips(G, hand_chips + (ed.chip_mod or 0))
                            mult = mult + (ed.mult_mod or 0)
                            mult = mod_mult(mult * (ed.x_mult_mod or 1))
                            uht(D0, T(chips=hand_chips if ed.chip_mod else None,
                                      mult=mult if (ed.mult_mod or ed.x_mult_mod) else None))
                            status(c, "extra", None, None, None, T(message="edition", chip_mod=ed.chip_mod,
                                                                   mult_mod=ed.mult_mod, x_mult_mod=ed.x_mult_mod,
                                                                   edition=True))

            G.delay(0.3)
            # ---------------------------------------------- held in hand
            for i in range(len(G.hand.cards)):
                reps = [1]
                rep = 0
                while rep < len(reps):
                    if reps[rep] != 1:
                        rr = reps[rep].jokers or reps[rep].seals
                        status(rr.card, "jokers", None, None, None, rr)
                    hc = G.hand.cards[i]
                    effects = [eval_card(G, hc, T(cardarea=G.hand, **base))]
                    for jk in list(G.jokers.cards):
                        e = jk.calculate_joker(T(cardarea=G.hand, other_card=hc, individual=True, **base))
                        if e:
                            effects.append(e)
                    if reps[rep] == 1:
                        e = eval_card(G, hc, T(repetition_only=True, cardarea=G.hand, repetition=True,
                                               card_effects=effects, **base))
                        if nonempty(e) and (nonempty(effects[0]) or len(effects) > 1):
                            for _ in range(e.seals.repetitions):
                                reps.append(e)
                        for jk in list(G.jokers.cards):
                            e = eval_card(G, jk, T(cardarea=G.hand, other_card=hc, repetition=True,
                                                   card_effects=effects, **base))
                            if nonempty(e):
                                for _ in range(e.jokers.repetitions):
                                    reps.append(e)
                    for eff in effects:
                        if eff.card:
                            G.juice_card(eff.card)
                        if eff.dollars:
                            G.ease_dollars(eff.dollars)
                            status(hc, "dollars", eff.dollars)
                        if eff.h_mult:
                            mult = mod_mult(mult + eff.h_mult)
                            uht(D0, T(mult=mult))
                            status(hc, "h_mult", eff.h_mult)
                        if eff.x_mult:
                            mult = mod_mult(mult * eff.x_mult)
                            uht(D0, T(mult=mult))
                            status(hc, "x_mult", eff.x_mult)
                        if eff.message:
                            uht(D0, T(mult=mult))
                            status(hc, "extra", None, None, None, eff)
                    rep += 1

            # ---------------------------------------------------- jokers
            nj = len(G.jokers.cards)
            for i in range(nj + len(G.consumeables.cards)):
                card = G.jokers.cards[i] if i < len(G.jokers.cards) else G.consumeables.cards[i - len(G.jokers.cards)]
                ed_eff = eval_card(G, card, T(cardarea=G.jokers, edition=True, **base))
                if ed_eff.jokers:
                    ed_eff.jokers.edition = True
                    if ed_eff.jokers.chip_mod:
                        hand_chips = mod_chips(G, hand_chips + ed_eff.jokers.chip_mod)
                        uht(D0, T(chips=hand_chips))
                        status(card, "jokers", None, None, None, T(message="edition", chip_mod=ed_eff.jokers.chip_mod,
                                                                   edition=True))
                    if ed_eff.jokers.mult_mod:
                        mult = mod_mult(mult + ed_eff.jokers.mult_mod)
                        uht(D0, T(mult=mult))
                        status(card, "jokers", None, None, None, T(message="edition", mult_mod=ed_eff.jokers.mult_mod,
                                                                   edition=True))
                effects = eval_card(G, card, T(cardarea=G.jokers, joker_main=True, **base))
                if effects.jokers:
                    ej = effects.jokers
                    ext_m = ext_c = False
                    if ej.mult_mod:
                        mult = mod_mult(mult + ej.mult_mod)
                        ext_m = True
                    if ej.chip_mod:
                        hand_chips = mod_chips(G, hand_chips + ej.chip_mod)
                        ext_c = True
                    if ej.Xmult_mod:
                        mult = mod_mult(mult * ej.Xmult_mod)
                        ext_m = True
                    uht(D0, T(chips=hand_chips if ext_c else None, mult=mult if ext_m else None))
                    status(card, "jokers", None, None, None, ej)
                for v in list(G.jokers.cards):
                    effect = v.calculate_joker(T(other_joker=card, **base))
                    if effect:
                        ext_m = ext_c = False
                        if effect.mult_mod:
                            mult = mod_mult(mult + effect.mult_mod)
                            ext_m = True
                        if effect.chip_mod:
                            hand_chips = mod_chips(G, hand_chips + effect.chip_mod)
                            ext_c = True
                        if effect.Xmult_mod:
                            mult = mod_mult(mult * effect.Xmult_mod)
                            ext_m = True
                        if ext_m or ext_c:
                            uht(D0, T(chips=hand_chips if ext_c else None, mult=mult if ext_m else None))
                            status(v, "jokers", None, None, None, effect)
                if ed_eff.jokers:
                    if ed_eff.jokers.x_mult_mod:
                        mult = mod_mult(mult * ed_eff.jokers.x_mult_mod)
                        uht(D0, T(mult=mult))
                        status(card, "jokers", None, None, None, T(message="edition",
                                                                   x_mult_mod=ed_eff.jokers.x_mult_mod, edition=True))

            res = GAME.selected_back.trigger_effect(T(context="final_scoring_step", chips=hand_chips, mult=mult))
            nu_chip, nu_mult = res if res else (None, None)
            mult = mod_mult(nu_mult if nu_mult is not None else mult)
            hand_chips = mod_chips(G, nu_chip if nu_chip is not None else hand_chips)

            cards_destroyed = []
            for c in scoring_hand:
                G.highlight_card(c, None, "down")
                destroyed = None
                for j in list(G.jokers.cards):
                    destroyed = j.calculate_joker(T(destroying_card=c, full_hand=G.play.cards))
                    if destroyed:
                        break
                if c.ability.name == "Glass Card" and not c.debuff and G.rng.random("glass") < GAME.probabilities.normal / c.ability.extra:
                    destroyed = True
                if destroyed:
                    if c.ability.name == "Glass Card":
                        c.shattered = True
                    else:
                        c.destroyed = True
                    cards_destroyed.append(c)
            for j in list(G.jokers.cards):
                eval_card(G, j, T(cardarea=G.jokers, remove_playing_cards=True, removed=cards_destroyed))
            for c in cards_destroyed:
                def kill(c: "Card" = c) -> None:
                    if c.ability.name == "Glass Card":
                        c.shatter()
                    else:
                        c.start_dissolve()
                G.ev(kill)
        else:
            mult = mod_mult(0)
            hand_chips = mod_chips(G, 0)
            G.ev(None)
            G.play_area_status_text("Not Allowed!")
            for j in list(G.jokers.cards):
                eff = eval_card(G, j, T(cardarea=G.jokers, debuffed_hand=True, **base))
                if eff.jokers:
                    status(j, "jokers", None, None, None, eff.jokers)

        score = G.floor(hand_chips * mult)
        round_score = GAME.chips + score

        def total() -> None:
            G._feedback("hand_scored", hand=text, chips=hand_chips, mult=mult, score=score, round_score=round_score)
            uht(T(delay=0, immediate=True), T(mult=0, chips=0, chip_total=score, level="", handname=""))
        G.ev(total, trigger="after", delay=0.4)
        G.check_and_set_high_score("hand", hand_chips * mult)
        G.last_score = T(chips=hand_chips, mult=mult, score=score, hand=text)
        if hand_chips * mult > 0:
            G.delay(0.8)
            G.ev(None)
        G.event(G.floor, trigger="ease", blocking=False, ref_table=GAME, ref_value="chips", ease_to=round_score,
                delay=0.5)
        G.event(G.floor, trigger="ease", blocking=True, ref_table=GAME.current_round.current_hand,
                ref_value="chip_total", ease_to=0, delay=0.5)

        def clear_name() -> None:
            GAME.current_round.current_hand.handname = ""
        G.ev(clear_name)
        G.delay(0.3)
        for j in list(G.jokers.cards):
            eff = eval_card(G, j, T(cardarea=G.jokers, after=True, **base))
            if eff.jokers:
                status(j, "jokers", None, None, None, eff.jokers)

        def debuff_played() -> None:
            if GAME.modifiers.debuff_played_cards:
                for c in scoring_hand:
                    c.ability.perma_debuff = True
        G.ev(debuff_played)

    # =========================================================== cash out
    def evaluate_round(self: "Game") -> None:
        G = self
        GAME = G.GAME
        dollars = 0
        rows: list[tuple[str, float]] = []
        if GAME.chips - GAME.blind.chips >= 0:
            G.add_round_eval_row(T(dollars=GAME.blind.dollars, name="blind1"))
            rows.append(("blind", GAME.blind.dollars))
            dollars = dollars + GAME.blind.dollars
        else:
            G.add_round_eval_row(T(dollars=0, name="blind1", saved=True))
            rows.append(("blind", 0))
        G.ev(GAME.blind.defeat, trigger="before", delay=1.3 * min(GAME.blind.dollars + 2, 7) / 2 * 0.15 + 0.5)
        G.delay(0.2)
        G.ev(None)
        GAME.selected_back.trigger_effect(T(context="eval"))
        cr = GAME.current_round
        if cr.hands_left > 0 and not GAME.modifiers.no_extra_hand_money:
            v = cr.hands_left * (GAME.modifiers.money_per_hand or 1)
            G.add_round_eval_row(T(dollars=v, disp=cr.hands_left, bonus=True, name="hands"))
            rows.append(("hands", v))
            dollars = dollars + v
        if cr.discards_left > 0 and GAME.modifiers.money_per_discard:
            v = cr.discards_left * GAME.modifiers.money_per_discard
            G.add_round_eval_row(T(dollars=v, disp=cr.discards_left, bonus=True, name="discards"))
            rows.append(("discards", v))
            dollars = dollars + v
        for i, j in enumerate(list(G.jokers.cards)):
            ret = j.calculate_dollar_bonus()
            if ret:
                G.add_round_eval_row(T(dollars=ret, bonus=True, name="joker" + str(i + 1), card=j))
                rows.append(("joker:" + j.key, ret))
                dollars = dollars + ret
        for i, t in enumerate(list(GAME.tags)):
            ret = t.apply_to_run(T(type="eval"))
            if ret:
                G.add_round_eval_row(T(dollars=ret.dollars, bonus=True, name="tag" + str(i + 1)))
                rows.append(("tag:" + t.key, ret.dollars))
                dollars = dollars + ret.dollars
        if GAME.dollars >= 5 and not GAME.modifiers.no_interest:
            v = GAME.interest_amount * min(math.floor(GAME.dollars / 5), GAME.interest_cap / 5)
            G.add_round_eval_row(T(bonus=True, name="interest", dollars=v))
            cs = G.PROFILE.career_stats
            if v == GAME.interest_amount * GAME.interest_cap / 5:
                cs.c_round_interest_cap_streak = cs.c_round_interest_cap_streak + 1
            else:
                cs.c_round_interest_cap_streak = 0
            rows.append(("interest", v))
            dollars = dollars + v
        G.add_round_eval_row(T(name="bottom", dollars=dollars))
        G.round_eval_rows = rows
