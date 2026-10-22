"""Replay an action log on the Python engine and the original game, step by step.

    python -m balatro.oracle.replay fails.jsonl [--index N] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import sys

from ..game import Game
from . import Oracle, diff, normalize


def replay(log: list[dict], verbose: bool = False, deck_key: str | None = None) -> int:
    start = log[0]
    with Oracle() as o:
        r = o.send(start)
        g0 = Game("X")
        dk = deck_key or (g0.data.center_by_name(start["deck"]).key if start.get("deck") else "b_red")
        G = Game(start["seed"], deck=dk, stake=start.get("stake", 1), challenge=start.get("challenge"),
                 hands_order=r["state"]["hands_order"]).start_run()
        for i, cmd in enumerate(log[1:], 1):
            before_py = normalize(G.snapshot())
            r = o.send(cmd)
            G.do(cmd)
            d = diff(normalize(G.snapshot()), normalize(r["state"]))
            if verbose:
                s = r["state"]
                print(f"{i:4d} {json.dumps(cmd)} -> state {s['state']} ante {s['ante']} ${s['dollars']}")
            if d:
                print(f"DIVERGED at action {i}: {json.dumps(cmd)}")
                for line in d[:80]:
                    print("   ", line)
                print("python state before this action:")
                for area in ("hand", "jokers", "consumeables", "pack_cards", "shop_jokers"):
                    print(f"   {area}: {[c.get('card') or c['key'] for c in before_py.get(area) or []]}")
                return i
    print("no divergence")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)
    lines = [json.loads(x) for x in open(a.file) if x.strip()]
    rec = lines[a.index]
    return 1 if replay(rec["log"], a.verbose) else 0


if __name__ == "__main__":
    sys.exit(main())
