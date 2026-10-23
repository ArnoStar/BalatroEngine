"""Static game data, extracted from the original source by tools/lua/extract_data.lua.

Everything (centers, blinds, tags, pools and their ordering, poker hands,
challenges) comes straight out of the game's own tables, so it can be
regenerated for a new game version instead of being transcribed by hand.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .lua import T, to_T

DATA_FILE = Path(__file__).with_name("data") / "game_data.json"
SPRITES_FILE = Path(__file__).with_name("data") / "sprites.json"


class GameData:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.version: str = raw["version"]
        self.P_CENTERS: dict[str, T] = {k: to_T(v) for k, v in raw["centers"].items()}
        self.P_CARDS: dict[str, T] = {k: to_T(v) for k, v in raw["cards"].items()}
        self.P_BLINDS: dict[str, T] = {k: to_T(v) for k, v in raw["blinds"].items()}
        self.P_TAGS: dict[str, T] = {k: to_T(v) for k, v in raw["tags"].items()}
        self.P_SEALS: dict[str, T] = {k: to_T(v) for k, v in raw["seals"].items()}
        self.P_STAKES: dict[str, T] = {k: to_T(v) for k, v in raw["stakes"].items()}
        for d in (self.P_CENTERS, self.P_BLINDS, self.P_TAGS, self.P_SEALS, self.P_STAKES):
            for k, v in d.items():
                v.key = k
        # pools hold the prototype objects themselves, in the game's sort order
        pools = {}
        for name, keys in raw["center_pools"].items():
            src = self.P_TAGS if name == "Tag" else self.P_SEALS if name == "Seal" else (
                self.P_STAKES if name == "Stake" else self.P_CENTERS)
            pools[name] = [src[k] for k in keys]
        self.P_CENTER_POOLS: dict[str, list[T]] = pools
        self.P_JOKER_RARITY_POOLS: list[list[T]] = [
            [self.P_CENTERS[k] for k in keys] for keys in raw["joker_rarity_pools"]
        ]
        self.handlist: list[str] = raw["handlist"]
        self.hands_proto: dict[str, Any] = raw["hands"]
        self.starting_params: dict[str, Any] = raw["starting_params"]
        self.challenges: list[T] = [to_T(c) for c in raw["challenges"]]
        self.poker_hand_names: dict[str, str] = raw["poker_hand_names"]
        # P_CARDS keys sorted the way pseudorandom_element sorts string keys
        self.P_CARDS_SORTED_KEYS = sorted(k for k in self.P_CARDS if k != "empty")
        # the starting deck loop runs over pairs(G.P_CARDS); its order never
        # matters (the result is sorted, erratic draws ignore the key)
        self.P_CARDS_PAIRS_ORDER = list(self.P_CARDS_SORTED_KEYS)
        self.P_CARD_KEY = {id(v): k for k, v in self.P_CARDS.items()}
        # Card:update writes consumeable.mod_num into the shared center config
        for v in self.P_CENTERS.values():
            if v.consumeable and v.config and v.config.max_highlighted:
                v.config.mod_num = min(5, v.config.max_highlighted)
        self.by_name: dict[str, list[str]] = {}
        for k, v in self.P_CENTERS.items():
            if v.name is not None:
                self.by_name.setdefault(v.name, []).append(k)

    def center_by_name(self, name: str) -> T | None:
        for v in self.P_CENTERS.values():
            if v.name == name:
                return v
        return None

    def challenge(self, cid: str) -> T:
        for c in self.challenges:
            if c.id == cid:
                return c
        raise KeyError(f"unknown challenge {cid!r}")

    def display_name(self, key: str) -> str:
        for d in (self.P_CENTERS, self.P_TAGS, self.P_BLINDS):
            if key in d:
                return d[key].display_name or d[key].name or key
        return key


@lru_cache(maxsize=1)
def load(path: str | None = None) -> GameData:
    p = Path(path) if path else DATA_FILE
    return GameData(json.loads(p.read_text()))


@lru_cache(maxsize=1)
def sprites() -> dict[str, Any]:
    """Where the game draws each card, blind, tag, seal and sticker in its
    sprite sheets (tools/lua/extract_sprites.lua): ``atlases`` (sheet file
    and cell size) and, per key, the atlas and the cell position.  For front
    ends that use the game's own textures; the engine itself never needs it."""
    return json.loads(SPRITES_FILE.read_text())

