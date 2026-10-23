"""The few pieces of on-screen geometry the game logic depends on.

A couple of game events wait for a UI box to slide into place before they run
(``update_shop`` fills the shop once ``|shop.T.y - shop.VT.y| < 3``,
``update_round_eval`` starts the cash-out evaluation once the evaluation box
arrives), so the time they take is part of the game's timeline.  This module
reproduces just that: the hand area's vertical slide (``CardArea:move``) and
the vertical motion of the UIBoxes attached to it (``Moveable:move_xy``), with
the same floating point operations as engine/moveable.lua.

Every other UIBox the logic touches (blind select, booster pack, shop sign,
...) only has its alignment fields written, so it is a plain record here.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .lua import T

if TYPE_CHECKING:
    from .game import Game

TILE_W = 20
TILE_H = 11.5
CARD_W = 2.4 * 35 / 41
CARD_H = 2.4 * 47 / 41
ROOM_PADDING_H = 0.7
ROOM_Y = ROOM_PADDING_H  # G.ROOM.T.y for a 16:9 window (wider than the room)
HAND_H = 0.95 * CARD_H


class Box:
    """A UIBox: only ``alignment.offset`` (and the ``py`` stash used by
    use_card) is read or written by the game logic."""

    def __init__(self, G: "Game", align: str = "", offset_y: float = 0.0, moving: bool = False) -> None:
        self.G = G
        self.alignment = T(type=align, offset=T(x=0, y=offset_y))
        self.removed = False
        self.areas: list[Any] = []
        self.moving = moving
        self.T_y = 0.0
        self.VT_y = 0.0
        self.vel_y = 0.0
        self.divider_added = None
        if moving:
            self._align()
            self.VT_y = self.T_y

    def _role_off(self) -> float:
        off = self.alignment.offset.y
        if "b" in self.alignment.type and "i" not in self.alignment.type:
            return off + HAND_H
        return off

    def _align(self) -> None:
        self.T_y = self.G.hand_T_y + self._role_off()

    def move(self) -> None:
        """Moveable:move for a Minor moveable with a Weak xy bond (y only)."""
        G = self.G
        self._align()
        # move_xy
        if self.T_y != self.VT_y or abs(self.vel_y) > 0.01:
            exp_xy = G.exp_xy
            vy = exp_xy * self.vel_y + (1 - exp_xy) * (self.T_y - self.VT_y) * 35 * G.move_dt
            mv = G.max_vel
            if vy * vy > mv * mv:
                actual = math.sqrt(vy * vy)
                vy = mv * vy / actual
            self.vel_y = vy
            self.VT_y = self.VT_y + vy
            if abs(self.VT_y - self.T_y) < 0.01 and abs(vy) < 0.01:
                self.VT_y = self.T_y
                self.vel_y = 0

    def remove(self) -> None:
        """UIBox:remove(): CardAreas embedded in the box go with it."""
        self.removed = True
        for area in self.areas:
            if not area.removed:
                area.remove()


def hand_desired_y(G: "Game") -> float:
    S = G.STATES
    up = (not G.deck_preview) and (G.STATE == S.SELECTING_HAND or G.STATE == S.DRAW_TO_HAND)
    return TILE_H - HAND_H - 1.9 * (1 if up else 0)


def move_hand(G: "Game") -> None:
    """The G.hand branch of CardArea:move."""
    desired = hand_desired_y(G)
    f = 15 * G.real_dt
    y = f * desired + (1 - f) * G.hand_T_y
    if abs(desired - y) < 0.01:
        y = desired
    G.hand_T_y = y
