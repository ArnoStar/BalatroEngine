"""High-level player actions with the same legality checks as the game's UI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable


if TYPE_CHECKING:
    from .cardarea import CardArea
    from .game import Game


class IllegalAction(ValueError):
    pass


class ActionsMixin:
    # ----------------------------------------------------------- helpers
    def _area(self: "Game", name: str) -> "CardArea":
        area = getattr(self, name, None)
        if area is None:
            raise IllegalAction(f"no area {name!r}")
        return area

    def _highlight(self: "Game", area: "CardArea", idxs: Iterable[int] | None) -> None:
        area.unhighlight_all()
        for i in idxs or ():
            if not 0 <= i < len(area.cards):
                raise IllegalAction(f"no card at {area.name}[{i}]")
            area.add_to_highlighted(area.cards[i], True)

    def _require(self: "Game", cond: bool, msg: str) -> None:
        if not cond:
            raise IllegalAction(msg)

    # ----------------------------------------------------------- blinds
    def act_select_blind(self: "Game") -> None:
        self._require(self.STATE == self.STATES.BLIND_SELECT and self.blind_select is not None, "not at blind select")
        self.select_blind()

    def act_skip_blind(self: "Game") -> None:
        self._require(self.STATE == self.STATES.BLIND_SELECT and self.blind_select is not None, "not at blind select")
        self._require(self.GAME.blind_on_deck in ("Small", "Big"), "the boss blind can't be skipped")
        self.skip_blind()

    def act_reroll_boss(self: "Game") -> None:
        self._require(self.STATE == self.STATES.BLIND_SELECT and self.blind_select is not None, "not at blind select")
        self._require(self.can_reroll_boss(), "can't reroll the boss")
        self.reroll_boss()

    # ------------------------------------------------------------- hand
    def act_play(self: "Game", idxs: list[int]) -> None:
        self._require(self.STATE == self.STATES.SELECTING_HAND, "not selecting a hand")
        self._highlight(self.hand, idxs)
        n = len(self.hand.highlighted)
        self._require(0 < n <= 5, "select 1-5 cards to play")
        self.play_cards_from_highlighted()
        self.advance()

    def act_discard(self: "Game", idxs: list[int]) -> None:
        self._require(self.STATE == self.STATES.SELECTING_HAND, "not selecting a hand")
        self._require(self.GAME.current_round.discards_left > 0, "no discards left")
        self._highlight(self.hand, idxs)
        self._require(len(self.hand.highlighted) > 0, "select cards to discard")
        self.discard_cards_from_highlighted()
        self.advance()

    def act_cash_out(self: "Game") -> None:
        self._require(self.STATE == self.STATES.ROUND_EVAL and self.round_eval is not None, "not at round evaluation")
        self.cash_out()

    # ------------------------------------------------------------- shop
    def act_reroll(self: "Game") -> None:
        self._require(self.STATE == self.STATES.SHOP and self.shop is not None, "not in the shop")
        cr = self.GAME.current_round
        self._require(not ((self.GAME.dollars - self.GAME.bankrupt_at) - cr.reroll_cost < 0 and cr.reroll_cost != 0),
                      "can't afford the reroll")
        self.reroll_shop()

    def act_buy(self: "Game", area: str, index: int, use: bool = False) -> None:
        self._require(self.STATE == self.STATES.SHOP and self.shop is not None, "not in the shop")
        a = self._area(area)
        self._require(0 <= index < len(a.cards), f"nothing at {area}[{index}]")
        card = a.cards[index]
        self._require(self.can_afford(card), "can't afford it")
        if area == "shop_jokers":
            if use:
                self._require(bool(card.ability.consumeable) and card.can_use_consumeable(), "can't use it now")
            else:
                self._require(self.check_for_buy_space(self, card), "no room")
            self.buy_from_shop(card, use)
        elif area in ("shop_vouchers", "shop_booster"):
            self.use_card(card)
            self.advance()
        else:
            raise IllegalAction(f"can't buy from {area}")

    def act_end_shop(self: "Game") -> None:
        self._require(self.STATE == self.STATES.SHOP and self.shop is not None, "not in the shop")
        self.toggle_shop()

    # -------------------------------------------------- jokers / consumables
    def act_use(self: "Game", index: int, targets: list[int] | None = None) -> None:
        self._require(0 <= index < len(self.consumeables.cards), "no such consumable")
        card = self.consumeables.cards[index]
        if targets is not None:
            self._highlight(self.hand, targets)
        self._require(card.can_use_consumeable(), "can't use this card now")
        self.use_card(card)
        self.advance()

    def act_sell(self: "Game", area: str, index: int) -> None:
        a = self._area(area)
        self._require(area in ("jokers", "consumeables") and 0 <= index < len(a.cards), "nothing to sell there")
        card = a.cards[index]
        self._require(card.can_sell_card(), "can't sell this card")
        self.sell_card(card)

    def act_sort(self: "Game", mode: str = "rank") -> None:
        """The 'Rank'/'Suit' sort buttons (the choice sticks for later draws)."""
        self.hand.sort("suit desc" if mode == "suit" else "desc")
        self.advance()

    def act_move(self: "Game", area: str, frm: int, to: int) -> None:
        a = self._area(area)
        self._require(0 <= frm < len(a.cards) and 0 <= to < len(a.cards), "bad move")
        c = a.cards.pop(frm)
        a.cards.insert(to, c)
        self.update_cards()

    # ------------------------------------------------------------- packs
    def act_pick(self: "Game", index: int, targets: list[int] | None = None) -> None:
        self._require(self.in_pack() and self.pack_cards is not None, "no pack open")
        self._require(0 <= index < len(self.pack_cards.cards), "no such pack card")
        card = self.pack_cards.cards[index]
        if targets is not None:
            self._highlight(self.hand, targets)
        self._require(self.can_select_pack_card(card), "can't take this card")
        self.use_card(card)
        self.advance()

    def act_skip_pack(self: "Game") -> None:
        self._require(self.in_pack() and self.pack_cards is not None and bool(self.pack_cards.cards), "no pack open")
        S = self.STATES
        self._require(self.STATE in (S.PLANET_PACK, S.STANDARD_PACK, S.BUFFOON_PACK) or bool(self.hand.cards)
                      or self.hand.config.card_limit <= 0, "can't skip yet")
        self.skip_booster()

    # ----------------------------------------------------------- dispatch
    def do(self: "Game", cmd: dict) -> None:
        """Apply an oracle-style command dict (see tools/lua/oracle.lua)."""
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
        elif c == "cheat":  # test helpers, no RNG involved
            if cmd.get("dollars") is not None:
                self.GAME.dollars = cmd["dollars"]
            if cmd.get("ante") is not None:
                self.GAME.round_resets.ante = cmd["ante"]
                self.GAME.round_resets.blind_ante = cmd["ante"]
            if cmd.get("boss") is not None:
                self.GAME.round_resets.blind_choices.Boss = cmd["boss"]
            self.advance()
        elif c == "add_joker":
            self.add_joker(cmd["key"], cmd.get("edition"))
            self.advance()
        elif c == "add_tag":
            from .tag import Tag
            self.add_tag(Tag(self, cmd["key"]))
            self.advance()
        elif c == "add_voucher":
            from .vouchers import apply_to_run
            self.GAME.used_vouchers[cmd["key"]] = True
            apply_to_run(self, None, self.P_CENTERS[cmd["key"]])
            self.advance()
        else:
            raise IllegalAction(f"unknown command {c!r}")
