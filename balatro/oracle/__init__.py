"""Run the ORIGINAL game code (LuaJIT, headless) as a ground-truth oracle.

Needs ``luajit`` on PATH and the extracted game source (BALATRO_SRC env var,
default: ../balatro_src next to this repository).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "lua"


class OracleError(RuntimeError):
    pass


class Oracle:
    def __init__(self, src: str | None = None, profile: str = "all", gamespeed: float = 1, dt: float = 1 / 60) -> None:
        luajit = shutil.which("luajit")
        if luajit is None:
            raise OracleError("luajit not found on PATH")
        if not (TOOLS / "oracle.lua").exists():
            raise OracleError(f"{TOOLS / 'oracle.lua'} not found: the oracle runs from a source checkout")
        env = dict(os.environ)
        if src:
            env["BALATRO_SRC"] = src
        env["ORACLE_PROFILE"] = profile
        env["ORACLE_GAMESPEED"] = str(gamespeed)
        env["ORACLE_DT"] = repr(dt)
        log = os.environ.get("ORACLE_LOG")
        self._log = open(log, "a") if log else subprocess.DEVNULL
        self.proc = subprocess.Popen([luajit, str(TOOLS / "oracle.lua")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self._log, text=True, env=env, bufsize=1)

    def send(self, cmd: dict[str, Any]) -> dict[str, Any]:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(cmd) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise OracleError("oracle process died")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise OracleError(reply.get("error", "unknown error"))
        return reply

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                assert self.proc.stdin
                self.proc.stdin.write('{"cmd":"quit"}\n')
                self.proc.stdin.flush()
            except Exception:
                pass
            self.proc.wait(timeout=5)

    def __enter__(self) -> "Oracle":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


AREAS = ("deck", "hand", "discard", "play", "jokers", "consumeables", "shop_jokers", "shop_vouchers",
         "shop_booster", "pack_cards")


def normalize(state: dict) -> dict:
    """Make a snapshot comparable: replace absolute sort_ids by ranks."""
    s = json.loads(json.dumps(state))
    ids = []
    for area in ("deck", "hand", "discard", "play", "jokers", "consumeables", "shop_jokers", "shop_vouchers",
                 "shop_booster", "pack_cards"):
        for c in s.get(area) or []:
            ids.append(c["sort_id"])
    for area in AREAS:
        if s.get(area) == {}:
            s[area] = []
    rank = {v: i for i, v in enumerate(sorted(set(ids)))}
    for area in ("deck", "hand", "discard", "play", "jokers", "consumeables", "shop_jokers", "shop_vouchers",
                 "shop_booster", "pack_cards"):
        for c in s.get(area) or []:
            c["sort_id"] = rank[c["sort_id"]]
    s.pop("state_complete", None)
    return _canon(s)


# packs whose variant (_1/_2) is picked with math.random on the *global*
# LuaJIT state (purely cosmetic, identical contents)
COSMETIC_KEYS = {"p_buffoon_normal_2": "p_buffoon_normal_1", "p_arcana_mega_2": "p_arcana_mega_1",
                 "p_celestial_mega_2": "p_celestial_mega_1"}


def _canon(v: Any) -> Any:
    """Lua/JSON artifacts: nil keys are absent, empty tables encode as {}."""
    if isinstance(v, dict):
        if not v:
            return []
        return {k: _canon(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_canon(x) for x in v]
    if isinstance(v, str):
        return COSMETIC_KEYS.get(v, v)
    return v


def diff(a: Any, b: Any, path: str = "") -> list[str]:
    """Readable differences between two normalized snapshots."""
    out: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append(f"{path}.{k}: missing in python (oracle={b[k]!r})")
            elif k not in b:
                out.append(f"{path}.{k}: missing in oracle (python={a[k]!r})")
            else:
                out.extend(diff(a[k], b[k], f"{path}.{k}"))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(diff(x, y, f"{path}[{i}]"))
    elif a != b:
        out.append(f"{path}: python={a!r} oracle={b!r}")
    return out
