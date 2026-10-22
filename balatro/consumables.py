"""Card:use_consumeable() and Card:can_use_consumeable() from card.lua."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .lua import T

if TYPE_CHECKING:
    from .card import Card
    from .game import Game


RANK_UP = {2: "3", 3: "4", 4: "5", 5: "6", 6: "7", 7: "8", 8: "9", 9: "T", 10: "J", 11: "Q", 12: "K", 13: "A", 14: "2"}
ID_TO_CHAR = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}


def set_consumeable_usage(G: "Game", card: "Card") -> None:
    if card.config.center_key and card.ability.consumeable:
        key = card.config.center_key
        cu = G.GAME.consumeable_usage
        if cu.get(key):
            cu[key].count += 1
        else:
            cu[key] = T(count=1, order=card.config.center.order, set=card.ability.set)
        tot = G.GAME.consumeable_usage_total or T(tarot=0, planet=0, spectral=0, tarot_planet=0, all=0)
        G.GAME.consumeable_usage_total = tot
        s = card.config.center.set
        if s == "Tarot":
            tot.tarot += 1
            tot.tarot_planet += 1
        elif s == "Planet":
            tot.planet += 1
            tot.tarot_planet += 1
        elif s == "Spectral":
            tot.spectral += 1
        tot.all += 1
        if s in ("Tarot", "Planet"):
            def outer() -> None:
                def inner() -> None:
                    G.GAME.last_tarot_planet = key
                G.add_event(inner)
            G.add_event(outer)


def use_consumeable(self: "Card", area: Any, copier: "Card | None" = None) -> None:
    G = self.G
    GAME = G.GAME
    if not copier:
        set_consumeable_usage(G, self)
    if self.debuff:
        return
    used_tarot = copier or self
    ab = self.ability
    cons = ab.consumeable
    name = ab.name
    hl = G.hand.highlighted

    if cons.mod_conv or cons.suit_conv:
        if name == "Death":
            rightmost = hl[0]
            for c in hl:
                if G.hand.index(c) > G.hand.index(rightmost):
                    rightmost = c
            for i in range(len(hl)):
                def death(i: int = i) -> None:
                    if G.hand.highlighted[i] is not rightmost:
                        G.copy_card(rightmost, G.hand.highlighted[i])
                G.add_event(death)
        elif name == "Strength":
            for i in range(len(hl)):
                def strength(i: int = i) -> None:
                    card = G.hand.highlighted[i]
                    suit_prefix = card.base.suit[0] + "_"
                    card.set_base(G.P_CARDS[suit_prefix + RANK_UP[card.base.id]])
                G.add_event(strength)
        elif cons.suit_conv:
            for i in range(len(hl)):
                G.add_event(lambda i=i: G.hand.highlighted[i].change_suit(cons.suit_conv))
        else:
            for i in range(len(hl)):
                G.add_event(lambda i=i: G.hand.highlighted[i].set_ability(G.P_CENTERS[cons.mod_conv]))
        G.add_event(G.hand.unhighlight_all)

    if name == "Black Hole":
        for k in G.hands_order():
            G.level_up_hand(self, k, True)

    if name in ("Talisman", "Deja Vu", "Trance", "Medium"):
        conv_card = hl[0]
        G.add_event(lambda: conv_card.set_seal(ab.extra, None, True))
        G.add_event(G.hand.unhighlight_all)

    if name == "Aura":
        def aura() -> None:
            edition = G.poll_edition("aura", None, True, True)
            G.hand.highlighted[0].set_edition(edition, True)
        G.add_event(aura)

    if name == "Cryptid":
        def cryptid() -> None:
            new_cards = []
            for _ in range(ab.extra):
                G.playing_card = (G.playing_card + 1) if G.playing_card else 1
                c = G.copy_card(G.hand.highlighted[0], None, None, G.playing_card)
                c.add_to_deck()
                G.deck.config.card_limit += 1
                G.playing_cards.append(c)
                G.hand.emplace(c)
                new_cards.append(c)
            G.playing_card_joker_effects(new_cards)
        G.add_event(cryptid)

    if name in ("Sigil", "Ouija"):
        if name == "Sigil":
            suit = G.rng.element(["S", "H", "D", "C"], G.rng.pseudoseed("sigil"))
            for i in range(len(G.hand.cards)):
                def sigil(i: int = i) -> None:
                    card = G.hand.cards[i]
                    card.set_base(G.P_CARDS[suit + "_" + ID_TO_CHAR[card.base.id]])
                G.add_event(sigil)
        if name == "Ouija":
            rank = G.rng.element(["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"], G.rng.pseudoseed("ouija"))
            for i in range(len(G.hand.cards)):
                def ouija(i: int = i) -> None:
                    card = G.hand.cards[i]
                    card.set_base(G.P_CARDS[card.base.suit[0] + "_" + rank])
                G.add_event(ouija)
            G.hand.change_size(-1)

    if cons.hand_type:
        G.level_up_hand(used_tarot, cons.hand_type)

    if cons.remove_card:
        destroyed_cards: list[Card] = []
        if name == "The Hanged Man":
            for i in range(len(hl) - 1, -1, -1):
                destroyed_cards.append(hl[i])

            def hanged() -> None:
                for i in range(len(G.hand.highlighted) - 1, -1, -1):
                    card = G.hand.highlighted[i]
                    if card.ability.name == "Glass Card":
                        card.shatter()
                    else:
                        card.start_dissolve()
            G.add_event(hanged)
        elif name in ("Familiar", "Grim", "Incantation"):
            destroyed_cards.append(G._random_card_from(G.hand.cards, "random_destroy"))

            def kill() -> None:
                for card in reversed(destroyed_cards):
                    if card.ability.name == "Glass Card":
                        card.shatter()
                    else:
                        card.start_dissolve()
            G.add_event(kill)

            def create() -> None:
                cards = []
                for _ in range(ab.extra):
                    cards.append(True)
                    suit = rank = None
                    if name == "Familiar":
                        rank = G.rng.element(["J", "Q", "K"], G.rng.pseudoseed("familiar_create"))
                        suit = G.rng.element(["S", "H", "D", "C"], G.rng.pseudoseed("familiar_create"))
                    elif name == "Grim":
                        rank = "A"
                        suit = G.rng.element(["S", "H", "D", "C"], G.rng.pseudoseed("grim_create"))
                    elif name == "Incantation":
                        rank = G.rng.element(["2", "3", "4", "5", "6", "7", "8", "9", "T"], G.rng.pseudoseed("incantation_create"))
                        suit = G.rng.element(["S", "H", "D", "C"], G.rng.pseudoseed("incantation_create"))
                    suit = suit or "S"
                    rank = rank or "A"
                    cen_pool = [v for v in G.P_CENTER_POOLS["Enhanced"] if v.key != "m_stone"]
                    center = G.rng.element(cen_pool, G.rng.pseudoseed("spe_card"))
                    G.create_playing_card(T(front=G.P_CARDS[suit + "_" + rank], center=center), G.hand)
                G.playing_card_joker_effects(cards)
            G.add_event(create)
        elif name == "Immolate":
            temp_hand = sorted(G.hand.cards, key=lambda c: c.sort_id)
            G.rng.shuffle(temp_hand, G.rng.pseudoseed("immolate"))
            for i in range(min(ab.extra.destroy, len(temp_hand))):
                destroyed_cards.append(temp_hand[i])

            def kill2() -> None:
                for card in reversed(destroyed_cards):
                    if card.ability.name == "Glass Card":
                        card.shatter()
                    else:
                        card.start_dissolve()
            G.add_event(kill2)
            G.ease_dollars(ab.extra.dollars)
        for j in list(G.jokers.cards):
            j.calculate_joker(T(remove_playing_cards=True, removed=destroyed_cards))

    if name == "The Fool":
        def fool() -> None:
            if G.consumeables.config.card_limit > len(G.consumeables.cards):
                card = G.create_card("Tarot_Planet", G.consumeables, None, None, None, None, GAME.last_tarot_planet, "fool")
                card.add_to_deck()
                G.consumeables.emplace(card)
        G.add_event(fool)
    if name == "The Hermit":
        G.add_event(lambda: G.ease_dollars(max(0, min(GAME.dollars, ab.extra)), True))
    if name == "Temperance":
        G.add_event(lambda: G.ease_dollars(ab.money, True))
    if name in ("The Emperor", "The High Priestess"):
        n = min(cons.tarots or cons.planets, G.consumeables.config.card_limit - len(G.consumeables.cards))
        for _ in range(n):
            def emp() -> None:
                if G.consumeables.config.card_limit > len(G.consumeables.cards):
                    card = G.create_card("Tarot" if name == "The Emperor" else "Planet", G.consumeables, None, None, None, None,
                                         None, "emp" if name == "The Emperor" else "pri")
                    card.add_to_deck()
                    G.consumeables.emplace(card)
            G.add_event(emp)
    if name in ("Judgement", "The Soul"):
        def jud() -> None:
            card = G.create_card("Joker", G.jokers, name == "The Soul", None, None, None, None, "jud" if name == "Judgement" else "sou")
            card.add_to_deck()
            G.jokers.emplace(card)
        G.add_event(jud)
    if name == "Ankh":
        deletable = [v for v in G.jokers.cards if not v.ability.eternal]
        chosen = G._random_card_from(G.jokers.cards, "ankh_choice")

        def ankh1() -> None:
            for v in deletable:
                if v is not chosen:
                    v.start_dissolve()
        G.add_event(ankh1)

        def ankh2() -> None:
            card = G.copy_card(chosen, None, None, None, bool(chosen.edition and chosen.edition.negative))
            card.add_to_deck()
            if card.edition and card.edition.negative:
                card.set_edition(None, True)
            G.jokers.emplace(card)
        G.add_event(ankh2)
    if name == "Wraith":
        def wraith() -> None:
            card = G.create_card("Joker", G.jokers, None, 0.99, None, None, None, "wra")
            card.add_to_deck()
            G.jokers.emplace(card)
            if GAME.dollars != 0:
                G.ease_dollars(-GAME.dollars, True)
        G.add_event(wraith)
    if name in ("The Wheel of Fortune", "Ectoplasm", "Hex"):
        if name == "The Wheel of Fortune":
            temp_pool = list(self.eligible_strength_jokers)
        else:
            temp_pool = list(self.eligible_editionless_jokers)
        if name in ("Ectoplasm", "Hex") or G.rng.random("wheel_of_fortune") < GAME.probabilities.normal / ab.extra:
            seed_key = {"The Wheel of Fortune": "wheel_of_fortune", "Ectoplasm": "ectoplasm", "Hex": "hex"}[name]

            def apply() -> None:
                eligible = G._random_card_from(temp_pool, seed_key)
                if name == "Ectoplasm":
                    edition = T(negative=True)
                elif name == "Hex":
                    edition = T(polychrome=True)
                else:
                    edition = G.poll_edition("wheel_of_fortune", None, True, True)
                eligible.set_edition(edition, True)
                if name == "Hex":
                    for v in list(G.jokers.cards):
                        if v is not eligible and not v.ability.eternal:
                            v.start_dissolve()
                if name == "Ectoplasm":
                    GAME.ecto_minus = GAME.ecto_minus or 1
                    G.hand.change_size(-GAME.ecto_minus)
                    GAME.ecto_minus += 1
            G.add_event(apply)


def can_use_consumeable(self: "Card", any_state: bool = False, skip_check: bool = False) -> bool:
    G = self.G
    S = G.STATES
    if not skip_check and ((G.play is not None and G.play.cards) or (G.GAME.STOP_USE and G.GAME.STOP_USE > 0)):
        return False
    if (G.STATE not in (S.HAND_PLAYED, S.DRAW_TO_HAND, S.PLAY_TAROT)) or any_state:
        name = self.ability.name
        cons = self.ability.consumeable
        if name in ("The Hermit", "Temperance", "Black Hole") or cons.hand_type:
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
            return len(G.jokers.cards) < G.jokers.config.card_limit or self.area is G.jokers
        if G.STATE in (S.SELECTING_HAND, S.TAROT_PACK, S.SPECTRAL_PACK, S.PLANET_PACK):
            if cons.max_highlighted:
                mod_num = cons.mod_num if cons.mod_num is not None else min(5, cons.max_highlighted)
                if mod_num >= len(G.hand.highlighted) >= (cons.min_highlighted or 1):
                    return True
            if name in ("Familiar", "Grim", "Incantation", "Immolate", "Sigil", "Ouija") and len(G.hand.cards) > 1:
                return True
    return False
