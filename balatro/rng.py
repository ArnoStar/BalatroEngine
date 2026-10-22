"""Exact re-implementation of Balatro's random number generation.

Balatro never keeps a long-lived RNG.  Every random decision goes through

    pseudorandom(pseudoseed(key))      (functions/misc_functions.lua)

* ``pseudoseed(key)`` advances a per-key stream stored in
  ``G.GAME.pseudorandom[key]`` (a float in [0, 1)) and mixes it with the hash
  of the run seed.
* ``math.randomseed(x)`` re-seeds LuaJIT's Tausworthe PRNG (lib_math.c) with
  that float and ``math.random`` draws from it.

Everything here reproduces those algorithms bit for bit (IEEE doubles,
correctly rounded "%.13f" formatting), so the Python engine sees exactly the
same numbers as the game.
"""

from __future__ import annotations

import math
import struct
from typing import Any, Callable, Iterable, MutableSequence, Sequence, TypeVar

T = TypeVar("T")

MASK64 = 0xFFFFFFFFFFFFFFFF
_PI = math.pi  # 3.14159265358979323846 as a double
_E = math.e  # 2.7182818284590452354 as a double

_pack_d = struct.Struct("<d").pack
_unpack_q = struct.Struct("<Q").unpack
_pack_q = struct.Struct("<Q").pack
_unpack_d = struct.Struct("<d").unpack


def _d2u(d: float) -> int:
    return _unpack_q(_pack_d(d))[0]


def _u2d(u: int) -> float:
    return _unpack_d(_pack_q(u))[0]


class LuaJITRandom:
    """LuaJIT 2.1 ``math.random`` / ``math.randomseed`` (Tausworthe, period 2^223)."""

    __slots__ = ("u0", "u1", "u2", "u3")

    def __init__(self, seed: float = 0.0) -> None:
        self.seed(seed)

    def seed(self, d: float) -> None:
        # random_seed(): r = 0x11090601 encodes 64-k[i] for the four generators
        u = [0, 0, 0, 0]
        r = 0x11090601
        for i in range(4):
            m = 1 << (r & 255)
            r >>= 8
            d = d * _PI + _E
            v = _d2u(d)
            if v < m:
                v += m
            u[i] = v
        self.u0, self.u1, self.u2, self.u3 = u
        for _ in range(10):
            self._step()

    def _step(self) -> int:
        # TW223_GEN(0, 63, 31, 18)
        z = self.u0
        z = ((((z << 31) & MASK64) ^ z) >> 45) ^ ((z & 0xFFFFFFFFFFFFFFFE) << 18) & MASK64
        self.u0 = z
        r = z
        # TW223_GEN(1, 58, 19, 28)
        z = self.u1
        z = ((((z << 19) & MASK64) ^ z) >> 30) ^ ((z & 0xFFFFFFFFFFFFFFC0) << 28) & MASK64
        self.u1 = z
        r ^= z
        # TW223_GEN(2, 55, 24, 7)
        z = self.u2
        z = ((((z << 24) & MASK64) ^ z) >> 48) ^ ((z & 0xFFFFFFFFFFFFFE00) << 7) & MASK64
        self.u2 = z
        r ^= z
        # TW223_GEN(3, 47, 21, 8)
        z = self.u3
        z = ((((z << 21) & MASK64) ^ z) >> 39) ^ ((z & 0xFFFFFFFFFFFE0000) << 8) & MASK64
        self.u3 = z
        r ^= z
        return r

    def random(self) -> float:
        """``math.random()``: a double in [0, 1)."""
        r = self._step()
        return _u2d((r & 0x000FFFFFFFFFFFFF) | 0x3FF0000000000000) - 1.0

    def randint(self, m: float, n: float | None = None) -> int:
        """``math.random(m)`` -> [1, m]  /  ``math.random(m, n)`` -> [m, n]."""
        d = self.random()
        if n is None:
            return int(math.floor(d * m) + 1.0)
        return int(math.floor(d * (n - m + 1.0)) + m)


def seeded_random(seed: float) -> float:
    """``math.randomseed(seed); return math.random()`` (hot path, unrolled)."""
    d = seed * _PI + _E
    u0 = _d2u(d)
    if u0 < 2:  # 1 << 1  (64-63)
        u0 += 2
    d = d * _PI + _E
    u1 = _d2u(d)
    if u1 < 64:  # 1 << 6
        u1 += 64
    d = d * _PI + _E
    u2 = _d2u(d)
    if u2 < 512:  # 1 << 9
        u2 += 512
    d = d * _PI + _E
    u3 = _d2u(d)
    if u3 < 131072:  # 1 << 17
        u3 += 131072
    r = 0
    for _ in range(11):  # 10 warm-up steps + the draw
        u0 = ((((u0 << 31) & MASK64) ^ u0) >> 45) ^ ((u0 & 0xFFFFFFFFFFFFFFFE) << 18) & MASK64
        u1 = ((((u1 << 19) & MASK64) ^ u1) >> 30) ^ ((u1 & 0xFFFFFFFFFFFFFFC0) << 28) & MASK64
        u2 = ((((u2 << 24) & MASK64) ^ u2) >> 48) ^ ((u2 & 0xFFFFFFFFFFFFFE00) << 7) & MASK64
        u3 = ((((u3 << 21) & MASK64) ^ u3) >> 39) ^ ((u3 & 0xFFFFFFFFFFFE0000) << 8) & MASK64
        r = u0 ^ u1 ^ u2 ^ u3
    return _u2d((r & 0x000FFFFFFFFFFFFF) | 0x3FF0000000000000) - 1.0


def pseudohash(s: str) -> float:
    """``pseudohash(str)`` from misc_functions.lua (iterates bytes right to left)."""
    num = 1.0
    data = s.encode("latin-1")
    for i in range(len(data), 0, -1):
        if num == 0.0:
            # Lua: 1.1239285023/0 = inf, inf % 1 = nan, and nan sticks.  This
            # really happens (e.g. 'erratic' .. '7LB2WVPK') and the game keeps
            # running on the NaN stream, so we must reproduce it, not raise.
            return math.nan
        num = ((1.1239285023 / num) * data[i - 1] * _PI + _PI * i) % 1
    return num


def _advance(value: float) -> float:
    # math.abs(tonumber(string.format("%.13f", (2.134453429141 + v*1.72431234) % 1)))
    return abs(float("%.13f" % ((2.134453429141 + value * 1.72431234) % 1)))


def lua_tostring(x: Any) -> str:
    """Lua's number -> string conversion (``%.14g``) for building RNG keys."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        if x == math.floor(x) and abs(x) < 1e15:
            return str(int(x))
        return "%.14g" % x
    return str(x)


def predict_pseudoseed(key: str, seed: str) -> float:
    """``pseudoseed(key, predict_seed)``: first value of a stream, no state."""
    v = _advance(pseudohash(key + seed))
    return (v + pseudohash(seed)) / 2


class PseudoRandom:
    """The ``G.GAME.pseudorandom`` table plus the helper functions using it."""

    __slots__ = ("seed", "hashed_seed", "state", "lua")

    def __init__(self, seed: str, state: dict[str, float] | None = None) -> None:
        self.seed = seed
        self.hashed_seed = pseudohash(seed)
        self.state: dict[str, float] = dict(state) if state else {}
        # shared generator object for multi-draw operations (shuffles, ...)
        self.lua = LuaJITRandom(0.0)

    # -- pseudoseed / pseudorandom -------------------------------------------------
    def pseudoseed(self, key: str) -> float:
        st = self.state
        v = st.get(key)
        if v is None:
            v = pseudohash(key + self.seed)
        v = _advance(v)
        st[key] = v
        return (v + self.hashed_seed) / 2

    def peek(self, key: str) -> float:
        """The value ``pseudoseed(key)`` would return, without advancing."""
        v = self.state.get(key)
        if v is None:
            v = pseudohash(key + self.seed)
        return (_advance(v) + self.hashed_seed) / 2

    def random(self, key: str | float) -> float:
        """``pseudorandom(key)`` -> float in [0, 1)."""
        seed = self.pseudoseed(key) if isinstance(key, str) else key
        return seeded_random(seed)

    def randint(self, key: str | float, lo: int, hi: int) -> int:
        """``pseudorandom(key, min, max)``."""
        seed = self.pseudoseed(key) if isinstance(key, str) else key
        self.lua.seed(seed)
        return self.lua.randint(lo, hi)

    # -- element / shuffle -------------------------------------------------------------
    def element(self, items: Sequence[T], seed: float) -> T:
        """``pseudorandom_element`` for a Lua array (already in its sorted order)."""
        self.lua.seed(seed)
        return items[self.lua.randint(len(items)) - 1]

    def element_index(self, n: int, seed: float) -> int:
        """0-based index chosen by ``pseudorandom_element`` over n sorted entries."""
        self.lua.seed(seed)
        return self.lua.randint(n) - 1

    def shuffle(self, items: MutableSequence[T], seed: float) -> None:
        """``pseudoshuffle``: in-place Fisher-Yates with Lua's 1-based indices.

        The caller is responsible for pre-sorting (by ``sort_id`` for cards).
        """
        rng = self.lua
        rng.seed(seed)
        for i in range(len(items), 1, -1):
            j = rng.randint(i)
            items[i - 1], items[j - 1] = items[j - 1], items[i - 1]

    def copy(self) -> "PseudoRandom":
        return PseudoRandom(self.seed, self.state)


def sorted_by_sort_id(items: Iterable[T], key: Callable[[T], Any] | None = None) -> list[T]:
    return sorted(items, key=key or (lambda c: c.sort_id))  # type: ignore[attr-defined]


def random_string(length: int, seed: float) -> str:
    """``random_string`` from misc_functions.lua (used to generate run seeds)."""
    rng = LuaJITRandom(seed)
    out = []
    for _ in range(length):
        if rng.random() > 0.7:
            c = rng.randint(ord("1"), ord("9"))
        elif rng.random() > 0.45:
            c = rng.randint(ord("A"), ord("N"))
        else:
            c = rng.randint(ord("P"), ord("Z"))
        out.append(chr(c))
    return "".join(out).upper()


SEED_ALPHABET = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"


def normalize_seed(seed: str) -> str:
    """Seeds typed in the game are upper-cased; '0' is not part of the alphabet."""
    return seed.upper().replace("0", "O")
