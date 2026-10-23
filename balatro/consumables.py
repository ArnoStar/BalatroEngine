"""Card:use_consumeable and Card:can_use_consumeable from card.lua."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .card import ID_TO_CHAR
from .lua import T

if TYPE_CHECKING:
    from .card import Card


def use_consumeable(self: "Card", area: Any, copier: "Card | None" = None) -> None:  # noqa: C901
    G = self.G
    GAME = G.GAME
    G.stop_use()
    if not copier:
        G.set_consumeable_usage(self)
    if self.debuff:
        return None
    used_tarot = copier or self
    ab = self.ability
    cons = ab.consumeable
    name = ab.name
    hand = G.hand
    ev = G.ev

    if cons.max_highlighted:
        G.update_hand_text(T(immediate=True, nopulse=True, delay=0), T(mult=0, chips=0, level="", handname=""))

    if cons.mod_conv or cons.suit_conv:
        ev(None, trigger="after", delay=0.4)
        for i in range(len(hand.highlighted)):
            ev(lambda i=i: hand.highlighted[i].flip(), trigger="after", delay=0.15)
        G.delay(0.2)
        if name == "Death":
            rightmost = hand.highlighted[0]
            for c in hand.highlighted:
                if hand.index(c) > hand.index(rightmost):
                    rightmost = c
            for i in range(len(hand.highlighted)):
                def death(i: int = i) -> None:
                    if hand.highlighted[i] is not rightmost:
                        G.copy_card(rightmost, hand.highlighted[i])
                ev(death, trigger="after", delay=0.1)
        elif name == "Strength":
            for i in range(len(hand.highlighted)):
                def strength(i: int = i) -> None:
                    card = hand.highlighted[i]
                    suit_prefix = card.base.suit[0] + "_"
                    rank = 2 if card.base.id == 14 else min(card.base.id + 1, 14)
                    rank_suffix = str(rank) if rank < 10 else ID_TO_CHAR[rank]
                    card.set_base(G.P_CARDS[suit_prefix + rank_suffix])
                ev(strength, trigger="after", delay=0.1)
        elif cons.suit_conv:
            for i in range(len(hand.highlighted)):
                ev(lambda i=i: hand.highlighted[i].change_suit(cons.suit_conv), trigger="after", delay=0.1)
        else:
            for i in range(len(hand.highlighted)):
                ev(lambda i=i: hand.highlighted[i].set_ability(G.P_CENTERS[cons.mod_conv]), trigger="after", delay=0.1)
        for i in range(len(hand.highlighted)):
            ev(lambda i=i: hand.highlighted[i].flip(), trigger="after", delay=0.15)
        ev(hand.unhighlight_all, trigger="after", delay=0.2)
        G.delay(0.5)

    if name == "Black Hole":
        G.update_hand_text(T(sound="button", volume=0.7, pitch=0.8, delay=0.3),
                           T(handname="All Hands", chips="...", mult="...", level=""))
        ev(None, trigger="after", delay=0.2)
        G.update_hand_text(T(delay=0), T(mult="+", StatusText=True))
        ev(None, trigger="after", delay=0.9)
        G.update_hand_text(T(delay=0), T(chips="+", StatusText=True))
        ev(None, trigger="after", delay=0.9)
        G.update_hand_text(T(sound="button", volume=0.7, pitch=0.9, delay=0), T(level="+1"))
        G.delay(1.3)
        for k in G.hands_order():
            G.level_up_hand(self, k, True)
        G.update_hand_text(T(sound="button", volume=0.7, pitch=1.1, delay=0), T(mult=0, chips=0, handname="", level=""))

    if name in ("Talisman", "Deja Vu", "Trance", "Medium"):
        conv_card = hand.highlighted[0]
        ev(None)
        ev(lambda: conv_card.set_seal(ab.extra, None, True), trigger="after", delay=0.1)
        G.delay(0.5)
        ev(hand.unhighlight_all, trigger="after", delay=0.2)

    if name == "Aura":
        def aura() -> None:
            edition = G.poll_edition("aura", None, True, True)
            hand.highlighted[0].set_edition(edition, True)
        ev(aura, trigger="after", delay=0.4)

    if name == "Cryptid":
        def cryptid() -> None:
            first_dissolve = None
            new_cards = []
            for _ in range(ab.extra):
                G.playing_card = (G.playing_card + 1) if G.playing_card else 1
                card = G.copy_card(hand.highlighted[0], None, None, G.playing_card)
                card.add_to_deck()
                G.deck.config.card_limit = G.deck.config.card_limit + 1
                G.playing_cards.append(card)
                hand.emplace(card)
                card.start_materialize(None, first_dissolve)
                first_dissolve = True
                new_cards.append(card)
            G.playing_card_joker_effects(new_cards)
        ev(cryptid)

    if name in ("Sigil", "Ouija"):
        ev(None, trigger="after", delay=0.4)
        for i in range(len(hand.cards)):
            ev(lambda i=i: hand.cards[i].flip(), trigger="after", delay=0.15)
        G.delay(0.2)
        if name == "Sigil":
            suit = G.rng.element(["S", "H", "D", "C"], G.rng.pseudoseed("sigil"))
            for i in range(len(hand.cards)):
                def sigil(i: int = i) -> None:
                    card = hand.cards[i]
                    bid = card.base.id
                    rank_suffix = str(bid) if bid < 10 else ID_TO_CHAR[bid]
                    card.set_base(G.P_CARDS[suit + "_" + rank_suffix])
                ev(sigil)
        if name == "Ouija":
            rank = G.rng.element(["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"],
                                 G.rng.pseudoseed("ouija"))
            for i in range(len(hand.cards)):
                def ouija(i: int = i) -> None:
                    card = hand.cards[i]
                    card.set_base(G.P_CARDS[card.base.suit[0] + "_" + rank])
                ev(ouija)
            hand.change_size(-1)
        for i in range(len(hand.cards)):
            ev(lambda i=i: hand.cards[i].flip(), trigger="after", delay=0.15)
        G.delay(0.5)

    if cons.hand_type:
        h = GAME.hands[cons.hand_type]
        G.update_hand_text(T(sound="button", volume=0.7, pitch=0.8, delay=0.3),
                           T(handname=cons.hand_type, chips=h.chips, mult=h.mult, level=h.level))
        G.level_up_hand(used_tarot, cons.hand_type)
        G.update_hand_text(T(sound="button", volume=0.7, pitch=1.1, delay=0), T(mult=0, chips=0, handname="", level=""))

    if cons.remove_card:
        destroyed: list[Card] = []
        if name == "The Hanged Man":
            for i in range(len(hand.highlighted) - 1, -1, -1):
                destroyed.append(hand.highlighted[i])
            ev(None, trigger="after", delay=0.4)

            def hanged() -> None:
                hl = hand.highlighted
                for i in range(len(hl) - 1, -1, -1):
                    card = hl[i]
                    if card.ability.name == "Glass Card":
                        card.shatter()
                    else:
                        card.start_dissolve(None, i == len(hl) - 1)
            ev(hanged, trigger="after", delay=0.2)
        elif name in ("Familiar", "Grim", "Incantation"):
            destroyed.append(G.random_card_from(list(hand.cards), "random_destroy"))
            ev(None, trigger="after", delay=0.4)

            def destroy() -> None:
                for i in range(len(destroyed) - 1, -1, -1):
                    card = destroyed[i]
                    if card.ability.name == "Glass Card":
                        card.shatter()
                    else:
                        card.start_dissolve(None, i != len(destroyed) - 1)
            ev(destroy, trigger="after", delay=0.1)

            def create() -> None:
                cards = []
                for i in range(ab.extra):
                    cards.append(True)
                    if name == "Familiar":
                        r = G.rng.element(["J", "Q", "K"], G.rng.pseudoseed("familiar_create"))
                        s = G.rng.element(["S", "H", "D", "C"], G.rng.pseudoseed("familiar_create"))
                    elif name == "Grim":
                        r = "A"
                        s = G.rng.element(["S", "H", "D", "C"], G.rng.pseudoseed("grim_create"))
                    else:
                        r = G.rng.element(["2", "3", "4", "5", "6", "7", "8", "9", "T"],
                                          G.rng.pseudoseed("incantation_create"))
                        s = G.rng.element(["S", "H", "D", "C"], G.rng.pseudoseed("incantation_create"))
                    s = s or "S"
                    r = r or "A"
                    pool = [v for v in G.P_CENTER_POOLS["Enhanced"] if v.key != "m_stone"]
                    center = G.rng.element(pool, G.rng.pseudoseed("spe_card"))
                    G.create_playing_card(T(front=G.P_CARDS[s + "_" + r], center=center), hand, None, i != 0, True)
                G.playing_card_joker_effects(cards)
            ev(create, trigger="after", delay=0.7)
        elif name == "Immolate":
            # (sorted by playing_card, then pseudoshuffle re-sorts by sort_id)
            temp = sorted(hand.cards, key=lambda c: c.sort_id)
            G.rng.shuffle(temp, G.rng.pseudoseed("immolate"))
            for i in range(ab.extra.destroy):
                if i < len(temp):  # (t[#t+1] = nil past the end adds nothing)
                    destroyed.append(temp[i])
            ev(None, trigger="after", delay=0.4)

            def immolate() -> None:
                for i in range(len(destroyed) - 1, -1, -1):
                    card = destroyed[i]
                    if card.ability.name == "Glass Card":
                        card.shatter()
                    else:
                        card.start_dissolve(None, i == len(destroyed) - 1)
            ev(immolate, trigger="after", delay=0.1)
            G.delay(0.5)
            G.ease_dollars(ab.extra.dollars)
        G.delay(0.3)
        for j in list(G.jokers.cards):
            j.calculate_joker(T(remove_playing_cards=True, removed=destroyed))

    if name == "The Fool":
        def fool() -> None:
            if G.consumeables.config.card_limit > len(G.consumeables.cards):
                card = G.create_card("Tarot_Planet", G.consumeables, None, None, None, None, GAME.last_tarot_planet, "fool")
                card.add_to_deck()
                G.consumeables.emplace(card)
        ev(fool, trigger="after", delay=0.4)
        G.delay(0.6)

    if name == "The Hermit":
        ev(lambda: G.ease_dollars(max(0, min(GAME.dollars, ab.extra)), True), trigger="after", delay=0.4)
        G.delay(0.6)

    if name == "Temperance":
        ev(lambda: G.ease_dollars(ab.money, True), trigger="after", delay=0.4)
        G.delay(0.6)

    if name in ("The Emperor", "The High Priestess"):
        n = min(cons.tarots or cons.planets, G.consumeables.config.card_limit - len(G.consumeables.cards))
        for _ in range(max(0, n)):
            def emp() -> None:
                if G.consumeables.config.card_limit > len(G.consumeables.cards):
                    typ = "Tarot" if name == "The Emperor" else "Planet"
                    card = G.create_card(typ, G.consumeables, None, None, None, None, None,
                                         "emp" if name == "The Emperor" else "pri")
                    card.add_to_deck()
                    G.consumeables.emplace(card)
            ev(emp, trigger="after", delay=0.4)
        G.delay(0.6)

    if name in ("Judgement", "The Soul"):
        def judge() -> None:
            card = G.create_card("Joker", G.jokers, name == "The Soul", None, None, None, None,
                                 "jud" if name == "Judgement" else "sou")
            card.add_to_deck()
            G.jokers.emplace(card)
        ev(judge, trigger="after", delay=0.4)
        G.delay(0.6)

    if name == "Ankh":
        deletable = [v for v in G.jokers.cards if not v.ability.eternal]
        chosen = G.random_card_from(list(G.jokers.cards), "ankh_choice")

        def ankh_destroy() -> None:
            first = None
            for v in deletable:
                if v is not chosen:
                    v.start_dissolve(None, first)
                    first = True
        ev(ankh_destroy, trigger="before", delay=0.75)

        def ankh_copy() -> None:
            card = G.copy_card(chosen, None, None, None, bool(chosen.edition and chosen.edition.negative))
            card.start_materialize()
            card.add_to_deck()
            if card.edition and card.edition.negative:
                card.set_edition(None, True)
            G.jokers.emplace(card)
        ev(ankh_copy, trigger="before", delay=0.4)

    if name == "Wraith":
        def wraith() -> None:
            card = G.create_card("Joker", G.jokers, None, 0.99, None, None, None, "wra")
            card.add_to_deck()
            G.jokers.emplace(card)
            if GAME.dollars != 0:
                G.ease_dollars(-GAME.dollars, True)
        ev(wraith, trigger="after", delay=0.4)
        G.delay(0.6)

    if name in ("The Wheel of Fortune", "Ectoplasm", "Hex"):
        if name in ("Ectoplasm", "Hex") or G.rng.random("wheel_of_fortune") < GAME.probabilities.normal / ab.extra:
            def wheel() -> None:
                seed = {"The Wheel of Fortune": "wheel_of_fortune", "Ectoplasm": "ectoplasm", "Hex": "hex"}[name]
                # the list Card:update keeps refreshing, as it is when this runs
                pool = self.eligible_strength_jokers if name == "The Wheel of Fortune" else self.eligible_editionless_jokers
                eligible = G.random_card_from(list(pool), seed)
                if name == "Ectoplasm":
                    edition = T(negative=True)
                elif name == "Hex":
                    edition = T(polychrome=True)
                else:
                    edition = G.poll_edition("wheel_of_fortune", None, True, True)
                eligible.set_edition(edition, True)
                if name == "Hex":
                    first = None
                    for v in list(G.jokers.cards):
                        if v is not eligible and not v.ability.eternal:
                            v.start_dissolve(None, first)
                            first = True
                if name == "Ectoplasm":
                    GAME.ecto_minus = GAME.ecto_minus or 1
                    G.hand.change_size(-GAME.ecto_minus)
                    GAME.ecto_minus = GAME.ecto_minus + 1
            ev(wheel, trigger="after", delay=0.4)
        else:
            ev(None, trigger="after", delay=0.4)
        G.delay(0.6)
    return None


def can_use_consumeable(self: "Card", any_state: Any = None, skip_check: Any = None) -> bool:
    G = self.G
    S = G.STATES
    if not skip_check and ((G.play is not None and G.play.cards) or G.CONTROLLER.locked
                           or (G.GAME.STOP_USE and G.GAME.STOP_USE > 0)):
        return False
    if (G.STATE != S.HAND_PLAYED and G.STATE != S.DRAW_TO_HAND and G.STATE != S.PLAY_TAROT) or any_state:
        ab = self.ability
        cons = ab.consumeable
        name = ab.name
        if name == "The Hermit" or cons.hand_type or name == "Temperance" or name == "Black Hole":
            return True
        if name == "The Wheel of Fortune":
            if self.eligible_strength_jokers:
                return True
        if name == "Ankh":
            for v in G.jokers.cards:
                if v.ability.set == "Joker" and G.jokers.config.card_limit > 1:
                    return True
        if name == "Aura":
            if G.hand is not None and len(G.hand.highlighted) == 1 and not G.hand.highlighted[0].edition:
                return True
        if name in ("Ectoplasm", "Hex"):
            if self.eligible_editionless_jokers:
                return True
        if name in ("The Emperor", "The High Priestess"):
            if len(G.consumeables.cards) < G.consumeables.config.card_limit or self.area is G.consumeables:
                return True
        if name == "The Fool":
            if ((len(G.consumeables.cards) < G.consumeables.config.card_limit or self.area is G.consumeables)
                    and G.GAME.last_tarot_planet and G.GAME.last_tarot_planet != "c_fool"):
                return True
        if name in ("Judgement", "The Soul", "Wraith"):
            if len(G.jokers.cards) < G.jokers.config.card_limit or self.area is G.jokers:
                return True
            return False
        if G.STATE in (S.SELECTING_HAND, S.TAROT_PACK, S.SPECTRAL_PACK, S.PLANET_PACK):
            if cons.max_highlighted:
                if cons.mod_num >= len(G.hand.highlighted) and len(G.hand.highlighted) >= (cons.min_highlighted or 1):
                    return True
            if name in ("Familiar", "Grim", "Incantation", "Immolate", "Sigil", "Ouija") and len(G.hand.cards) > 1:
                return True
    return False
