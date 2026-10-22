"""Command line interface.

    python -m balatro analyze ABCD1234 --deck red --stake white --antes 8
    python -m balatro analyze ABCD1234 --json
    python -m balatro search --tags tag_uncommon tag_uncommon --count 5
    python -m balatro play ABCD1234             (interactive, with peek/undo)
    python -m balatro verify --runs 20          (needs luajit + game source)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import random
import sys
import time
from multiprocessing import Pool

from .game import DECK_NAMES, STAKE_NAMES, Game
from .rng import SEED_ALPHABET
from .search import check_seed


def _deck(name: str) -> str:
    return DECK_NAMES.get(name.lower().replace(" deck", ""), name)


def _stake(v: str) -> int:
    return STAKE_NAMES[v.lower()] if v.lower() in STAKE_NAMES else int(v)


def cmd_analyze(a: argparse.Namespace) -> int:
    from .analyzer import analyze
    rep = analyze(a.seed, deck=_deck(a.deck), stake=_stake(a.stake), antes=a.antes, rerolls=a.rerolls,
                  open_packs=not a.no_packs)
    if a.json:
        print(json.dumps(dataclasses.asdict(rep), indent=1))
    else:
        print(rep.to_text())
    return 0


def cmd_search(a: argparse.Namespace) -> int:
    rnd = random.Random(a.rng_seed)
    deck, stake = _deck(a.deck), _stake(a.stake)
    found = 0
    t0 = time.time()
    tried = 0
    with Pool(a.jobs or os.cpu_count()) as pool:
        while found < a.count:
            batch = ["".join(rnd.choice(SEED_ALPHABET) for _ in range(8)) for _ in range(2000)]
            jobs = [(s, deck, stake, a.tags, a.boss, a.voucher, a.hand) for s in batch]
            for res in pool.imap_unordered(check_seed, jobs, chunksize=50):
                tried += 1
                if res:
                    found += 1
                    print(res, flush=True)
                    if found >= a.count:
                        break
            if a.max_tries and tried >= a.max_tries:
                break
    dt = time.time() - t0
    print(f"# {found} found in {tried} seeds ({tried / max(dt, 1e-9):.0f} seeds/s)", file=sys.stderr)
    return 0


def cmd_play(a: argparse.Namespace) -> int:
    from .repl import run
    run(Game(a.seed, deck=_deck(a.deck), stake=_stake(a.stake)).start_run())
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    from .oracle.fuzz import main as fuzz_main
    argv = ["--runs", str(a.runs), "--seed", str(a.rng_seed)]
    if a.deck:
        argv += ["--deck", a.deck]
    return fuzz_main(argv)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m balatro")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("analyze", help="predict a seed ante by ante")
    p.add_argument("seed")
    p.add_argument("--deck", default="red")
    p.add_argument("--stake", default="white")
    p.add_argument("--antes", type=int, default=8)
    p.add_argument("--rerolls", type=int, default=2, help="shop rerolls to show per shop")
    p.add_argument("--no-packs", action="store_true", help="don't open booster packs")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("search", help="find seeds matching ante-1 conditions")
    p.add_argument("--deck", default="red")
    p.add_argument("--stake", default="white")
    p.add_argument("--tags", nargs=2, metavar=("SMALL", "BIG"), help="e.g. tag_uncommon tag_negative")
    p.add_argument("--boss", help="e.g. bl_hook")
    p.add_argument("--voucher", help="e.g. v_hone")
    p.add_argument("--hand", nargs="+", help="cards that must be in the first hand, e.g. H_A S_A")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--max-tries", type=int, default=0)
    p.add_argument("--jobs", type=int, default=0)
    p.add_argument("--rng-seed", type=int, default=None)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("play", help="play a seed in the terminal (with peek/undo)")
    p.add_argument("seed")
    p.add_argument("--deck", default="red")
    p.add_argument("--stake", default="white")
    p.set_defaults(func=cmd_play)

    p = sub.add_parser("verify", help="differential test against the original game (needs luajit)")
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--deck", default=None)
    p.add_argument("--rng-seed", type=int, default=0)
    p.set_defaults(func=cmd_verify)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
