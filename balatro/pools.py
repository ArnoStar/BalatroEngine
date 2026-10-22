"""Card / tag / voucher / boss generation (common_events.lua + create_card_for_shop)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .card import Card
from .lua import T
from .rng import lua_tostring

if TYPE_CHECKING:
    from .cardarea import CardArea
    from .game import Game


UNAVAILABLE = "UNAVAILABLE"


class PoolsMixin:
    # ------------------------------------------------------------------ pools
    def get_current_pool(self: "Game", _type: str, _rarity: float | None = None, _legendary: Any = None,
                         _append: str | None = None) -> tuple[list[str], str]:
        G = self
        GAME = G.GAME
        ante = GAME.round_resets.ante
        if _type == "Joker":
            rarity = _rarity if _rarity is not None else G.rng.random("rarity" + lua_tostring(ante) + (_append or ""))
            rarity = 4 if _legendary else (3 if rarity > 0.95 else (2 if rarity > 0.7 else 1))
            starting_pool = G.P_JOKER_RARITY_POOLS[rarity - 1]
            pool_key = "Joker" + str(rarity) + ((_append or "") if not _legendary else "")
        else:
            starting_pool = G.P_CENTER_POOLS[_type]
            pool_key = _type + (_append or "")

        pool: list[str] = []
        pool_size = 0
        showman = None
        for v in starting_pool:
            add = None
            if _type == "Enhanced":
                add = True
            elif _type == "Demo":
                add = True
            elif _type == "Tag":
                if (not v.requires or G.is_discovered(v.requires)) and (not v.min_ante or v.min_ante <= ante):
                    add = True
            else:
                if showman is None:
                    showman = bool(G.find_joker("Showman"))
                if not (GAME.used_jokers.get(v.key) and not showman) and (G.is_unlocked(v) or v.rarity == 4):
                    if v.set == "Voucher":
                        if not GAME.used_vouchers.get(v.key):
                            include = True
                            if v.requires:
                                for vv in v.requires:
                                    if not GAME.used_vouchers.get(vv):
                                        include = False
                            if G.shop_vouchers is not None:
                                for vv in G.shop_vouchers.cards:
                                    if vv.config.center.key == v.key:
                                        include = False
                            if include:
                                add = True
                    elif v.set == "Planet":
                        if not v.config.softlock or GAME.hands[v.config.hand_type].played > 0:
                            add = True
                    elif v.enhancement_gate:
                        add = None
                        for vv in G.playing_cards:
                            if vv.config.center.key == v.enhancement_gate:
                                add = True
                    else:
                        add = True
                    if v.name in ("Black Hole", "The Soul"):
                        add = False
            if v.no_pool_flag and GAME.pool_flags.get(v.no_pool_flag):
                add = None
            if v.yes_pool_flag and not GAME.pool_flags.get(v.yes_pool_flag):
                add = None
            if add and not GAME.banned_keys.get(v.key):
                pool.append(v.key)
                pool_size += 1
            else:
                pool.append(UNAVAILABLE)

        if pool_size == 0:
            if _type in ("Tarot", "Tarot_Planet"):
                pool = ["c_strength"]
            elif _type == "Planet":
                pool = ["c_pluto"]
            elif _type == "Spectral":
                pool = ["c_incantation"]
            elif _type == "Voucher":
                pool = ["v_blank"]
            elif _type == "Tag":
                pool = ["tag_handy"]
            else:
                pool = ["j_joker"]
        return pool, pool_key + (lua_tostring(ante) if not _legendary else "")

    def pick_from_pool(self: "Game", pool: list[str], pool_key: str) -> str:
        """pseudorandom_element + the '_resample' loop used everywhere."""
        rng = self.rng
        center = pool[rng.element_index(len(pool), rng.pseudoseed(pool_key))]
        it = 1
        while center == UNAVAILABLE:
            it += 1
            center = pool[rng.element_index(len(pool), rng.pseudoseed(pool_key + "_resample" + str(it)))]
        return center

    def get_next_voucher_key(self: "Game", _from_tag: bool = False) -> str:
        pool, pool_key = self.get_current_pool("Voucher")
        if _from_tag:
            pool_key = "Voucher_fromtag"
        return self.pick_from_pool(pool, pool_key)

    def get_next_tag_key(self: "Game", append: str | None = None) -> str:
        if self.FORCE_TAG:
            return self.FORCE_TAG
        pool, pool_key = self.get_current_pool("Tag", None, None, append)
        return self.pick_from_pool(pool, pool_key)

    def poll_edition(self: "Game", _key: str | None = None, _mod: float | None = None, _no_neg: Any = None,
                     _guaranteed: Any = None) -> T | None:
        G = self
        _mod = _mod if _mod is not None else 1
        poll = G.rng.random(_key or "edition_generic")
        if _guaranteed:
            if poll > 1 - 0.003 * 25 and not _no_neg:
                return T(negative=True)
            elif poll > 1 - 0.006 * 25:
                return T(polychrome=True)
            elif poll > 1 - 0.02 * 25:
                return T(holo=True)
            elif poll > 1 - 0.04 * 25:
                return T(foil=True)
        else:
            rate = G.GAME.edition_rate
            if poll > 1 - 0.003 * _mod and not _no_neg:
                return T(negative=True)
            elif poll > 1 - 0.006 * rate * _mod:
                return T(polychrome=True)
            elif poll > 1 - 0.02 * rate * _mod:
                return T(holo=True)
            elif poll > 1 - 0.04 * rate * _mod:
                return T(foil=True)
        return None

    def random_p_card(self: "Game", seed_key: str) -> T:
        """pseudorandom_element(G.P_CARDS, pseudoseed(key)) -> P_CARDS entry."""
        keys = self.data.P_CARDS_SORTED_KEYS
        return self.P_CARDS[keys[self.rng.element_index(len(keys), self.rng.pseudoseed(seed_key))]]

    # ------------------------------------------------------------- create_card
    def create_card(self: "Game", _type: str, area: "CardArea | None", legendary: Any = None,
                    _rarity: float | None = None, skip_materialize: Any = None, soulable: Any = None,
                    forced_key: Any = None, key_append: str | None = None) -> Card:
        G = self
        GAME = G.GAME
        area = area if area is not None else G.jokers
        ante = lua_tostring(GAME.round_resets.ante)
        if not forced_key and soulable and not GAME.banned_keys.get("c_soul"):
            showman = bool(G.find_joker("Showman"))
            if _type in ("Tarot", "Spectral", "Tarot_Planet") and not (GAME.used_jokers.get("c_soul") and not showman):
                if G.rng.random("soul_" + _type + ante) > 0.997:
                    forced_key = "c_soul"
            if _type in ("Planet", "Spectral") and not (GAME.used_jokers.get("c_black_hole") and not showman):
                if G.rng.random("soul_" + _type + ante) > 0.997:
                    forced_key = "c_black_hole"
        if _type == "Base":
            forced_key = "c_base"

        if forced_key and not GAME.banned_keys.get(forced_key):
            center = G.P_CENTERS[forced_key]
            _type = center.set if center.set != "Default" else _type
        else:
            pool, pool_key = G.get_current_pool(_type, _rarity, legendary, key_append)
            center = G.P_CENTERS[G.pick_from_pool(pool, pool_key)]

        front = None
        if _type in ("Base", "Enhanced"):
            front = G.random_p_card("front" + (key_append or "") + ante)

        card = Card(G, front, center, {
            "bypass_discovery_center": area in (G.shop_jokers, G.pack_cards, G.shop_vouchers, G.jokers, G.consumeables),
            "discover": area is G.jokers or area is G.consumeables,
        })

        if _type == "Joker":
            if GAME.modifiers.all_eternal:
                card.set_eternal(True)
            if area is G.shop_jokers or area is G.pack_cards:
                ep_poll = G.rng.random(("packetper" if area is G.pack_cards else "etperpoll") + ante)
                if GAME.modifiers.enable_eternals_in_shop and ep_poll > 0.7:
                    card.set_eternal(True)
                elif GAME.modifiers.enable_perishables_in_shop and 0.4 < ep_poll <= 0.7:
                    card.set_perishable(True)
                if GAME.modifiers.enable_rentals_in_shop and G.rng.random(
                        ("packssjr" if area is G.pack_cards else "ssjr") + ante) > 0.7:
                    card.set_rental(True)
            edition = G.poll_edition("edi" + (key_append or "") + ante)
            card.set_edition(edition)
        return card

    def create_playing_card(self: "Game", card_init: T | None, area: "CardArea | None",
                            skip_materialize: Any = None, silent: Any = None, colours: Any = None) -> Card:
        G = self
        card_init = card_init or T()
        if card_init.front is None:
            card_init.front = G.random_p_card("front")
        if card_init.center is None:
            card_init.center = G.P_CENTERS["c_base"]
        G.playing_card = (G.playing_card + 1) if G.playing_card else 1
        _area = area if area is not None else G.hand
        card = Card(G, card_init.front, card_init.center, {"playing_card": G.playing_card})
        G.playing_cards.append(card)
        card.playing_card = G.playing_card
        if area is not None:
            area.emplace(card)
        del _area
        return card

    def copy_card(self: "Game", other: Card, new_card: Card | None = None, card_scale: Any = None,
                  playing_card: int | None = None, strip_edition: Any = None) -> Card:
        from .lua import copy_table
        G = self
        if new_card is None:
            new_card = Card(G, None, G.P_CENTERS["c_base"], {"playing_card": playing_card})
        new_card.set_ability(other.config.center)
        new_card.ability.type = other.ability.type
        new_card.set_base(other.config.card)
        for k, v in other.ability.items():
            new_card.ability[k] = copy_table(v)
        if not strip_edition:
            new_card.set_edition(other.edition or T(), None, True)
        new_card.set_seal(other.seal, True)
        if other.params:
            new_card.params = other.params
            new_card.params["playing_card"] = playing_card
        new_card.debuff = other.debuff
        new_card.pinned = other.pinned
        return new_card

    # ----------------------------------------------------------------- packs
    def get_pack(self: "Game", _key: str | None = None, _type: str | None = None) -> T:
        G = self
        GAME = G.GAME
        if not GAME.first_shop_buffoon and not GAME.banned_keys.get("p_buffoon_normal_1"):
            GAME.first_shop_buffoon = True
            # math.random(1, 2) on the *global* LuaJIT state only picks the
            # artwork; both packs are identical
            return G.P_CENTERS["p_buffoon_normal_1"]
        cume = 0.0
        boosters = G.P_CENTER_POOLS["Booster"]
        for v in boosters:
            if (not _type or _type == v.kind) and not GAME.banned_keys.get(v.key):
                cume += v.weight if v.weight is not None else 1
        poll = G.rng.random(G.rng.pseudoseed((_key or "pack_generic") + lua_tostring(GAME.round_resets.ante))) * cume
        it = 0.0
        center = None
        for v in boosters:
            if not GAME.banned_keys.get(v.key):
                w = v.weight if v.weight is not None else 1
                if not _type or _type == v.kind:
                    it += w
                if it >= poll and it - w <= poll:
                    center = v
                    break
        return center

    # ------------------------------------------------------------------ boss
    def get_new_boss(self: "Game") -> str:
        G = self
        GAME = G.GAME
        ante = GAME.round_resets.ante
        presc = GAME.perscribed_bosses
        if presc and presc.get(ante):
            ret = presc.pop(ante)
            GAME.bosses_used[ret] = GAME.bosses_used[ret] + 1
            return ret
        if G.FORCE_BOSS:
            return G.FORCE_BOSS
        eligible: dict[str, Any] = {}
        win_ante = GAME.win_ante
        for k, v in G.P_BLINDS.items():
            b = v.boss
            if not b:
                continue
            if not b.showdown and (b.min <= max(1, ante) and ((max(1, ante) % win_ante) != 0 or ante < 2)):
                eligible[k] = True
            elif b.showdown and (ante % win_ante) == 0 and ante >= 2:
                eligible[k] = True
        for k in GAME.banned_keys:
            eligible.pop(k, None)
        min_use = 100
        for k, v in GAME.bosses_used.items():
            if k in eligible:
                eligible[k] = v
                if v <= min_use:
                    min_use = v
        for k in list(eligible):
            if eligible[k] is not True and eligible[k] > min_use:
                del eligible[k]
        keys = sorted(eligible)
        boss = keys[G.rng.element_index(len(keys), G.rng.pseudoseed("boss"))]
        GAME.bosses_used[boss] = GAME.bosses_used[boss] + 1
        return boss

    # -------------------------------------------------- per-round random cards
    def _random_card_from(self: "Game", cards: list[Card], seed_key: str) -> Card:
        ordered = sorted(cards, key=lambda c: c.sort_id)
        return ordered[self.rng.element_index(len(ordered), self.rng.pseudoseed(seed_key))]

    def reset_idol_card(self: "Game") -> None:
        G = self
        cr = G.GAME.current_round
        cr.idol_card.rank = "Ace"
        cr.idol_card.suit = "Spades"
        valid = [v for v in G.playing_cards if v.ability.effect != "Stone Card"]
        if valid:
            c = G._random_card_from(valid, "idol" + lua_tostring(G.GAME.round_resets.ante))
            cr.idol_card.rank = c.base.value
            cr.idol_card.suit = c.base.suit
            cr.idol_card.id = c.base.id

    def reset_mail_rank(self: "Game") -> None:
        G = self
        cr = G.GAME.current_round
        cr.mail_card.rank = "Ace"
        valid = [v for v in G.playing_cards if v.ability.effect != "Stone Card"]
        if valid:
            c = G._random_card_from(valid, "mail" + lua_tostring(G.GAME.round_resets.ante))
            cr.mail_card.rank = c.base.value
            cr.mail_card.id = c.base.id

    def reset_ancient_card(self: "Game") -> None:
        G = self
        cr = G.GAME.current_round
        suits = [s for s in ("Spades", "Hearts", "Clubs", "Diamonds") if s != cr.ancient_card.suit]
        cr.ancient_card.suit = G.rng.element(suits, G.rng.pseudoseed("anc" + lua_tostring(G.GAME.round_resets.ante)))

    def reset_castle_card(self: "Game") -> None:
        G = self
        cr = G.GAME.current_round
        cr.castle_card.suit = "Spades"
        valid = [v for v in G.playing_cards if v.ability.effect != "Stone Card"]
        if valid:
            c = G._random_card_from(valid, "cas" + lua_tostring(G.GAME.round_resets.ante))
            cr.castle_card.suit = c.base.suit

    def reset_blinds(self: "Game") -> None:
        G = self
        rr = G.GAME.round_resets
        if rr.blind_states is None:
            rr.blind_states = T(Small="Select", Big="Upcoming", Boss="Upcoming")
        if rr.blind_states.Boss == "Defeated":
            rr.blind_states.Small = "Upcoming"
            rr.blind_states.Big = "Upcoming"
            rr.blind_states.Boss = "Upcoming"
            G.GAME.blind_on_deck = "Small"
            rr.blind_choices.Boss = G.get_new_boss()
            rr.boss_rerolled = False

    # ------------------------------------------------------------- shop cards
    def create_card_for_shop(self: "Game", area: "CardArea") -> Card:
        G = self
        GAME = G.GAME
        for tag in list(GAME.tags):
            forced = tag.apply_to_run(T(type="store_joker_create", area=area))
            if forced:
                for t2 in list(GAME.tags):
                    if t2.apply_to_run(T(type="store_joker_modify", card=forced)):
                        break
                return forced
        GAME.spectral_rate = GAME.spectral_rate or 0
        total_rate = GAME.joker_rate + GAME.tarot_rate + GAME.planet_rate + GAME.playing_card_rate + GAME.spectral_rate
        polled_rate = G.rng.random(G.rng.pseudoseed("cdt" + lua_tostring(GAME.round_resets.ante))) * total_rate
        check_rate = 0
        illusion = GAME.used_vouchers.get("v_illusion")
        base_type = "Base"
        if illusion and G.rng.random(G.rng.pseudoseed("illusion")) > 0.6:
            base_type = "Enhanced"
        for typ, val in (("Joker", GAME.joker_rate), ("Tarot", GAME.tarot_rate), ("Planet", GAME.planet_rate),
                         (base_type, GAME.playing_card_rate), ("Spectral", GAME.spectral_rate)):
            if check_rate < polled_rate <= check_rate + val:
                card = G.create_card(typ, area, None, None, None, None, None, "sho")

                def modify(card: Card = card) -> None:
                    for t in list(GAME.tags):
                        if t.apply_to_run(T(type="store_joker_modify", card=card)):
                            break
                G.add_event(modify)
                if typ in ("Base", "Enhanced") and illusion and G.rng.random(G.rng.pseudoseed("illusion")) > 0.8:
                    edition_poll = G.rng.random(G.rng.pseudoseed("illusion"))
                    if edition_poll > 1 - 0.15:
                        edition = T(polychrome=True)
                    elif edition_poll > 0.5:
                        edition = T(holo=True)
                    else:
                        edition = T(foil=True)
                    card.set_edition(edition)
                return card
            check_rate += val
        raise RuntimeError("create_card_for_shop: no card type selected")
