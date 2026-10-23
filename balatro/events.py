"""Exact port of engine/event.lua (Event, EventManager).

Balatro runs all of its game logic through this queue.  Events are handled
once per frame, in order; a *blocking* event stops every later *blockable*
event from being handled in the same frame, and timed events ('after',
'before', 'ease') wait on ``G.TIMERS.TOTAL`` (game time, scaled by the game
speed) or ``G.TIMERS.REAL``.  Several effects of the game (cards dissolving,
jokers being eaten, booster packs filling up) run in non-blockable timed
events, so *when* they happen relative to the rest of the queue changes what
the game does.  Reproducing the queue frame by frame is what makes the
engine agree with the game in those races.

Event functions follow the Lua convention: return a truthy value when the
event is complete, anything else to be called again next frame.
"""

from __future__ import annotations

import copy
import types
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .game import Game


def copy_value(v: Any, memo: dict[int, Any]) -> Any:
    """copy.deepcopy that also copies closures (deepcopy shares functions, but
    an event's function captures game objects that must be the copy's)."""
    if isinstance(v, types.FunctionType):
        return copy_function(v, memo)
    return copy.deepcopy(v, memo)


def copy_function(f: types.FunctionType, memo: dict[int, Any]) -> types.FunctionType:
    if not f.__closure__ and not f.__defaults__ and not f.__kwdefaults__:
        return f
    done = memo.get(id(f))
    if done is not None:
        return done
    todo = []
    cells = []
    for c in f.__closure__ or ():
        nc = memo.get(id(c))
        if nc is None:
            nc = types.CellType()
            memo[id(c)] = nc
            todo.append((c, nc))
        cells.append(nc)
    g = types.FunctionType(f.__code__, f.__globals__, f.__name__, None, tuple(cells) if cells else None)
    g.__qualname__ = f.__qualname__
    memo[id(f)] = g
    memo.setdefault(id(memo), []).append(f)  # keep f alive while memo is used
    for c, nc in todo:
        try:
            v = c.cell_contents
        except ValueError:  # an unassigned cell
            continue
        nc.cell_contents = copy_value(v, memo)
    if f.__defaults__:
        g.__defaults__ = tuple(copy_value(v, memo) for v in f.__defaults__)
    if f.__kwdefaults__:
        g.__kwdefaults__ = {k: copy_value(v, memo) for k, v in f.__kwdefaults__.items()}
    return g


def _true(*_a: Any) -> bool:
    return True


def _ident(t: Any) -> Any:
    return t


class Event:
    __slots__ = ("G", "trigger", "blocking", "blockable", "complete", "start_timer", "func", "delay", "no_delete",
                 "created_on_pause", "timer", "time", "ease_ref", "ease_key", "ease_start", "ease_end",
                 "ease_start_time", "ease_end_time", "ease_type", "tag")

    def __init__(self, G: "Game", func: Callable[..., Any] | None = None, trigger: str = "immediate",
                 delay: float = 0, blocking: bool = True, blockable: bool = True, no_delete: bool | None = None,
                 timer: str | None = None, start_timer: bool = False, pause_force: bool | None = None,
                 ref_table: Any = None, ref_value: Any = None, ease_to: float | None = None, ease: str = "lerp",
                 tag: str | None = None) -> None:
        self.G = G
        self.trigger = trigger
        self.blocking = blocking
        self.blockable = blockable
        self.complete = False
        self.start_timer = start_timer
        self.func = func or _true
        self.delay = delay
        self.no_delete = no_delete
        self.created_on_pause = bool(pause_force or G.SETTINGS.paused)
        self.timer = timer or ("REAL" if self.created_on_pause else "TOTAL")
        self.tag = tag
        self.ease_start_time: float | None
        self.ease_end_time: float | None
        if trigger == "ease":
            self.ease_type = ease
            self.ease_ref = ref_table
            self.ease_key = ref_value
            self.ease_start = ref_table[ref_value] if ref_table is not None else 0
            self.ease_end = ease_to
            self.ease_start_time = None
            self.ease_end_time = None
            if func is None:
                self.func = _ident
        self.time = G.TIMERS[self.timer]

    def __deepcopy__(self, memo: dict[int, Any]) -> "Event":
        new = Event.__new__(Event)
        memo[id(self)] = new
        for k in Event.__slots__:
            if hasattr(self, k):
                setattr(new, k, copy_value(getattr(self, k), memo))
        return new

    def handle(self, res: list) -> None:
        # res = [blocking, completed, time_done, pause_skip]
        res[0] = self.blocking
        res[1] = self.complete
        G = self.G
        if not self.created_on_pause and G.SETTINGS.paused:
            res[3] = True
            return
        timers = G.TIMERS
        if not self.start_timer:
            self.time = timers[self.timer]
            self.start_timer = True
        trig = self.trigger
        if trig == "after":
            if self.time + self.delay <= timers[self.timer]:
                res[2] = True
                res[1] = self.func()
        elif trig == "ease":
            now = timers[self.timer]
            if self.ease_start_time is None:
                self.ease_start_time = now
                self.ease_end_time = now + self.delay
                if self.ease_ref is not None:
                    self.ease_start = self.ease_ref[self.ease_key]
            if not self.complete:
                if self.ease_end_time >= now:
                    if self.ease_ref is not None:
                        span = self.ease_end_time - self.ease_start_time
                        pd = (self.ease_end_time - now) / span if span else 0.0
                        if self.ease_type == "lerp":
                            self.ease_ref[self.ease_key] = self.func(pd * self.ease_start + (1 - pd) * self.ease_end)
                        elif self.ease_type == "quad":
                            pd = pd * pd
                            self.ease_ref[self.ease_key] = self.func(pd * self.ease_start + (1 - pd) * self.ease_end)
                        else:  # 'elastic' is only used for visuals
                            self.ease_ref[self.ease_key] = self.func(pd * self.ease_start + (1 - pd) * self.ease_end)
                else:
                    if self.ease_ref is not None:
                        self.ease_ref[self.ease_key] = self.func(self.ease_end)
                    self.complete = True
                    res[1] = True
                    res[2] = True
        elif trig == "condition":
            if not self.complete:
                res[1] = self.func()
            res[2] = True
        elif trig == "before":
            if not self.complete:
                res[1] = self.func()
            if self.time + self.delay <= timers[self.timer]:
                res[2] = True
        elif trig == "immediate":
            res[1] = self.func()
            res[2] = True
        if res[1]:
            self.complete = True

    def __repr__(self) -> str:
        fl = ("B" if self.blocking else "-") + ("b" if self.blockable else "-")
        return f"<Event {self.trigger} {self.delay} {fl} {self.tag or getattr(self.func, '__qualname__', '?')}>"


class EventManager:
    """Only the 'base' queue matters for the game logic (the others hold
    tutorial / unlock / achievement UI), so it is the only one modelled."""

    __slots__ = ("G", "queue", "queue_timer", "queue_dt", "queue_last_processed", "_res")

    def __init__(self, G: "Game") -> None:
        self.G = G
        self.queue: list[Event] = []
        self.queue_timer = G.TIMERS["REAL"]
        self.queue_dt = 1 / 60
        self.queue_last_processed = G.TIMERS["REAL"]
        self._res = [False, False, False, False]

    def add_event(self, event: Event, front: bool = False) -> None:
        self.G._idle = None
        if front:
            self.queue.insert(0, event)
        else:
            self.queue.append(event)

    def clear_queue(self) -> None:
        self.queue[:] = [e for e in self.queue if e.no_delete]

    def update(self, dt: float, forced: bool = False) -> None:
        self.queue_timer = self.queue_timer + dt
        if self.queue_timer >= self.queue_last_processed + self.queue_dt or forced:
            self.queue_last_processed = self.queue_last_processed + (0 if forced else self.queue_dt)
            v = self.queue
            blocked = False
            res = self._res
            i = 0
            while i < len(v):
                res[0] = res[1] = res[2] = res[3] = False
                e = v[i]
                if not blocked or not e.blockable:
                    e.handle(res)
                if res[3]:
                    i += 1
                else:
                    if not blocked and res[0]:
                        blocked = True
                    if res[1] and res[2]:
                        del v[i]
                    else:
                        i += 1

    def busy(self) -> bool:
        """What the oracle (and a player) waits for: a blocking or blockable
        event that is not a 'no_delete' bookkeeping event."""
        for e in self.queue:
            if (e.blocking or e.blockable) and not e.no_delete:
                return True
        return False
