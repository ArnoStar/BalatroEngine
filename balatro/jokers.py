"""Card:calculate_joker() from card.lua, ported branch for branch.

The order of the checks matters (some generic checks, e.g. ``x_mult > 1``,
come before the name-specific ones) and so does the short-circuit order of
conditions that consume RNG (e.g. ``is_face() and pseudorandom('business')``),
so this file follows the original structure exactly.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .lua import T, nonempty
from .rng import lua_tostring

if TYPE_CHECKING:
    from .card import Card


def _remove_eaten(self: "Card") -> None:
    """The 'eaten / melted / extinct' animation: removal ~0.3s later (non-blockable)."""
    G = self.G

    def ev() -> None:
        def rm() -> None:
            if G.jokers is not None:
                G.jokers.remove_card(self)
            self.remove()
        G.defer(rm)
    G.add_event(ev)


def calculate_joker(self: "Card", context: T) -> Any:  # noqa: C901 - mirrors the Lua
    G = self.G
    GAME = G.GAME
    if self.debuff:
        return None
    ab = self.ability
    name = ab.name

    if ab.set == "Planet" and not self.debuff:
        if context.joker_main:
            if GAME.used_vouchers.get("v_observatory") and ab.consumeable.hand_type == context.scoring_name:
                return T(Xmult_mod=G.P_CENTERS["v_observatory"].config.extra)

    if ab.set != "Joker" or self.debuff:
        return None

    if name == "Blueprint":
        other = None
        cards = G.jokers.cards
        for i, c in enumerate(cards):
            if c is self:
                other = cards[i + 1] if i + 1 < len(cards) else None
        if other is not None and other is not self:
            context.blueprint = (context.blueprint + 1) if context.blueprint else 1
            context.blueprint_card = context.blueprint_card or self
            if context.blueprint > len(G.jokers.cards) + 1:
                return None
            ret = other.calculate_joker(context)
            if ret:
                ret.card = context.blueprint_card or self
                return ret
    if name == "Brainstorm":
        other = G.jokers.cards[0] if G.jokers.cards else None
        if other is not None and other is not self:
            context.blueprint = (context.blueprint + 1) if context.blueprint else 1
            context.blueprint_card = context.blueprint_card or self
            if context.blueprint > len(G.jokers.cards) + 1:
                return None
            ret = other.calculate_joker(context)
            if ret:
                ret.card = context.blueprint_card or self
                return ret

    cons = G.consumeables

    def cons_space() -> bool:
        return len(cons.cards) + GAME.consumeable_buffer < cons.config.card_limit

    def make_consumable(typ: str, append: str) -> None:
        def ev() -> None:
            card = G.create_card(typ, G.consumeables, None, None, None, None, None, append)
            card.add_to_deck()
            G.consumeables.emplace(card)
            GAME.consumeable_buffer = 0
        G.add_event(ev)

    # ----------------------------------------------------------------- contexts
    if context.open_booster:
        if name == "Hallucination" and cons_space():
            if G.rng.random("halu" + lua_tostring(GAME.round_resets.ante)) < GAME.probabilities.normal / ab.extra:
                GAME.consumeable_buffer += 1
                make_consumable("Tarot", "hal")
    elif context.buying_card:
        pass
    elif context.selling_self:
        if name == "Luchador":
            if GAME.blind and (not GAME.blind.disabled and GAME.blind.get_type() == "Boss"):
                GAME.blind.disable()
        if name == "Diet Cola":
            from .tag import Tag
            G.add_event(lambda: G.add_tag(Tag(G, "tag_double")))
        if name == "Invisible Joker" and ab.invis_rounds >= ab.extra and not context.blueprint:
            jokers = [c for c in G.jokers.cards if c is not self]
            if jokers:
                if len(G.jokers.cards) <= G.jokers.config.card_limit:
                    chosen = G._random_card_from(jokers, "invisible")
                    card = G.copy_card(chosen, None, None, None, bool(chosen.edition and chosen.edition.negative))
                    if card.ability.invis_rounds is not None:
                        card.ability.invis_rounds = 0
                    card.add_to_deck()
                    G.jokers.emplace(card)
    elif context.selling_card:
        if name == "Campfire" and not context.blueprint:
            ab.x_mult = ab.x_mult + ab.extra
        return None
    elif context.reroll_shop:
        if name == "Flash Card" and not context.blueprint:
            ab.mult = ab.mult + ab.extra
    elif context.ending_shop:
        if name == "Perkeo":
            if G.consumeables.cards:
                def perkeo() -> None:
                    card = G.copy_card(G._random_card_from(G.consumeables.cards, "perkeo"), None)
                    card.set_edition(T(negative=True), True)
                    card.add_to_deck()
                    G.consumeables.emplace(card)
                G.add_event(perkeo)
            return None
        return None
    elif context.skip_blind:
        return None
    elif context.skipping_booster:
        if name == "Red Card" and not context.blueprint:
            ab.mult = ab.mult + ab.extra
        return None
    elif context.playing_card_added and not self.getting_sliced:
        if name == "Hologram" and not context.blueprint and context.cards:
            ab.x_mult = ab.x_mult + len(context.cards) * ab.extra
    elif context.first_hand_drawn:
        if name == "Certificate":
            def cert() -> None:
                card = G.create_playing_card(T(front=G.random_p_card("cert_fr"), center=G.P_CENTERS["c_base"]), G.hand)
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
            G.add_event(cert)
            G.playing_card_joker_effects([True])
    elif context.setting_blind and not self.getting_sliced:
        src = context.blueprint_card or self
        if name == "Chicot" and not context.blueprint and context.blind.boss and not self.getting_sliced:
            def chicot() -> None:
                G.add_event(GAME.blind.disable)
            G.add_event(chicot)
        if name == "Madness" and not context.blueprint and not context.blind.boss:
            ab.x_mult = ab.x_mult + ab.extra
            destructable = [c for c in G.jokers.cards if c is not self and not c.ability.eternal and not c.getting_sliced]
            to_destroy = G._random_card_from(destructable, "madness") if destructable else None
            if to_destroy is not None and not src.getting_sliced:
                to_destroy.getting_sliced = True
                G.add_event(to_destroy.start_dissolve)
        if name == "Burglar" and not src.getting_sliced:
            def burglar() -> None:
                G.ease_discard(-GAME.current_round.discards_left, None, True)
                G.ease_hands_played(ab.extra)
            G.add_event(burglar)
        if name == "Riff-raff" and not src.getting_sliced and len(G.jokers.cards) + GAME.joker_buffer < G.jokers.config.card_limit:
            to_create = min(2, G.jokers.config.card_limit - (len(G.jokers.cards) + GAME.joker_buffer))
            GAME.joker_buffer = GAME.joker_buffer + to_create

            def riff() -> None:
                for _ in range(to_create):
                    card = G.create_card("Joker", G.jokers, None, 0, None, None, None, "rif")
                    card.add_to_deck()
                    G.jokers.emplace(card)
                    GAME.joker_buffer = 0
            G.add_event(riff)
        if name == "Cartomancer" and not src.getting_sliced and cons_space():
            GAME.consumeable_buffer += 1

            def carto() -> None:
                make_consumable("Tarot", "car")
            G.add_event(carto)
        if name == "Ceremonial Dagger" and not context.blueprint:
            my_pos = None
            for i, c in enumerate(G.jokers.cards):
                if c is self:
                    my_pos = i
                    break
            if (my_pos is not None and my_pos + 1 < len(G.jokers.cards) and not self.getting_sliced
                    and not G.jokers.cards[my_pos + 1].ability.eternal and not G.jokers.cards[my_pos + 1].getting_sliced):
                sliced = G.jokers.cards[my_pos + 1]
                sliced.getting_sliced = True
                GAME.joker_buffer = GAME.joker_buffer - 1

                def dagger() -> None:
                    GAME.joker_buffer = 0
                    ab.mult = ab.mult + sliced.sell_cost * 2
                    sliced.start_dissolve()
                G.add_event(dagger)
        if name == "Marble Joker" and not src.getting_sliced:
            from .card import Card

            def marble() -> None:
                front = G.random_p_card("marb_fr")
                G.playing_card = (G.playing_card + 1) if G.playing_card else 1
                card = Card(G, front, G.P_CENTERS["m_stone"], {"playing_card": G.playing_card})
                G.play.emplace(card)
                G.playing_cards.append(card)
            G.add_event(marble)

            def grow() -> None:
                G.deck.config.card_limit += 1
            G.add_event(grow)
            G.draw_card(G.play, G.deck)
            G.playing_card_joker_effects([True])
        return None
    elif context.destroying_card and not context.blueprint:
        if (name == "Sixth Sense" and len(context.full_hand) == 1 and context.full_hand[0].get_id() == 6
                and GAME.current_round.hands_played == 0):
            if cons_space():
                GAME.consumeable_buffer += 1
                make_consumable("Spectral", "sixth")
            return True
        return None
    elif context.cards_destroyed:
        pass  # never produced by the game
    elif context.remove_playing_cards:
        if name == "Caino" and not context.blueprint:
            face_cards = sum(1 for v in context.removed if v.is_face())
            if face_cards > 0:
                ab.caino_xmult = ab.caino_xmult + face_cards * ab.extra
            return None
        if name == "Glass Joker" and not context.blueprint:
            glass_cards = sum(1 for v in context.removed if v.shattered)
            if glass_cards > 0:
                def outer() -> None:
                    def inner() -> None:
                        ab.x_mult = ab.x_mult + ab.extra * glass_cards
                    G.add_event(inner)
                G.add_event(outer)
            return None
    elif context.using_consumeable:
        if name == "Glass Joker" and not context.blueprint and context.consumeable.ability.name == "The Hanged Man":
            shattered = sum(1 for v in G.hand.highlighted if v.ability.name == "Glass Card")
            if shattered > 0:
                ab.x_mult = ab.x_mult + ab.extra * shattered
            return None
        if name == "Fortune Teller" and not context.blueprint and context.consumeable.ability.set == "Tarot":
            pass
        if name == "Constellation" and not context.blueprint and context.consumeable.ability.set == "Planet":
            ab.x_mult = ab.x_mult + ab.extra
            return None
        return None
    elif context.debuffed_hand:
        if name == "Matador":
            if GAME.blind.triggered:
                G.ease_dollars(ab.extra)
                GAME.dollar_buffer = (GAME.dollar_buffer or 0) + ab.extra
                G.add_event(lambda: setattr(GAME, "dollar_buffer", 0))
                return T(dollars=ab.extra)
    elif context.pre_discard:
        if name == "Burnt Joker" and GAME.current_round.discards_used <= 0 and not context.hook:
            from .poker import get_poker_hand_info
            text = get_poker_hand_info(G, G.hand.highlighted)[0]
            G.level_up_hand(context.blueprint_card or self, text, None, 1)
    elif context.discard:
        if name == "Ramen" and not context.blueprint:
            if ab.x_mult - ab.extra <= 1:
                _remove_eaten(self)
                return T(message="Eaten!")
            ab.x_mult = ab.x_mult - ab.extra
            return T(message="-x")
        if name == "Yorick" and not context.blueprint:
            if ab.yorick_discards <= 1:
                ab.yorick_discards = ab.extra.discards
                ab.x_mult = ab.x_mult + ab.extra.xmult
                return T(message="x")
            ab.yorick_discards = ab.yorick_discards - 1
            return None
        if name == "Trading Card" and not context.blueprint and GAME.current_round.discards_used <= 0 and len(context.full_hand) == 1:
            G.ease_dollars(ab.extra)
            return T(remove=True, card=self)
        if name == "Castle" and not context.other_card.debuff and context.other_card.is_suit(GAME.current_round.castle_card.suit) and not context.blueprint:
            ab.extra.chips = ab.extra.chips + ab.extra.chip_mod
            return T(message="Upgrade!", card=self)
        if name == "Mail-In Rebate" and not context.other_card.debuff and context.other_card.get_id() == GAME.current_round.mail_card.id:
            G.ease_dollars(ab.extra)
            return T(card=self)
        if name == "Hit the Road" and not context.other_card.debuff and context.other_card.get_id() == 11 and not context.blueprint:
            ab.x_mult = ab.x_mult + ab.extra
            return T(card=self)
        if name == "Green Joker" and not context.blueprint and context.other_card is context.full_hand[-1]:
            prev = ab.mult
            ab.mult = max(0, ab.mult - ab.extra.discard_sub)
            if ab.mult != prev:
                return T(card=self)
        if name == "Faceless Joker" and context.other_card is context.full_hand[-1]:
            faces = sum(1 for v in context.full_hand if v.is_face())
            if faces >= ab.extra.faces:
                G.add_event(lambda: G.ease_dollars(ab.extra.dollars))
                return None
        return None
    elif context.end_of_round:
        if context.individual:
            pass
        elif context.repetition:
            if context.cardarea is G.hand:
                if name == "Mime" and (nonempty(context.card_effects[0]) or len(context.card_effects) > 1):
                    return T(repetitions=ab.extra, card=self)
        elif not context.blueprint:
            if name == "Campfire" and GAME.blind.boss and ab.x_mult > 1:
                ab.x_mult = 1
                return T(message="Reset")
            if name == "Rocket" and GAME.blind.boss:
                ab.extra.dollars = ab.extra.dollars + ab.extra.increase
                return T(message="Upgrade!")
            if name == "Turtle Bean" and not context.blueprint:
                if ab.extra.h_size - ab.extra.h_mod <= 0:
                    _remove_eaten(self)
                    return T(message="Eaten!")
                ab.extra.h_size = ab.extra.h_size - ab.extra.h_mod
                G.hand.change_size(-ab.extra.h_mod)
                return T(message="-h")
            if name == "Invisible Joker" and not context.blueprint:
                ab.invis_rounds = ab.invis_rounds + 1
                return T(message="invis")
            if name == "Popcorn" and not context.blueprint:
                if ab.mult - ab.extra <= 0:
                    _remove_eaten(self)
                    return T(message="Eaten!")
                ab.mult = ab.mult - ab.extra
                return T(message="-mult")
            if name == "To Do List" and not context.blueprint:
                hands = [k for k in G.hands_order() if GAME.hands[k].visible and k != ab.to_do_poker_hand]
                ab.to_do_poker_hand = G.rng.element(hands, G.rng.pseudoseed("to_do"))
                return T(message="Reset")
            if name == "Egg":
                ab.extra_value = ab.extra_value + ab.extra
                self.set_cost()
                return T(message="Value Up!")
            if name == "Gift Card":
                for v in G.jokers.cards:
                    v.ability.extra_value = (v.ability.extra_value or 0) + ab.extra
                    v.set_cost()
                for v in G.consumeables.cards:
                    v.ability.extra_value = (v.ability.extra_value or 0) + ab.extra
                    v.set_cost()
                return T(message="Value Up!")
            if name == "Hit the Road" and ab.x_mult > 1:
                ab.x_mult = 1
                return T(message="Reset")
            if name in ("Gros Michel", "Cavendish"):
                if G.rng.random("cavendish" if name == "Cavendish" else "gros_michel") < GAME.probabilities.normal / ab.extra.odds:
                    _remove_eaten(self)
                    if name == "Gros Michel":
                        GAME.pool_flags.gros_michel_extinct = True
                    return T(message="Extinct!")
                return T(message="Safe!")
            if name == "Mr. Bones" and context.game_over and GAME.chips / GAME.blind.chips >= 0.25:
                G.add_event(self.start_dissolve)
                return T(message="Saved", saved=True)
    elif context.individual:
        oc = context.other_card
        if context.cardarea is G.play:
            if name == "Hiker":
                oc.ability.perma_bonus = oc.ability.perma_bonus or 0
                oc.ability.perma_bonus = oc.ability.perma_bonus + ab.extra
                return T(extra=T(message="Upgrade!"), card=self)
            if name == "Lucky Cat" and oc.lucky_trigger and not context.blueprint:
                ab.x_mult = ab.x_mult + ab.extra
                return T(extra=T(focus=self, message="Upgrade!"), card=self)
            if name == "Wee Joker" and oc.get_id() == 2 and not context.blueprint:
                ab.extra.chips = ab.extra.chips + ab.extra.chip_mod
                return T(extra=T(focus=self, message="Upgrade!"), card=self)
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
                    GAME.consumeable_buffer += 1

                    def func() -> None:
                        make_consumable("Tarot", "8ba")
                    return T(extra=T(focus=self, message="+1 Tarot", func=func), card=self)
            if name == "The Idol" and oc.get_id() == GAME.current_round.idol_card.id and oc.is_suit(GAME.current_round.idol_card.suit):
                return T(x_mult=ab.extra, card=self)
            if name == "Scary Face" and oc.is_face():
                return T(chips=ab.extra, card=self)
            if name == "Smiley Face" and oc.is_face():
                return T(mult=ab.extra, card=self)
            if name == "Golden Ticket" and oc.ability.name == "Gold Card":
                GAME.dollar_buffer = (GAME.dollar_buffer or 0) + ab.extra
                G.add_event(lambda: setattr(GAME, "dollar_buffer", 0))
                return T(dollars=ab.extra, card=self)
            if name == "Scholar" and oc.get_id() == 14:
                return T(chips=ab.extra.chips, mult=ab.extra.mult, card=self)
            if name == "Walkie Talkie" and (oc.get_id() == 10 or oc.get_id() == 4):
                return T(chips=ab.extra.chips, mult=ab.extra.mult, card=self)
            if name == "Business Card" and oc.is_face() and G.rng.random("business") < GAME.probabilities.normal / ab.extra:
                GAME.dollar_buffer = (GAME.dollar_buffer or 0) + 2
                G.add_event(lambda: setattr(GAME, "dollar_buffer", 0))
                return T(dollars=2, card=self)
            if name == "Fibonacci" and oc.get_id() in (2, 3, 5, 8, 14):
                return T(mult=ab.extra, card=self)
            if name == "Even Steven":
                cid = oc.get_id()
                if 0 <= cid <= 10 and cid % 2 == 0:
                    return T(mult=ab.extra, card=self)
            if name == "Odd Todd":
                cid = oc.get_id()
                if (0 <= cid <= 10 and cid % 2 == 1) or cid == 14:
                    return T(chips=ab.extra, card=self)
            if ab.effect == "Suit Mult" and oc.is_suit(ab.extra.suit):
                return T(mult=ab.extra.s_mult, card=self)
            if name == "Rough Gem" and oc.is_suit("Diamonds"):
                GAME.dollar_buffer = (GAME.dollar_buffer or 0) + ab.extra
                G.add_event(lambda: setattr(GAME, "dollar_buffer", 0))
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
                    return T(message="Debuffed", card=self)
                return T(h_mult=13, card=self)
            if name == "Baron" and oc.get_id() == 13:
                if oc.debuff:
                    return T(message="Debuffed", card=self)
                return T(x_mult=ab.extra, card=self)
            if name == "Reserved Parking" and oc.is_face() and G.rng.random("parking") < GAME.probabilities.normal / ab.extra.odds:
                if oc.debuff:
                    return T(message="Debuffed", card=self)
                GAME.dollar_buffer = (GAME.dollar_buffer or 0) + ab.extra.dollars
                G.add_event(lambda: setattr(GAME, "dollar_buffer", 0))
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
                        return T(message="Debuffed", card=self)
                    return T(h_mult=2 * temp_mult, card=self)
    elif context.repetition:
        oc = context.other_card
        if context.cardarea is G.play:
            if name == "Sock and Buskin" and oc.is_face():
                return T(repetitions=ab.extra, card=self)
            if name == "Hanging Chad" and context.scoring_hand and oc is context.scoring_hand[0]:
                return T(repetitions=ab.extra, card=self)
            if name == "Dusk" and GAME.current_round.hands_left == 0:
                return T(repetitions=ab.extra, card=self)
            if name == "Seltzer":
                return T(repetitions=1, card=self)
            if name == "Hack" and oc.get_id() in (2, 3, 4, 5):
                return T(repetitions=ab.extra, card=self)
        if context.cardarea is G.hand:
            if name == "Mime" and (nonempty(context.card_effects[0]) or len(context.card_effects) > 1):
                return T(repetitions=ab.extra, card=self)
    elif context.other_joker:
        if name == "Baseball Card" and context.other_joker.config.center.rarity == 2 and self is not context.other_joker:
            return T(Xmult_mod=ab.extra)
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
    if name == "Spare Trousers" and (ph["Two Pair"] or ph["Full House"]) and not context.blueprint:
        ab.mult = ab.mult + ab.extra
        return T(card=self, message="Upgrade!")
    if name == "Space Joker" and G.rng.random("space") < GAME.probabilities.normal / ab.extra:
        return T(card=self, level_up=True, message="Level Up!")
    if name == "Square Joker" and len(context.full_hand) == 4 and not context.blueprint:
        ab.extra.chips = ab.extra.chips + ab.extra.chip_mod
        return T(card=self, message="Upgrade!")
    if name == "Runner" and ph["Straight"] and not context.blueprint:
        ab.extra.chips = ab.extra.chips + ab.extra.chip_mod
        return T(card=self, message="Upgrade!")
    if name == "Midas Mask" and not context.blueprint:
        faces = []
        for v in context.scoring_hand:
            if v.is_face():
                faces.append(v)
                v.set_ability(G.P_CENTERS["m_gold"], None, True)
        if faces:
            return T(card=self, message="Gold")
    if name == "Vampire" and not context.blueprint:
        enhanced = []
        for v in context.scoring_hand:
            if v.config.center is not G.P_CENTERS["c_base"] and not v.debuff and not v.vampired:
                enhanced.append(v)
                v.vampired = True
                v.set_ability(G.P_CENTERS["c_base"], None, True)

                def unvamp(v: "Card" = v) -> None:
                    v.vampired = None
                G.add_event(unvamp)
        if enhanced:
            ab.x_mult = ab.x_mult + ab.extra * len(enhanced)
            return T(card=self, message="x")
    if name == "To Do List" and context.scoring_name == ab.to_do_poker_hand:
        G.ease_dollars(ab.extra.dollars)
        GAME.dollar_buffer = (GAME.dollar_buffer or 0) + ab.extra.dollars
        G.add_event(lambda: setattr(GAME, "dollar_buffer", 0))
        return T(dollars=ab.extra.dollars)
    if name == "DNA" and GAME.current_round.hands_played == 0:
        if len(context.full_hand) == 1:
            G.playing_card = (G.playing_card + 1) if G.playing_card else 1
            card = G.copy_card(context.full_hand[0], None, None, G.playing_card)
            card.add_to_deck()
            G.deck.config.card_limit += 1
            G.playing_cards.append(card)
            G.hand.emplace(card)
            # evaluate_play's card_eval_status_text() runs
            # playing_card_joker_effects(playing_cards_created) synchronously
            return T(card=self, message="Copied!", playing_cards_created=[True])
    if name == "Ride the Bus" and not context.blueprint:
        faces = any(c.is_face() for c in context.scoring_hand)
        if faces:
            last = ab.mult
            ab.mult = 0
            if last > 0:
                return T(card=self, message="Reset")
        else:
            ab.mult = ab.mult + ab.extra
    if name == "Obelisk" and not context.blueprint:
        reset = True
        play_more_than = GAME.hands[context.scoring_name].played or 0
        for k in G.hands_order():
            v = GAME.hands[k]
            if k != context.scoring_name and v.played >= play_more_than and v.visible:
                reset = False
        if reset:
            if ab.x_mult > 1:
                ab.x_mult = 1
                return T(card=self, message="Reset")
        else:
            ab.x_mult = ab.x_mult + ab.extra
    if name == "Green Joker" and not context.blueprint:
        ab.mult = ab.mult + ab.extra.hand_add
        return T(card=self, message="+mult")
    return None


def _after(self: "Card", context: T) -> Any:
    ab = self.ability
    name = ab.name
    if name == "Ice Cream" and not context.blueprint:
        if ab.extra.chips - ab.extra.chip_mod <= 0:
            _remove_eaten(self)
            return T(message="Melted!")
        ab.extra.chips = ab.extra.chips - ab.extra.chip_mod
        return T(message="-chips")
    if name == "Seltzer" and not context.blueprint:
        if ab.extra - 1 <= 0:
            _remove_eaten(self)
            return T(message="Drank!")
        ab.extra = ab.extra - 1
        return T(message=str(ab.extra))
    return None


def _joker_main(self: "Card", context: T) -> Any:  # noqa: C901
    G = self.G
    GAME = G.GAME
    ab = self.ability
    name = ab.name
    ph = context.poker_hands
    cons = G.consumeables

    if name == "Loyalty Card":
        ab.loyalty_remaining = (ab.extra.every - 1 - (GAME.hands_played - ab.hands_played_at_create)) % (ab.extra.every + 1)
        if context.blueprint:
            if ab.loyalty_remaining == ab.extra.every:
                return T(Xmult_mod=ab.extra.Xmult)
        else:
            if ab.loyalty_remaining == 0:
                pass
            elif ab.loyalty_remaining == ab.extra.every:
                return T(Xmult_mod=ab.extra.Xmult)
    if name != "Seeing Double" and ab.x_mult > 1 and (ab.type == "" or ph[ab.type]):
        return T(Xmult_mod=ab.x_mult)
    if ab.t_mult > 0 and ph[ab.type]:
        return T(mult_mod=ab.t_mult)
    if ab.t_chips > 0 and ph[ab.type]:
        return T(chip_mod=ab.t_chips)
    if name == "Half Joker" and len(context.full_hand) <= ab.extra.size:
        return T(mult_mod=ab.extra.mult)
    if name == "Abstract Joker":
        x = sum(1 for c in G.jokers.cards if c.ability.set == "Joker")
        return T(mult_mod=x * ab.extra)
    if name == "Acrobat" and GAME.current_round.hands_left == 0:
        return T(Xmult_mod=ab.extra)
    if name == "Mystic Summit" and GAME.current_round.discards_left == ab.extra.d_remaining:
        return T(mult_mod=ab.extra.mult)
    if name == "Misprint":
        temp_mult = G.rng.randint("misprint", ab.extra.min, ab.extra.max)
        return T(mult_mod=temp_mult)
    if name == "Banner" and GAME.current_round.discards_left > 0:
        return T(chip_mod=GAME.current_round.discards_left * ab.extra)
    if name == "Stuntman":
        return T(chip_mod=ab.extra.chip_mod)
    if name == "Matador":
        if GAME.blind.triggered:
            G.ease_dollars(ab.extra)
            GAME.dollar_buffer = (GAME.dollar_buffer or 0) + ab.extra
            G.add_event(lambda: setattr(GAME, "dollar_buffer", 0))
            return T(dollars=ab.extra)
    if name == "Supernova":
        return T(mult_mod=GAME.hands[context.scoring_name].played)
    if name == "Ceremonial Dagger" and ab.mult > 0:
        return T(mult_mod=ab.mult)
    if name == "Vagabond" and len(cons.cards) + GAME.consumeable_buffer < cons.config.card_limit:
        if GAME.dollars <= ab.extra:
            GAME.consumeable_buffer += 1

            def vag() -> None:
                card = G.create_card("Tarot", G.consumeables, None, None, None, None, None, "vag")
                card.add_to_deck()
                G.consumeables.emplace(card)
                GAME.consumeable_buffer = 0
            G.add_event(vag)
            return T(message="+1 Tarot", card=self)
    if name == "Superposition" and len(cons.cards) + GAME.consumeable_buffer < cons.config.card_limit:
        aces = sum(1 for c in context.scoring_hand if c.get_id() == 14)
        if aces >= 1 and ph["Straight"]:
            GAME.consumeable_buffer += 1

            def sup() -> None:
                card = G.create_card("Tarot", G.consumeables, None, None, None, None, None, "sup")
                card.add_to_deck()
                G.consumeables.emplace(card)
                GAME.consumeable_buffer = 0
            G.add_event(sup)
            return T(message="+1 Tarot", card=self)
    if name == "Seance" and len(cons.cards) + GAME.consumeable_buffer < cons.config.card_limit:
        if ph[ab.extra.poker_hand]:
            GAME.consumeable_buffer += 1

            def sea() -> None:
                card = G.create_card("Spectral", G.consumeables, None, None, None, None, None, "sea")
                card.add_to_deck()
                G.consumeables.emplace(card)
                GAME.consumeable_buffer = 0
            G.add_event(sea)
            return T(message="+1 Spectral", card=self)
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
            return T(Xmult_mod=ab.extra)
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
            return T(Xmult_mod=ab.extra)
    if name == "Wee Joker":
        return T(chip_mod=ab.extra.chips)
    if name == "Castle" and ab.extra.chips > 0:
        return T(chip_mod=ab.extra.chips)
    if name == "Blue Joker" and len(G.deck.cards) > 0:
        return T(chip_mod=ab.extra * len(G.deck.cards))
    if name == "Erosion" and (GAME.starting_deck_size - len(G.playing_cards)) > 0:
        return T(mult_mod=ab.extra * (GAME.starting_deck_size - len(G.playing_cards)))
    if name == "Square Joker":
        return T(chip_mod=ab.extra.chips)
    if name == "Runner":
        return T(chip_mod=ab.extra.chips)
    if name == "Ice Cream":
        return T(chip_mod=ab.extra.chips)
    if name == "Stone Joker" and ab.stone_tally > 0:
        return T(chip_mod=ab.extra * ab.stone_tally)
    if name == "Steel Joker" and ab.steel_tally > 0:
        return T(Xmult_mod=1 + ab.extra * ab.steel_tally)
    if name == "Bull" and (GAME.dollars + (GAME.dollar_buffer or 0)) > 0:
        return T(chip_mod=ab.extra * max(0, GAME.dollars + (GAME.dollar_buffer or 0)))
    if name == "Driver's License":
        if (ab.driver_tally or 0) >= 16:
            return T(Xmult_mod=ab.extra)
    if name == "Blackboard":
        black, all_cards = 0, 0
        for c in G.hand.cards:
            all_cards += 1
            if c.is_suit("Clubs", None, True) or c.is_suit("Spades", None, True):
                black += 1
        if black == all_cards:
            return T(Xmult_mod=ab.extra)
    if name == "Joker Stencil":
        if (G.jokers.config.card_limit - len(G.jokers.cards)) > 0:
            return T(Xmult_mod=ab.x_mult)
    if name == "Swashbuckler" and ab.mult > 0:
        return T(mult_mod=ab.mult)
    if name == "Joker":
        return T(mult_mod=ab.mult)
    if name == "Spare Trousers" and ab.mult > 0:
        return T(mult_mod=ab.mult)
    if name == "Ride the Bus" and ab.mult > 0:
        return T(mult_mod=ab.mult)
    if name == "Flash Card" and ab.mult > 0:
        return T(mult_mod=ab.mult)
    if name == "Popcorn" and ab.mult > 0:
        return T(mult_mod=ab.mult)
    if name == "Green Joker" and ab.mult > 0:
        return T(mult_mod=ab.mult)
    if name == "Fortune Teller" and GAME.consumeable_usage_total and GAME.consumeable_usage_total.tarot > 0:
        return T(mult_mod=GAME.consumeable_usage_total.tarot)
    if name == "Gros Michel":
        return T(mult_mod=ab.extra.mult)
    if name == "Cavendish":
        return T(Xmult_mod=ab.extra.Xmult)
    if name == "Red Card" and ab.mult > 0:
        return T(mult_mod=ab.mult)
    if name == "Card Sharp" and GAME.hands.get(context.scoring_name) and GAME.hands[context.scoring_name].played_this_round > 1:
        return T(Xmult_mod=ab.extra.Xmult)
    if name == "Bootstraps" and math.floor((GAME.dollars + (GAME.dollar_buffer or 0)) / ab.extra.dollars) >= 1:
        return T(mult_mod=ab.extra.mult * math.floor((GAME.dollars + (GAME.dollar_buffer or 0)) / ab.extra.dollars))
    if name == "Caino" and ab.caino_xmult > 1:
        return T(Xmult_mod=ab.caino_xmult)
    return None
