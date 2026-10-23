"""Replay a failure log on the engine and the original game, step by step.

    python -m balatro.oracle.replay fails.jsonl [--index N] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import sys

from ..game import Game
from . import Oracle, diff, normalize

AREAS = ("hand", "jokers", "consumeables", "pack_cards", "shop_jokers")


def _short(c: dict) -> str:
    s = c.get("card") or c["key"]
    if c.get("highlighted"):
        s += "^"
    if c.get("forced"):
        s += "!"
    if c.get("debuff"):
        s += "~"
    return s


def replay(log: list[dict], verbose: bool = False, gamespeed: float = 1) -> int:
    start = log[0]
    with Oracle(gamespeed=gamespeed) as o:
        r = o.send(start)
        g0 = Game("X")
        dk = g0.data.center_by_name(start["deck"]).key if start.get("deck") else "b_red"
        G = Game(start["seed"], deck=dk, stake=start.get("stake", 1), challenge=start.get("challenge"),
                 hands_order=r["state"]["hands_order"], game_speed=gamespeed).start_run()
        prev = normalize(r["state"])
        for i, cmd in enumerate(log[1:], 1):
            before = normalize(G.snapshot())
            r = o.send(cmd)
            G.do(cmd)
            d = diff(normalize(G.snapshot()), normalize(r["state"]))
            if verbose:
                s = r["state"]
                print(f"{i:4d} {json.dumps(cmd)} -> state {s['state']} ante {s['ante']} ${s['dollars']}")
            if d:
                print(f"DIVERGED at command {i}: {json.dumps(cmd)}")
                for line in d[:80]:
                    print("   ", line)
                print("state before this command (python / game):")
                for area in AREAS:
                    print(f"   {area}: {[_short(c) for c in before.get(area) or []]}")
                    print(f"   {' ' * len(area)}  {[_short(c) for c in prev.get(area) or []]}")
                return i
            prev = normalize(r["state"])
    print("no divergence")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--gamespeed", type=float, default=None)
    a = ap.parse_args(argv)
    lines = [json.loads(x) for x in open(a.file) if x.strip()]
    rec = lines[a.index]
    speed = a.gamespeed if a.gamespeed is not None else rec.get("gamespeed", 1)
    return 1 if replay(rec["log"], a.verbose, speed) else 0


if __name__ == "__main__":
    sys.exit(main())
