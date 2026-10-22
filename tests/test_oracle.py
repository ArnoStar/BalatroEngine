"""Differential tests against the original game (skipped without luajit/game source)."""

import os
import shutil
from pathlib import Path

import pytest

from balatro import Game
from balatro.oracle import TOOLS, Oracle, diff, normalize

SRC = os.environ.get("BALATRO_SRC") or str(TOOLS.parents[2] / "balatro_src")
pytestmark = pytest.mark.skipif(shutil.which("luajit") is None or not Path(SRC, "game.lua").exists(),
                                reason="needs luajit and the extracted game source")


def test_scripted_round():
    cmds = [{"cmd": "select_blind"}, {"cmd": "play", "cards": [0, 1, 2, 3, 4]}, {"cmd": "discard", "cards": [0, 1]},
            {"cmd": "play", "cards": [0, 1]}, {"cmd": "play", "cards": [0, 1, 2]}]
    with Oracle() as o:
        r = o.send({"cmd": "start", "seed": "TESTSEED"})
        G = Game("TESTSEED", hands_order=r["state"]["hands_order"]).start_run()
        assert not diff(normalize(G.snapshot()), normalize(r["state"]))
        for c in cmds:
            r = o.send(c)
            G.do(c)
            assert not diff(normalize(G.snapshot()), normalize(r["state"])), c


@pytest.mark.slow
def test_fuzz_short():
    from balatro.oracle.fuzz import main
    assert main(["--runs", "2", "--seed", "5", "--steps", "60"]) == 0
