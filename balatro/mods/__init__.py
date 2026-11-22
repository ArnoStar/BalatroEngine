"""Mods: changes to the game's rules, for game modes the original game doesn't have.

A mod is an object whose hooks the engine calls at fixed places of the game's
code.  Every hook does nothing by default, and a game without mods never calls
one, so a run without mods is exactly the original game (same seed, same
choices, same run).  A mod keeps to the original wherever its mode allows:
the PvP mode is the original game until a round is lost, and in the coop mode
the first player's deck, the shop, the bosses and the tags keep the original's
random streams (what the second player does can still change them).

    G = Game("SEED", mods=["pvp"]).start_run()
    G = Game("SEED", mods=[{"key": "pvp"}]).start_run()

A mod's state lives on the mod object (``G.mod("pvp")``), which ``Game.clone``
copies with the rest of the game.  Hooks:

- ``setup(G)``: in ``start_run``, once the deck, the stake and the challenge
  are applied and before the starting deck is made.
- ``start(G)``: in ``start_run``, once the starting deck is made, before the
  game runs to the blind select.
- ``blind_amount(G, ante, amount)``: a blind's base chips (``get_blind_amount``).
- ``round_lost(G)``: a round is lost: True keeps the run going (as Mr. Bones
  does: no blind reward, then the shop).
- ``round_ended(G, lost, saved)``: a round ended (``end_round``), before the
  ante goes up; ``lost``: under the blind's chips; ``saved``: a joker saved it.
- ``out_of_hands(G)`` / ``out_of_cards(G)``: whether the round ends because the
  player has no hands left / no cards left (None: the game's own rule).
- ``hand_size_changed(G, area, delta)``: the hand's size changed by ``delta``.
- ``shuffle_key(G, area, key)``: the random stream a card area is shuffled with.
- ``before_command(G, cmd)``, ``command(G, cmd)`` (True: the mod played it),
  ``after_command(G, cmd)``, ``legal_actions(G, actions)``: the player's
  commands (``Game.do``) and what is legal (``Game.legal_actions``).
- ``state()``: what the mod adds to the run's state, as plain data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from ..cardarea import CardArea
    from ..game import Game


class Mod:
    """A change to the rules (see the module's documentation)."""

    key = ""

    def __init__(self, **options: Any) -> None:
        self.options = options

    def __repr__(self) -> str:
        return f"<Mod {self.key}>"

    def spec(self) -> dict[str, Any]:
        """The mod as plain data (``make_mod`` makes it again)."""
        return {"key": self.key, **self.options}

    # ------------------------------------------------------------- set-up
    def setup(self, G: "Game") -> None:
        pass

    def start(self, G: "Game") -> None:
        pass

    # -------------------------------------------------------------- rules
    def blind_amount(self, G: "Game", ante: int, amount: float) -> float:
        return amount

    def round_lost(self, G: "Game") -> bool | None:
        return None

    def round_ended(self, G: "Game", lost: bool, saved: bool) -> None:
        pass

    def out_of_hands(self, G: "Game") -> bool | None:
        return None

    def out_of_cards(self, G: "Game") -> bool | None:
        return None

    def hand_size_changed(self, G: "Game", area: "CardArea", delta: int) -> None:
        pass

    def shuffle_key(self, G: "Game", area: "CardArea", key: str) -> str:
        return key

    # ----------------------------------------------------------- commands
    def before_command(self, G: "Game", cmd: dict) -> None:
        pass

    def command(self, G: "Game", cmd: dict) -> bool:
        return False

    def after_command(self, G: "Game", cmd: dict) -> None:
        pass

    def legal_actions(self, G: "Game", actions: list[dict]) -> list[dict]:
        return actions

    # -------------------------------------------------------------- state
    def state(self) -> dict[str, Any]:
        return {}


def registry() -> dict[str, type[Mod]]:
    from .coop import Coop
    from .pvp import PvP
    return {PvP.key: PvP, Coop.key: Coop}


def make_mod(spec: "Mod | str | dict[str, Any]") -> Mod:
    """A mod from its key (``"pvp"``), its spec (``{"key": "coop", "players": 2}``), a content
    mod's package (``{"format": 1, "id": ...}``, balatro.mods.content) or itself."""
    if isinstance(spec, Mod):
        return spec
    if isinstance(spec, str):
        spec = {"key": spec}
    if "format" in spec:  # a content mod's package (balatro.mods.content)
        from .content import ContentMod
        return ContentMod(dict(spec))
    options = dict(spec)
    key = options.pop("key", None)
    mods = registry()
    if key not in mods:
        raise ValueError(f"unknown mod {key!r} (there are {', '.join(sorted(mods))})")
    return mods[key](**options)


def make_mods(specs: Iterable["Mod | str | dict[str, Any]"] | None) -> list[Mod]:
    return [make_mod(s) for s in specs or ()]


def examples() -> dict[str, dict[str, Any]]:
    """The example content mods that come with the engine (id: package):
    ``fruit_stand`` (jokers with their own art), ``wild_rules`` (decks,
    blinds, consumables, vouchers, rules) and ``creative`` (creative mode)."""
    import json
    from pathlib import Path
    folder = Path(__file__).with_name("examples")
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(folder.glob("*.json")):
        pkg = json.loads(f.read_text())
        out[pkg["id"]] = pkg
    return out


__all__ = ["Mod", "make_mod", "make_mods", "registry", "examples"]
