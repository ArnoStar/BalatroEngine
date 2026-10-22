"""Fast ante-1 predictions for seed searching (no Game object, no cards).

These reproduce exactly what ``Game.start_run()`` + the first ``select_blind``
compute, for a normal (non-challenge) run with an all-unlocked profile, at a
fraction of the cost.  ``tests/test_quick.py`` checks them against the engine.
"""

from __future__ import annotations

from functools import lru_cache

from . import data as data_mod
from .rng import PseudoRandom, normalize_seed

UNAVAILABLE = "UNAVAILABLE"
DECK_START_VOUCHERS = {
    "b_magic": ("v_crystal_ball",),
    "b_nebula": ("v_telescope",),
    "b_zodiac": ("v_tarot_merchant", "v_planet_merchant", "v_overstock_norm"),
}
DECK_HAND_SIZE = {"b_painted": 10}


@lru_cache(maxsize=None)
def _tag_pool(ante: int) -> tuple[str, ...]:
    d = data_mod.load()
    return tuple(t.key if (not t.min_ante or t.min_ante <= ante) else UNAVAILABLE for t in d.P_CENTER_POOLS["Tag"])


@lru_cache(maxsize=None)
def _voucher_pool(used: frozenset[str]) -> tuple[str, ...]:
    d = data_mod.load()
    out = []
    for v in d.P_CENTER_POOLS["Voucher"]:
        ok = v.key not in used and all(r in used for r in (v.requires or ()))
        out.append(v.key if ok else UNAVAILABLE)
    return tuple(out)


@lru_cache(maxsize=None)
def _ante1_bosses() -> tuple[str, ...]:
    d = data_mod.load()
    return tuple(sorted(k for k, v in d.P_BLINDS.items() if v.boss and not v.boss.showdown and v.boss.min <= 1))


def _pick(pr: PseudoRandom, pool: tuple[str, ...], key: str) -> str:
    c = pool[pr.element_index(len(pool), pr.pseudoseed(key))]
    it = 1
    while c == UNAVAILABLE:
        it += 1
        c = pool[pr.element_index(len(pool), pr.pseudoseed(key + "_resample" + str(it)))]
    return c


class Ante1:
    """Everything known at the first blind selection of a seed."""

    __slots__ = ("seed", "deck", "pr", "_tags", "_boss", "_voucher")

    def __init__(self, seed: str, deck: str = "b_red", normalize: bool = True) -> None:
        self.seed = normalize_seed(seed) if normalize else seed
        self.deck = deck
        self.pr = PseudoRandom(self.seed)
        self._tags: tuple[str, str] | None = None
        self._boss: str | None = None
        self._voucher: str | None = None

    @property
    def boss(self) -> str:
        if self._boss is None:
            pool = _ante1_bosses()
            self._boss = pool[self.pr.element_index(len(pool), self.pr.pseudoseed("boss"))]
        return self._boss

    @property
    def voucher(self) -> str:
        if self._voucher is None:
            used = frozenset(DECK_START_VOUCHERS.get(self.deck, ()))
            self._voucher = _pick(self.pr, _voucher_pool(used), "Voucher1")
        return self._voucher

    @property
    def tags(self) -> tuple[str, str]:
        if self._tags is None:
            pool = _tag_pool(1)
            small = _pick(self.pr, pool, "Tag1")
            big = _pick(self.pr, pool, "Tag1")
            self._tags = (small, big)
        return self._tags

    def starting_deck(self) -> list[str]:
        """Card keys in creation (sort_id) order."""
        d = data_mod.load()
        keys = d.P_CARDS_SORTED_KEYS
        if self.deck == "b_erratic":
            pr = PseudoRandom(self.seed)  # separate stream, state irrelevant to the others
            picks = [keys[pr.element_index(52, pr.pseudoseed("erratic"))] for _ in range(52)]
        else:
            picks = list(keys)
        protos = []
        for k in picks:
            s, r = k[0], k[2]
            if self.deck == "b_abandoned" and r in ("K", "Q", "J"):
                continue
            protos.append(s + r)
        protos.sort()
        out = [p[0] + "_" + p[1] for p in protos]
        if self.deck == "b_checkered":
            out = [("S" if k[0] == "C" else "H" if k[0] == "D" else k[0]) + k[1:] for k in out]
        return out

    def first_hand(self) -> list[str]:
        """The 8 (Painted: 10) cards drawn for the Small Blind, in draw order."""
        cards = self.starting_deck()
        pr = PseudoRandom(self.seed)
        pr.shuffle(cards, pr.pseudoseed("nr1"))
        n = DECK_HAND_SIZE.get(self.deck, 8)
        return cards[-1:-n - 1:-1]


def ante1(seed: str, deck: str = "b_red") -> Ante1:
    return Ante1(seed, deck)
