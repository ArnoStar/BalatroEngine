"""A small text REPL to play (and peek into) a seed with the engine.

    python -m balatro play SEED [--deck red] [--stake white]

Commands (indices are 0-based, as shown on screen):
  select | skip | rerollboss             blind selection
  p 0 1 2 ...  | d 0 1 ...               play / discard cards from hand
  sort rank|suit                         sort the hand
  cashout                                collect money after a round
  buy j|v|b I [use]  | reroll | next     shop: joker-row / voucher / booster
  use I [T T ...]                        use consumable I on hand cards T
  sell j|c I                             sell joker / consumable
  pick I [T ...] | skippack              booster packs
  peek [N]                               the next N cards that will be drawn
  undo | s(tate) | help | quit
"""

from __future__ import annotations

import shlex
import sys

from .actions import IllegalAction
from .analyzer import describe
from .card import card_label
from .game import STATE_NAMES, Game

AREA = {"j": "shop_jokers", "v": "shop_vouchers", "b": "shop_booster"}


def show(G: Game) -> str:
    GAME = G.GAME
    cr = GAME.current_round
    rr = GAME.round_resets
    lines = [f"--- {STATE_NAMES.get(G.STATE, G.STATE)} | ante {rr.ante} round {GAME.round} | ${GAME.dollars:g}"
             f" | hands {cr.hands_left} discards {cr.discards_left}"]
    if G.STATE == G.STATES.BLIND_SELECT and G.blind_select is not None:
        bod = GAME.blind_on_deck
        key = rr.blind_choices[bod]
        lines.append(f"next blind: {bod} - {G.data.display_name(key)} "
                     f"({G.get_blind_amount(rr.ante) * G.P_BLINDS[key].mult * GAME.starting_params.ante_scaling:,.0f} chips)"
                     f"   boss: {G.data.display_name(rr.blind_choices.Boss)}")
        tag = rr.blind_tags.get(bod) if rr.blind_tags and bod in ("Small", "Big") else None
        if tag:
            lines.append(f"skip tag: {G.data.display_name(tag)}")
    elif GAME.blind and GAME.blind.name:
        lines.append(f"blind: {GAME.blind.name} {GAME.chips:,.0f}/{GAME.blind.chips:,.0f}")
    if G.jokers.cards:
        lines.append("jokers: " + " | ".join(f"{i}:{describe(c)}" for i, c in enumerate(G.jokers.cards)))
    if G.consumeables.cards:
        lines.append("consumables: " + " | ".join(f"{i}:{describe(c)}" for i, c in enumerate(G.consumeables.cards)))
    if GAME.tags:
        lines.append("tags: " + ", ".join(G.data.display_name(t.key) for t in GAME.tags))
    if G.hand.cards:
        lines.append("hand: " + "  ".join(f"{i}:{card_label(c)}{'(back)' if c.facing == 'back' else ''}"
                                          for i, c in enumerate(G.hand.cards)))
    if G.STATE == G.STATES.SHOP and G.shop is not None:
        for short, area in AREA.items():
            cards = getattr(G, area).cards
            if cards:
                lines.append(f"shop {short}: " + " | ".join(f"{i}:{describe(c)} ${c.cost}" for i, c in enumerate(cards)))
        lines.append(f"reroll: ${cr.reroll_cost}")
    if G.in_pack() and G.pack_cards is not None:
        lines.append(f"pack (choose {GAME.pack_choices}): " + " | ".join(f"{i}:{describe(c)}" for i, c in enumerate(G.pack_cards.cards)))
    if G.STATE == G.STATES.ROUND_EVAL:
        lines.append(f"cash out: ${cr.dollars:g}")
    if getattr(G, "last_score", None) is not None and G.STATE in (G.STATES.SELECTING_HAND, G.STATES.ROUND_EVAL):
        ls = G.last_score
        lines.append(f"last hand: {ls.hand} {ls.chips:g} x {ls.mult:g} = {ls.score:,.0f}")
    return "\n".join(lines)


def run(G: Game, inp=sys.stdin, out=sys.stdout) -> None:
    history: list[Game] = []
    out.write(show(G) + "\n")
    for raw in inp:
        args = shlex.split(raw)
        if not args:
            continue
        c, rest = args[0].lower(), args[1:]
        nums = [int(x) for x in rest if x.lstrip("-").isdigit()]
        try:
            if c in ("q", "quit", "exit"):
                return
            if c in ("h", "help", "?"):
                out.write(__doc__ or "")
                continue
            if c in ("s", "state"):
                out.write(show(G) + "\n")
                continue
            if c == "peek":
                n = nums[0] if nums else 10
                nxt = [card_label(x) for x in reversed(G.deck.cards[-n:])]
                out.write("next draws: " + " ".join(nxt) + "\n")
                continue
            if c == "undo":
                if history:
                    G = history.pop()
                    out.write(show(G) + "\n")
                else:
                    out.write("nothing to undo\n")
                continue
            snapshot = G.clone()
            if c == "select":
                G.act_select_blind()
            elif c == "skip":
                G.act_skip_blind()
            elif c == "rerollboss":
                G.act_reroll_boss()
            elif c in ("p", "play"):
                G.act_play(nums)
            elif c in ("d", "discard"):
                G.act_discard(nums)
            elif c == "sort":
                G.act_sort(rest[0] if rest else "rank")
            elif c == "cashout":
                G.act_cash_out()
            elif c == "buy":
                G.act_buy(AREA[rest[0]], int(rest[1]), use=len(rest) > 2 and rest[2] == "use")
            elif c == "reroll":
                G.act_reroll()
            elif c == "next":
                G.act_end_shop()
            elif c == "use":
                G.act_use(nums[0], nums[1:])
            elif c == "sell":
                G.act_sell("jokers" if rest[0] == "j" else "consumeables", int(rest[1]))
            elif c == "pick":
                G.act_pick(nums[0], nums[1:])
            elif c == "skippack":
                G.act_skip_pack()
            else:
                out.write("unknown command (help)\n")
                continue
            history.append(snapshot)
        except (IllegalAction, IndexError, KeyError, ValueError) as e:
            out.write(f"! {e}\n")
            continue
        out.write(show(G) + "\n")
        if G.STATE == G.STATES.GAME_OVER:
            out.write("GAME OVER (undo to go back)\n")
