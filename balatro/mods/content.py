"""Content mods: new jokers, consumables, vouchers, decks, boss blinds and rules,
as data (a package, see ``spec`` and docs/mods.md).

    G = Game("SEED", mods=[package]).start_run()      # package: the mod's JSON

A ``ContentMod`` compiles its package once: each item becomes a center (a
blind) like the game's own, keyed ``j_<mod id>_<key>`` and so on, whose
``mod_item`` the engine's hooks read (calculate_joker, use_consumeable,
apply_to_run, Back.apply_to_run, Blind).  The game's data tables are copied
for a game with content mods (``extend_data``), so the original game's tables
never change: a run without mods is still exactly the original game.

A run with content mods unlocks and discovers nothing (its rules aren't the
game's).
"""

from __future__ import annotations

import copy
import math
from typing import TYPE_CHECKING, Any, Callable

from ..lua import T, nonempty, to_T
from . import Mod
from . import expr as E
from . import spec as S

if TYPE_CHECKING:
    from ..card import Card
    from ..data import GameData
    from ..game import Game


class ModError(ValueError):
    """A package that can't be played: ``errors`` says why (paths in the package)."""

    def __init__(self, errors: list[str], mod_id: str | None = None) -> None:
        self.errors = list(errors)
        self.mod_id = mod_id
        head = f"mod {mod_id!r}: " if mod_id else ""
        more = f" (and {len(errors) - 3} more)" if len(errors) > 3 else ""
        super().__init__(head + "; ".join(errors[:3]) + more)


def _x(v: Any) -> E.Node:
    """An expression from the package (a number or true/false stands for itself)."""
    if isinstance(v, bool) or E.is_number(v):
        return ("const", v)
    return E.parse(v)


def _num(v: Any) -> float | None:
    return v if E.is_number(v) and v == v else None


# ===================================================================== items
class Item:
    """One item of a package, compiled: its center (or blind) and what it does."""

    def __init__(self, mod: "ContentMod", kind: str, spec: dict[str, Any]) -> None:
        self.mod = mod
        self.kind = kind
        self.spec = spec
        self.short = spec["key"]
        self.key = S.full_key(mod.id, kind, spec["key"])
        self.rng_key = f"{mod.id}_{spec['key']}"
        self.config: dict[str, Any] = dict(spec.get("config") or {})
        # trigger: [(condition, actions, actions when the condition is false)]
        self.effects: dict[str, list[tuple[E.Node | None, list[tuple[str, Any]], list[tuple[str, Any]] | None]]] = {}
        for eff in spec.get("effects", []):
            cond = _x(eff["if"]) if "if" in eff else None
            otherwise = _actions(eff["else"]) if "else" in eff else None
            self.effects.setdefault(eff["on"], []).append((cond, _actions(eff.get("do", [])), otherwise))
        self.use = _actions(spec["use"]) if "use" in spec else None
        self.redeem = _actions(spec.get("redeem", []))
        self.can_use = _x(spec["can_use"]) if "can_use" in spec else None
        self.targets: tuple[int, int] | None = None
        if "targets" in spec:
            lo = spec["targets"].get("min", 1)
            self.targets = (lo, spec["targets"].get("max", lo))
        self.passive: dict[str, float] = dict(spec.get("passive") or {})
        self.blueprint_compat = spec.get("blueprint_compat", True)
        self.debuff_card = _x(spec["debuff_card"]) if "debuff_card" in spec else None
        self.debuff_hand = _x(spec["debuff_hand"]) if "debuff_hand" in spec else None
        self.on_set = _actions(spec.get("on_set", []))
        self.on_hand = _actions(spec.get("on_hand", []))

    def __deepcopy__(self, memo: dict[int, Any]) -> "Item":
        return self  # (compiled once, never changed: shared by a game's copies)

    def __repr__(self) -> str:
        return f"<Item {self.key}>"


def _actions(actions: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for a in actions:
        (name, arg), = a.items()
        if name in ("chips", "mult", "xmult", "dollars", "retrigger", "hands", "discards"):
            arg = _x(arg)
        elif name == "set":
            arg = {k: _x(v) for k, v in arg.items()}
        elif name == "level_up":
            if isinstance(arg, dict):
                arg = {"hand": _x(arg["hand"]) if "hand" in arg else None,
                       "levels": _x(arg.get("levels", 1))}
            else:
                arg = {"hand": None, "levels": _x(arg)}
        elif name == "modify_run":
            arg = {k: _x(v) for k, v in arg.items()}
        elif name == "modify":
            arg = dict(arg)
            if "where" in arg:
                arg["where"] = _x(arg["where"])
            if "chips" in arg:
                arg["chips"] = _x(arg["chips"])
        out.append((name, arg))
    return out


# ===================================================================== the mod
class ContentMod(Mod):
    """A content mod, from its package (``spec``).  Raises ModError for a
    package that isn't valid."""

    def __init__(self, package: dict[str, Any]) -> None:
        errors = S.validate(package)
        if errors:
            raise ModError(errors, package.get("id") if isinstance(package, dict) else None)
        super().__init__()
        self.package = package
        self.id: str = package["id"]
        self.key = self.id
        self.version: str = package["version"]
        self.name: str = package["name"]
        self.rules: dict[str, float] = dict(package.get("rules") or {})
        self.creative = bool(package.get("creative"))
        self.items: list[Item] = []
        for kind in ("jokers", "consumables", "vouchers", "decks", "blinds"):
            for it in package.get(kind, []):
                self.items.append(Item(self, kind, it))
        self.centers: dict[str, T] = {}
        self.blinds: dict[str, T] = {}
        for item in self.items:
            if item.kind == "blinds":
                self.blinds[item.key] = _blind_center(item)
            else:
                self.centers[item.key] = _center(item)

    def __repr__(self) -> str:
        return f"<ContentMod {self.id} {self.version}>"

    def __deepcopy__(self, memo: dict[int, Any]) -> "ContentMod":
        return self  # (no state of its own: the run's state is in the cards' abilities)

    def spec(self) -> dict[str, Any]:
        return self.package

    def setup(self, G: "Game") -> None:
        if self.rules:
            apply_modifiers(G, {k: v for k, v in self.rules.items()}, 1, start=True)

    def command(self, G: "Game", cmd: dict) -> bool:
        if self.creative and cmd.get("cmd") == "creative":
            from .creative import creative
            creative(G, cmd)
            return True
        return False

    def legal_actions(self, G: "Game", actions: list[dict]) -> list[dict]:
        if self.creative and not G.is_game_over() and not any(a.get("cmd") == "creative" for a in actions):
            return actions + [{"cmd": "creative"}]
        return actions

    def state(self) -> dict[str, Any]:
        return {"id": self.id, "version": self.version, "creative": self.creative}


def _sprite_pos(item: Item) -> T:
    s = item.spec.get("sprite")
    if isinstance(s, dict) and "x" in s:
        return T(x=s["x"], y=s["y"])
    return T(x=0, y=0)


def _center(item: Item) -> T:
    s = item.spec
    kind = item.kind
    c = T(key=item.key, name=item.key, display_name=s["name"], unlocked=True, discovered=True, alerted=True,
          pos=_sprite_pos(item), mod=item.mod.id)
    if kind == "jokers":
        c.update(set="Joker", rarity=s.get("rarity", 1), cost=s.get("cost", 5),
                 blueprint_compat=item.blueprint_compat, eternal_compat=s.get("eternal_compat", True),
                 perishable_compat=s.get("perishable_compat", True),
                 config=T(extra=to_T(dict(item.config)) if item.config else None))
    elif kind == "consumables":
        cfg = T(extra=to_T(dict(item.config)) if item.config else None)
        if "hand" in s:
            cfg.hand_type = s["hand"]
        if item.targets is not None:
            cfg.min_highlighted = item.targets[0]
            cfg.max_highlighted = item.targets[1]
            cfg.mod_num = min(5, item.targets[1])
        c.update(set=s["set"], consumeable=True, cost=s.get("cost", 4 if s["set"] == "Spectral" else 3), config=cfg)
    elif kind == "vouchers":
        c.update(set="Voucher", cost=s.get("cost", 10), available=True,
                 config=T(extra=to_T(dict(item.config)) if item.config else None),
                 requires=list(s["requires"]) if s.get("requires") else None)
    elif kind == "decks":
        c.update(set="Back", stake=1, config=T())
    c.mod_item = item
    return c


def _blind_center(item: Item) -> T:
    s = item.spec
    b = T(key=item.key, name=item.key, display_name=s["name"], mult=s.get("mult", 2), dollars=s.get("dollars", 5),
          debuff=T(), vars=T(), defeated=False, discovered=True, mod=item.mod.id,
          boss=T(min=s.get("min_ante", 1), max=s.get("max_ante", 10), showdown=True if s.get("showdown") else None))
    b.mod_item = item
    return b


# ===================================================================== data
POOLS = {"Joker": ("Joker",), "Tarot": ("Tarot", "Tarot_Planet", "Consumeables"),
         "Planet": ("Planet", "Tarot_Planet", "Consumeables"), "Spectral": ("Spectral", "Consumeables"),
         "Voucher": ("Voucher",), "Back": ("Back",)}


def extend_data(base: "GameData", mods: list[ContentMod]) -> "GameData":
    """The game's data with the mods' items added (the original stays as it is)."""
    d = copy.copy(base)
    d.P_CENTERS = dict(base.P_CENTERS)
    d.P_BLINDS = dict(base.P_BLINDS)
    d.P_CENTER_POOLS = {k: list(v) for k, v in base.P_CENTER_POOLS.items()}
    d.P_JOKER_RARITY_POOLS = [list(p) for p in base.P_JOKER_RARITY_POOLS]
    d.by_name = {k: list(v) for k, v in base.by_name.items()}
    order = 1000
    errors: list[str] = []
    ids: set[str] = set()
    for mod in mods:
        if mod.id in ids:
            errors.append(f"mod {mod.id!r} is there twice")
            continue
        ids.add(mod.id)
        for key, c in mod.centers.items():
            if key in d.P_CENTERS:
                errors.append(f"mod {mod.id!r}: {key!r} is already in the game")
                continue
            order += 1
            if c.order is None:
                c.order = order
            d.P_CENTERS[key] = c
            d.by_name[c.name] = [key]
            item: Item = c.mod_item
            if item.kind == "jokers" and not item.spec.get("in_shop", True):
                continue  # (only made by name: a deck, a challenge, an effect's create)
            for pool in POOLS[c.set]:
                d.P_CENTER_POOLS[pool].append(c)
            if c.set == "Joker":
                d.P_JOKER_RARITY_POOLS[c.rarity - 1].append(c)
        for key, b in mod.blinds.items():
            if key in d.P_BLINDS:
                errors.append(f"mod {mod.id!r}: {key!r} is already in the game")
                continue
            order += 1
            if b.order is None:
                b.order = order
            d.P_BLINDS[key] = b
    for mod in mods:
        for path, key in S.references(mod.package):
            if key not in d.P_CENTERS and key not in d.P_TAGS and key not in d.P_BLINDS:
                errors.append(f"mod {mod.id!r}: {path}: there is no {key!r} (in the game or the run's mods)")
    if errors:
        raise ModError(errors)
    return d


def content_mods(mods: list[Mod]) -> list[ContentMod]:
    return [m for m in mods if isinstance(m, ContentMod)]


# ===================================================================== reading the game
def _card_field(c: Any, name: str) -> Any:
    from ..card import Card
    if not isinstance(c, Card):
        return None
    ab = c.ability
    playing = ab.set in ("Default", "Enhanced")
    if name == "rank":
        return c.get_id() if playing else None
    if name == "rank_name":
        return c.base.value if playing else None
    if name == "suit":
        return c.base.suit if playing else None
    if name == "face":
        return bool(c.is_face()) if playing else False
    if name == "chips":
        return c.base.nominal if playing else None
    if name == "enhancement":
        return c.config.center.key if ab.set == "Enhanced" else None
    if name == "seal":
        return c.seal
    if name == "edition":
        return c.edition.type if c.edition else None
    if name == "debuffed":
        return bool(c.debuff)
    if name == "key":
        return c.config.center.key
    if name == "set":
        return ab.set
    if name == "rarity":
        return c.config.center.rarity
    if name == "sell_value":
        return c.sell_cost
    if name == "cost":
        return c.cost
    return None


def _game_field(G: "Game", name: str) -> Any:
    GAME = G.GAME
    cr = GAME.current_round
    rr = GAME.round_resets
    if name == "money":
        return GAME.dollars + (GAME.dollar_buffer or 0)
    if name == "ante":
        return rr.ante
    if name == "round":
        return GAME.round
    if name == "hands_left":
        return cr.hands_left
    if name == "discards_left":
        return cr.discards_left
    if name == "hands_played":
        return cr.hands_played
    if name == "discards_used":
        return cr.discards_used
    if name == "hand_size":
        return G.hand.config.card_limit if G.hand is not None else GAME.starting_params.hand_size
    if name == "deck_count":
        return len(G.deck.cards) if G.deck is not None else 0
    if name == "full_deck_count":
        return len(G.playing_cards)
    if name == "joker_count":
        return len(G.jokers.cards) if G.jokers is not None else 0
    if name == "joker_slots":
        return G.jokers.config.card_limit if G.jokers is not None else GAME.starting_params.joker_slots
    if name == "consumable_count":
        return len(G.consumeables.cards) if G.consumeables is not None else 0
    if name == "consumable_slots":
        return G.consumeables.config.card_limit if G.consumeables is not None else 0
    if name == "probability":
        return GAME.probabilities.normal
    if name == "blind_boss":
        return bool(GAME.blind and GAME.blind.boss)
    if name == "blind_chips":
        return GAME.blind.chips if GAME.blind else 0
    if name == "round_chips":
        return GAME.chips
    if name == "skips":
        return GAME.skips
    if name == "rerolls":
        return GAME.round_scores.times_rerolled.amt
    if name == "interest_cap":
        return GAME.interest_cap
    if name == "stake":
        return GAME.stake
    if name == "hands_per_round":
        return rr.hands
    if name == "discards_per_round":
        return rr.discards
    return None


class _Env(E.Env):
    """What a mod's expression reads in the game, where it runs."""

    def __init__(self, G: "Game", item: Item, values: Any = None, joker: Any = None, card: Any = None,
                 other: Any = None, context: T | None = None, extra: dict[str, Any] | None = None) -> None:
        self.G = G
        self.item = item
        self.values = values if values is not None else item.config
        self.joker = joker
        self.card = card
        self.other = other
        self.context = context or T()
        self.extra = extra or {}

    def with_card(self, card: Any) -> "_Env":
        e = copy.copy(self)
        e.card = card
        return e

    def _hand_name(self) -> str | None:
        return self.extra.get("hand_name") or self.context.scoring_name

    def lookup(self, root: str, path: tuple[str, ...]) -> Any:
        G = self.G
        first = path[0] if path else None
        if root == "self":
            if first is None:
                return None
            v = self.values.get(first) if hasattr(self.values, "get") else None
            return v if len(path) == 1 else None
        if root in ("card", "other"):
            base = self.card if root == "card" else self.other
        elif root == "game":
            base = _game_field(G, first) if first else None
            return base if len(path) == 1 else None
        elif root == "joker":
            j = self.joker
            if j is None or first is None:
                return None
            if first == "position":
                cards = G.jokers.cards if G.jokers is not None else []
                return next((i + 1 for i, c in enumerate(cards) if c is j), None)
            if first == "sell_value":
                return j.sell_cost
            if first == "edition":
                return j.edition.type if j.edition else None
            return None
        elif root == "hand":
            name = self._hand_name()
            if name is None or first is None or name not in G.GAME.hands:
                return None
            h = G.GAME.hands[name]
            played = self.extra.get("played", self.context.full_hand) or []
            scoring = self.extra.get("scoring", self.context.scoring_hand) or []
            return {"name": name, "level": h.level, "played": h.played, "played_this_round": h.played_this_round,
                    "count": len(played), "scoring_count": len(scoring), "chips": h.chips,
                    "mult": h.mult}.get(first)
        elif root == "blind":
            b = self.context.blind
            if b is None or first is None:
                return None
            return {"boss": bool(b.boss), "key": b.key, "chips": G.GAME.blind.chips if G.GAME.blind else None,
                    "mult": b.mult, "dollars": b.dollars}.get(first)
        elif root == "event":
            return self.extra.get("event", {}).get(first) if first else None
        else:
            base = self._list(root)
        if not path:
            return base
        v = _card_field(base, path[0])
        return v if len(path) == 1 else None

    def _list(self, root: str) -> Any:
        G = self.G
        c = self.context
        if root == "jokers":
            return list(G.jokers.cards) if G.jokers is not None else []
        if root == "consumables":
            return list(G.consumeables.cards) if G.consumeables is not None else []
        if root == "full_deck":
            return list(G.playing_cards)
        if root == "deck":
            return list(G.deck.cards) if G.deck is not None else []
        if root == "held":
            return list(G.hand.cards) if G.hand is not None else []
        if root == "scoring":
            return list(self.extra.get("scoring", c.scoring_hand) or [])
        if root == "played":
            return list(self.extra.get("played", c.full_hand) or [])
        if root == "discarded":
            return list(c.full_hand or [])
        if root == "selected":
            return list(G.hand.highlighted) if G.hand is not None else []
        return None

    def field(self, value: Any, name: str) -> Any:
        return _card_field(value, name)

    def call(self, name: str, args: list[Any]) -> Any:
        G = self.G
        GAME = G.GAME
        from ..card import Card
        if name == "is_suit":
            c, suit = args
            return bool(c.is_suit(suit)) if isinstance(c, Card) and isinstance(suit, str) else False
        if name == "is_rank":
            c, r = args
            if not isinstance(c, Card) or c.ability.set not in ("Default", "Enhanced"):
                return False
            return c.get_id() == r if E.is_number(r) else c.base.value == r
        if name == "is_face":
            c = args[0]
            return bool(c.is_face()) if isinstance(c, Card) else False
        if name.startswith("count"):
            cards = args[0] if isinstance(args[0], list) else []
            if name == "count":
                return len(cards)
            arg = args[1] if len(args) > 1 else None
            test: Callable[[Card], bool] = {
                "count_suit": lambda c: bool(c.is_suit(arg)),
                "count_rank": lambda c: (c.ability.set in ("Default", "Enhanced")
                                         and (c.get_id() == arg if E.is_number(arg) else c.base.value == arg)),
                "count_face": lambda c: c.ability.set in ("Default", "Enhanced") and bool(c.is_face()),
                "count_enhancement": lambda c: c.config.center.key == arg,
                "count_seal": lambda c: c.seal == arg,
                "count_edition": lambda c: bool(c.edition) and c.edition.type == arg,
                "count_key": lambda c: c.config.center.key == arg,
            }.get(name, lambda c: False)
            return sum(1 for c in cards if isinstance(c, Card) and test(c))
        if name == "hand_level":
            h = GAME.hands.get(args[0]) if isinstance(args[0], str) else None
            return h.level if h else None
        if name == "times_played":
            h = GAME.hands.get(args[0]) if isinstance(args[0], str) else None
            return h.played if h else None
        if name == "has_joker":
            return G.jokers is not None and any(j.config.center.key == args[0] for j in G.jokers.cards)
        if name == "has_voucher":
            return bool(GAME.used_vouchers.get(args[0])) if isinstance(args[0], str) else False
        if name == "has_hand":
            ph = self.extra.get("poker_hands", self.context.poker_hands)
            return bool(ph is not None and isinstance(args[0], str) and nonempty(ph.get(args[0])))
        if name in ("chance", "random"):
            label = args[2] if len(args) > 2 and isinstance(args[2], str) else ""
            key = self.item.rng_key + ("_" + label if label else "")
            if name == "chance":
                n, d = args[0], args[1]
                if not (E.is_number(n) and E.is_number(d)) or d == 0:
                    return False
                return G.rng.random(key) < GAME.probabilities.normal * n / d
            lo, hi = args[0], args[1]
            if not (E.is_number(lo) and E.is_number(hi)):
                return None
            lo, hi = int(math.floor(lo)), int(math.floor(hi))
            return G.rng.randint(key, min(lo, hi), max(lo, hi))
        return None


def ev(node: E.Node | None, env: _Env) -> Any:
    return None if node is None else E.evaluate(node, env)


# ===================================================================== run modifiers
def apply_modifiers(G: "Game", values: dict[str, Any], sign: int = 1, start: bool = False) -> None:
    """Change the run (a mod's rules, a deck's start, a joker's passive changes, modify_run).
    ``start``: before the run's starting numbers are taken (start_run)."""
    GAME = G.GAME
    sp = GAME.starting_params
    rr = GAME.round_resets
    for k, v in values.items():
        if not E.is_number(v):
            continue
        if k == "probability_mult":
            if v == 0:
                continue
            for p in list(GAME.probabilities):
                GAME.probabilities[p] = GAME.probabilities[p] * v if sign > 0 else GAME.probabilities[p] / v
            continue
        if k == "blind_scale":
            sp.ante_scaling = sp.ante_scaling * v
            continue
        n = v * sign
        if k == "interest_cap":
            GAME.interest_cap = GAME.interest_cap + n
        elif k == "win_ante":
            GAME.win_ante = max(1, GAME.win_ante + int(n))
        elif k == "discount_percent":
            GAME.discount_percent = max(0, min(100, GAME.discount_percent + n))
            if not start:
                G.ev(G.refresh_all_costs)
        elif start:
            if k == "shop_slots":
                GAME.shop.joker_max = max(1, GAME.shop.joker_max + int(n))
            elif k in ("dollars", "hands", "discards", "hand_size", "joker_slots", "consumable_slots",
                       "reroll_cost"):
                sp[k] = max(0 if k in ("dollars", "reroll_cost", "discards", "joker_slots", "consumable_slots")
                            else 1, sp[k] + n) if k != "dollars" else sp[k] + n
        elif k == "dollars":
            G.ease_dollars(n)
        elif k == "hands":
            rr.hands = max(1, rr.hands + n)
            G.ease_hands_played(n)
        elif k == "discards":
            rr.discards = max(0, rr.discards + n)
            G.ease_discard(n)
        elif k == "hand_size":
            if G.hand is not None:
                G.hand.change_size(int(n))
        elif k == "joker_slots":
            if G.jokers is not None:
                G.jokers.config.card_limit = G.jokers.config.card_limit + int(n)
        elif k == "consumable_slots":
            if G.consumeables is not None:
                G.consumeables.config.card_limit = G.consumeables.config.card_limit + int(n)
        elif k == "reroll_cost":
            rr.reroll_cost = rr.reroll_cost + n
            GAME.current_round.reroll_cost = max(0, GAME.current_round.reroll_cost + n)
        elif k == "shop_slots":
            G.change_shop_size(int(n))


# ===================================================================== actions
_RETURNING = ("hand_played", "hand_finished", "round_end", "discard", "hand_not_allowed", "score", "other_joker")


class _Run:
    """One pass of an item's effects (their actions add up)."""

    def __init__(self, G: "Game", item: Item, env: _Env, trigger: str | None, src: Any,
                 owner: Any = None, blueprint: bool = False) -> None:
        self.G = G
        self.item = item
        self.env = env
        self.trigger = trigger
        self.src = src            # the card its texts show on (a Blueprint copying it: the Blueprint)
        self.owner = owner        # the joker whose values ``set`` changes
        self.blueprint = blueprint
        self.fired = False
        self.chips = 0.0
        self.mult = 0.0
        self.xmult: float | None = None
        self.dollars = 0.0
        self.reps = 0
        self.message: str | None = None
        self.remove = False
        self.destroy_self = False

    def status(self, message: str | None = None, dollars: float | None = None) -> None:
        G = self.G
        if dollars:
            G.card_eval_status_text(self.src, "dollars", dollars)
        if message:
            G.card_eval_status_text(self.src, "extra", None, None, None, T(message=message))

    def act(self, name: str, arg: Any) -> None:  # noqa: C901
        G = self.G
        GAME = G.GAME
        env = self.env
        t = self.trigger
        if name in ("chips", "mult", "xmult"):
            v = _num(ev(arg, env))
            if v is None:
                return
            if name == "chips":
                self.chips += v
            elif name == "mult":
                self.mult += v
            else:
                self.xmult = v if self.xmult is None else self.xmult * v
        elif name == "dollars":
            v = _num(ev(arg, env))
            if not v:
                return
            self.dollars += v
            if G.hand is None:  # (the start of the run: a deck's voucher)
                apply_modifiers(G, {"dollars": v}, 1, start=True)
            elif t in ("card_scored", "card_held"):
                _dollar_buffer(G, v)  # (the scoring loop eases them)
            elif t == "cash_out":
                pass
            elif t in _RETURNING:
                G.ease_dollars(v)
                _dollar_buffer(G, v)
            elif self.item.kind == "consumables":
                G.ev(lambda: G.ease_dollars(v, True), trigger="after", delay=0.4)
                G.delay(0.6)
            else:
                G.ease_dollars(v)
                if self.item.kind == "jokers":
                    self.status(dollars=v)
        elif name == "retrigger":
            v = _num(ev(arg, env))
            if v and v > 0:
                self.reps += int(v)
        elif name == "set":
            if self.blueprint or self.owner is None:
                return
            extra = self.owner.ability.extra
            new = {k: ev(node, env) for k, node in arg.items()}
            for k, v in new.items():
                if v is not None and not isinstance(v, (list, dict)) and not hasattr(v, "ability"):
                    extra[k] = v
        elif name == "message":
            self.message = arg
        elif name == "level_up":
            hand = ev(arg["hand"], env) if arg["hand"] is not None else env._hand_name()
            levels = _num(ev(arg["levels"], env))
            if not isinstance(hand, str) or hand not in GAME.hands or not levels:
                return
            levels = int(levels)
            if G.hand is None:
                G.ev(lambda: G.level_up_hand(None, hand, True, levels))
            elif t in ("hand_played", "score", "hand_finished"):
                G.level_up_hand(self.src, hand, None, levels)
            else:
                h = GAME.hands[hand]
                G.update_hand_text(T(sound="button", volume=0.7, pitch=0.8, delay=0.3),
                                   T(handname=hand, chips=h.chips, mult=h.mult, level=h.level))
                G.level_up_hand(self.src, hand, None, levels)
                G.update_hand_text(T(sound="button", volume=0.7, pitch=1.1, delay=0),
                                   T(mult=0, chips=0, handname="", level=""))
        elif name == "create":
            if G.jokers is None:  # (the start of the run: once the card areas are there)
                G.ev(lambda: _create(G, self.item, arg))
            else:
                _create(G, self.item, arg, consumable_use=self.item.kind == "consumables")
        elif name == "destroy_self":
            if arg and not self.blueprint:
                self.destroy_self = True
        elif name == "destroy_card":
            if arg:
                self.remove = True
        elif name in ("hands", "discards"):
            v = _num(ev(arg, env))
            if v and G.hand is not None:
                v = int(v)
                (G.ease_hands_played if name == "hands" else G.ease_discard)(v)
        elif name == "modify_run":
            apply_modifiers(G, {k: ev(node, env) for k, node in arg.items()}, 1, start=G.hand is None)
        elif name == "modify":
            _modify(G, self, arg)
        elif name == "add_tag":
            from ..tag import Tag
            G.ev(lambda: G.add_tag(Tag(G, arg)))
        elif name == "disable_boss":
            if arg and GAME.blind and GAME.blind.boss and not GAME.blind.disabled:
                def dis() -> None:
                    GAME.blind.disable()
                G.ev(dis)
                if self.message is None:
                    self.message = "ph_boss_disabled"


def _dollar_buffer(G: "Game", amount: float) -> None:
    GAME = G.GAME
    GAME.dollar_buffer = (GAME.dollar_buffer or 0) + amount

    def clear() -> None:
        GAME.dollar_buffer = 0
    G.ev(clear)


def _create(G: "Game", item: Item, arg: dict[str, Any], consumable_use: bool = False) -> None:
    GAME = G.GAME
    s = arg["set"]
    key = arg.get("key")
    edition = arg.get("edition")
    append = item.rng_key
    if s == "Joker":
        negative = edition == "negative"
        if not negative and len(G.jokers.cards) + GAME.joker_buffer >= G.jokers.config.card_limit:
            return
        if not negative:
            GAME.joker_buffer = GAME.joker_buffer + 1
        rarity = arg.get("rarity")
        roll = {1: 0, 2: 0.9, 3: 0.99}.get(rarity) if rarity else None

        def make_joker() -> None:
            card = G.create_card("Joker", G.jokers, rarity == 4, roll, None, None, key, append)
            if edition:
                card.set_edition(T({edition: True}), True)
            card.add_to_deck()
            G.jokers.emplace(card)
            card.start_materialize()
            GAME.joker_buffer = 0
        G.ev(make_joker, trigger="after", delay=0.4 if consumable_use else 0)
        return
    cons = G.consumeables
    negative = edition == "negative"
    if not negative and len(cons.cards) + GAME.consumeable_buffer >= cons.config.card_limit:
        return
    if not negative:
        GAME.consumeable_buffer = GAME.consumeable_buffer + 1

    def make() -> None:
        card = G.create_card(s, G.consumeables, None, None, None, None, key, append)
        if edition:
            card.set_edition(T({edition: True}), True)
        card.add_to_deck()
        G.consumeables.emplace(card)
        GAME.consumeable_buffer = 0
    if consumable_use:
        G.ev(make, trigger="after", delay=0.4)
    else:
        G.ev(make, trigger="before", delay=0.0)


_RANK_UP = {2: "3", 3: "4", 4: "5", 5: "6", 6: "7", 7: "8", 8: "9", 9: "T", 10: "J", 11: "Q", 12: "K", 13: "A",
            14: "2"}
_RANK_DOWN = {2: "A", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "T", 12: "J", 13: "Q",
              14: "K"}


def _change_card(G: "Game", c: "Card", arg: dict[str, Any], chips: float | None) -> None:
    from ..card import SUIT_CODE
    playing = c.ability.set in ("Default", "Enhanced")
    if "enhancement" in arg and playing:
        e = arg["enhancement"]
        c.set_ability(G.P_CENTERS["c_base" if e == "none" else e], None, True)
    if "seal" in arg and playing:
        c.set_seal(None if arg["seal"] == "none" else arg["seal"], None, True)
    if "edition" in arg:
        c.set_edition(None if arg["edition"] == "none" else T({arg["edition"]: True}), True)
    if "suit" in arg and playing and c.base.suit:
        c.change_suit(arg["suit"])
    if "rank" in arg and playing and c.base.suit and c.ability.effect != "Stone Card":
        r = arg["rank"]
        bid = c.base.id
        char = (_RANK_UP.get(bid) if r == "up" else _RANK_DOWN.get(bid) if r == "down" else S.RANKS.get(r))
        if char:
            c.set_base(G.P_CARDS[SUIT_CODE[c.base.suit] + char])
    if chips:
        c.ability.perma_bonus = (c.ability.perma_bonus or 0) + chips


def _modify(G: "Game", run: _Run, arg: dict[str, Any]) -> None:
    env = run.env
    target = arg.get("target", "selected" if run.item.kind == "consumables" else "card")
    if target == "card":
        cards = [env.card] if env.card is not None else []
    else:
        cards = env._list(target) or []
    if "where" in arg:
        cards = [c for c in cards if E.truthy(ev(arg["where"], env.with_card(c)))]
    if not cards:
        return
    chips = {id(c): _num(ev(arg["chips"], env.with_card(c))) for c in cards} if "chips" in arg else {}
    if arg.get("destroy"):
        _destroy_selected(G, run, cards)
        return
    if target == "selected":
        # (as the game's Tarot cards: flip them, change them, flip them back)
        G.ev(None, trigger="after", delay=0.4)
        for c in cards:
            G.ev(c.flip, trigger="after", delay=0.15)
        G.delay(0.2)
        for c in cards:
            G.ev(lambda c=c: _change_card(G, c, arg, chips.get(id(c))), trigger="after", delay=0.1)
        for c in cards:
            G.ev(c.flip, trigger="after", delay=0.15)
        G.ev(G.hand.unhighlight_all, trigger="after", delay=0.2)
        G.delay(0.5)
        return
    for c in cards:
        _change_card(G, c, arg, chips.get(id(c)))
        G.juice_card(c, None)


def _destroy_selected(G: "Game", run: _Run, cards: list["Card"]) -> None:
    from ..lua import T as _T
    G.ev(None, trigger="after", delay=0.4)

    def destroy() -> None:
        for i in range(len(cards) - 1, -1, -1):
            card = cards[i]
            if card.ability.name == "Glass Card":
                card.shatter()
            else:
                card.start_dissolve(None, i == len(cards) - 1)
    G.ev(destroy, trigger="after", delay=0.2)
    G.delay(0.3)
    for j in list(G.jokers.cards):
        j.calculate_joker(_T(remove_playing_cards=True, removed=cards))


# ===================================================================== jokers
def _trigger(G: "Game", card: "Card", c: T) -> str | None:  # noqa: C901 - calculate_joker's order of contexts
    if c.open_booster:
        return "pack_opened"
    if c.buying_card:
        return "card_bought"
    if c.selling_self:
        return "sold"
    if c.selling_card:
        return "card_sold"
    if c.reroll_shop:
        return "shop_reroll"
    if c.ending_shop:
        return "shop_exit"
    if c.skip_blind:
        return "blind_skipped"
    if c.skipping_booster:
        return "pack_skipped"
    if c.playing_card_added:
        return None if card.getting_sliced else "cards_added"
    if c.first_hand_drawn:
        return "first_hand_drawn"
    if c.setting_blind:
        return None if card.getting_sliced else "blind_selected"
    if c.destroying_card:
        return None if c.blueprint else "card_destroy"
    if c.cards_destroyed:
        return None
    if c.remove_playing_cards:
        return "cards_destroyed"
    if c.using_consumeable:
        return "consumable_used"
    if c.debuffed_hand:
        return "hand_not_allowed"
    if c.pre_discard:
        return "discard_start"
    if c.discard:
        return "discard"
    if c.end_of_round:
        if c.individual:
            return None
        if c.repetition:
            return "retrigger_held" if c.cardarea is G.hand else None
        return None if c.blueprint else "round_end"
    if c.individual:
        return "card_scored" if c.cardarea is G.play else "card_held" if c.cardarea is G.hand else None
    if c.repetition:
        return "retrigger_scored" if c.cardarea is G.play else "retrigger_held" if c.cardarea is G.hand else None
    if c.other_joker:
        return "other_joker"
    if c.cardarea is G.jokers:
        if c.before:
            return "hand_played"
        if c.after:
            return "hand_finished"
        if c.joker_main:
            return "score"
    return None


def _joker_env(G: "Game", card: "Card", item: Item, c: T, trigger: str) -> _Env:
    other = None
    extra: dict[str, Any] = {}
    if trigger == "other_joker":
        other = c.other_joker
    elif trigger in ("card_bought", "card_sold"):
        other = c.card
    elif trigger == "consumable_used":
        other = c.consumeable
    if trigger == "cards_added":
        extra["event"] = {"count": len(c.cards or [])}
    elif trigger == "cards_destroyed":
        removed = c.removed or []
        extra["event"] = {"count": len(removed), "faces": sum(1 for v in removed if v.is_face()),
                          "glass": sum(1 for v in removed if v.shattered)}
    card_ref = c.destroying_card if trigger == "card_destroy" else c.other_card
    if trigger == "card_destroy":
        # (destroying_card comes after scoring: the hand is the one just played)
        extra["played"] = c.full_hand
        extra["scoring"] = G.last_scoring.scoring if G.last_scoring else c.full_hand
        extra["hand_name"] = G.last_scoring.text if G.last_scoring else None
    return _Env(G, item, values=card.ability.extra or T(), joker=card, card=card_ref, other=other, context=c,
                extra=extra)


def joker_calculate(card: "Card", c: T) -> Any:  # noqa: C901
    """Card:calculate_joker for a mod's joker."""
    G = card.G
    item: Item = card.config.center.mod_item
    trigger = _trigger(G, card, c)
    if trigger is None:
        return None
    effects = item.effects.get(trigger)
    if not effects:
        return None
    blueprint = bool(c.blueprint)
    if blueprint and not item.blueprint_compat:
        return None
    if trigger == "retrigger_held" and not c.end_of_round and not (
            nonempty(c.card_effects[0]) or len(c.card_effects) > 1):
        return None  # (as Mime: only a card that did something is retriggered)
    src = c.blueprint_card or card
    env = _joker_env(G, card, item, c, trigger)
    run = _Run(G, item, env, trigger, src, owner=card, blueprint=blueprint)
    for cond, actions, otherwise in effects:
        if cond is not None and not E.truthy(ev(cond, env)):
            if otherwise is None:
                continue
            actions = otherwise
        if trigger == "card_destroy" and actions is otherwise:
            for name, arg in actions:  # (the card isn't destroyed: only the else's actions)
                run.act(name, arg)
            continue
        run.fired = True
        for name, arg in actions:
            run.act(name, arg)
    if not run.fired:
        return None
    if run.destroy_self:
        from ..jokers import _eaten
        _eaten(card)
    return _joker_result(G, card, c, trigger, run)


def _joker_result(G: "Game", card: "Card", c: T, trigger: str, run: _Run) -> Any:  # noqa: C901
    msg = run.message
    if trigger == "card_scored":
        r = T(card=card)
        if run.chips:
            r.chips = run.chips
        if run.mult:
            r.mult = run.mult
        if run.xmult is not None and run.xmult != 1:
            r.x_mult = run.xmult
        if run.dollars:
            r.dollars = run.dollars
        if msg:
            r.extra = T(focus=card, message=msg)
        return r if len(r) > 1 else None
    if trigger == "card_held":
        if c.other_card is not None and c.other_card.debuff:
            return T(message="k_debuffed", card=card)
        r = T(card=card)
        if run.mult:
            r.h_mult = run.mult
        if run.xmult is not None and run.xmult != 1:
            r.x_mult = run.xmult
        if run.dollars:
            r.dollars = run.dollars
        if msg:
            r.message = msg
        return r if len(r) > 1 else None
    if trigger in ("retrigger_scored", "retrigger_held"):
        if run.reps <= 0:
            return None
        return T(message=msg or "k_again_ex", repetitions=run.reps, card=card)
    if trigger in ("score", "other_joker"):
        r = T()
        if run.chips:
            r.chip_mod = run.chips
        if run.mult:
            r.mult_mod = run.mult
        if run.xmult is not None and run.xmult != 1:
            r.Xmult_mod = run.xmult
        if run.dollars:
            r.dollars = run.dollars
        if not r and not msg:
            return None
        r.message = msg or "msg"
        if trigger == "other_joker" and (r.chip_mod or r.mult_mod or r.Xmult_mod):
            G.juice_card(c.other_joker, 0.5, 0.5)
        return r
    if trigger == "card_destroy":
        return True
    if trigger == "cash_out":
        return run.dollars or None
    if trigger in _RETURNING:
        r = T(card=card)
        if msg:
            r.message = msg
        if run.dollars:
            r.dollars = run.dollars
        if run.remove:
            r.remove = True
            r.delay = 0.45
        return r if len(r) > 1 else None
    # (the rest show their own texts, as the game's jokers do there)
    if msg:
        run.status(msg)
    return None


def joker_cash_out(card: "Card") -> float | None:
    """Card:calculate_dollar_bonus for a mod's joker (its cash_out effects)."""
    G = card.G
    item: Item = card.config.center.mod_item
    effects = item.effects.get("cash_out")
    if not effects:
        return None
    env = _Env(G, item, values=card.ability.extra or T(), joker=card)
    run = _Run(G, item, env, "cash_out", card, owner=card)
    for cond, actions, otherwise in effects:
        if cond is not None and not E.truthy(ev(cond, env)):
            if otherwise is None:
                continue
            actions = otherwise
        for name, arg in actions:
            run.act(name, arg)
    return run.dollars if run.dollars else None


def _passive(card: "Card", sign: int) -> None:
    """A joker's passive changes while it is in play: hands per round change
    from the next round (as Troubadour), the rest at once (Juggler, Drunkard)."""
    item: Item = card.config.center.mod_item
    if not item.passive:
        return
    values = dict(item.passive)
    hands = values.pop("hands", None)
    if hands:
        rr = card.G.GAME.round_resets
        rr.hands = rr.hands + hands * sign
    apply_modifiers(card.G, values, sign)


def joker_added(card: "Card", from_debuff: bool) -> None:
    _passive(card, 1)


def joker_removed(card: "Card", from_debuff: bool) -> None:
    _passive(card, -1)


# ===================================================================== consumables
PACK_OR_HAND = (1, 9, 10, 15)  # SELECTING_HAND, TAROT_PACK, PLANET_PACK, SPECTRAL_PACK


def consumable_can_use(card: "Card") -> bool:
    G = card.G
    item: Item = card.config.center.mod_item
    if item.targets is not None:
        if G.STATE not in PACK_OR_HAND or G.hand is None:
            return False
        n = len(G.hand.highlighted)
        if not item.targets[0] <= n <= item.targets[1]:
            return False
    if item.can_use is not None:
        return E.truthy(ev(item.can_use, _Env(G, item, values=T(item.config))))
    return True


def consumable_use(card: "Card", copier: Any = None) -> None:
    G = card.G
    item: Item = card.config.center.mod_item
    if item.targets is not None:
        G.update_hand_text(T(immediate=True, nopulse=True, delay=0), T(mult=0, chips=0, level="", handname=""))
    env = _Env(G, item, values=T(item.config), context=T())
    run = _Run(G, item, env, None, copier or card)
    for name, arg in item.use or []:
        run.act(name, arg)
    if run.message:
        G.ev(lambda: G.card_eval_status_text(copier or card, "extra", None, None, None, T(message=run.message)),
             trigger="after", delay=0.2)


# ===================================================================== vouchers
def voucher_redeem(G: "Game", card: Any, center: T) -> None:
    """Card:apply_to_run for a mod's voucher (also from a deck at the start of a run)."""
    item: Item = center.mod_item
    env = _Env(G, item, values=T(item.config))
    run = _Run(G, item, env, None, card)
    for name, arg in item.redeem:
        if name == "message" and card is None:
            continue
        run.act(name, arg)
    if run.message and card is not None:
        G.card_eval_status_text(card, "extra", None, None, None, T(message=run.message))


# ===================================================================== decks
def deck_apply(back: Any) -> None:
    """Back:apply_to_run for a mod's deck."""
    G = back.G
    GAME = G.GAME
    item: Item = back.effect.center.mod_item
    s = item.spec
    if s.get("start"):
        apply_modifiers(G, s["start"], 1, start=True)
    from ..card import apply_to_run
    for v in s.get("vouchers", []):
        GAME.used_vouchers[v] = True
        GAME.starting_voucher_count = (GAME.starting_voucher_count or 0) + 1
        apply_to_run(G, None, G.P_CENTERS[v])
    if s.get("consumables"):
        G.delay(0.4)

        def cons() -> None:
            for v in s["consumables"]:
                c = G.create_card("Tarot", G.consumeables, None, None, None, None, v, "deck")
                c.add_to_deck()
                G.consumeables.emplace(c)
        G.ev(cons)
    for i, v in enumerate(s.get("jokers", [])):
        G.ev(lambda v=v, i=i: G.add_joker(v, None, i != 0))


def deck_cards(center: T) -> T | None:
    """A mod deck's cards, in the form of a challenge's deck (Game.starting_protos)."""
    item: Item | None = center.mod_item if center is not None else None
    cards = item.spec.get("cards") if item is not None else None
    if not cards:
        return None
    de = T()
    for k, field, table in (("ranks", "yes_ranks", S.RANKS), ("no_ranks", "no_ranks", S.RANKS),
                            ("suits", "yes_suits", None), ("no_suits", "no_suits", None)):
        if cards.get(k):
            de[field] = T({(table[x] if table else x[0]): True for x in cards[k]})
    de.enhancement = cards.get("enhancement")
    de.edition = cards.get("edition")
    de.gold_seal = cards.get("seal")
    return de


# ===================================================================== blinds
def _blind_env(G: "Game", item: Item, card: Any = None, hand: dict[str, Any] | None = None) -> _Env:
    return _Env(G, item, values=T(), card=card, context=T(), extra=hand or {})


def blind_set(blind: Any) -> None:
    G = blind.G
    item: Item = blind.config.blind.mod_item
    undo = T()
    env = _blind_env(G, item)
    for name, arg in item.on_set:
        if name == "message":
            G.play_area_status_text(arg)
            continue
        if name == "hand_size":
            G.hand.change_size(int(arg))
            undo.hand_size = (undo.hand_size or 0) + int(arg)
            continue
        v = _num(ev(arg, env))
        if not v:
            continue
        if name == "dollars":
            G.ease_dollars(v)
        elif name == "hands":
            v = int(v)
            G.ease_hands_played(v)
            undo.hands = (undo.hands or 0) + v
        elif name == "discards":
            v = int(v)
            G.ease_discard(v)
            undo.discards = (undo.discards or 0) + v
    blind.mod_undo = undo


def blind_disable(blind: Any) -> None:
    G = blind.G
    undo = blind.mod_undo
    if not undo:
        return
    if undo.hands:
        G.ease_hands_played(-undo.hands)
    if undo.discards:
        G.ease_discard(-undo.discards)
    if undo.hand_size:
        G.hand.change_size(-undo.hand_size)
    blind.mod_undo = None


def blind_defeat(blind: Any) -> None:
    undo = blind.mod_undo
    if undo and undo.hand_size and not blind.disabled:
        blind.G.hand.change_size(-undo.hand_size)
    blind.mod_undo = None


def blind_debuffs_card(blind: Any, card: "Card") -> bool:
    item: Item = blind.config.blind.mod_item
    if item.debuff_card is None:
        return False
    return E.truthy(ev(item.debuff_card, _blind_env(blind.G, item, card=card)))


def blind_debuffs_hand(blind: Any, cards: list["Card"], poker_hands: T, handname: str) -> bool:
    item: Item = blind.config.blind.mod_item
    if item.debuff_hand is None:
        return False
    hand = {"hand_name": handname, "played": cards, "scoring": cards, "poker_hands": poker_hands}
    return E.truthy(ev(item.debuff_hand, _blind_env(blind.G, item, hand=hand)))


def blind_hand_played(blind: Any, cards: list["Card"], poker_hands: T, handname: str) -> None:
    G = blind.G
    item: Item = blind.config.blind.mod_item
    if not item.on_hand:
        return
    env = _blind_env(G, item, hand={"hand_name": handname, "played": cards, "scoring": cards,
                                    "poker_hands": poker_hands})
    for name, arg in item.on_hand:
        if name == "message":
            G.play_area_status_text(arg)
        elif name == "dollars":
            v = _num(ev(arg, env))
            if v:
                G.ease_dollars(v)
                blind.wiggle()
