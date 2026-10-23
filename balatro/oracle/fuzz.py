"""Differential fuzzing against the original game.

Plays random (but legal) actions on both the engine and the headless
original game and compares the complete state after every action.

    python -m balatro.oracle.fuzz --runs 20 --seed 1
    python -m balatro.oracle.fuzz --sweep jokers      # one run per joker
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import time
import traceback
from typing import Any

from ..actions import IllegalAction
from ..game import Game, Profile
from ..poker import get_poker_hand_info
from . import Oracle, OracleError, diff, normalize

DECKS = ["Red Deck", "Blue Deck", "Yellow Deck", "Green Deck", "Black Deck", "Magic Deck", "Nebula Deck",
         "Ghost Deck", "Abandoned Deck", "Checkered Deck", "Zodiac Deck", "Painted Deck", "Anaglyph Deck",
         "Plasma Deck", "Erratic Deck"]
SEED_CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"


def best_play(G: Game) -> list[int]:
    """Greedy: the subset with the largest base chips*mult."""
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


def subset(rnd: random.Random, n: int, lo: int = 1, hi: int = 5) -> list[int]:
    if n <= 0:
        return []
    k = rnd.randint(min(lo, n), min(hi, n))
    return sorted(rnd.sample(range(n), k))


WEIGHTS = {"select_blind": 10, "skip_blind": 2.5, "reroll_boss": 1, "cash_out": 1, "buy": 3, "reroll": 1.5,
           "end_shop": 2.5, "use": 1.5, "sell": 0.3, "pick": 3, "skip_pack": 1, "sort": 0.2}


def fit(G: Game, cards: list[int]) -> list[int]:
    """A selection the game allows: forced cards are always selected, 5 at most."""
    forced = [i for i, c in enumerate(G.hand.cards) if c.ability.forced_selection]
    rest = [i for i in cards if i not in forced]
    return sorted(forced + rest[:max(0, 5 - len(forced))])


def candidates(G: Game, rnd: random.Random) -> list[tuple[float, dict]]:
    out: list[tuple[float, dict]] = []
    nhand = len(G.hand.cards) if G.hand is not None else 0
    for a in G.legal_actions():
        c = a["cmd"]
        if c == "play":
            out.append((8, {"cmd": "play", "cards": fit(G, best_play(G))}))
            out.append((1.5, {"cmd": "play", "cards": fit(G, subset(rnd, nhand))}))
        elif c == "discard":
            out.append((3, {"cmd": "discard", "cards": fit(G, subset(rnd, nhand))}))
        elif c in ("use", "pick") and "max" in a:
            for _ in range(3):
                t = subset(rnd, nhand, a["min"], a["max"])
                cmd = {"cmd": c, "index": a["index"], "targets": t}
                ok = G.can_use(a["index"], t) if c == "use" else G.can_select_pack_card(G.pack_cards.cards[a["index"]], t)
                if ok:
                    out.append((WEIGHTS[c], cmd))
                    break
        elif c in ("use", "pick"):
            out.append((WEIGHTS[c], dict(a, targets=[])))
        else:
            out.append((WEIGHTS.get(c, 1), dict(a)))
    if G.STATE == G.STATES.SELECTING_HAND:
        for area in ("jokers", "hand"):
            n = len(getattr(G, area).cards)
            if n > 1:
                out.append((0.3, {"cmd": "move", "area": area, "from": rnd.randrange(n), "to": rnd.randrange(n)}))
    return out


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
    if kind == "tags":
        return [[{"cmd": "add_tag", "key": k}] for k in sorted(G.P_TAGS)]
    raise ValueError(kind)


def run_one(oracle: Oracle, seed: str, deck: str, stake: int, rnd: random.Random, opts: argparse.Namespace,
            challenge: str | None = None, inject: list[dict] | None = None) -> dict:
    start = {"cmd": "start", "seed": seed, "deck": deck, "stake": stake}
    if challenge:
        start = {"cmd": "start", "seed": seed, "challenge": challenge, "stake": 1}
    log: list[dict] = [start]
    result: dict[str, Any] = {"seed": seed, "deck": deck, "stake": start["stake"], "challenge": challenge,
                              "gamespeed": opts.gamespeed, "log": log}
    r = oracle.send(start)
    g0 = Game("X")
    G = Game(seed, deck=g0.data.center_by_name(deck).key if not challenge else "b_red", stake=start["stake"],
             challenge=challenge, hands_order=r["state"]["hands_order"], game_speed=opts.gamespeed,
             profile=Profile.fresh() if opts.profile == "fresh" else None).start_run()

    def fail(msg: list[str]) -> dict:
        result.update(ok=False, diff=msg)
        return result

    d = diff(normalize(G.snapshot()), normalize(r["state"]))
    if d:
        return fail(d[:60])
    boss_keys = [k for k, v in G.P_BLINDS.items() if v.boss]
    joker_keys = [v.key for v in G.P_CENTER_POOLS["Joker"]]
    pending = list(inject or [])
    steps = 0
    last_state = None
    while steps < opts.steps:
        if G.is_game_over() or G.GAME.round_resets.ante > opts.max_ante:
            break
        cmd: dict | None = None
        if pending:
            cmd = pending.pop(0)
        elif G.STATE == G.STATES.SHOP and last_state != G.STATES.SHOP:
            if rnd.random() < opts.money_prob:
                cmd = {"cmd": "cheat", "dollars": G.GAME.dollars + rnd.randint(10, 60)}
            elif rnd.random() < opts.joker_prob and len(G.jokers.cards) < G.jokers.config.card_limit:
                cmd = {"cmd": "add_joker", "key": rnd.choice(joker_keys)}
                if rnd.random() < 0.2:
                    cmd["edition"] = rnd.choice(["foil", "holo", "polychrome", "negative"])
        elif (G.STATE == G.STATES.SELECTING_HAND and G.GAME.current_round.hands_left <= 1
              and rnd.random() < opts.win_prob):
            cmd = {"cmd": "cheat", "win": True}
        elif (G.STATE == G.STATES.BLIND_SELECT and last_state != G.STATES.BLIND_SELECT
              and G.GAME.blind_on_deck == "Small"):
            if rnd.random() < opts.ante_prob:
                cmd = {"cmd": "cheat", "ante": G.GAME.round_resets.ante + rnd.randint(1, 3)}
            elif rnd.random() < opts.boss_prob:
                cmd = {"cmd": "cheat", "boss": rnd.choice(boss_keys)}
        last_state = G.STATE
        if cmd is None:
            acts = candidates(G, rnd)
            if not acts:
                return fail([f"no legal actions in state {G.STATE}"])
            cmd = choose(rnd, acts)
            steps += 1
        log.append(cmd)
        try:
            r = oracle.send(cmd)
        except OracleError as e:
            return fail([f"oracle error: {e}"])
        try:
            G.do(cmd)
        except IllegalAction as e:
            return fail([f"python illegal: {e}"])
        except Exception as e:  # engine bug
            return fail([f"python exception: {e!r}", traceback.format_exc()])
        d = diff(normalize(G.snapshot()), normalize(r["state"]))
        if d:
            return fail(d[:60])
    result.update(ok=True, steps=steps, ante=G.GAME.round_resets.ante, final=normalize(r["state"]))
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--max-ante", type=int, default=9)
    ap.add_argument("--seed", type=int, default=0, help="fuzzer RNG seed")
    ap.add_argument("--deck", default=None)
    ap.add_argument("--stake", type=int, default=None)
    ap.add_argument("--money-prob", type=float, default=0.5)
    ap.add_argument("--joker-prob", type=float, default=0.3)
    ap.add_argument("--ante-prob", type=float, default=0.15)
    ap.add_argument("--boss-prob", type=float, default=0.3)
    ap.add_argument("--challenge-prob", type=float, default=0.15)
    ap.add_argument("--win-prob", type=float, default=0.7, help="beat a blind that is about to be lost")
    ap.add_argument("--sweep", choices=["jokers", "consumables", "vouchers", "bosses", "tags"], default=None,
                    help="run i injects the i-th item of this kind first")
    ap.add_argument("--sweep-offset", type=int, default=0)
    ap.add_argument("--sweep-step", type=int, default=1)
    ap.add_argument("--profile", choices=["all", "fresh"], default="all")
    ap.add_argument("--gamespeed", type=float, default=1, help="the game speed setting (0.5, 1, 2, 4)")
    ap.add_argument("--out", default=None, help="append failures (json lines) here")
    ap.add_argument("--record", default=None, help="append passing runs (log + the game's final state) here")
    opts = ap.parse_args(argv)
    rnd = random.Random(opts.seed)
    g0 = Game("X")
    fails = 0
    done = 0
    with Oracle(profile=opts.profile, gamespeed=opts.gamespeed) as oracle:
        for n in range(opts.runs):
            seed = "".join(rnd.choice(SEED_CHARS) for _ in range(8))
            deck = opts.deck or rnd.choice(DECKS)
            stake = opts.stake or rnd.randint(1, 8)
            challenge = None
            if not opts.deck and not opts.sweep and rnd.random() < opts.challenge_prob:
                challenge = rnd.choice([c.id for c in g0.data.challenges])
            inject = None
            if opts.sweep:
                items = sweep_items(g0, opts.sweep)
                idx = opts.sweep_offset + n * opts.sweep_step
                if idx >= len(items):
                    break
                inject = items[idx]
            t0 = time.time()
            res = run_one(oracle, seed, deck, stake, rnd, opts, challenge, inject)
            dt = time.time() - t0
            done += 1
            label = f"{seed} {challenge or deck} stake {res['stake']}" + (
                f" +{inject[0].get('key') or inject[0].get('boss')}" if inject else "")
            if res["ok"]:
                print(f"[{n}] OK   {label}: {res['steps']} steps, ante {res['ante']} ({dt:.1f}s)", flush=True)
                if opts.record:
                    with open(opts.record, "a") as f:
                        f.write(json.dumps(res) + "\n")
            else:
                fails += 1
                print(f"[{n}] FAIL {label} after {len(res['log']) - 1} commands ({dt:.1f}s)", flush=True)
                print("     last commands:", json.dumps(res["log"][-4:]), flush=True)
                for line in res["diff"][:25]:
                    print("    ", line, flush=True)
                if opts.out:
                    with open(opts.out, "a") as f:
                        f.write(json.dumps(res) + "\n")
    print(f"{done - fails}/{done} runs identical", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
