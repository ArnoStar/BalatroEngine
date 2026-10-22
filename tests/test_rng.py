"""Bit-exact checks of balatro.rng against vectors produced by the game's Lua code."""

import json
import math
import pathlib

import pytest

from balatro.rng import LuaJITRandom, PseudoRandom, pseudohash, random_string, seeded_random

VECTORS = json.loads((pathlib.Path(__file__).parent / "vectors" / "rng.json").read_text())


def same(a: float, b: float) -> bool:
    return a == b or (math.isnan(a) and math.isnan(b))


def test_pseudohash():
    for s, expected in VECTORS["hashes"]:
        assert same(pseudohash(s), float(expected)), s


def test_pseudoseed_streams():
    for seed, key, values in VECTORS["streams"]:
        pr = PseudoRandom(seed)
        got = [pr.pseudoseed(key) for _ in values]
        assert all(same(a, float(b)) for a, b in zip(got, values)), (seed, key)


def test_math_random():
    for d, values in VECTORS["randoms"]:
        rng = LuaJITRandom(float(d))
        assert [rng.random() for _ in values] == [float(v) for v in values], d
        assert seeded_random(float(d)) == float(values[0])


def test_math_random_int():
    for d, ints, ranged in VECTORS["ints"]:
        rng = LuaJITRandom(float(d))
        assert [rng.randint(i * 7) for i in range(1, len(ints) + 1)] == ints
        rng = LuaJITRandom(float(d))
        assert [rng.randint(i, i * 9) for i in range(1, len(ranged) + 1)] == ranged


@pytest.mark.parametrize("seed,ids", VECTORS["shuffles"])
def test_pseudoshuffle(seed, ids):
    pr = PseudoRandom(seed)
    items = list(range(1, 53))
    pr.shuffle(items, pr.pseudoseed("shuffle"))
    assert items == ids


def test_random_string():
    for d, s in VECTORS["strings"]:
        assert random_string(8, float(d)) == s
