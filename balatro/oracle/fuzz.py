"""Differential fuzzing against the original game.

Plays random (but legal) actions on both the Python engine and the headless
original game and compares the complete state after every action.

    python -m balatro.oracle.fuzz --runs 20 --seed 1
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import time
from typing import Any

from ..actions import IllegalAction
from ..game import Game
from ..poker import get_poker_hand_info
from . import Oracle, OracleError, diff, normalize

DECKS = ["Red Deck", "Blue Deck", "Yellow Deck", "Green Deck", "Black Deck", "Magic Deck", "Nebula Deck",
         "Ghost Deck", "Abandoned Deck", "Checkered Deck", "Zodiac Deck", "Painted Deck", "Anaglyph Deck",
         "Plasma Deck", "Erratic Deck"]
SEED_CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"


def deck_key(G: Game, name: str) -> str:
    c = G.data.center_by_name(name)
    assert c is not None
    return c.key


def best_play(G: Game) -> list[int]:
    """Greedy: the subset with the largest base (chips*mult) value."""
    cards = G.hand.cards
    best: tuple[float, list[int]] = (-1.0, [0])
    for n in range(1, min(5, len(cards)) + 1):
        for combo in itertools.combinations(range(len(cards)), n):
            sel = [cards[i] for i in combo]
            text, _, _, scoring, _ = get_poker_hand_info(G, sel)
            if text == "NULL":
                continue
            h = G.GAME.hands[text]
            chips = h.chips + sum(c.base.nominal or 0 for c in scoring if not c.debuff)
            val = chips * h.mult
            if val > best[0]:
                best = (val, list(combo))
    return best[1]


def target_options(G: Game, card: Any, rnd: random.Random) -> list[list[int]]:
    cons = card.ability.consumeable or {}
    n = len(G.hand.cards)
    opts: list[list[int]] = [[]]
    mx = cons.get("max_highlighted") if hasattr(cons, "get") else None
    if mx and n:
        for _ in range(3):
            k = rnd.randint(cons.get("min_highlighted") or 1, min(mx, n))
            opts.append(sorted(rnd.sample(range(n), k)))
    elif n:
        opts.append([rnd.randrange(n)])
    return opts


def usable_consumables(G: Game, rnd: random.Random, base: list[int] | None = None) -> list[dict]:
    out = []
    saved = [G.hand.index(c) for c in G.hand.highlighted] if G.hand is not None else []
    for i, c in enumerate(G.consumeables.cards):
        for targets in target_options(G, c, rnd):
            G._highlight(G.hand, targets)
            if c.can_use_consumeable():
                out.append({"cmd": "use", "index": i, "targets": targets})
                break
    G._highlight(G.hand, saved)
    return out


def legal_actions(G: Game, rnd: random.Random, opts: argparse.Namespace) -> list[tuple[float, dict]]:
    S = G.STATES
    st = G.STATE
    acts: list[tuple[float, dict]] = []
    GAME = G.GAME
    if st == S.BLIND_SELECT and G.blind_select is not None:
        acts.append((10, {"cmd": "select_blind"}))
        if GAME.blind_on_deck in ("Small", "Big"):
            acts.append((2.5, {"cmd": "skip_blind"}))
        if G.can_reroll_boss():
            acts.append((1, {"cmd": "reroll_boss"}))
        acts += [(1.5, a) for a in usable_consumables(G, rnd)]
        acts += [(0.2, {"cmd": "sell", "area": "jokers", "index": i}) for i, c in enumerate(G.jokers.cards) if c.can_sell_card()]
    elif st == S.SELECTING_HAND:
        if G.hand.cards:
            acts.append((8, {"cmd": "play", "cards": best_play(G)}))
            k = rnd.randint(1, min(5, len(G.hand.cards)))
            acts.append((1.5, {"cmd": "play", "cards": sorted(rnd.sample(range(len(G.hand.cards)), k))}))
            if GAME.current_round.discards_left > 0:
                k = rnd.randint(1, min(5, len(G.hand.cards)))
                acts.append((3, {"cmd": "discard", "cards": sorted(rnd.sample(range(len(G.hand.cards)), k))}))
        acts += [(2, a) for a in usable_consumables(G, rnd)]
        acts += [(0.3, {"cmd": "sell", "area": "jokers", "index": i}) for i, c in enumerate(G.jokers.cards) if c.can_sell_card()]
        if len(G.jokers.cards) > 1:
            acts.append((0.3, {"cmd": "move", "area": "jokers", "from": rnd.randrange(len(G.jokers.cards)),
                               "to": rnd.randrange(len(G.jokers.cards))}))
        if len(G.hand.cards) > 1:
            acts.append((0.3, {"cmd": "move", "area": "hand", "from": rnd.randrange(len(G.hand.cards)),
                               "to": rnd.randrange(len(G.hand.cards))}))
            acts.append((0.3, {"cmd": "sort", "mode": rnd.choice(["suit", "rank"])}))
    elif st == S.ROUND_EVAL and G.round_eval is not None:
        acts.append((1, {"cmd": "cash_out"}))
    elif st == S.SHOP and G.shop is not None:
        for i, c in enumerate(G.shop_jokers.cards):
            if G.can_afford(c):
                if G.check_for_buy_space(G, c):
                    acts.append((3, {"cmd": "buy", "area": "shop_jokers", "index": i}))
                if c.ability.consumeable and c.can_use_consumeable():
                    acts.append((1, {"cmd": "buy", "area": "shop_jokers", "index": i, "use": True}))
        for area in ("shop_vouchers", "shop_booster"):
            for i, c in enumerate(getattr(G, area).cards):
                if G.can_afford(c):
                    acts.append((3, {"cmd": "buy", "area": area, "index": i}))
        cr = GAME.current_round
        if not ((GAME.dollars - GAME.bankrupt_at) - cr.reroll_cost < 0 and cr.reroll_cost != 0):
            acts.append((1.5, {"cmd": "reroll"}))
        acts += [(1, a) for a in usable_consumables(G, rnd)]
        acts += [(0.4, {"cmd": "sell", "area": "jokers", "index": i}) for i, c in enumerate(G.jokers.cards) if c.can_sell_card()]
        acts += [(0.3, {"cmd": "sell", "area": "consumeables", "index": i}) for i, c in enumerate(G.consumeables.cards)]
        acts.append((2.5, {"cmd": "end_shop"}))
    elif G.in_pack() and G.pack_cards is not None and G.pack_cards.cards:
        for i, c in enumerate(G.pack_cards.cards):
            for targets in target_options(G, c, rnd) if c.ability.consumeable else [[]]:
                G._highlight(G.hand, targets)
                if G.can_select_pack_card(c):
                    acts.append((3, {"cmd": "pick", "index": i, "targets": targets}))
                    break
        G._highlight(G.hand, [])
        try:
            if (st in (S.PLANET_PACK, S.STANDARD_PACK, S.BUFFOON_PACK) or G.hand.cards or G.hand.config.card_limit <= 0):
                acts.append((1, {"cmd": "skip_pack"}))
        except Exception:
            pass
    return acts


def choose(rnd: random.Random, acts: list[tuple[float, dict]]) -> dict:
    total = sum(w for w, _ in acts)
    x = rnd.random() * total
    for w, a in acts:
        x -= w
        if x <= 0:
            return a
    return acts[-1][1]


def sweep_items(G: Game, kind: str) -> list[list[dict]]:
    """Commands that inject one specific item per run (to exercise every card)."""
    if kind == "jokers":
        return [[{"cmd": "add_joker", "key": v.key}] for v in G.P_CENTER_POOLS["Joker"]]
    if kind == "consumables":
        out = []
        for pool in ("Tarot", "Planet", "Spectral"):
            for v in G.P_CENTER_POOLS[pool]:
                out.append([{"cmd": "add_joker", "key": v.key}])
        for k in ("c_soul", "c_black_hole"):
            out.append([{"cmd": "add_joker", "key": k}])
        return out
    if kind == "vouchers":
        return [[{"cmd": "add_voucher", "key": v.key}] for v in G.P_CENTER_POOLS["Voucher"]]
    if kind == "bosses":
        return [[{"cmd": "cheat", "boss": k, "ante": max(1, v.boss.min) if not v.boss.showdown else 8}]
                for k, v in sorted(G.P_BLINDS.items()) if v.boss]
    raise ValueError(kind)


def run_one(oracle: Oracle, seed: str, deck: str, stake: int, rnd: random.Random, opts: argparse.Namespace,
            challenge: str | None = None, inject: list[dict] | None = None) -> dict:
    log: list[dict] = [{"cmd": "start", "seed": seed, "deck": deck, "stake": stake}]
    if challenge:
        log[0] = {"cmd": "start", "seed": seed, "challenge": challenge, "stake": 1}
    r = oracle.send(log[0])
    from ..game import Profile
    G = Game(seed, deck=deck_key_cache.get(deck, "b_red"), stake=log[0]["stake"], challenge=challenge,
             hands_order=r["state"]["hands_order"],
             profile=Profile.fresh() if opts.profile == "fresh" else None).start_run()
    boss_keys = [k for k, v in G.P_BLINDS.items() if v.boss]
    for cmd in inject or []:
        log.append(cmd)
        r = oracle.send(cmd)
        G.do(cmd)
    steps = 0
    joker_keys = [v.key for v in G.P_CENTER_POOLS["Joker"]]
    last_state = None
    while steps < opts.steps:
        d = diff(normalize(G.snapshot()), normalize(r["state"]))
        if d:
            return {"ok": False, "seed": seed, "deck": deck, "stake": stake, "log": log, "diff": d[:60]}
        if G.STATE == G.STATES.GAME_OVER or G.GAME.round_resets.ante > opts.max_ante:
            break
        # occasional help so runs reach later content
        if G.STATE == G.STATES.SHOP and last_state != G.STATES.SHOP:
            if rnd.random() < opts.money_prob:
                cmd = {"cmd": "cheat", "dollars": G.GAME.dollars + rnd.randint(10, 60)}
                log.append(cmd)
                r = oracle.send(cmd)
                G.do(cmd)
                continue
            if rnd.random() < opts.joker_prob and len(G.jokers.cards) < G.jokers.config.card_limit:
                cmd = {"cmd": "add_joker", "key": rnd.choice(joker_keys)}
                if rnd.random() < 0.2:
                    cmd["edition"] = rnd.choice(["foil", "holo", "polychrome", "negative"])
                log.append(cmd)
                r = oracle.send(cmd)
                G.do(cmd)
                last_state = G.STATE
                continue
        # occasionally jump ahead / force a boss so late-game content is exercised
        if (G.STATE == G.STATES.BLIND_SELECT and G.blind_select is not None and last_state != G.STATES.BLIND_SELECT
                and G.GAME.blind_on_deck == "Small"):
            cmd = None
            if rnd.random() < opts.ante_prob:
                cmd = {"cmd": "cheat", "ante": G.GAME.round_resets.ante + rnd.randint(1, 3)}
            elif rnd.random() < opts.boss_prob:
                cmd = {"cmd": "cheat", "boss": rnd.choice(boss_keys)}
            if cmd is not None:
                log.append(cmd)
                r = oracle.send(cmd)
                G.do(cmd)
                last_state = G.STATE
                continue
        last_state = G.STATE
        acts = legal_actions(G, rnd, opts)
        if not acts:
            return {"ok": False, "seed": seed, "deck": deck, "stake": stake, "log": log,
                    "diff": [f"no legal actions in state {G.STATE}"]}
        cmd = choose(rnd, acts)
        log.append(cmd)
        try:
            r = oracle.send(cmd)
        except OracleError as e:
            return {"ok": False, "seed": seed, "deck": deck, "stake": stake, "log": log, "diff": [f"oracle error: {e}"]}
        try:
            G.do(cmd)
        except IllegalAction as e:
            return {"ok": False, "seed": seed, "deck": deck, "stake": stake, "log": log, "diff": [f"python illegal: {e}"]}
        except Exception as e:  # engine bug
            import traceback
            return {"ok": False, "seed": seed, "deck": deck, "stake": stake, "log": log,
                    "diff": [f"python exception: {e!r}", traceback.format_exc()]}
        steps += 1
    return {"ok": True, "seed": seed, "deck": deck, "stake": stake, "steps": steps, "ante": G.GAME.round_resets.ante}


deck_key_cache: dict[str, str] = {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--max-ante", type=int, default=9)
    ap.add_argument("--seed", type=int, default=0, help="fuzzer RNG seed")
    ap.add_argument("--deck", default=None)
    ap.add_argument("--stake", type=int, default=None)
    ap.add_argument("--money-prob", type=float, default=0.5)
    ap.add_argument("--joker-prob", type=float, default=0.3)
    ap.add_argument("--ante-prob", type=float, default=0.15)
    ap.add_argument("--boss-prob", type=float, default=0.3)
    ap.add_argument("--challenge-prob", type=float, default=0.15)
    ap.add_argument("--sweep", choices=["jokers", "consumables", "vouchers", "bosses"], default=None,
                    help="run i injects the i-th item of this kind first")
    ap.add_argument("--profile", choices=["all", "fresh"], default="all")
    ap.add_argument("--sweep-offset", type=int, default=0)
    ap.add_argument("--sweep-step", type=int, default=1)
    ap.add_argument("--out", default=None, help="write failures (json lines) here")
    opts = ap.parse_args(argv)
    rnd = random.Random(opts.seed)
    g0 = Game("X")
    for d in DECKS:
        deck_key_cache[d] = deck_key(g0, d)
    fails = 0
    with Oracle(profile=opts.profile) as oracle:
        for n in range(opts.runs):
            seed = "".join(rnd.choice(SEED_CHARS) for _ in range(8))
            deck = opts.deck or rnd.choice(DECKS)
            stake = opts.stake or rnd.randint(1, 8)
            challenge = None
            if not opts.deck and rnd.random() < opts.challenge_prob:
                challenge = rnd.choice([c.id for c in g0.data.challenges])
                deck = "Challenge Deck"
                stake = 1
            inject = None
            if opts.sweep:
                items = sweep_items(g0, opts.sweep)
                idx = opts.sweep_offset + n * opts.sweep_step
                if idx >= len(items):
                    break
                inject = items[idx]
                challenge = None
                if deck == "Challenge Deck":
                    deck = "Red Deck"
            t0 = time.time()
            res = run_one(oracle, seed, deck, stake, rnd, opts, challenge, inject)
            dt = time.time() - t0
            label = f"{seed} {challenge or deck} stake {stake}" + (f" +{inject[0].get('key') or inject[0].get('boss')}" if inject else "")
            if res["ok"]:
                print(f"[{n}] OK   {label}: {res['steps']} steps, ante {res['ante']} ({dt:.1f}s)")
            else:
                fails += 1
                print(f"[{n}] FAIL {label} after {len(res['log']) - 1} actions ({dt:.1f}s)")
                print("     last actions:", json.dumps(res["log"][-4:]))
                for line in res["diff"][:25]:
                    print("    ", line)
                if opts.out:
                    with open(opts.out, "a") as f:
                        f.write(json.dumps(res) + "\n")
    print(f"{opts.runs - fails}/{opts.runs} runs identical")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
