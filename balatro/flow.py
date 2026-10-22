"""Round flow: blind selection, drawing, playing, scoring, end of round.

Port of functions/state_events.lua, the matching parts of
functions/button_callbacks.lua and the Game:update_* state functions.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .lua import T, floor, nonempty
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


class FlowMixin:
    # ================================================================ driver
    def advance(self: "Game", max_iter: int = 1000000) -> None:
        """Run the game loop until it waits for input.

        Mirrors Game:update(): every frame the event manager handles at most
        ONE blocking event (EventManager:update sets ``blocked`` after the
        first blocking event it handles, completed or not), then the state
        machine runs (Game:update_*), then every card runs Card:update.
        """
        G = self
        ev = G.events
        for _ in range(max_iter):
            if ev:
                ev.popleft()()
            before = (G.STATE, G.STATE_COMPLETE)
            G.update_state()
            G.update_cards()
            if ev or (G.STATE, G.STATE_COMPLETE) != before:
                continue
            if G.deferred:
                G.run_deferred_one_frame()
                continue
            return
        raise RuntimeError("advance(): no fixed point (infinite loop?)")

    def update_state(self: "Game") -> None:
        G = self
        S = G.STATES
        st = G.STATE
        if st == S.SELECTING_HAND:
            if not G.hand.cards and G.deck.cards:
                G.STATE = S.DRAW_TO_HAND
                G.STATE_COMPLETE = False
            else:
                G.update_selecting_hand()
        elif st == S.HAND_PLAYED:
            G.update_hand_played()
        elif st == S.DRAW_TO_HAND:
            G.update_draw_to_hand()
        elif st == S.NEW_ROUND:
            G.update_new_round()
        elif st == S.BLIND_SELECT:
            G.update_blind_select()
        elif st == S.ROUND_EVAL:
            G.update_round_eval()
        elif st == S.SHOP:
            G.update_shop()
        elif st in (S.TAROT_PACK, S.SPECTRAL_PACK, S.STANDARD_PACK, S.BUFFOON_PACK, S.PLANET_PACK):
            G.update_pack()
        elif st == S.GAME_OVER:
            if not G.STATE_COMPLETE:
                # update_game_over pauses the game: every pending event was
                # created unpaused and is skipped from now on.  Timed
                # non-blockable effects (eaten jokers, shattered/dissolved
                # cards) were created during the scoring animations, seconds
                # before the end of round, so they already happened - together
                # with the events they queued.
                G.STATE_COMPLETE = True
                G.events.clear()
                G.run_deferred()  # fires them and the events they queue
                G.events.clear()

    # ----------------------------------------------------- state functions
    def update_selecting_hand(self: "Game") -> None:
        G = self
        if not G.hand.cards and not G.deck.cards and not G.play.cards:
            G.end_round()
        if G.shop is not None:
            G.remove_shop()
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True
            if not G.hand.cards and not G.deck.cards:
                G.end_round()

    def update_hand_played(self: "Game") -> None:
        G = self
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True

            def ev() -> None:
                # this event sits behind ~2s of scoring animations; every timed
                # effect queued while scoring (shattered glass, Sixth Sense,
                # eaten jokers) has fired by now, before end_round's RNG
                # (Idol/Mail/Castle picks over G.playing_cards)
                G.run_deferred_one_frame()
                if G.GAME.chips - G.GAME.blind.chips >= 0 or G.GAME.current_round.hands_left < 1:
                    G.STATE = G.STATES.NEW_ROUND
                else:
                    G.STATE = G.STATES.DRAW_TO_HAND
                G.STATE_COMPLETE = False
            G.add_event(ev)

    def update_draw_to_hand(self: "Game") -> None:
        G = self
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True
            for tag in list(G.GAME.tags):
                tag.apply_to_run(T(type="round_start_bonus"))

            def ev() -> None:
                if G.draw_from_deck_to_hand(None):
                    return
                cr = G.GAME.current_round
                if cr.hands_played == 0 and cr.discards_used == 0 and G.GAME.facing_blind:
                    for j in list(G.jokers.cards):
                        j.calculate_joker(T(first_hand_drawn=True))

                def ev2() -> None:
                    G.STATE = G.STATES.SELECTING_HAND
                    G.STATE_COMPLETE = False
                    G.GAME.blind.drawn_to_hand()
                G.add_event(ev2)
            G.add_event(ev)

    def update_new_round(self: "Game") -> None:
        G = self
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True
            G.end_round()

    def update_blind_select(self: "Game") -> None:
        G = self
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True

            def ev() -> None:
                def ev2() -> None:
                    G.create_blind_select()
                    for tag in list(G.GAME.tags):
                        tag.apply_to_run(T(type="immediate"))
                    for tag in list(G.GAME.tags):
                        if tag.apply_to_run(T(type="new_blind_choice")):
                            break
                G.add_event(ev2)
            G.add_event(ev)

    def update_round_eval(self: "Game") -> None:
        G = self
        if not G.STATE_COMPLETE:
            G.STATE_COMPLETE = True

            def ev() -> None:
                G.GAME.facing_blind = None
                G.round_eval = True
                G.add_event(G.evaluate_round)
            G.add_event(ev)

    # ======================================================== blind select
    def create_blind_select(self: "Game") -> None:
        """create_UIBox_blind_select(): decides blind_on_deck, orbital choices, tags."""
        from .tag import Tag
        G = self
        GAME = G.GAME
        rr = GAME.round_resets
        bs = rr.blind_states
        GAME.blind_on_deck = ("Small" if bs.Small not in ("Defeated", "Skipped", "Hide") else
                              "Big" if bs.Big not in ("Defeated", "Skipped", "Hide") else "Boss")
        G.blind_select = T(tags=T())
        for typ in ("Small", "Big", "Boss"):
            if bs[typ] == "Hide":
                continue
            G.create_blind_choice(typ)
            if typ in ("Small", "Big") and rr.blind_tags and rr.blind_tags.get(typ):
                G.blind_select.tags[typ] = Tag(G, rr.blind_tags[typ], None, typ)

    def create_blind_choice(self: "Game", typ: str, run_info: bool = False) -> None:
        G = self
        GAME = G.GAME
        if not GAME.blind_on_deck:
            GAME.blind_on_deck = "Small"
        if not run_info:
            GAME.round_resets.blind_states[GAME.blind_on_deck] = "Select"
        ante = GAME.round_resets.ante
        GAME.orbital_choices = GAME.orbital_choices or T()
        if GAME.orbital_choices.get(ante) is None:
            GAME.orbital_choices[ante] = T()
        if not GAME.orbital_choices[ante].get(typ):
            poker_hands = [k for k in G.hands_order() if GAME.hands[k].visible]
            GAME.orbital_choices[ante][typ] = G.rng.element(poker_hands, G.rng.pseudoseed("orbital"))
        GAME.round_resets.blind_ante = GAME.round_resets.blind_ante or GAME.round_resets.ante

    def select_blind(self: "Game") -> None:
        G = self
        assert G.STATE == G.STATES.BLIND_SELECT and G.blind_select is not None, "not selecting a blind"
        GAME = G.GAME
        GAME.facing_blind = True
        blind = G.P_BLINDS[GAME.round_resets.blind_choices[GAME.blind_on_deck]]

        def ev() -> None:
            G.ease_round(1)
            GAME.round_resets.blind = blind
            GAME.round_resets.blind_states[GAME.blind_on_deck] = "Current"
            G.blind_select = None
        G.add_event(ev)
        G.add_event(G.new_round)
        G.advance()

    def skip_blind(self: "Game") -> None:
        G = self
        assert G.STATE == G.STATES.BLIND_SELECT and G.blind_select is not None, "not selecting a blind"
        GAME = G.GAME
        tag = G.blind_select.tags.get(GAME.blind_on_deck)
        assert tag is not None, "this blind can't be skipped"
        GAME.skips = (GAME.skips or 0) + 1
        G.add_tag(tag)
        skipped = GAME.blind_on_deck or "Small"
        skip_to = "Big" if GAME.blind_on_deck == "Small" else "Boss"
        GAME.round_resets.blind_states[skipped] = "Skipped"
        GAME.round_resets.blind_states[skip_to] = "Select"
        GAME.blind_on_deck = skip_to

        def ev() -> None:
            for j in list(G.jokers.cards):
                j.calculate_joker(T(skip_blind=True))
            for t in list(GAME.tags):
                t.apply_to_run(T(type="immediate"))
            for t in list(GAME.tags):
                if t.apply_to_run(T(type="new_blind_choice")):
                    break
        G.add_event(ev)
        G.advance()

    def reroll_boss(self: "Game", _from_ui: bool = True) -> None:
        G = self
        GAME = G.GAME
        GAME.round_resets.boss_rerolled = True
        if not G.from_boss_tag:
            G.ease_dollars(-10)
        G.from_boss_tag = None

        def ev() -> None:
            GAME.round_resets.blind_choices.Boss = G.get_new_boss()
            G.create_blind_choice("Boss")
            for t in list(GAME.tags):
                if t.apply_to_run(T(type="new_blind_choice")):
                    break
        G.add_event(ev)
        if _from_ui:
            G.advance()

    def can_reroll_boss(self: "Game") -> bool:
        GAME = self.GAME
        return ((GAME.dollars - GAME.bankrupt_at) - 10 >= 0) and bool(
            GAME.used_vouchers.get("v_retcon") or (GAME.used_vouchers.get("v_directors_cut") and not GAME.round_resets.boss_rerolled))

    # ============================================================ new round
    def new_round(self: "Game") -> None:
        G = self
        GAME = G.GAME

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

            def ev2() -> None:
                G.STATE = G.STATES.DRAW_TO_HAND
                G.deck.shuffle("nr" + lua_tostring(rr.ante))
                G.STATE_COMPLETE = False
            G.add_event(ev2)
        G.add_event(ev)

    # ========================================================= draw/discard
    def draw_from_deck_to_hand(self: "Game", e: int | None = None) -> bool | None:
        G = self
        S = G.STATES
        if G.STATE not in (S.TAROT_PACK, S.SPECTRAL_PACK) and G.hand.config.card_limit <= 0 and not G.hand.cards:
            G.STATE = S.GAME_OVER
            G.STATE_COMPLETE = False
            return True
        hand_space = e if e is not None else min(len(G.deck.cards), G.hand.config.card_limit - len(G.hand.cards))
        bl = G.GAME.blind
        cr = G.GAME.current_round
        if bl.name == "The Serpent" and not bl.disabled and (cr.hands_played > 0 or cr.discards_used > 0):
            hand_space = min(len(G.deck.cards), 3)
        for _ in range(hand_space):
            G.draw_card(G.deck, G.hand, None, True)
        return None

    def discard_cards_from_highlighted(self: "Game", e: Any = None, hook: bool = False) -> None:
        G = self
        GAME = G.GAME
        for v in G.playing_cards:
            v.ability.forced_selection = None
        highlighted_count = min(len(G.hand.highlighted), G.discard.config.card_limit - len(G.play.cards))
        if highlighted_count > 0:
            G.hand.highlighted.sort(key=lambda c: G.hand.index(c))
            hl = G.hand.highlighted
            for j in list(G.jokers.cards):
                j.calculate_joker(T(pre_discard=True, full_hand=hl, hook=hook))
            cards = []
            destroyed_cards = []
            for i in range(highlighted_count):
                c = hl[i]
                c.calculate_seal(T(discard=True))
                removed = False
                for j in list(G.jokers.cards):
                    ev = j.calculate_joker(T(discard=True, other_card=c, full_hand=hl))
                    if ev:
                        if ev.remove:
                            removed = True
                cards.append(c)
                if removed:
                    destroyed_cards.append(c)
                    if c.ability.name == "Glass Card":
                        c.shatter()
                    else:
                        c.start_dissolve()
                else:
                    c.ability.discarded = True
                    G.draw_card(G.hand, G.discard, c)
            if destroyed_cards:
                for j in list(G.jokers.cards):
                    eval_card(G, j, T(cardarea=G.jokers, remove_playing_cards=True, removed=destroyed_cards))
            GAME.round_scores.cards_discarded.amt += len(cards)
            if not hook:
                if GAME.modifiers.discard_cost:
                    G.ease_dollars(-GAME.modifiers.discard_cost)
                G.ease_discard(-1)
                GAME.current_round.discards_used += 1
                G.STATE = G.STATES.DRAW_TO_HAND

                def ev2() -> None:
                    G.STATE_COMPLETE = False
                G.add_event(ev2)

    def play_cards_from_highlighted(self: "Game", e: Any = None) -> None:
        G = self
        GAME = G.GAME
        if G.play.cards:
            return
        GAME.blind.triggered = False
        for v in G.playing_cards:
            v.ability.forced_selection = None
        G.hand.highlighted.sort(key=lambda c: G.hand.index(c))

        def ev0() -> None:
            G.STATE = G.STATES.HAND_PLAYED
            G.STATE_COMPLETE = True
        G.add_event(ev0)
        G.ease_hands_played(-1)
        for c in list(G.hand.highlighted):
            c.base.times_played += 1
            c.ability.played_this_ante = True
            GAME.round_scores.cards_played.amt += 1
            G.draw_card(G.hand, G.play, c)
        GAME.blind.press_play()

        def ev1() -> None:
            G.add_event(G.evaluate_play)

            def ev2() -> None:
                G.draw_from_play_to_discard()
                GAME.hands_played += 1
                GAME.current_round.hands_played += 1
            G.add_event(ev2)

            def ev3() -> None:
                G.STATE_COMPLETE = False
            G.add_event(ev3)
        G.add_event(ev1)

    def draw_from_play_to_discard(self: "Game") -> None:
        G = self
        for v in list(G.play.cards):
            if not v.shattered and not v.destroyed:
                G.draw_card(G.play, G.discard, v)

    def draw_from_play_to_hand(self: "Game", cards: list["Card"]) -> None:
        G = self
        for c in cards:
            if not c.shattered and not c.destroyed:
                G.draw_card(G.play, G.hand, c, True)

    def draw_from_discard_to_deck(self: "Game") -> None:
        G = self

        def ev() -> None:
            for _ in range(len(G.discard.cards)):
                G.draw_card(G.discard, G.deck)
        G.add_event(ev)

    def draw_from_hand_to_deck(self: "Game") -> None:
        G = self
        for _ in range(len(G.hand.cards)):
            G.draw_card(G.hand, G.deck)

    def draw_from_hand_to_discard(self: "Game") -> None:
        G = self
        for _ in range(len(G.hand.cards)):
            G.draw_card(G.hand, G.discard)

    # ============================================================== scoring
    def evaluate_play(self: "Game") -> None:
        G = self
        GAME = G.GAME
        text, disp_text, poker_hands, scoring_hand, non_loc_disp_text = get_poker_hand_info(G, G.play.cards)
        hand = GAME.hands[text]
        hand.played += 1
        hand.played_this_round += 1
        GAME.last_hand_played = text
        GAME.hand_usage[text] = (GAME.hand_usage.get(text) or 0) + 1
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
        G.last_scoring = T(text=text, disp_text=disp_text, scoring=list(scoring_hand))

        ctx_base = dict(full_hand=G.play.cards, scoring_hand=scoring_hand, scoring_name=text, poker_hands=poker_hands)
        mult = 0.0
        hand_chips = 0.0
        if not GAME.blind.debuff_hand(G.play.cards, poker_hands, text):
            mult = mod_mult(hand.mult)
            hand_chips = mod_chips(G, hand.chips)
            if GAME.first_used_hand_level and GAME.first_used_hand_level > 0:
                G.level_up_hand(None, text, None, GAME.first_used_hand_level)
                GAME.first_used_hand_level = None
            for j in list(G.jokers.cards):
                effects = eval_card(G, j, T(cardarea=G.jokers, before=True, **ctx_base))
                if effects.jokers:
                    if effects.jokers.playing_cards_created:  # via card_eval_status_text
                        G.playing_card_joker_effects(effects.jokers.playing_cards_created)
                    if effects.jokers.level_up:
                        G.level_up_hand(j, text)
            mult = mod_mult(hand.mult)
            hand_chips = mod_chips(G, hand.chips)
            mult, hand_chips, modded = GAME.blind.modify_hand(G.play.cards, poker_hands, text, mult, hand_chips)
            mult, hand_chips = mod_mult(mult), mod_chips(G, hand_chips)

            # --- played cards
            for c in scoring_hand:
                if c.ability.effect != "Stone Card":
                    cp = GAME.cards_played[c.base.value]
                    cp.total += 1
                    cp.suits[c.base.suit] = True
                if c.debuff:
                    GAME.blind.triggered = True
                    continue
                reps: list[Any] = [1]
                ev = eval_card(G, c, T(repetition_only=True, cardarea=G.play, repetition=True, **ctx_base))
                if nonempty(ev):
                    for _ in range(ev.seals.repetitions):
                        reps.append(ev)
                for j in list(G.jokers.cards):
                    ev = eval_card(G, j, T(cardarea=G.play, other_card=c, repetition=True, **ctx_base))
                    if nonempty(ev) and ev.jokers:
                        for _ in range(ev.jokers.repetitions):
                            reps.append(ev)
                for _r in reps:
                    effects = [eval_card(G, c, T(cardarea=G.play, full_hand=G.play.cards, scoring_hand=scoring_hand, poker_hand=text))]
                    for j in list(G.jokers.cards):
                        ev = j.calculate_joker(T(cardarea=G.play, other_card=c, individual=True, **ctx_base))
                        if ev:
                            effects.append(ev)
                    c.lucky_trigger = None
                    for eff in effects:
                        if eff.chips:
                            hand_chips = mod_chips(G, hand_chips + eff.chips)
                        if eff.mult:
                            mult = mod_mult(mult + eff.mult)
                        if eff.p_dollars:
                            G.ease_dollars(eff.p_dollars)
                        if eff.dollars:
                            G.ease_dollars(eff.dollars)
                        if eff.extra:
                            ex = eff.extra
                            if ex.mult_mod:
                                mult = mod_mult(mult + ex.mult_mod)
                            if ex.chip_mod:
                                hand_chips = mod_chips(G, hand_chips + ex.chip_mod)
                            if ex.swap:
                                old_mult = mult
                                mult = mod_mult(hand_chips)
                                hand_chips = mod_chips(G, old_mult)
                            if ex.func:
                                ex.func()
                        if eff.x_mult:
                            mult = mod_mult(mult * eff.x_mult)
                        if eff.edition:
                            ed = eff.edition
                            hand_chips = mod_chips(G, hand_chips + (ed.chip_mod or 0))
                            mult = mult + (ed.mult_mod or 0)
                            mult = mod_mult(mult * (ed.x_mult_mod or 1))

            # --- cards held in hand
            for hc in list(G.hand.cards):
                reps = [1]
                k = 0
                while k < len(reps):
                    effects = [eval_card(G, hc, T(cardarea=G.hand, **ctx_base))]
                    for j in list(G.jokers.cards):
                        ev = j.calculate_joker(T(cardarea=G.hand, other_card=hc, individual=True, **ctx_base))
                        if ev:
                            effects.append(ev)
                    if reps[k] == 1:
                        ev = eval_card(G, hc, T(repetition_only=True, cardarea=G.hand, repetition=True, card_effects=effects, **ctx_base))
                        if nonempty(ev) and (nonempty(effects[0]) or len(effects) > 1):
                            for _ in range(ev.seals.repetitions):
                                reps.append(ev)
                        for j in list(G.jokers.cards):
                            ev = eval_card(G, j, T(cardarea=G.hand, other_card=hc, repetition=True, card_effects=effects, **ctx_base))
                            if nonempty(ev):
                                for _ in range(ev.jokers.repetitions):
                                    reps.append(ev)
                    for eff in effects:
                        if eff.dollars:
                            G.ease_dollars(eff.dollars)
                        if eff.h_mult:
                            mult = mod_mult(mult + eff.h_mult)
                        if eff.x_mult:
                            mult = mod_mult(mult * eff.x_mult)
                    k += 1

            # --- jokers (and consumables: Observatory planets)
            nj = len(G.jokers.cards)
            for i in range(nj + len(G.consumeables.cards)):
                _card = G.jokers.cards[i] if i < len(G.jokers.cards) else G.consumeables.cards[i - len(G.jokers.cards)]
                edition_effects = eval_card(G, _card, T(cardarea=G.jokers, edition=True, **ctx_base))
                if edition_effects.jokers:
                    edition_effects.jokers.edition = True
                    if edition_effects.jokers.chip_mod:
                        hand_chips = mod_chips(G, hand_chips + edition_effects.jokers.chip_mod)
                    if edition_effects.jokers.mult_mod:
                        mult = mod_mult(mult + edition_effects.jokers.mult_mod)
                effects = eval_card(G, _card, T(cardarea=G.jokers, joker_main=True, **ctx_base))
                if effects.jokers:
                    ej = effects.jokers
                    if ej.mult_mod:
                        mult = mod_mult(mult + ej.mult_mod)
                    if ej.chip_mod:
                        hand_chips = mod_chips(G, hand_chips + ej.chip_mod)
                    if ej.Xmult_mod:
                        mult = mod_mult(mult * ej.Xmult_mod)
                for v in list(G.jokers.cards):
                    effect = v.calculate_joker(T(other_joker=_card, **ctx_base))
                    if effect:
                        if effect.mult_mod:
                            mult = mod_mult(mult + effect.mult_mod)
                        if effect.chip_mod:
                            hand_chips = mod_chips(G, hand_chips + effect.chip_mod)
                        if effect.Xmult_mod:
                            mult = mod_mult(mult * effect.Xmult_mod)
                if edition_effects.jokers:
                    if edition_effects.jokers.x_mult_mod:
                        mult = mod_mult(mult * edition_effects.jokers.x_mult_mod)

            res = GAME.selected_back.trigger_effect(T(context="final_scoring_step", chips=hand_chips, mult=mult))
            if res:
                nu_chip, nu_mult = res
                mult = mod_mult(nu_mult if nu_mult is not None else mult)
                hand_chips = mod_chips(G, nu_chip if nu_chip is not None else hand_chips)

            cards_destroyed = []
            for c in scoring_hand:
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
                G.add_event(kill)
        else:
            mult = mod_mult(0)
            hand_chips = mod_chips(G, 0)
            for j in list(G.jokers.cards):
                eval_card(G, j, T(cardarea=G.jokers, debuffed_hand=True, **ctx_base))

        score = floor(hand_chips * mult)
        G.last_score = T(chips=hand_chips, mult=mult, score=score, hand=text)
        chips_before = GAME.chips

        def add_chips() -> None:
            GAME.chips = chips_before + score
        G.add_event(add_chips)
        GAME.round_scores.hand.amt = max(GAME.round_scores.hand.amt, hand_chips * mult)

        for j in list(G.jokers.cards):
            eval_card(G, j, T(cardarea=G.jokers, after=True, **ctx_base))

        def ev_debuff() -> None:
            if GAME.modifiers.debuff_played_cards:
                for c in scoring_hand:
                    c.ability.perma_debuff = True
        G.add_event(ev_debuff)

    # ============================================================ end round
    def end_round(self: "Game") -> None:
        G = self
        GAME = G.GAME

        def ev() -> None:
            G.run_deferred_one_frame()  # see update_hand_played
            game_over = True
            game_won = False
            if GAME.chips - GAME.blind.chips >= 0:
                game_over = False
            for j in list(G.jokers.cards):
                ret = j.calculate_joker(T(end_of_round=True, game_over=game_over))
                if ret and ret.saved:
                    game_over = False
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
                handname, played = "High Card", -1
                for k in G.hands_order():
                    v = GAME.hands[k]
                    # the Lua compares against an `_order` that is never
                    # updated, so ties go to the *last* hand in pairs() order
                    if v.played > played or (v.played == played and 100 > v.order):
                        played = v.played
                        handname = k
                GAME.current_round.most_played_poker_hand = handname
            del game_won
            # end of round effects of cards held in hand
            for i, hc in enumerate(list(G.hand.cards)):
                reps: list[Any] = [1]
                k = 0
                while k < len(reps):
                    effects = [hc.get_end_of_round_effect()]
                    for j in list(G.jokers.cards):
                        ev_ = j.calculate_joker(T(cardarea=G.hand, other_card=hc, individual=True, end_of_round=True))
                        if ev_:
                            effects.append(ev_)
                    if reps[k] == 1:
                        ev_ = eval_card(G, hc, T(end_of_round=True, cardarea=G.hand, repetition=True, repetition_only=True))
                        if nonempty(ev_) and (nonempty(effects[0]) or len(effects) > 1):
                            for _ in range(ev_.seals.repetitions):
                                reps.append(ev_)
                        for j in list(G.jokers.cards):
                            ev_ = eval_card(G, j, T(cardarea=G.hand, other_card=hc, repetition=True, end_of_round=True, card_effects=effects))
                            if nonempty(ev_):
                                for _ in range(ev_.jokers.repetitions):
                                    reps.append(ev_)
                    for eff in effects:
                        if eff.h_dollars:
                            G.ease_dollars(eff.h_dollars)
                    k += 1
            G.draw_from_hand_to_discard()
            if GAME.blind.get_type() == "Boss":
                GAME.voucher_restock = None
                if GAME.modifiers.set_eternal_ante and GAME.round_resets.ante == GAME.modifiers.set_eternal_ante:
                    for j in G.jokers.cards:
                        j.set_eternal(True)
                if GAME.modifiers.set_joker_slots_ante and GAME.round_resets.ante == GAME.modifiers.set_joker_slots_ante:
                    G.jokers.config.card_limit = 0
                G.ease_ante(1)
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
                if rr.temp_handsize:
                    G.hand.change_size(-rr.temp_handsize)
                    rr.temp_handsize = None
                if rr.temp_reroll_cost is not None:
                    rr.temp_reroll_cost = None
                    G.calculate_reroll_cost(True)
                G.reset_idol_card()
                G.reset_mail_rank()
                G.reset_ancient_card()
                G.reset_castle_card()
                for v in G.playing_cards:
                    v.ability.discarded = None
                    v.ability.forced_selection = None
            G.add_event(ev2)
        G.add_event(ev)

    def evaluate_round(self: "Game") -> None:
        G = self
        GAME = G.GAME
        dollars = 0
        rows = []
        if GAME.chips - GAME.blind.chips >= 0:
            rows.append(("blind", GAME.blind.dollars))
            dollars += GAME.blind.dollars
        G.add_event(GAME.blind.defeat)
        GAME.selected_back.trigger_effect(T(context="eval"))
        cr = GAME.current_round
        if cr.hands_left > 0 and not GAME.modifiers.no_extra_hand_money:
            v = cr.hands_left * (GAME.modifiers.money_per_hand or 1)
            rows.append(("hands", v))
            dollars += v
        if cr.discards_left > 0 and GAME.modifiers.money_per_discard:
            v = cr.discards_left * GAME.modifiers.money_per_discard
            rows.append(("discards", v))
            dollars += v
        for i, j in enumerate(list(G.jokers.cards)):
            ret = j.calculate_dollar_bonus()
            if ret:
                rows.append((f"joker:{j.key}", ret))
                dollars += ret
        for t in list(GAME.tags):
            ret = t.apply_to_run(T(type="eval"))
            if ret:
                rows.append((f"tag:{t.key}", ret.dollars))
                dollars += ret.dollars
        if GAME.dollars >= 5 and not GAME.modifiers.no_interest:
            v = GAME.interest_amount * min(math.floor(GAME.dollars / 5), GAME.interest_cap / 5)
            rows.append(("interest", v))
            dollars += v
        G.round_eval_rows = rows

        def set_total() -> None:
            GAME.current_round.dollars = dollars
        G.add_event(set_total)

    def cash_out(self: "Game") -> None:
        G = self
        GAME = G.GAME
        assert G.STATE == G.STATES.ROUND_EVAL and G.round_eval is not None, "not at round evaluation"
        G.deck.shuffle("cashout" + lua_tostring(GAME.round_resets.ante))

        def ev() -> None:
            G.round_eval = None
            cr = GAME.current_round
            cr.jokers_purchased = 0
            cr.discards_left = max(0, GAME.round_resets.discards + GAME.round_bonus.discards)
            cr.hands_left = max(1, GAME.round_resets.hands + GAME.round_bonus.next_hands)
            G.STATE = G.STATES.SHOP
            GAME.shop_free = None
            GAME.shop_d6ed = None
            G.STATE_COMPLETE = False
        G.add_event(ev)
        G.ease_dollars(GAME.current_round.dollars)

        def ev2() -> None:
            GAME.previous_round.dollars = GAME.dollars
        G.add_event(ev2)
        G.ease_chips(0)
        if GAME.round_resets.blind_states.Boss == "Defeated":
            GAME.round_resets.blind_ante = GAME.round_resets.ante
            GAME.round_resets.blind_tags.Small = G.get_next_tag_key()
            GAME.round_resets.blind_tags.Big = G.get_next_tag_key()
        G.reset_blinds()
        G.advance()
