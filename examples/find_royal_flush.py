"""Find seeds whose ante-1 skip tags are both Uncommon AND whose very first
hand contains a royal flush (the search the original main.py was doing).

    python examples/find_royal_flush.py [count]
"""

from __future__ import annotations

import os
import random
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from balatro.quick import Ante1  # noqa: E402
from balatro.rng import SEED_ALPHABET  # noqa: E402

ROYALS = [{f"{s}_{r}" for r in "AKQJT"} for s in "SHDC"]


def check(seed: str) -> tuple[str, list[str], str] | None:
    a = Ante1(seed)
    if a.tags != ("tag_uncommon", "tag_uncommon"):
        return None
    hand = a.first_hand()
    hs = set(hand)
    for suit, royal in zip("SHDC", ROYALS):
        if royal <= hs:
            return seed, hand, suit
    return None


def main() -> None:
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    rnd = random.Random()
    found, tried, t0 = 0, 0, time.time()
    with Pool(os.cpu_count()) as pool:
        while found < want:
            batch = ["".join(rnd.choice(SEED_ALPHABET) for _ in range(8)) for _ in range(20000)]
            for res in pool.imap_unordered(check, batch, chunksize=500):
                tried += 1
                if res:
                    seed, hand, suit = res
                    found += 1
                    print(f"{seed}: royal flush in {suit}, first hand {' '.join(hand)}", flush=True)
                    if found >= want:
                        break
            rate = tried / (time.time() - t0)
            print(f"  ... {tried:,} seeds ({rate:,.0f}/s)", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
