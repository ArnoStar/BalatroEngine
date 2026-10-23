"""The player's actions.

Every action is checked the way the game's buttons check it (the button
exists and is enabled), applied between two frames like a click, and then
the game runs until it waits for the player again.  Card selections (play,
discard, consumable targets) are made first and the game is let settle
before the button is pressed, as a player selects cards before clicking.

All methods take 0-based indices into the on-screen (left to right) order of
the card areas.  ``legal_actions()`` lists what can be done right now
without changing anything.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterable, Iterator

if TYPE_CHECKING:
    from .card import Card
    from .cardarea import CardArea
    from .game import Game


class IllegalAction(ValueError):
    """The action is not possible in the current state."""


PACK_STATES = (9, 10, 15, 17, 18)


class ActionsMixin:
    # ------------------------------------------------------------- helpers
    def _area(self: "Game", name: str) -> "CardArea":
        area = getattr(self, name, None) if name in (
            "jokers", "consumeables", "hand", "shop_jokers", "shop_vouchers", "shop_booster", "pack_cards") else None
        if area is None or area.removed:
            raise IllegalAction(f"no card area {name!r} right now")
        return area

    def _require(self: "Game", cond: Any, msg: str) -> None:
        if not cond:
            raise IllegalAction(msg)

    def _select(self: "Game", idxs: Iterable[int] | None) -> None:
        """Select exactly these hand cards (forced cards stay selected), then
        let the game settle."""
        G = self
        idxs = list(idxs or [])
        hand = G.hand
        for i in idxs:
            G._require(isinstance(i, int) and 0 <= i < len(hand.cards), f"no card at hand[{i}]")
        G._require(len(set(idxs)) == len(idxs), "a card is selected twice")
        hand.unhighlight_all()
        for i in idxs:
            c = hand.cards[i]
            if not any(h is c for h in hand.highlighted):
                hand.add_to_highlighted(c, True)
        G.settle()

    @contextmanager
    def _hypothetical_selection(self: "Game", idxs: Iterable[int] | None) -> Iterator[None]:
        """Temporarily pretend these hand cards are selected (no side effects)."""
        hand = self.hand
        saved = hand.highlighted
        forced = [c for c in saved if c.ability.forced_selection]
        sel = list(forced)
        for i in idxs or []:
            c = hand.cards[i]
            if not any(h is c for h in sel) and len(sel) < hand.config.highlighted_limit:
                sel.append(c)
        hand.highlighted = sel
        try:
            yield
        finally:
            hand.highlighted = saved

    def preview_hand(self: "Game", idxs: Iterable[int]) -> dict[str, Any]:
        """What the game shows while these hand cards are selected, without
        changing anything: the poker hand, its level, chips and mult, the
        scoring cards (hand indices) and whether the boss blind forbids the
        hand.  Forced cards (Cerulean Bell) count as selected.  A face-down
        card in the selection hides the hand, as in the game ('????')."""
        G = self
        G._require(G.STATE == G.STATES.SELECTING_HAND and G.hand is not None, "not selecting a hand")
        idxs = list(idxs)
        hand = G.hand
        for i in idxs:
            G._require(isinstance(i, int) and 0 <= i < len(hand.cards), f"no card at hand[{i}]")
        G._require(len(set(idxs)) == len(idxs), "a card is selected twice")
        forced = {id(c) for c in hand.highlighted if c.ability.forced_selection}
        n = len(forced | {id(hand.cards[i]) for i in idxs})
        G._require(n <= hand.config.highlighted_limit, f"at most {hand.config.highlighted_limit} cards can be selected")
        blind = G.GAME.blind
        with G._hypothetical_selection(idxs):
            sel = list(hand.highlighted)
            saved = (blind.triggered, G.boss_throw_hand) if blind else None
            try:
                text, disp, poker_hands, scoring, _ = G.get_poker_hand_info(sel)
                not_allowed = bool(text != "NULL" and blind and blind.debuff_hand(sel, poker_hands, text, True))
            finally:
                if blind and saved:
                    blind.triggered, G.boss_throw_hand = saved
        out: dict[str, Any] = {"selected": [hand.cards.index(c) for c in sel], "hand": None, "level": None,
                               "chips": None, "mult": None, "scoring": [], "not_allowed": False, "hidden": False}
        if text == "NULL":
            return out
        if any(c.facing == "back" for c in sel):
            out["hidden"] = True
            return out
        h = G.GAME.hands[text]
        out.update(hand=text, display=disp, level=h.level, chips=h.chips, mult=h.mult,
                   scoring=[hand.cards.index(c) for c in scoring], not_allowed=not_allowed)
        return out

    def in_pack(self: "Game") -> bool:
        return self.STATE in PACK_STATES

    def ready(self: "Game") -> bool:
        """Whether the game is waiting for the player."""
        return self.settled() or self.is_game_over()

    def is_game_over(self: "Game") -> bool:
        return self.STATE == self.STATES.GAME_OVER

    # ------------------------------------------------------------ checks
    def can_select_blind(self: "Game") -> bool:
        return self.STATE == self.STATES.BLIND_SELECT and self.blind_select is not None and not self.blind_select.removed

    def can_skip_blind(self: "Game") -> bool:
        return (self.can_select_blind() and self.GAME.blind_on_deck in ("Small", "Big")
                and self.blind_select_tags.get(self.GAME.blind_on_deck) is not None)

    def can_play(self: "Game", idxs: list[int]) -> bool:
        G = self
        if G.STATE != G.STATES.SELECTING_HAND or not G.hand.cards:
            return False
        n = len({*idxs} | {G.hand.index(c) for c in G.hand.highlighted if c.ability.forced_selection})
        return 0 < n <= 5 and all(0 <= i < len(G.hand.cards) for i in idxs)

    def can_discard(self: "Game", idxs: list[int]) -> bool:
        G = self
        if G.STATE != G.STATES.SELECTING_HAND or G.GAME.current_round.discards_left <= 0:
            return False
        n = len({*idxs} | {G.hand.index(c) for c in G.hand.highlighted if c.ability.forced_selection})
        return 0 < n <= 5 and all(0 <= i < len(G.hand.cards) for i in idxs)

    def can_afford(self: "Game", card: "Card") -> bool:
        G = self
        if card.ability.set == "Voucher":
            return not (card.cost > G.GAME.dollars - G.GAME.bankrupt_at)
        return not (card.cost > 0 and card.cost > G.GAME.dollars - G.GAME.bankrupt_at)

    def in_shop(self: "Game") -> bool:
        return self.STATE == self.STATES.SHOP and self.shop is not None and not self.shop.removed

    def can_reroll_shop(self: "Game") -> bool:
        cr = self.GAME.current_round
        return self.in_shop() and not ((self.GAME.dollars - self.GAME.bankrupt_at) - cr.reroll_cost < 0 and cr.reroll_cost != 0)

    def can_use(self: "Game", index: int, targets: list[int] | None = None) -> bool:
        G = self
        if not (0 <= index < len(G.consumeables.cards)):
            return False
        c = G.consumeables.cards[index]
        if not c.ability.consumeable:
            return False
        if targets is not None and G.hand is not None:
            if not all(0 <= i < len(G.hand.cards) for i in targets):
                return False
            with G._hypothetical_selection(targets):
                return c.can_use_consumeable()
        return c.can_use_consumeable()

    def can_select_pack_card(self: "Game", card: "Card", targets: list[int] | None = None) -> bool:
        G = self
        if card.ability.consumeable:
            if targets is not None:
                if not all(0 <= i < len(G.hand.cards) for i in targets):
                    return False
                with G._hypothetical_selection(targets):
                    return card.can_use_consumeable()
            return card.can_use_consumeable()
        return (card.ability.set != "Joker" or bool(card.edition and card.edition.negative)
                or len(G.jokers.cards) < G.jokers.config.card_limit)

    def can_skip_pack(self: "Game") -> bool:
        G = self
        S = G.STATES
        return (G.in_pack() and G.pack_cards is not None and not G.pack_cards.removed and bool(G.pack_cards.cards)
                and (G.STATE in (S.PLANET_PACK, S.STANDARD_PACK, S.BUFFOON_PACK)
                     or (G.hand is not None and (bool(G.hand.cards) or G.hand.config.card_limit <= 0))))

    # ------------------------------------------------------------ blinds
    def act_select_blind(self: "Game") -> None:
        self._require(self.can_select_blind(), "not at the blind select screen")
        self.select_blind()
        self.settle()

    def act_skip_blind(self: "Game") -> None:
        self._require(self.can_skip_blind(), "this blind can't be skipped")
        self.skip_blind()
        self.settle()

    def act_reroll_boss(self: "Game") -> None:
        self._require(self.can_select_blind(), "not at the blind select screen")
        self._require(self.can_reroll_boss(), "can't reroll the boss")
        self.reroll_boss()
        self.settle()

    # -------------------------------------------------------------- hand
    def act_play(self: "Game", idxs: list[int]) -> None:
        """Play the hand cards at these indices."""
        G = self
        G._require(G.STATE == G.STATES.SELECTING_HAND, "not selecting a hand")
        G._require(G.can_play(list(idxs)), "select 1 to 5 hand cards to play")
        G._select(idxs)
        G._require(0 < len(G.hand.highlighted) <= 5, "select 1 to 5 cards to play")
        G.play_cards_from_highlighted()
        G.settle()

    def act_discard(self: "Game", idxs: list[int]) -> None:
        G = self
        G._require(G.STATE == G.STATES.SELECTING_HAND, "not selecting a hand")
        G._require(G.GAME.current_round.discards_left > 0, "no discards left")
        G._require(G.can_discard(list(idxs)), "select 1 to 5 hand cards to discard")
        G._select(idxs)
        G._require(len(G.hand.highlighted) > 0, "select cards to discard")
        G.discard_cards_from_highlighted()
        G.settle()

    def act_sort(self: "Game", mode: str = "rank") -> None:
        """The hand's 'Rank' / 'Suit' sort buttons (the choice sticks)."""
        G = self
        G._require(G.hand is not None, "no hand")
        if mode == "suit":
            G.sort_hand_suit()
        else:
            G.sort_hand_value()
        G.settle()

    def act_move(self: "Game", area: str, frm: int, to: int) -> None:
        """Drag a card to another position in its area (jokers, hand, consumables)."""
        G = self
        a = G._area(area)
        G._require(area in ("jokers", "hand", "consumeables"), "cards can only be moved in jokers/hand/consumeables")
        G._require(0 <= frm < len(a.cards) and 0 <= to < len(a.cards), "bad move")
        c = a.cards.pop(frm)
        a.cards.insert(to, c)
        a.align_cards()
        G.settle()

    # ------------------------------------------------------------ rounds
    def act_cash_out(self: "Game") -> None:
        G = self
        G._require(G.STATE == G.STATES.ROUND_EVAL and G.round_eval is not None and not G.round_eval.removed,
                   "not at the round evaluation")
        G.cash_out()
        G.settle()

    # -------------------------------------------------------------- shop
    def act_buy(self: "Game", area: str, index: int, use: bool = False) -> None:
        """Buy a shop card (``use=True``: buy and use a consumable at once),
        redeem the voucher (area 'shop_vouchers') or open a pack ('shop_booster')."""
        G = self
        G._require(G.in_shop(), "not in the shop")
        a = G._area(area)
        G._require(0 <= index < len(a.cards), f"nothing at {area}[{index}]")
        card = a.cards[index]
        G._require(G.can_afford(card), "can't afford it")
        if area == "shop_jokers":
            if use:
                G._require(bool(card.ability.consumeable) and card.can_use_consumeable(), "can't use it now")
            G.buy_from_shop(card, use)
        elif area in ("shop_vouchers", "shop_booster"):
            G.use_card(card)
        else:
            raise IllegalAction(f"can't buy from {area}")
        G.settle()

    def act_reroll(self: "Game") -> None:
        G = self
        G._require(G.in_shop(), "not in the shop")
        G._require(G.can_reroll_shop(), "can't afford the reroll")
        G.reroll_shop()
        G.settle()

    def act_end_shop(self: "Game") -> None:
        G = self
        G._require(G.in_shop(), "not in the shop")
        G.toggle_shop()
        G.settle()

    # ------------------------------------------------- jokers / consumables
    def act_use(self: "Game", index: int, targets: list[int] | None = None) -> None:
        """Use consumable ``index``; ``targets``: the hand cards to select first."""
        G = self
        G._require(0 <= index < len(G.consumeables.cards), "no such consumable")
        card = G.consumeables.cards[index]
        G._require(bool(card.ability.consumeable), "that card can't be used")
        if targets is not None and G.hand is not None:
            G._require(G.can_use(index, targets), "can't use this card now")
            G._select(targets)
        G._require(card.can_use_consumeable(), "can't use this card now")
        G.use_card(card)
        G.settle()

    def act_sell(self: "Game", area: str, index: int) -> None:
        G = self
        a = G._area(area)
        G._require(area in ("jokers", "consumeables") and 0 <= index < len(a.cards), "nothing to sell there")
        card = a.cards[index]
        G._require(card.can_sell_card(), "can't sell this card")
        G.sell_card(card)
        G.settle()

    # ------------------------------------------------------------- packs
    def act_pick(self: "Game", index: int, targets: list[int] | None = None) -> None:
        """Take (or use) pack card ``index``; ``targets``: hand cards to select first."""
        G = self
        G._require(G.in_pack() and G.pack_cards is not None and not G.pack_cards.removed, "no pack open")
        G._require(0 <= index < len(G.pack_cards.cards), "no such pack card")
        card = G.pack_cards.cards[index]
        if targets is not None and card.ability.consumeable:
            G._require(G.can_select_pack_card(card, targets), "can't take this card")
            G._select(targets)
        G._require(G.can_select_pack_card(card), "can't take this card")
        G.use_card(card)
        G.settle()

    def act_skip_pack(self: "Game") -> None:
        G = self
        G._require(G.can_skip_pack(), "can't skip the pack now")
        G.skip_booster()
        G.settle()

    # ----------------------------------------------------- legal actions
    def legal_actions(self: "Game") -> list[dict]:
        """What the player can do now, as command dicts for :meth:`do`.

        Card choices are left open: ``play``/``discard`` list the hand size as
        ``"n"`` and accept any 1-5 card indices; consumables that need targets
        list ``"min"``/``"max"`` targets and whether they can be used with
        ``targets=[]`` (already)."""
        G = self
        S = G.STATES
        out: list[dict] = []
        if G.is_game_over():
            return out
        st = G.STATE
        cr = G.GAME.current_round
        if st == S.BLIND_SELECT and G.can_select_blind():
            out.append({"cmd": "select_blind"})
            if G.can_skip_blind():
                out.append({"cmd": "skip_blind"})
            if G.can_reroll_boss():
                out.append({"cmd": "reroll_boss"})
        elif st == S.SELECTING_HAND and G.hand.cards:
            out.append({"cmd": "play", "n": len(G.hand.cards)})
            if cr.discards_left > 0:
                out.append({"cmd": "discard", "n": len(G.hand.cards)})
            out.append({"cmd": "sort", "mode": "rank"})
            out.append({"cmd": "sort", "mode": "suit"})
        elif st == S.ROUND_EVAL and G.round_eval is not None and not G.round_eval.removed:
            out.append({"cmd": "cash_out"})
        elif G.in_shop():
            for i, c in enumerate(G.shop_jokers.cards):
                if G.can_afford(c):
                    if G.check_space(c):
                        out.append({"cmd": "buy", "area": "shop_jokers", "index": i})
                    if c.ability.consumeable and c.can_use_consumeable():
                        out.append({"cmd": "buy", "area": "shop_jokers", "index": i, "use": True})
            for area in ("shop_vouchers", "shop_booster"):
                for i, c in enumerate(getattr(G, area).cards):
                    if G.can_afford(c):
                        out.append({"cmd": "buy", "area": area, "index": i})
            if G.can_reroll_shop():
                out.append({"cmd": "reroll"})
            out.append({"cmd": "end_shop"})
        elif G.in_pack() and G.pack_cards is not None and not G.pack_cards.removed and G.pack_cards.cards:
            for i, c in enumerate(G.pack_cards.cards):
                d = {"cmd": "pick", "index": i}
                if c.ability.consumeable and c.ability.consumeable.max_highlighted:
                    d.update(min=c.ability.consumeable.min_highlighted or 1, max=c.ability.consumeable.mod_num)
                    out.append(d)
                elif G.can_select_pack_card(c):
                    out.append(d)
            if G.can_skip_pack():
                out.append({"cmd": "skip_pack"})
        # consumables and selling work in most states
        if G.consumeables is not None:
            for i, c in enumerate(G.consumeables.cards):
                cons = c.ability.consumeable
                if not cons:
                    continue
                if cons.max_highlighted:
                    blocked = (G.play is not None and G.play.cards) or G.CONTROLLER.locked or G.GAME.STOP_USE > 0
                    if st in (S.SELECTING_HAND, S.TAROT_PACK, S.SPECTRAL_PACK, S.PLANET_PACK) and not blocked:
                        out.append({"cmd": "use", "index": i, "min": cons.min_highlighted or 1, "max": cons.mod_num})
                elif c.can_use_consumeable():
                    out.append({"cmd": "use", "index": i})
            for area in ("jokers", "consumeables"):
                for i, c in enumerate(getattr(G, area).cards):
                    if c.can_sell_card():
                        out.append({"cmd": "sell", "area": area, "index": i})
        return out

    def check_space(self: "Game", card: "Card") -> bool:
        """G.FUNCS.check_for_buy_space without its 'no space' alert."""
        G = self
        ab = card.ability
        neg = 1 if card.edition and card.edition.negative else 0
        return not (ab.set != "Voucher" and ab.set != "Enhanced" and ab.set != "Default"
                    and not (ab.set == "Joker" and len(G.jokers.cards) < G.jokers.config.card_limit + neg)
                    and not (ab.consumeable and len(G.consumeables.cards) < G.consumeables.config.card_limit + neg))

    # ----------------------------------------------------------- dispatch
    def do(self: "Game", cmd: dict) -> None:
        """Apply a command dict, e.g. ``{"cmd": "play", "cards": [0, 1]}``."""
        c = cmd["cmd"]
        if c == "select_blind":
            self.act_select_blind()
        elif c == "skip_blind":
            self.act_skip_blind()
        elif c == "reroll_boss":
            self.act_reroll_boss()
        elif c == "play":
            self.act_play(cmd["cards"])
        elif c == "discard":
            self.act_discard(cmd["cards"])
        elif c == "cash_out":
            self.act_cash_out()
        elif c == "reroll":
            self.act_reroll()
        elif c == "buy":
            self.act_buy(cmd["area"], cmd["index"], bool(cmd.get("use")))
        elif c == "end_shop":
            self.act_end_shop()
        elif c == "use":
            self.act_use(cmd["index"], cmd.get("targets"))
        elif c == "sell":
            self.act_sell(cmd["area"], cmd["index"])
        elif c == "pick":
            self.act_pick(cmd["index"], cmd.get("targets"))
        elif c == "skip_pack":
            self.act_skip_pack()
        elif c == "move":
            self.act_move(cmd["area"], cmd["from"], cmd["to"])
        elif c == "sort":
            self.act_sort(cmd.get("mode", "rank"))
        elif c == "state":
            pass
        elif c == "cheat":  # test helpers (no RNG involved)
            if cmd.get("dollars") is not None:
                self.GAME.dollars = cmd["dollars"]
            if cmd.get("ante") is not None:
                self.GAME.round_resets.ante = cmd["ante"]
                self.GAME.round_resets.blind_ante = cmd["ante"]
            if cmd.get("boss") is not None:
                self.GAME.round_resets.blind_choices.Boss = cmd["boss"]
            if cmd.get("win") and self.STATE == self.STATES.SELECTING_HAND:
                # beat the blind now (as if a hand had scored enough)
                self.GAME.chips = self.GAME.blind.chips
                self.STATE = self.STATES.NEW_ROUND
                self.STATE_COMPLETE = False
            self.settle()
        elif c == "add_joker":
            self.add_joker(cmd["key"], cmd.get("edition"))
            self.settle()
        elif c == "add_tag":  # (an Orbital Tag gets a hand the way Double Tag copies do)
            from .tag import Tag
            if cmd["key"] == "tag_orbital":
                self.orbital_hand = cmd.get("orbital_hand") or "High Card"
            self.add_tag(Tag(self, cmd["key"]))
            self.orbital_hand = None
            self.settle()
        elif c == "add_voucher":  # redeem for free, through a voucher card
            from .card import Card
            self.GAME.used_vouchers[cmd["key"]] = True
            card = Card(self, None, self.P_CENTERS[cmd["key"]])
            card.apply_to_run()
            card.remove()
            self.settle()
        else:
            raise IllegalAction(f"unknown command {c!r}")
