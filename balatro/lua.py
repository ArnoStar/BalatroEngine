"""Small helpers that give Python code Lua-table / Lua-number semantics.

The engine is a close port of the game's Lua, so keeping the same data model
(``ability.extra.x_mult``-style tables that return ``nil`` for missing keys)
keeps the port auditable line by line against the original source.
"""

from __future__ import annotations

import math
from typing import Any


class T(dict):
    """A Lua-like table: attribute access, missing keys read as ``None``,
    assigning ``None`` deletes the key."""

    __slots__ = ()

    def __bool__(self) -> bool:  # every Lua table is truthy; use nonempty() for next(t)
        return True

    def __getattr__(self, key: str) -> Any:
        return self.get(key)

    def __setattr__(self, key: str, value: Any) -> None:
        if value is None:
            self.pop(key, None)
        else:
            self[key] = value

    def __delattr__(self, key: str) -> None:
        self.pop(key, None)

    def __repr__(self) -> str:
        return "T(" + dict.__repr__(self) + ")"


def to_T(obj: Any) -> Any:
    """Recursively convert plain dicts (e.g. from JSON) into ``T`` tables."""
    if isinstance(obj, dict):
        return T({k: to_T(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [to_T(v) for v in obj]
    return obj


def copy_table(obj: Any) -> Any:
    """``copy_table`` from misc_functions.lua: deep copy of tables."""
    if isinstance(obj, T):
        return T({k: copy_table(v) for k, v in obj.items()})
    if isinstance(obj, dict):
        return {k: copy_table(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [copy_table(v) for v in obj]
    return obj


def floor(x: float) -> float:
    """``math.floor`` that, like Lua, passes inf/nan through."""
    if x != x or x in (math.inf, -math.inf):
        return x
    return math.floor(x)


def lua_mod(a: float, b: float) -> float:
    """Lua ``a % b`` for numbers (``a - floor(a/b)*b``)."""
    if b == 0:
        return math.nan
    return a - math.floor(a / b) * b


def truthy(v: Any) -> bool:
    """Lua truthiness: only ``nil`` and ``false`` are false."""
    return v is not None and v is not False


def nonempty(t: Any) -> bool:
    """``next(t)`` on a table."""
    return t is not None and len(t) > 0
