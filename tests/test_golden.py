"""Runs recorded from the original game (``fuzz --record``), replayed offline.

Each record holds the commands of one run and the game's complete final
state, so these check the engine against the real game without luajit.
"""

import json
from pathlib import Path

import pytest

from balatro import Game
from balatro.oracle import diff, normalize

VECTORS = Path(__file__).with_name("vectors") / "golden.jsonl"
RECORDS = [json.loads(line) for line in VECTORS.read_text().splitlines() if line.strip()] if VECTORS.exists() else []


@pytest.mark.parametrize("rec", RECORDS, ids=[f"{r['seed']}-{r.get('challenge') or r['deck']}" for r in RECORDS])
def test_recorded_run(rec):
    start = rec["log"][0]
    g0 = Game("X")
    deck = g0.data.center_by_name(start["deck"]).key if start.get("deck") else "b_red"
    G = Game(start["seed"], deck=deck, stake=start.get("stake", 1), challenge=start.get("challenge"),
             hands_order=rec["final"]["hands_order"], game_speed=rec.get("gamespeed", 1)).start_run()
    for cmd in rec["log"][1:]:
        G.do(cmd)
    d = diff(normalize(G.snapshot()), rec["final"])
    assert not d, "\n".join(d[:30])
