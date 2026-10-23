"""Card:calculate_joker() from card.lua, ported branch for branch.

The order of the checks matters (some generic checks, e.g. ``x_mult > 1``,
come before the name-specific ones), so does the short-circuit order of
conditions that consume RNG (``is_face() and pseudorandom('business')``),
and so do the events and status texts each branch queues (their delays are
part of the timeline).  Returned tables keep every field the callers read:
``message`` (only its presence matters), ``delay``, ``card``, the scoring
fields, ``repetitions``, ``remove``, ``saved``, ``level_up``, ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .lua import T, lua_div, lua_mod, nonempty

if TYPE_CHECKING:
    from .card import Card

MSG = "msg"


def _eaten(self: "Card") -> None:
    """The 'eaten / melted / extinct / drank' animation: removal 0.3s later."""
    G = self.G

    def outer() -> None:
        def rm() -> None:
            G.jokers.remove_card(self)
            self.remove()
        G.ev(rm, trigger="after", delay=0.3, blockable=False)
    G.ev(outer)


def calculate_joker(self: "Card", context: T) -> Any:  # noqa: C901 - mirrors the Lua
    G = self.G
    GAME = G.GAME
    if self.debuff:
        return None
    ab = self.ability
    if ab.set == "Planet" and not self.debuff:
        if context.joker_main:
            if GAME.used_vouchers.get("v_observatory") and ab.consumeable.hand_type == context.scoring_name:
                return T(message=MSG, Xmult_mod=G.P_CENTERS["v_observatory"].config.extra)
    if ab.set != "Joker" or self.debuff:
        return None
    name = ab.name
    jokers = G.jokers.cards

    if name == "Blueprint":
        other = None
        for i, c in enumerate(jokers):
            if c is self:
                other = jokers[i + 1] if i + 1 < len(jokers) else None
        if other is not None and other is not self:
            context.blueprint = (context.blueprint + 1) if context.blueprint else 1
            context.blueprint_card = context.blueprint_card or self
            if context.blueprint > len(jokers) + 1:
                return None
            ret = other.calculate_joker(context)
            if ret:
                ret.card = context.blueprint_card or self
                return ret
    if name == "Brainstorm":
        other = jokers[0] if jokers else None
        if other is not None and other is not self:
            context.blueprint = (context.blueprint + 1) if context.blueprint else 1
            context.blueprint_card = context.blueprint_card or self
            if context.blueprint > len(jokers) + 1:
                return None
            ret = other.calculate_joker(context)
            if ret:
                ret.card = context.blueprint_card or self
                return ret

    cons = G.consumeables
    src = context.blueprint_card or self

    def cons_space() -> bool:
        return len(cons.cards) + GAME.consumeable_buffer < cons.config.card_limit

    def status(card: Any, delay: float | None = None) -> None:
        G.card_eval_status_text(card, "extra", None, None, None, T(message=MSG, delay=delay))

    def later_status(card: Any, delay: float | None = None) -> None:
        G.ev(lambda: status(card, delay))

    def make_consumable(typ: str, append: str) -> None:
        def f() -> None:
            card = G.create_card(typ, G.consumeables, None, None, None, None, None, append)
            card.add_to_deck()
            G.consumeables.emplace(card)
            GAME.consumeable_buffer = 0
        G.ev(f, trigger="before", delay=0.0)

    def dollar_buffer(amount: float) -> None:
        GAME.dollar_buffer = (GAME.dollar_buffer or 0) + amount

        def clear() -> None:
            GAME.dollar_buffer = 0
        G.ev(clear)

    # ================================================================ contexts
    if context.open_booster:
        if name == "Hallucination" and cons_space():
            if G.rng.random("halu" + G.ante_str()) < GAME.probabilities.normal / ab.extra:
                GAME.consumeable_buffer = GAME.consumeable_buffer + 1
                make_consumable("Tarot", "hal")
                status(self)
    elif context.buying_card:
        pass
    elif context.selling_self:
        if name == "Luchador":
            if GAME.blind and (not GAME.blind.disabled and GAME.blind.get_type() == "Boss"):
                status(src)
                GAME.blind.disable()
        if name == "Diet Cola":
            from .tag import Tag
            G.ev(lambda: G.add_tag(Tag(G, "tag_double")))
        if name == "Invisible Joker" and ab.invis_rounds >= ab.extra and not context.blueprint:
            others = [c for c in jokers if c is not self]
            if others:
                if len(jokers) <= G.jokers.config.card_limit:
                    status(src)
                    chosen = G.random_card_from(others, "invisible")
                    card = G.copy_card(chosen, None, None, None, bool(chosen.edition and chosen.edition.negative))
                    if card.ability.invis_rounds is not None:
                        card.ability.invis_rounds = 0
                    card.add_to_deck()
                    G.jokers.emplace(card)
                else:
                    status(src)
            else:
                status(src)
    elif context.selling_card:
        if name == "Campfire" and not context.blueprint:
            ab.x_mult = ab.x_mult + ab.extra
            later_status(self)
        return None
    elif context.reroll_shop:
        if name == "Flash Card" and not context.blueprint:
            ab.mult = ab.mult + ab.extra
            later_status(self)
    elif context.ending_shop:
        if name == "Perkeo":
            if cons.cards:
                def perkeo() -> None:
                    card = G.copy_card(G.random_card_from(list(G.consumeables.cards), "perkeo"), None)
                    card.set_edition(T(negative=True), True)
                    card.add_to_deck()
                    G.consumeables.emplace(card)
                G.ev(perkeo)
                status(src)
            return None
        return None
    elif context.skip_blind:
        if name == "Throwback" and not context.blueprint:
            later_status(self)
        return None
    elif context.skipping_booster:
        if name == "Red Card" and not context.blueprint:
            ab.mult = ab.mult + ab.extra
            later_status(self, 0.45)
        return None
    elif context.playing_card_added and not self.getting_sliced:
        if name == "Hologram" and not context.blueprint and context.cards and len(context.cards) > 0:
            ab.x_mult = ab.x_mult + len(context.cards) * ab.extra
            status(self)
    elif context.first_hand_drawn:
        if name == "Certificate":
            def cert() -> None:
                card = G.create_playing_card(T(front=G.random_p_card("cert_fr"), center=G.P_CENTERS["c_base"]),
                                             G.hand, None, None, True)
                seal_type = G.rng.random(G.rng.pseudoseed("certsl"))
                if seal_type > 0.75:
                    card.set_seal("Red", True)
                elif seal_type > 0.5:
                    card.set_seal("Blue", True)
                elif seal_type > 0.25:
                    card.set_seal("Gold", True)
                else:
                    card.set_seal("Purple", True)
                GAME.blind.debuff_card(card)
                G.hand.sort()
            G.ev(cert)
            G.playing_card_joker_effects([True])
    elif context.setting_blind and not self.getting_sliced:
        if name == "Chicot" and not context.blueprint and context.blind.boss and not self.getting_sliced:
            def chicot() -> None:
                def disable() -> None:
                    GAME.blind.disable()
                    G.delay(0.4)
                G.ev(disable)
                status(self)
            G.ev(chicot)
        if name == "Madness" and not context.blueprint and not context.blind.boss:
            ab.x_mult = ab.x_mult + ab.extra
            destructable = [c for c in jokers if c is not self and not c.ability.eternal and not c.getting_sliced]
            to_destroy = G.random_card_from(destructable, "madness") if destructable else None
            if to_destroy is not None and not src.getting_sliced:
                to_destroy.getting_sliced = True
                G.ev(lambda: to_destroy.start_dissolve(None, None, 1.6))
            if not src.getting_sliced:
                status(src)
        if name == "Burglar" and not src.getting_sliced:
            def burglar() -> None:
                G.ease_discard(-GAME.current_round.discards_left, None, True)
                G.ease_hands_played(ab.extra)
                status(src)
            G.ev(burglar)
        if name == "Riff-raff" and not src.getting_sliced and len(jokers) + GAME.joker_buffer < G.jokers.config.card_limit:
            n = min(2, G.jokers.config.card_limit - (len(jokers) + GAME.joker_buffer))
            GAME.joker_buffer = GAME.joker_buffer + n

            def riff() -> None:
                for _ in range(n):
                    card = G.create_card("Joker", G.jokers, None, 0, None, None, None, "rif")
                    card.add_to_deck()
                    G.jokers.emplace(card)
                    card.start_materialize()
                    GAME.joker_buffer = 0
            G.ev(riff)
            status(src)
        if name == "Cartomancer" and not src.getting_sliced and cons_space():
            GAME.consumeable_buffer = GAME.consumeable_buffer + 1

            def carto() -> None:
                def f() -> None:
                    card = G.create_card("Tarot", G.consumeables, None, None, None, None, None, "car")
                    card.add_to_deck()
                    G.consumeables.emplace(card)
                    GAME.consumeable_buffer = 0
                G.ev(f)
                status(src)
            G.ev(carto)
        if name == "Ceremonial Dagger" and not context.blueprint:
            my_pos = None
            for i, c in enumerate(jokers):
                if c is self:
                    my_pos = i
                    break
            if (my_pos is not None and my_pos + 1 < len(jokers) and not self.getting_sliced
                    and not jokers[my_pos + 1].ability.eternal and not jokers[my_pos + 1].getting_sliced):
                sliced = jokers[my_pos + 1]
                sliced.getting_sliced = True
                GAME.joker_buffer = GAME.joker_buffer - 1

                def dagger() -> None:
                    GAME.joker_buffer = 0
                    ab.mult = ab.mult + sliced.sell_cost * 2
                    sliced.start_dissolve(None, None, 1.6)
                G.ev(dagger)
                status(self)
        if name == "Marble Joker" and not src.getting_sliced:
            from .card import Card

            def marble() -> None:
                front = G.random_p_card("marb_fr")
                G.playing_card = (G.playing_card + 1) if G.playing_card else 1
                card = Card(G, front, G.P_CENTERS["m_stone"], {"playing_card": G.playing_card})
                card.start_materialize()
                G.play.emplace(card)
                G.playing_cards.append(card)
            G.ev(marble)
            status(src)

            def grow() -> None:
                G.deck.config.card_limit = G.deck.config.card_limit + 1
            G.ev(grow)
            G.draw_card(G.play, G.deck, 90, "up", None)
            G.playing_card_joker_effects([True])
        return None
    elif context.destroying_card and not context.blueprint:
        if (name == "Sixth Sense" and len(context.full_hand) == 1 and context.full_hand[0].get_id() == 6
                and GAME.current_round.hands_played == 0):
            if cons_space():
                GAME.consumeable_buffer = GAME.consumeable_buffer + 1
                make_consumable("Spectral", "sixth")
                status(src)
            return True
        return None
    elif context.cards_destroyed:
        pass  # never produced by the game
    elif context.remove_playing_cards:
        if name == "Caino" and not context.blueprint:
            faces = sum(1 for v in context.removed if v.is_face())
            if faces > 0:
                ab.caino_xmult = ab.caino_xmult + faces * ab.extra
                later_status(self)
            return None
        if name == "Glass Joker" and not context.blueprint:
            glass = sum(1 for v in context.removed if v.shattered)
            if glass > 0:
                def outer() -> None:
                    def inner() -> None:
                        ab.x_mult = ab.x_mult + ab.extra * glass
                    G.ev(inner)
                    status(self)
                G.ev(outer)
            return None
    elif context.using_consumeable:
        if name == "Glass Joker" and not context.blueprint and context.consumeable.ability.name == "The Hanged Man":
            shattered = sum(1 for v in G.hand.highlighted if v.ability.name == "Glass Card")
            if shattered > 0:
                ab.x_mult = ab.x_mult + ab.extra * shattered
                later_status(self)
            return None
        if name == "Fortune Teller" and not context.blueprint and context.consumeable.ability.set == "Tarot":
            later_status(self)
        if name == "Constellation" and not context.blueprint and context.consumeable.ability.set == "Planet":
            ab.x_mult = ab.x_mult + ab.extra
            later_status(self)
            return None
        return None
    elif context.debuffed_hand:
        if name == "Matador":
            if GAME.blind.triggered:
                G.ease_dollars(ab.extra)
                dollar_buffer(ab.extra)
                return T(message=MSG, dollars=ab.extra)
    elif context.pre_discard:
        if name == "Burnt Joker" and GAME.current_round.discards_used <= 0 and not context.hook:
            text = G.get_poker_hand_info(G.hand.highlighted)[0]
            status(src)
            h = GAME.hands[text]
            G.update_hand_text(T(sound="button", volume=0.7, pitch=0.8, delay=0.3),
                               T(handname=text, chips=h.chips, mult=h.mult, level=h.level))
            G.level_up_hand(src, text, None, 1)
            G.update_hand_text(T(sound="button", volume=0.7, pitch=1.1, delay=0),
                               T(mult=0, chips=0, handname="", level=""))
    elif context.discard:
        oc = context.other_card
        if name == "Ramen" and not context.blueprint:
            if ab.x_mult - ab.extra <= 1:
                _eaten(self)
                return T(message=MSG)
            ab.x_mult = ab.x_mult - ab.extra
            return T(delay=0.2, message=MSG)
        if name == "Yorick" and not context.blueprint:
            if ab.yorick_discards <= 1:
                ab.yorick_discards = ab.extra.discards
                ab.x_mult = ab.x_mult + ab.extra.xmult
                return T(delay=0.2, message=MSG)
            ab.yorick_discards = ab.yorick_discards - 1
            return None
        if name == "Trading Card" and not context.blueprint and GAME.current_round.discards_used <= 0 and len(context.full_hand) == 1:
            G.ease_dollars(ab.extra)
            return T(message=MSG, delay=0.45, remove=True, card=self)
        if name == "Castle" and not oc.debuff and oc.is_suit(GAME.current_round.castle_card.suit) and not context.blueprint:
            ab.extra.chips = ab.extra.chips + ab.extra.chip_mod
            return T(message=MSG, card=self)
        if name == "Mail-In Rebate" and not oc.debuff and oc.get_id() == GAME.current_round.mail_card.id:
            G.ease_dollars(ab.extra)
            return T(message=MSG, card=self)
        if name == "Hit the Road" and not oc.debuff and oc.get_id() == 11 and not context.blueprint:
            ab.x_mult = ab.x_mult + ab.extra
            return T(message=MSG, delay=0.45, card=self)
        if name == "Green Joker" and not context.blueprint and oc is context.full_hand[-1]:
            prev = ab.mult
            ab.mult = max(0, ab.mult - ab.extra.discard_sub)
            if ab.mult != prev:
                return T(message=MSG, card=self)
        if name == "Faceless Joker" and oc is context.full_hand[-1]:
            faces = sum(1 for v in context.full_hand if v.is_face())
            if faces >= ab.extra.faces:
                def faceless() -> None:
                    G.ease_dollars(ab.extra.dollars)
                    status(src, 0.45)
                G.ev(faceless)
                return None
        return None
    elif context.end_of_round:
        if context.individual:
            pass
        elif context.repetition:
            if context.cardarea is G.hand:
                if name == "Mime" and (nonempty(context.card_effects[0]) or len(context.card_effects) > 1):
                    return T(message=MSG, repetitions=ab.extra, card=self)
        elif not context.blueprint:
            if name == "Campfire" and GAME.blind.boss and ab.x_mult > 1:
                ab.x_mult = 1
                return T(message=MSG)
            if name == "Rocket" and GAME.blind.boss:
                ab.extra.dollars = ab.extra.dollars + ab.extra.increase
                return T(message=MSG)
            if name == "Turtle Bean" and not context.blueprint:
                if ab.extra.h_size - ab.extra.h_mod <= 0:
                    _eaten(self)
                    return T(message=MSG)
                ab.extra.h_size = ab.extra.h_size - ab.extra.h_mod
                G.hand.change_size(-ab.extra.h_mod)
                return T(message=MSG)
            if name == "Invisible Joker" and not context.blueprint:
                ab.invis_rounds = ab.invis_rounds + 1
                return T(message=MSG)
            if name == "Popcorn" and not context.blueprint:
                if ab.mult - ab.extra <= 0:
                    _eaten(self)
                    return T(message=MSG)
                ab.mult = ab.mult - ab.extra
                return T(message=MSG)
            if name == "To Do List" and not context.blueprint:
                hands = [k for k in G.hands_order() if GAME.hands[k].visible and k != ab.to_do_poker_hand]
                ab.to_do_poker_hand = G.rng.element(hands, G.rng.pseudoseed("to_do"))
                return T(message=MSG)
            if name == "Egg":
                ab.extra_value = ab.extra_value + ab.extra
                self.set_cost()
                return T(message=MSG)
            if name == "Gift Card":
                for v in list(jokers):
                    v.ability.extra_value = (v.ability.extra_value or 0) + ab.extra
                    v.set_cost()
                for v in list(cons.cards):
                    v.ability.extra_value = (v.ability.extra_value or 0) + ab.extra
                    v.set_cost()
                return T(message=MSG)
            if name == "Hit the Road" and ab.x_mult > 1:
                ab.x_mult = 1
                return T(message=MSG)
            if name in ("Gros Michel", "Cavendish"):
                if G.rng.random("cavendish" if name == "Cavendish" else "gros_michel") < GAME.probabilities.normal / ab.extra.odds:
                    _eaten(self)
                    if name == "Gros Michel":
                        GAME.pool_flags.gros_michel_extinct = True
                    return T(message=MSG)
                return T(message=MSG)
            if name == "Mr. Bones" and context.game_over and lua_div(GAME.chips, GAME.blind.chips) >= 0.25:
                G.ev(self.start_dissolve)
                return T(message=MSG, saved=True)
    elif context.individual:
        oc = context.other_card
        if context.cardarea is G.play:
            if name == "Hiker":
                oc.ability.perma_bonus = oc.ability.perma_bonus or 0
                oc.ability.perma_bonus = oc.ability.perma_bonus + ab.extra
                return T(extra=T(message=MSG), card=self)
            if name == "Lucky Cat" and oc.lucky_trigger and not context.blueprint:
                ab.x_mult = ab.x_mult + ab.extra
                return T(extra=T(focus=self, message=MSG), card=self)
            if name == "Wee Joker" and oc.get_id() == 2 and not context.blueprint:
                ab.extra.chips = ab.extra.chips + ab.extra.chip_mod
                return T(extra=T(focus=self, message=MSG), card=self)
            if name == "Photograph":
                first_face = None
                for c in context.scoring_hand:
                    if c.is_face():
                        first_face = c
                        break
                if oc is first_face:
                    return T(x_mult=ab.extra, card=self)
            if name == "8 Ball" and cons_space():
                if oc.get_id() == 8 and G.rng.random("8ball") < GAME.probabilities.normal / ab.extra:
                    GAME.consumeable_buffer = GAME.consumeable_buffer + 1

                    def eight() -> None:
                        make_consumable("Tarot", "8ba")
                    return T(extra=T(focus=self, message=MSG, func=eight), card=self)
            if name == "The Idol" and oc.get_id() == GAME.current_round.idol_card.id and oc.is_suit(GAME.current_round.idol_card.suit):
                return T(x_mult=ab.extra, card=self)
            if name == "Scary Face" and oc.is_face():
                return T(chips=ab.extra, card=self)
            if name == "Smiley Face" and oc.is_face():
                return T(mult=ab.extra, card=self)
            if name == "Golden Ticket" and oc.ability.name == "Gold Card":
                dollar_buffer(ab.extra)
                return T(dollars=ab.extra, card=self)
            if name == "Scholar" and oc.get_id() == 14:
                return T(chips=ab.extra.chips, mult=ab.extra.mult, card=self)
            if name == "Walkie Talkie" and (oc.get_id() == 10 or oc.get_id() == 4):
                return T(chips=ab.extra.chips, mult=ab.extra.mult, card=self)
            if name == "Business Card" and oc.is_face() and G.rng.random("business") < GAME.probabilities.normal / ab.extra:
                dollar_buffer(2)
                return T(dollars=2, card=self)
            if name == "Fibonacci" and (oc.get_id() == 2 or oc.get_id() == 3 or oc.get_id() == 5 or oc.get_id() == 8
                                        or oc.get_id() == 14):
                return T(mult=ab.extra, card=self)
            if name == "Even Steven" and oc.get_id() <= 10 and oc.get_id() >= 0 and lua_mod(oc.get_id(), 2) == 0:
                return T(mult=ab.extra, card=self)
            if name == "Odd Todd" and ((oc.get_id() <= 10 and oc.get_id() >= 0 and lua_mod(oc.get_id(), 2) == 1)
                                       or oc.get_id() == 14):
                return T(chips=ab.extra, card=self)
            if ab.effect == "Suit Mult" and oc.is_suit(ab.extra.suit):
                return T(mult=ab.extra.s_mult, card=self)
            if name == "Rough Gem" and oc.is_suit("Diamonds"):
                dollar_buffer(ab.extra)
                return T(dollars=ab.extra, card=self)
            if name == "Onyx Agate" and oc.is_suit("Clubs"):
                return T(mult=ab.extra, card=self)
            if name == "Arrowhead" and oc.is_suit("Spades"):
                return T(chips=ab.extra, card=self)
            if name == "Bloodstone" and oc.is_suit("Hearts") and G.rng.random("bloodstone") < GAME.probabilities.normal / ab.extra.odds:
                return T(x_mult=ab.extra.Xmult, card=self)
            if name == "Ancient Joker" and oc.is_suit(GAME.current_round.ancient_card.suit):
                return T(x_mult=ab.extra, card=self)
            if name == "Triboulet" and (oc.get_id() == 12 or oc.get_id() == 13):
                return T(x_mult=ab.extra, card=self)
        if context.cardarea is G.hand:
            if name == "Shoot the Moon" and oc.get_id() == 12:
                if oc.debuff:
                    return T(message=MSG, card=self)
                return T(h_mult=13, card=self)
            if name == "Baron" and oc.get_id() == 13:
                if oc.debuff:
                    return T(message=MSG, card=self)
                return T(x_mult=ab.extra, card=self)
            if name == "Reserved Parking" and oc.is_face() and G.rng.random("parking") < GAME.probabilities.normal / ab.extra.odds:
                if oc.debuff:
                    return T(message=MSG, card=self)
                dollar_buffer(ab.extra.dollars)
                return T(dollars=ab.extra.dollars, card=self)
            if name == "Raised Fist":
                temp_mult, temp_id = 15, 15
                raised = None
                for c in G.hand.cards:
                    if temp_id >= c.base.id and c.ability.effect != "Stone Card":
                        temp_mult = c.base.nominal
                        temp_id = c.base.id
                        raised = c
                if raised is oc:
                    if oc.debuff:
                        return T(message=MSG, card=self)
                    return T(h_mult=2 * temp_mult, card=self)
    elif context.repetition:
        oc = context.other_card
        if context.cardarea is G.play:
            if name == "Sock and Buskin" and oc.is_face():
                return T(message=MSG, repetitions=ab.extra, card=self)
            if name == "Hanging Chad" and oc is context.scoring_hand[0]:
                return T(message=MSG, repetitions=ab.extra, card=self)
            if name == "Dusk" and GAME.current_round.hands_left == 0:
                return T(message=MSG, repetitions=ab.extra, card=self)
            if name == "Seltzer":
                return T(message=MSG, repetitions=1, card=self)
            if name == "Hack" and (oc.get_id() == 2 or oc.get_id() == 3 or oc.get_id() == 4 or oc.get_id() == 5):
                return T(message=MSG, repetitions=ab.extra, card=self)
        if context.cardarea is G.hand:
            if name == "Mime" and (nonempty(context.card_effects[0]) or len(context.card_effects) > 1):
                return T(message=MSG, repetitions=ab.extra, card=self)
    elif context.other_joker:
        if name == "Baseball Card" and context.other_joker.config.center.rarity == 2 and self is not context.other_joker:
            G.ev(None)
            return T(message=MSG, Xmult_mod=ab.extra)
    else:
        if context.cardarea is G.jokers:
            if context.before:
                return _before(self, context)
            elif context.after:
                return _after(self, context)
            else:
                return _joker_main(self, context)
    return None


def _before(self: "Card", context: T) -> Any:
    G = self.G
    GAME = G.GAME
    ab = self.ability
    name = ab.name
    ph = context.poker_hands
    if name == "Spare Trousers" and (nonempty(ph["Two Pair"]) or nonempty(ph["Full House"])) and not context.blueprint:
        ab.mult = ab.mult + ab.extra
        return T(message=MSG, card=self)
    if name == "Space Joker" and G.rng.random("space") < GAME.probabilities.normal / ab.extra:
        return T(card=self, level_up=True, message=MSG)
    if name == "Square Joker" and len(context.full_hand) == 4 and not context.blueprint:
        ab.extra.chips = ab.extra.chips + ab.extra.chip_mod
        return T(message=MSG, card=self)
    if name == "Runner" and nonempty(context.poker_hands["Straight"]) and not context.blueprint:
        ab.extra.chips = ab.extra.chips + ab.extra.chip_mod
        return T(message=MSG, card=self)
    if name == "Midas Mask" and not context.blueprint:
        faces = []
        for v in context.scoring_hand:
            if v.is_face():
                faces.append(v)
                v.set_ability(G.P_CENTERS["m_gold"], None, True)
                G.ev(None)
        if faces:
            return T(message=MSG, card=self)
    if name == "Vampire" and not context.blueprint:
        enhanced = []
        for v in context.scoring_hand:
            if v.config.center is not G.P_CENTERS["c_base"] and not v.debuff and not v.vampired:
                enhanced.append(v)
                v.vampired = True
                v.set_ability(G.P_CENTERS["c_base"], None, True)

                def unvamp(v: Any = v) -> None:
                    v.vampired = None
                G.ev(unvamp)
        if enhanced:
            ab.x_mult = ab.x_mult + ab.extra * len(enhanced)
            return T(message=MSG, card=self)
    if name == "To Do List" and context.scoring_name == ab.to_do_poker_hand:
        G.ease_dollars(ab.extra.dollars)
        GAME.dollar_buffer = (GAME.dollar_buffer or 0) + ab.extra.dollars

        def clear() -> None:
            GAME.dollar_buffer = 0
        G.ev(clear)
        return T(message=MSG, dollars=ab.extra.dollars)
    if name == "DNA" and GAME.current_round.hands_played == 0:
        if len(context.full_hand) == 1:
            G.playing_card = (G.playing_card + 1) if G.playing_card else 1
            card = G.copy_card(context.full_hand[0], None, None, G.playing_card)
            card.add_to_deck()
            G.deck.config.card_limit = G.deck.config.card_limit + 1
            G.playing_cards.append(card)
            G.hand.emplace(card)
            G.ev(card.start_materialize)
            return T(message=MSG, card=self, playing_cards_created=[True])
    if name == "Ride the Bus" and not context.blueprint:
        faces = any(c.is_face() for c in context.scoring_hand)
        if faces:
            last = ab.mult
            ab.mult = 0
            if last > 0:
                return T(card=self, message=MSG)
        else:
            ab.mult = ab.mult + ab.extra
    if name == "Obelisk" and not context.blueprint:
        reset = True
        more_than = GAME.hands[context.scoring_name].played or 0
        for k, v in GAME.hands.items():
            if k != context.scoring_name and v.played >= more_than and v.visible:
                reset = False
        if reset:
            if ab.x_mult > 1:
                ab.x_mult = 1
                return T(card=self, message=MSG)
        else:
            ab.x_mult = ab.x_mult + ab.extra
    if name == "Green Joker" and not context.blueprint:
        ab.mult = ab.mult + ab.extra.hand_add
        return T(card=self, message=MSG)
    return None


def _after(self: "Card", context: T) -> Any:
    ab = self.ability
    name = ab.name
    if name == "Ice Cream" and not context.blueprint:
        if ab.extra.chips - ab.extra.chip_mod <= 0:
            _eaten(self)
            return T(message=MSG)
        ab.extra.chips = ab.extra.chips - ab.extra.chip_mod
        return T(message=MSG)
    if name == "Seltzer" and not context.blueprint:
        if ab.extra - 1 <= 0:
            _eaten(self)
            return T(message=MSG)
        ab.extra = ab.extra - 1
        return T(message=MSG)
    return None


def _joker_main(self: "Card", context: T) -> Any:  # noqa: C901
    G = self.G
    GAME = G.GAME
    ab = self.ability
    name = ab.name
    ph = context.poker_hands
    cons = G.consumeables
    floor = G.floor
    if name == "Loyalty Card":
        ab.loyalty_remaining = lua_mod(ab.extra.every - 1 - (GAME.hands_played - ab.hands_played_at_create), ab.extra.every + 1)
        if context.blueprint:
            if ab.loyalty_remaining == ab.extra.every:
                return T(message=MSG, Xmult_mod=ab.extra.Xmult)
        else:
            if ab.loyalty_remaining == 0:
                pass  # juice_card_until (a non-blocking UI loop)
            elif ab.loyalty_remaining == ab.extra.every:
                return T(message=MSG, Xmult_mod=ab.extra.Xmult)
    if name != "Seeing Double" and ab.x_mult > 1 and (ab.type == "" or nonempty(ph[ab.type])):
        return T(message=MSG, Xmult_mod=ab.x_mult)
    if ab.t_mult > 0 and nonempty(ph[ab.type]):
        return T(message=MSG, mult_mod=ab.t_mult)
    if ab.t_chips > 0 and nonempty(ph[ab.type]):
        return T(message=MSG, chip_mod=ab.t_chips)
    if name == "Half Joker" and len(context.full_hand) <= ab.extra.size:
        return T(message=MSG, mult_mod=ab.extra.mult)
    if name == "Abstract Joker":
        x = sum(1 for c in G.jokers.cards if c.ability.set == "Joker")
        return T(message=MSG, mult_mod=x * ab.extra)
    if name == "Acrobat" and GAME.current_round.hands_left == 0:
        return T(message=MSG, Xmult_mod=ab.extra)
    if name == "Mystic Summit" and GAME.current_round.discards_left == ab.extra.d_remaining:
        return T(message=MSG, mult_mod=ab.extra.mult)
    if name == "Misprint":
        m = G.rng.randint("misprint", ab.extra.min, ab.extra.max)
        return T(message=MSG, mult_mod=m)
    if name == "Banner" and GAME.current_round.discards_left > 0:
        return T(message=MSG, chip_mod=GAME.current_round.discards_left * ab.extra)
    if name == "Stuntman":
        return T(message=MSG, chip_mod=ab.extra.chip_mod)
    if name == "Matador":
        if GAME.blind.triggered:
            G.ease_dollars(ab.extra)
            GAME.dollar_buffer = (GAME.dollar_buffer or 0) + ab.extra

            def clear() -> None:
                GAME.dollar_buffer = 0
            G.ev(clear)
            return T(message=MSG, dollars=ab.extra)
    if name == "Supernova":
        return T(message=MSG, mult_mod=GAME.hands[context.scoring_name].played)
    if name == "Ceremonial Dagger" and ab.mult > 0:
        return T(message=MSG, mult_mod=ab.mult)
    if name == "Vagabond" and len(cons.cards) + GAME.consumeable_buffer < cons.config.card_limit:
        if GAME.dollars <= ab.extra:
            GAME.consumeable_buffer = GAME.consumeable_buffer + 1
            _make(G, "Tarot", "vag")
            return T(message=MSG, card=self)
    if name == "Superposition" and len(cons.cards) + GAME.consumeable_buffer < cons.config.card_limit:
        aces = sum(1 for c in context.scoring_hand if c.get_id() == 14)
        if aces >= 1 and nonempty(ph["Straight"]):
            GAME.consumeable_buffer = GAME.consumeable_buffer + 1
            _make(G, "Tarot", "sup")
            return T(message=MSG, card=self)
    if name == "Seance" and len(cons.cards) + GAME.consumeable_buffer < cons.config.card_limit:
        if nonempty(ph[ab.extra.poker_hand]):
            GAME.consumeable_buffer = GAME.consumeable_buffer + 1
            _make(G, "Spectral", "sea")
            return T(message=MSG, card=self)
    if name == "Flower Pot":
        suits = {"Hearts": 0, "Diamonds": 0, "Spades": 0, "Clubs": 0}
        for c in context.scoring_hand:
            if c.ability.name != "Wild Card":
                if c.is_suit("Hearts", True) and suits["Hearts"] == 0:
                    suits["Hearts"] += 1
                elif c.is_suit("Diamonds", True) and suits["Diamonds"] == 0:
                    suits["Diamonds"] += 1
                elif c.is_suit("Spades", True) and suits["Spades"] == 0:
                    suits["Spades"] += 1
                elif c.is_suit("Clubs", True) and suits["Clubs"] == 0:
                    suits["Clubs"] += 1
        for c in context.scoring_hand:
            if c.ability.name == "Wild Card":
                if c.is_suit("Hearts") and suits["Hearts"] == 0:
                    suits["Hearts"] += 1
                elif c.is_suit("Diamonds") and suits["Diamonds"] == 0:
                    suits["Diamonds"] += 1
                elif c.is_suit("Spades") and suits["Spades"] == 0:
                    suits["Spades"] += 1
                elif c.is_suit("Clubs") and suits["Clubs"] == 0:
                    suits["Clubs"] += 1
        if suits["Hearts"] > 0 and suits["Diamonds"] > 0 and suits["Spades"] > 0 and suits["Clubs"] > 0:
            return T(message=MSG, Xmult_mod=ab.extra)
    if name == "Seeing Double":
        suits = {"Hearts": 0, "Diamonds": 0, "Spades": 0, "Clubs": 0}
        for c in context.scoring_hand:
            if c.ability.name != "Wild Card":
                if c.is_suit("Hearts"):
                    suits["Hearts"] += 1
                if c.is_suit("Diamonds"):
                    suits["Diamonds"] += 1
                if c.is_suit("Spades"):
                    suits["Spades"] += 1
                if c.is_suit("Clubs"):
                    suits["Clubs"] += 1
        for c in context.scoring_hand:
            if c.ability.name == "Wild Card":
                if c.is_suit("Clubs") and suits["Clubs"] == 0:
                    suits["Clubs"] += 1
                elif c.is_suit("Diamonds") and suits["Diamonds"] == 0:
                    suits["Diamonds"] += 1
                elif c.is_suit("Spades") and suits["Spades"] == 0:
                    suits["Spades"] += 1
                elif c.is_suit("Hearts") and suits["Hearts"] == 0:
                    suits["Hearts"] += 1
        if (suits["Hearts"] > 0 or suits["Diamonds"] > 0 or suits["Spades"] > 0) and suits["Clubs"] > 0:
            return T(message=MSG, Xmult_mod=ab.extra)
    if name == "Wee Joker":
        return T(message=MSG, chip_mod=ab.extra.chips)
    if name == "Castle" and ab.extra.chips > 0:
        return T(message=MSG, chip_mod=ab.extra.chips)
    if name == "Blue Joker" and len(G.deck.cards) > 0:
        return T(message=MSG, chip_mod=ab.extra * len(G.deck.cards))
    if name == "Erosion" and (GAME.starting_deck_size - len(G.playing_cards)) > 0:
        return T(message=MSG, mult_mod=ab.extra * (GAME.starting_deck_size - len(G.playing_cards)))
    if name == "Square Joker":
        return T(message=MSG, chip_mod=ab.extra.chips)
    if name == "Runner":
        return T(message=MSG, chip_mod=ab.extra.chips)
    if name == "Ice Cream":
        return T(message=MSG, chip_mod=ab.extra.chips)
    if name == "Stone Joker" and ab.stone_tally > 0:
        return T(message=MSG, chip_mod=ab.extra * ab.stone_tally)
    if name == "Steel Joker" and ab.steel_tally > 0:
        return T(message=MSG, Xmult_mod=1 + ab.extra * ab.steel_tally)
    if name == "Bull" and (GAME.dollars + (GAME.dollar_buffer or 0)) > 0:
        return T(message=MSG, chip_mod=ab.extra * max(0, GAME.dollars + (GAME.dollar_buffer or 0)))
    if name == "Driver's License":
        if (ab.driver_tally or 0) >= 16:
            return T(message=MSG, Xmult_mod=ab.extra)
    if name == "Blackboard":
        black, total = 0, 0
        for c in G.hand.cards:
            total += 1
            if c.is_suit("Clubs", None, True) or c.is_suit("Spades", None, True):
                black += 1
        if black == total:
            return T(message=MSG, Xmult_mod=ab.extra)
    if name == "Joker Stencil":
        if (G.jokers.config.card_limit - len(G.jokers.cards)) > 0:
            return T(message=MSG, Xmult_mod=ab.x_mult)
    if name == "Swashbuckler" and ab.mult > 0:
        return T(message=MSG, mult_mod=ab.mult)
    if name == "Joker":
        return T(message=MSG, mult_mod=ab.mult)
    if name == "Spare Trousers" and ab.mult > 0:
        return T(message=MSG, mult_mod=ab.mult)
    if name == "Ride the Bus" and ab.mult > 0:
        return T(message=MSG, mult_mod=ab.mult)
    if name == "Flash Card" and ab.mult > 0:
        return T(message=MSG, mult_mod=ab.mult)
    if name == "Popcorn" and ab.mult > 0:
        return T(message=MSG, mult_mod=ab.mult)
    if name == "Green Joker" and ab.mult > 0:
        return T(message=MSG, mult_mod=ab.mult)
    if name == "Fortune Teller" and GAME.consumeable_usage_total and GAME.consumeable_usage_total.tarot > 0:
        return T(message=MSG, mult_mod=GAME.consumeable_usage_total.tarot)
    if name == "Gros Michel":
        return T(message=MSG, mult_mod=ab.extra.mult)
    if name == "Cavendish":
        return T(message=MSG, Xmult_mod=ab.extra.Xmult)
    if name == "Red Card" and ab.mult > 0:
        return T(message=MSG, mult_mod=ab.mult)
    if name == "Card Sharp" and GAME.hands[context.scoring_name] and GAME.hands[context.scoring_name].played_this_round > 1:
        return T(message=MSG, Xmult_mod=ab.extra.Xmult)
    if name == "Bootstraps" and floor((GAME.dollars + (GAME.dollar_buffer or 0)) / ab.extra.dollars) >= 1:
        return T(message=MSG, mult_mod=ab.extra.mult * floor((GAME.dollars + (GAME.dollar_buffer or 0)) / ab.extra.dollars))
    if name == "Caino" and ab.caino_xmult > 1:
        return T(message=MSG, Xmult_mod=ab.caino_xmult)
    return None


def _make(G: Any, typ: str, append: str) -> None:
    GAME = G.GAME

    def f() -> None:
        card = G.create_card(typ, G.consumeables, None, None, None, None, None, append)
        card.add_to_deck()
        G.consumeables.emplace(card)
        GAME.consumeable_buffer = 0
    G.ev(f, trigger="before", delay=0.0)
