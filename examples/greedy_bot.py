"""A simple bot that plays whole runs through the library API.

    python examples/greedy_bot.py [SEED] [--deck red] [--stake 1]

It plays the hand with the best base score, discards towards flushes when
that hand is weak, buys the jokers it can afford and skips packs.  It is not
good at the game; it shows how to drive the engine.
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from balatro import STATES, Game  # noqa: E402
from balatro.poker import get_poker_hand_info  # noqa: E402


def best_hand(G: Game) -> tuple[float, list[int]]:
    """The 1-5 card selection with the highest base chips x mult."""
    cards = G.hand.cards
    best: tuple[float, list[int]] = (-1.0, [0])
    for n in range(1, min(5, len(cards)) + 1):
        for combo in itertools.combinations(range(len(cards)), n):
            text, _, _, scoring, _ = get_poker_hand_info(G, [cards[i] for i in combo])
            if text == "NULL":
                continue
            h = G.GAME.hands[text]
            value = (h.chips + sum(c.base.nominal for c in scoring if not c.debuff)) * h.mult
            if value > best[0]:
                best = (value, list(combo))
    return best


def flush_discard(G: Game) -> list[int]:
    """Discard up to 5 cards that are not of the most common suit."""
    suits: dict[str, int] = {}
    for c in G.hand.cards:
        suits[c.base.suit] = suits.get(c.base.suit, 0) + 1
    keep = max(suits, key=suits.get)
    return [i for i, c in enumerate(G.hand.cards) if c.base.suit != keep][:5]


def play_round(G: Game) -> None:
    while G.STATE == STATES.SELECTING_HAND:
        value, cards = best_hand(G)
        need = G.GAME.blind.chips - G.GAME.chips
        if value < need / 2 and G.GAME.current_round.discards_left > 0 and G.GAME.current_round.hands_left > 1:
            discard = flush_discard(G) or [0]
            G.act_discard(discard)
        else:
            G.act_play(cards)


def shop(G: Game) -> None:
    bought = True
    while bought:
        bought = False
        for i, c in enumerate(G.shop_jokers.cards):
            if c.ability.set == "Joker" and G.can_afford(c) and G.check_space(c):
                G.act_buy("shop_jokers", i)
                bought = True
                break
    G.act_end_shop()


def run(seed: str, deck: str = "red", stake: int = 1, verbose: bool = True) -> Game:
    G = Game(seed, deck=deck, stake=stake).start_run()
    while not G.is_game_over() and not (G.GAME.won and G.STATE == STATES.SHOP):
        st = G.STATE
        if st == STATES.BLIND_SELECT:
            G.act_select_blind()
            if verbose:
                print(G.summary(), "\n")
        elif st == STATES.SELECTING_HAND:
            play_round(G)
        elif st == STATES.ROUND_EVAL:
            G.act_cash_out()
        elif st == STATES.SHOP:
            shop(G)
        elif G.in_pack():
            G.act_skip_pack()
        else:
            raise RuntimeError(f"unexpected state {st}")
    result = "won" if G.GAME.won else f"lost at ante {G.GAME.round_resets.ante}"
    print(f"{seed}: {result}, round {G.GAME.round}, ${G.GAME.dollars:,.0f}, "
          f"jokers: {', '.join(c.key for c in G.jokers.cards) or '-'}")
    return G


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("seed", nargs="?", default="TESTSEED")
    ap.add_argument("--deck", default="red")
    ap.add_argument("--stake", type=int, default=1)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    run(a.seed, a.deck, a.stake, verbose=not a.quiet)
