"""PvP: two players race on the same seed, each with their own run.

The run is the original game, except that a lost round doesn't end it: the
round ends as when Mr. Bones saves it (no blind reward, then the shop), so the
two runs go through the same blinds in step.  The mod records every blind the
run resolves (played, lost or skipped) in ``blinds``; the match (``match_state``)
turns the two players' records into hit points:

- each player starts with ``START_HP`` hit points;
- once both players have finished a blind, each loses
  ``floor(other's chips / own chips)`` hit points (4 times fewer chips than the
  other: 4 hit points), but not before ante ``SAFE_ANTES + 1``;
- a player who lost the round loses ``LOSS_DAMAGE`` instead, at any ante;
- a blind is skipped only when both players skip it, so a skipped blind
  hurts nobody;
- the match is over when a player has no hit points left: the other wins (both
  at once: the one with more left; as many: a draw).

The match also makes a late player move on (``timeout_command``): the round is
lost, the cash out taken, the pack skipped, the shop left.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ..actions import IllegalAction
from . import Mod

if TYPE_CHECKING:
    from ..game import Game

START_HP = 50
LOSS_DAMAGE = 10
SAFE_ANTES = 3
_HUGE = 10 ** 9


class PvP(Mod):
    key = "pvp"

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.blinds: list[dict[str, Any]] = []
        self._skipping: str | None = None

    # -------------------------------------------------------------- rules
    def round_lost(self, G: "Game") -> bool:
        return True

    def round_ended(self, G: "Game", lost: bool, saved: bool) -> None:
        GAME = G.GAME
        b = GAME.blind
        self.blinds.append({
            "ante": GAME.round_resets.ante, "round": GAME.round, "slot": b.get_type(),
            "blind": b.config.blind.key if b.config.blind else None, "chips": GAME.chips, "target": b.chips,
            "lost": lost and not saved, "saved": saved, "skipped": False,
        })

    # ----------------------------------------------------------- commands
    def before_command(self, G: "Game", cmd: dict) -> None:
        self._skipping = G.GAME.blind_on_deck if cmd.get("cmd") == "skip_blind" else None

    def after_command(self, G: "Game", cmd: dict) -> None:
        if cmd.get("cmd") == "skip_blind" and self._skipping:
            self.blinds.append({"ante": G.GAME.round_resets.ante, "round": G.GAME.round, "slot": self._skipping,
                                "blind": None, "chips": 0, "target": 0, "lost": False, "saved": False,
                                "skipped": True})
        self._skipping = None

    def command(self, G: "Game", cmd: dict) -> bool:
        if cmd.get("cmd") != "forfeit_round":
            return False
        # the round is lost now, as if the last hand had been played (the timer ran out)
        G._require(G.STATE == G.STATES.SELECTING_HAND and G.GAME.blind is not None and G.GAME.facing_blind,
                   "not playing a round")
        G.STATE = G.STATES.NEW_ROUND
        G.STATE_COMPLETE = False
        G.settle()
        return True

    def timeout_command(self, G: "Game") -> dict | None:
        """What the game does for a player whose time ran out, in the current
        state (None at the blind select: the match decides the blind)."""
        S = G.STATES
        if G.is_game_over():
            return None
        if G.STATE == S.SELECTING_HAND:
            return {"cmd": "forfeit_round"}
        if G.STATE == S.ROUND_EVAL:
            return {"cmd": "cash_out"}
        if G.in_pack():
            if G.can_skip_pack():
                return {"cmd": "skip_pack"}
            for i, c in enumerate(G.pack_cards.cards if G.pack_cards is not None else []):
                if G.can_select_pack_card(c):
                    return {"cmd": "pick", "index": i}
            raise IllegalAction("the pack can't be left")
        if G.in_shop():
            return {"cmd": "end_shop"}
        return None

    def state(self) -> dict[str, Any]:
        return {"blinds": [dict(b) for b in self.blinds]}


# ------------------------------------------------------------------ the match
def _ratio(other: float, mine: float) -> int:
    """floor(other / mine), for any chips the game can make (inf, nan: 'naneinf')."""
    try:
        r = other / mine
    except ZeroDivisionError:
        return _HUGE if other > 0 else 0
    except OverflowError:
        return _HUGE
    if r != r or r <= 0:
        return 0
    if r == math.inf or r >= _HUGE:
        return _HUGE
    return int(math.floor(r))


def damage(mine: dict[str, Any], other: dict[str, Any] | None) -> int:
    """The hit points a player loses for one blind (``mine``) against the other player's same blind."""
    if mine.get("skipped"):
        return 0
    if mine.get("lost"):
        return LOSS_DAMAGE
    if mine.get("ante", 1) <= SAFE_ANTES or other is None or other.get("skipped"):
        return 0
    return _ratio(float(other.get("chips") or 0), float(mine.get("chips") or 0))


def match_state(blinds: list[list[dict[str, Any]]], start_hp: int = START_HP,
                eliminated: list[bool] | None = None) -> dict[str, Any]:
    """The players' hit points after the blinds both have finished.

    ``blinds``: each player's ``PvP.blinds``; ``eliminated``: a player whose
    run is over for good (the game's own game over).  Returns ``hp`` (never
    below 0), ``rounds`` (per blind both finished: each one's ``damage`` and
    ``hp`` after it), ``over`` and ``winner`` (the player's index, None for a
    draw or while it goes on)."""
    n = len(blinds)
    hp = [start_hp] * n
    rounds: list[dict[str, Any]] = []
    over = False
    for i in range(min(len(b) for b in blinds) if blinds else 0):
        entries = [b[i] for b in blinds]
        dmg = [damage(entries[p], entries[1 - p] if n == 2 else None) for p in range(n)]
        hp = [h - d for h, d in zip(hp, dmg)]
        rounds.append({"index": i, "ante": entries[0].get("ante"), "slot": entries[0].get("slot"),
                       "players": entries, "damage": dmg, "hp": [max(0, h) for h in hp]})
        if any(h <= 0 for h in hp):
            over = True
            break
    for p, out in enumerate(eliminated or []):
        if out:
            hp[p] = min(hp[p], 0)
            over = True
    winner = None
    if over:
        best = max(hp)
        leaders = [p for p, h in enumerate(hp) if h == best]
        winner = leaders[0] if len(leaders) == 1 else None
    return {"hp": [max(0, h) for h in hp], "rounds": rounds, "over": over, "winner": winner}


__all__ = ["LOSS_DAMAGE", "PvP", "SAFE_ANTES", "START_HP", "damage", "match_state"]
