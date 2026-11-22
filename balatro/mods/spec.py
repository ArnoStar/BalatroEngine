"""The format of content mods (format 1): what a package may contain, checked.

A package is plain JSON (``docs/mods.md`` documents every field).  ``validate``
returns what is wrong with one, each error with its path in the package
(``jokers[0].effects[1].if: unknown name 'cardd'``); ``normalize`` returns
the package with every default filled in, which is what the engine runs.
Nothing in a package is code: effects are triggers, conditions and actions,
conditions and amounts are expressions (``balatro.mods.expr``).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from . import expr as E

FORMAT = 1
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$")
ASSET_NAME = re.compile(r"^[a-z0-9_][a-z0-9_.-]{0,47}$")
LANG_PATTERN = re.compile(r"^[a-z]{2}(_[A-Za-z0-9]{2,3})?(-[a-z]{2})?$")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
LOC_KEY = re.compile(r"^[a-z]_[a-z0-9_]+$")

MAX_PACKAGE_BYTES = 1_500_000
MAX_ASSET_BYTES = 256_000
MAX_ASSETS = 64
MAX_ITEMS = 100
MAX_EFFECTS = 32
MAX_ACTIONS = 16
MAX_CONFIG = 32
MAX_TEXT_LINES = 8
MAX_LINE = 160

RANKS = {"2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9", "10": "T",
         "Jack": "J", "Queen": "Q", "King": "K", "Ace": "A"}
RANK_IDS = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "Jack": 11, "Queen": 12,
            "King": 13, "Ace": 14}
SUITS = ("Spades", "Hearts", "Clubs", "Diamonds")
SEALS = ("Gold", "Red", "Blue", "Purple")
EDITIONS = ("foil", "holo", "polychrome", "negative")
ENHANCEMENTS = ("m_bonus", "m_mult", "m_wild", "m_glass", "m_steel", "m_stone", "m_gold", "m_lucky")
POKER_HANDS = ("Flush Five", "Flush House", "Five of a Kind", "Straight Flush", "Four of a Kind", "Full House",
               "Flush", "Straight", "Three of a Kind", "Two Pair", "Pair", "High Card")
CONSUMABLE_SETS = ("Tarot", "Planet", "Spectral")
ATLASES = {"Joker": (10, 16), "Tarot": (10, 6), "Voucher": (9, 4), "centers": (7, 5), "Planet": (10, 6),
           "Spectral": (10, 6)}

# The run modifiers: one vocabulary for a mod's rules, a deck's start, a
# joker's passive changes and the modify_run action.
RUN_MODIFIERS = ("dollars", "hands", "discards", "hand_size", "joker_slots", "consumable_slots", "interest_cap",
                 "reroll_cost", "shop_slots", "discount_percent", "probability_mult", "win_ante", "blind_scale")
START_ONLY = ("win_ante", "blind_scale")
NOT_PASSIVE = ("dollars", "win_ante", "blind_scale", "shop_slots", "reroll_cost", "discount_percent")

# ---------------------------------------------------------------- scopes
CARD_FIELDS = ("rank", "rank_name", "suit", "face", "chips", "enhancement", "seal", "edition", "debuffed", "key",
               "set", "rarity", "sell_value", "cost")
GAME_FIELDS = ("money", "ante", "round", "hands_left", "discards_left", "hands_played", "discards_used", "hand_size",
               "deck_count", "full_deck_count", "joker_count", "joker_slots", "consumable_count",
               "consumable_slots", "probability", "blind_boss", "blind_chips", "round_chips", "skips", "rerolls",
               "interest_cap", "stake", "hands_per_round", "discards_per_round")
HAND_FIELDS = ("name", "level", "played", "played_this_round", "count", "scoring_count", "chips", "mult")
JOKER_FIELDS = ("position", "sell_value", "edition")
BLIND_FIELDS = ("boss", "key", "chips", "mult", "dollars")
EVENT_FIELDS = ("count", "faces", "glass")
CARD_LISTS = ("jokers", "consumables", "full_deck", "deck", "held")
HAND_LISTS = ("scoring", "played")

GAME_FUNCTIONS = {
    "is_suit": (2, 2), "is_rank": (2, 2), "is_face": (1, 1), "count": (1, 1), "count_suit": (2, 2),
    "count_rank": (2, 2), "count_face": (1, 1), "count_enhancement": (2, 2), "count_seal": (2, 2),
    "count_edition": (2, 2), "count_key": (2, 2), "hand_level": (1, 1), "times_played": (1, 1),
    "has_joker": (1, 1), "has_voucher": (1, 1),
}
HAND_FUNCTIONS = {"has_hand": (1, 1)}
RANDOM_FUNCTIONS = {"chance": (2, 3), "random": (2, 3)}

# ---------------------------------------------------------------- triggers
HAND_TRIGGERS = ("hand_played", "card_scored", "card_held", "retrigger_scored", "retrigger_held", "score",
                 "other_joker", "hand_finished", "card_destroy", "hand_not_allowed")
CARD_TRIGGERS = ("card_scored", "card_held", "retrigger_scored", "retrigger_held", "discard", "card_destroy")
OTHER_TRIGGERS = ("other_joker", "card_bought", "card_sold", "consumable_used")
JOKER_TRIGGERS = (
    "hand_played", "card_scored", "card_held", "retrigger_scored", "retrigger_held", "score", "other_joker",
    "hand_finished", "discard", "discard_start", "round_end", "cash_out", "card_destroy", "blind_selected",
    "first_hand_drawn", "shop_reroll", "shop_exit", "blind_skipped", "pack_opened", "pack_skipped", "card_bought",
    "card_sold", "sold", "consumable_used", "cards_added", "cards_destroyed", "hand_not_allowed",
)
SCORING_ACTIONS = {
    "card_scored": ("chips", "mult", "xmult"),
    "card_held": ("mult", "xmult"),
    "score": ("chips", "mult", "xmult"),
    "other_joker": ("chips", "mult", "xmult"),
}
ACTIONS = ("chips", "mult", "xmult", "dollars", "retrigger", "set", "message", "level_up", "create", "destroy_self",
           "destroy_card", "hands", "discards", "modify_run", "modify", "add_tag", "disable_boss")
MODIFY_FIELDS = ("target", "where", "enhancement", "seal", "edition", "suit", "rank", "chips", "destroy")
TARGETS = ("card", "scoring", "played", "held", "selected")


def scope_for(kind: str, trigger: str | None, config: dict[str, Any] | None,
              allow_impure: bool = True) -> E.Scope:
    """The names an expression may use in this place of a package."""
    roots: dict[str, Any] = {"game": GAME_FIELDS, "self": tuple(config or ()), **{k: () for k in CARD_LISTS}}
    functions = dict(GAME_FUNCTIONS)
    if kind == "joker":
        roots["joker"] = JOKER_FIELDS
    if trigger in HAND_TRIGGERS or kind == "blind_hand":
        roots["hand"] = HAND_FIELDS
        roots.update({k: () for k in HAND_LISTS})
        functions.update(HAND_FUNCTIONS)
    if trigger in CARD_TRIGGERS or kind in ("blind_card", "modify"):
        roots["card"] = CARD_FIELDS
    if trigger in OTHER_TRIGGERS:
        roots["other"] = CARD_FIELDS
    if trigger in ("discard", "discard_start"):
        roots["discarded"] = ()
    if trigger == "blind_selected":
        roots["blind"] = BLIND_FIELDS
    if trigger in ("cards_added", "cards_destroyed"):
        roots["event"] = EVENT_FIELDS
    if kind == "consumable":
        roots["selected"] = ()
    functions.update(RANDOM_FUNCTIONS)
    # (list roots have no fields: they are only passed to functions)
    return E.Scope(roots, functions, impure=RANDOM_FUNCTIONS, allow_impure=allow_impure, refs=("card", "other"))


# ---------------------------------------------------------------- validation
class _V:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def err(self, path: str, msg: str) -> None:
        if len(self.errors) < 200:
            self.errors.append(f"{path}: {msg}" if path else msg)

    def obj(self, path: str, v: Any, allowed: tuple[str, ...] | None = None) -> bool:
        if not isinstance(v, dict):
            self.err(path, "must be an object")
            return False
        if allowed is not None:
            for k in v:
                if k not in allowed:
                    self.err(path, f"unknown field {k!r}")
        return True

    def string(self, path: str, v: Any, lo: int = 0, hi: int = 200, pattern: re.Pattern[str] | None = None) -> bool:
        if not isinstance(v, str):
            self.err(path, "must be a string")
            return False
        if not lo <= len(v) <= hi:
            self.err(path, f"must have {lo} to {hi} characters")
            return False
        if pattern is not None and not pattern.match(v):
            self.err(path, f"{v!r} doesn't match {pattern.pattern}")
            return False
        return True

    def number(self, path: str, v: Any, lo: float | None = None, hi: float | None = None,
               integer: bool = False) -> bool:
        if not E.is_number(v) or v != v or v in (float("inf"), float("-inf")):
            self.err(path, "must be a number")
            return False
        if integer and v != int(v):
            self.err(path, "must be a whole number")
            return False
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            self.err(path, f"must be between {lo} and {hi}")
            return False
        return True

    def boolean(self, path: str, v: Any) -> bool:
        if not isinstance(v, bool):
            self.err(path, "must be true or false")
            return False
        return True

    def one_of(self, path: str, v: Any, options: tuple[str, ...]) -> bool:
        if v not in options:
            self.err(path, f"must be one of {', '.join(map(str, options))}")
            return False
        return True

    def array(self, path: str, v: Any, hi: int) -> bool:
        if not isinstance(v, list):
            self.err(path, "must be a list")
            return False
        if len(v) > hi:
            self.err(path, f"has at most {hi} entries")
            return False
        return True

    def expression(self, path: str, v: Any, scope: E.Scope) -> E.Node | None:
        if isinstance(v, bool) or E.is_number(v):
            return ("const", v)  # a plain number (or true/false) where an expression goes
        if not isinstance(v, str):
            self.err(path, "must be an expression (a string) or a number")
            return None
        try:
            node = E.parse(v)
        except E.ExprError as e:
            self.err(path, str(e))
            return None
        for m in E.check(node, scope):
            self.err(path, m)
        return node


def _text(v: _V, path: str, item: dict[str, Any]) -> None:
    v.string(f"{path}.name", item.get("name"), 1, 40)
    text = item.get("text", [])
    if v.array(f"{path}.text", text, MAX_TEXT_LINES):
        for i, line in enumerate(text):
            v.string(f"{path}.text[{i}]", line, 0, MAX_LINE)
    loc = item.get("loc", {})
    if v.obj(f"{path}.loc", loc):
        for lang, t in loc.items():
            p = f"{path}.loc.{lang}"
            if not LANG_PATTERN.match(str(lang)):
                v.err(p, "is not a language code (en-us, fr, pt_BR ...)")
            if v.obj(p, t, ("name", "text")):
                if "name" in t:
                    v.string(f"{p}.name", t["name"], 1, 40)
                if "text" in t and v.array(f"{p}.text", t["text"], MAX_TEXT_LINES):
                    for i, line in enumerate(t["text"]):
                        v.string(f"{p}.text[{i}]", line, 0, MAX_LINE)


def _sprite(v: _V, path: str, s: Any, assets: dict[str, Any] | None, kind: str) -> None:
    if s is None:
        return
    if isinstance(s, str):
        # (a package without its images, ``logic``, names them all the same: the engine doesn't draw)
        if assets is not None and s not in assets:
            v.err(path, f"no asset named {s!r} in the package's assets")
        elif not ASSET_NAME.match(s):
            v.err(path, "an asset's name is lowercase letters, digits, _ . -")
        return
    if kind == "blind":
        if v.obj(path, s, ("blind",)):
            v.string(f"{path}.blind", s.get("blind"), 1, 40, re.compile(r"^bl_[a-z_]+$"))
        return
    if v.obj(path, s, ("atlas", "x", "y")):
        atlas = s.get("atlas")
        if v.one_of(f"{path}.atlas", atlas, tuple(ATLASES)):
            w, h = ATLASES[atlas]
            v.number(f"{path}.x", s.get("x"), 0, w - 1, True)
            v.number(f"{path}.y", s.get("y"), 0, h - 1, True)


def _config(v: _V, path: str, cfg: Any) -> dict[str, Any]:
    if cfg is None:
        return {}
    if not v.obj(path, cfg):
        return {}
    if len(cfg) > MAX_CONFIG:
        v.err(path, f"has at most {MAX_CONFIG} values")
    for k, val in cfg.items():
        if not KEY_PATTERN.match(k):
            v.err(f"{path}.{k}", "a value's name is lowercase letters, digits and _")
        if not (E.is_number(val) or isinstance(val, (str, bool))):
            v.err(f"{path}.{k}", "must be a number, a string or true/false")
        elif isinstance(val, str) and len(val) > 60:
            v.err(f"{path}.{k}", "has at most 60 characters")
    return dict(cfg)


def _modifiers(v: _V, path: str, mods: Any, context: str, scope: E.Scope | None = None) -> None:
    if not v.obj(path, mods):
        return
    for k, val in mods.items():
        p = f"{path}.{k}"
        if k not in RUN_MODIFIERS:
            v.err(p, f"unknown run modifier (they are {', '.join(RUN_MODIFIERS)})")
            continue
        if context in ("passive", "action") and k in START_ONLY:
            v.err(p, "only a mod's rules or a deck's start can change it")
        if context == "passive" and k in NOT_PASSIVE:
            v.err(p, "a joker's passive changes can't include it (use an effect)")
        if scope is not None and isinstance(val, str):
            v.expression(p, val, scope)
        elif k in ("probability_mult", "blind_scale"):
            v.number(p, val, 0.01, 1000)
        else:
            v.number(p, val, -1000, 1000)


def _actions(v: _V, path: str, actions: Any, kind: str, trigger: str | None, config: dict[str, Any],
             scope: E.Scope) -> None:
    if not v.array(path, actions, MAX_ACTIONS):
        return
    scoring = SCORING_ACTIONS.get(trigger or "", ())
    for i, a in enumerate(actions):
        p = f"{path}[{i}]"
        if not v.obj(p, a):
            continue
        if len(a) != 1:
            v.err(p, "an action is an object with one field: what it does ({\"mult\": 4})")
            continue
        (name, arg), = a.items()
        p = f"{p}.{name}"
        if name not in ACTIONS:
            v.err(p, f"unknown action (they are {', '.join(ACTIONS)})")
            continue
        if name in ("chips", "mult", "xmult"):
            if name not in scoring:
                v.err(p, f"only scores in {', '.join(t for t, s in SCORING_ACTIONS.items() if name in s)}")
            v.expression(p, arg, scope)
        elif name == "retrigger":
            if trigger not in ("retrigger_scored", "retrigger_held"):
                v.err(p, "only in retrigger_scored and retrigger_held")
            v.expression(p, arg, scope)
        elif name in ("dollars", "hands", "discards"):
            v.expression(p, arg, scope)
        elif name == "set":
            if kind != "joker":
                v.err(p, "only a joker keeps values")
            if v.obj(p, arg):
                for k, e in arg.items():
                    if k not in config:
                        v.err(f"{p}.{k}", "is not one of the joker's config values")
                    v.expression(f"{p}.{k}", e, scope)
        elif name == "message":
            v.string(p, arg, 1, 40)
        elif name == "level_up":
            if E.is_number(arg) or isinstance(arg, str):
                v.expression(p, arg, scope)
                if trigger not in ("hand_played", "score", "hand_finished") and kind != "consumable":
                    v.err(p, "levels up the played hand: name the hand ({\"hand\": \"'Flush'\"}) elsewhere")
            elif v.obj(p, arg, ("hand", "levels")):
                if "hand" in arg:
                    v.expression(f"{p}.hand", arg["hand"], scope)
                elif trigger not in ("hand_played", "score", "hand_finished"):
                    v.err(f"{p}.hand", "is needed here (there is no played hand)")
                if "levels" in arg:
                    v.expression(f"{p}.levels", arg["levels"], scope)
        elif name == "create":
            if v.obj(p, arg, ("set", "key", "rarity", "edition")):
                v.one_of(f"{p}.set", arg.get("set"), CONSUMABLE_SETS + ("Joker",))
                if "key" in arg:
                    v.string(f"{p}.key", arg["key"], 3, 64, re.compile(r"^[a-z]+_[a-z0-9_]+$"))
                if "rarity" in arg:
                    if arg.get("set") != "Joker":
                        v.err(f"{p}.rarity", "only for jokers")
                    v.number(f"{p}.rarity", arg["rarity"], 1, 4, True)
                if "edition" in arg:
                    v.one_of(f"{p}.edition", arg["edition"], EDITIONS)
        elif name in ("destroy_self", "disable_boss"):
            v.boolean(p, arg)
            if name == "destroy_self" and kind != "joker":
                v.err(p, "only a joker destroys itself")
        elif name == "destroy_card":
            v.boolean(p, arg)
            if trigger != "discard":
                v.err(p, "only in discard (card_destroy destroys the card its condition picks)")
        elif name == "modify_run":
            _modifiers(v, p, arg, "action", scope)
        elif name == "modify":
            _modify(v, p, arg, kind, trigger, config)
        elif name == "add_tag":
            v.string(p, arg, 5, 40, re.compile(r"^tag_[a-z_]+$"))


def _modify(v: _V, p: str, arg: Any, kind: str, trigger: str | None, config: dict[str, Any]) -> None:
    if not v.obj(p, arg, MODIFY_FIELDS):
        return
    target = arg.get("target", "selected" if kind == "consumable" else "card")
    if v.one_of(f"{p}.target", target, TARGETS):
        if target == "card" and trigger not in CARD_TRIGGERS:
            v.err(f"{p}.target", "there is no card here: use scoring, played, held or selected")
        if target in HAND_LISTS and trigger not in HAND_TRIGGERS:
            v.err(f"{p}.target", "there is no played hand here")
        if target == "selected" and kind != "consumable":
            v.err(f"{p}.target", "only a consumable has selected cards")
    if "where" in arg:
        v.expression(f"{p}.where", arg["where"], scope_for("modify", trigger, config))
    if "enhancement" in arg:
        v.one_of(f"{p}.enhancement", arg["enhancement"], ENHANCEMENTS + ("none",))
    if "seal" in arg:
        v.one_of(f"{p}.seal", arg["seal"], SEALS + ("none",))
    if "edition" in arg:
        v.one_of(f"{p}.edition", arg["edition"], ("foil", "holo", "polychrome", "none"))
    if "suit" in arg:
        v.one_of(f"{p}.suit", arg["suit"], SUITS)
    if "rank" in arg:
        v.one_of(f"{p}.rank", arg["rank"], tuple(RANKS) + ("up", "down"))
    if "chips" in arg:
        v.expression(f"{p}.chips", arg["chips"], scope_for("modify", trigger, config))
    if "destroy" in arg:
        v.boolean(f"{p}.destroy", arg["destroy"])
        if target != "selected":
            v.err(f"{p}.destroy", "only the selected cards of a consumable (card_destroy and destroy_card do it "
                  "elsewhere)")
    if not any(k in arg for k in ("enhancement", "seal", "edition", "suit", "rank", "chips", "destroy")):
        v.err(p, "changes nothing (enhancement, seal, edition, suit, rank, chips or destroy)")


def _effects(v: _V, path: str, effects: Any, kind: str, triggers: tuple[str, ...],
             config: dict[str, Any]) -> None:
    if not v.array(path, effects, MAX_EFFECTS):
        return
    for i, eff in enumerate(effects):
        p = f"{path}[{i}]"
        if not v.obj(p, eff, ("on", "if", "do", "else")):
            continue
        trigger = eff.get("on")
        if not v.one_of(f"{p}.on", trigger, triggers):
            continue
        scope = scope_for(kind, trigger, config)
        if "if" in eff:
            v.expression(f"{p}.if", eff["if"], scope)
        if "do" not in eff:
            if trigger != "card_destroy":
                v.err(f"{p}.do", "is missing (the actions)")
        else:
            _actions(v, f"{p}.do", eff["do"], kind, trigger, config, scope)
        if "else" in eff:
            if "if" not in eff:
                v.err(f"{p}.else", "needs an if")
            _actions(v, f"{p}.else", eff["else"], kind, trigger, config, scope)


def _items(v: _V, pkg: dict[str, Any], name: str) -> list[Any]:
    items = pkg.get(name, [])
    if not v.array(name, items, MAX_ITEMS):
        return []
    seen: set[str] = set()
    for i, it in enumerate(items):
        if isinstance(it, dict):
            k = it.get("key")
            if v.string(f"{name}[{i}].key", k, 1, 32, KEY_PATTERN):
                if k in seen:
                    v.err(f"{name}[{i}].key", f"{k!r} is used twice")
                seen.add(k)
    return [it for it in items if isinstance(it, dict)]


ITEM_FIELDS = ("key", "name", "text", "vars", "loc", "sprite")


def _vars(v: _V, path: str, item: dict[str, Any], kind: str, config: dict[str, Any]) -> None:
    vs = item.get("vars", [])
    if v.array(path, vs, 8):
        for i, e in enumerate(vs):
            v.expression(f"{path}[{i}]", e, scope_for(kind, None, config, allow_impure=False))


def validate(pkg: Any) -> list[str]:
    """What is wrong with a package (empty: it can be played)."""
    v = _V()
    if not v.obj("", pkg, ("format", "id", "name", "version", "author", "description", "tags", "loc", "rules",
                           "creative", "jokers", "consumables", "vouchers", "decks", "blinds", "assets")):
        return v.errors
    try:
        size = len(json.dumps(pkg, ensure_ascii=False).encode())
    except (TypeError, ValueError):
        v.err("", "is not plain JSON")
        return v.errors
    if size > MAX_PACKAGE_BYTES:
        v.err("", f"a package has at most {MAX_PACKAGE_BYTES // 1000} kB ({size // 1000} kB)")
    if pkg.get("format") != FORMAT:
        v.err("format", f"must be {FORMAT} (the version of this format)")
    v.string("id", pkg.get("id"), 3, 32, ID_PATTERN)
    if pkg.get("id") in ("pvp", "coop"):
        v.err("id", "is a built-in game mode's")
    v.string("name", pkg.get("name"), 1, 60)
    v.string("version", pkg.get("version"), 5, 20, VERSION_PATTERN)
    if "author" in pkg:
        v.string("author", pkg["author"], 0, 60)
    if "description" in pkg:
        v.string("description", pkg["description"], 0, 2000)
    tags = pkg.get("tags", [])
    if v.array("tags", tags, 8):
        for i, t in enumerate(tags):
            v.string(f"tags[{i}]", t, 1, 24, re.compile(r"^[a-z0-9][a-z0-9 -]*$"))
    loc = pkg.get("loc", {})
    if v.obj("loc", loc):
        for lang, t in loc.items():
            if v.obj(f"loc.{lang}", t, ("name", "description")):
                for k, hi in (("name", 60), ("description", 2000)):
                    if k in t:
                        v.string(f"loc.{lang}.{k}", t[k], 0, hi)
    assets = pkg.get("assets")
    if assets is not None and v.obj("assets", assets):
        if len(assets) > MAX_ASSETS:
            v.err("assets", f"has at most {MAX_ASSETS} images")
        for k, data in assets.items():
            _asset(v, f"assets.{k}", k, data)
    elif assets is not None:
        assets = {}
    if "rules" in pkg:
        _modifiers(v, "rules", pkg["rules"], "start")
    if "creative" in pkg:
        v.boolean("creative", pkg["creative"])

    for i, j in enumerate(_items(v, pkg, "jokers")):
        p = f"jokers[{i}]"
        v.obj(p, j, ITEM_FIELDS + ("rarity", "cost", "config", "blueprint_compat", "eternal_compat",
                                   "perishable_compat", "passive", "effects", "in_shop"))
        _text(v, p, j)
        _sprite(v, f"{p}.sprite", j.get("sprite"), assets, "joker")
        v.number(f"{p}.rarity", j.get("rarity", 1), 1, 4, True)
        v.number(f"{p}.cost", j.get("cost", 5), 1, 50, True)
        for k in ("blueprint_compat", "eternal_compat", "perishable_compat", "in_shop"):
            if k in j:
                v.boolean(f"{p}.{k}", j[k])
        cfg = _config(v, f"{p}.config", j.get("config"))
        _vars(v, f"{p}.vars", j, "joker", cfg)
        if "passive" in j:
            _modifiers(v, f"{p}.passive", j["passive"], "passive")
        _effects(v, f"{p}.effects", j.get("effects", []), "joker", JOKER_TRIGGERS, cfg)

    for i, c in enumerate(_items(v, pkg, "consumables")):
        p = f"consumables[{i}]"
        v.obj(p, c, ITEM_FIELDS + ("set", "cost", "config", "hand", "targets", "can_use", "use"))
        _text(v, p, c)
        _sprite(v, f"{p}.sprite", c.get("sprite"), assets, "consumable")
        v.one_of(f"{p}.set", c.get("set"), CONSUMABLE_SETS)
        v.number(f"{p}.cost", c.get("cost", 3), 1, 50, True)
        cfg = _config(v, f"{p}.config", c.get("config"))
        _vars(v, f"{p}.vars", c, "consumable", cfg)
        if "hand" in c:
            v.one_of(f"{p}.hand", c["hand"], POKER_HANDS)
            if c.get("set") != "Planet":
                v.err(f"{p}.hand", "only a Planet card levels up a hand by itself (use level_up)")
        elif c.get("set") == "Planet" and "use" not in c:
            v.err(p, "a Planet card needs a hand (or its own use)")
        if "targets" in c and v.obj(f"{p}.targets", c["targets"], ("min", "max")):
            lo = c["targets"].get("min", 1)
            hi = c["targets"].get("max", lo)
            if v.number(f"{p}.targets.min", lo, 1, 5, True) and v.number(f"{p}.targets.max", hi, 1, 5, True) \
                    and lo > hi:
                v.err(f"{p}.targets", "min is more than max")
        scope = scope_for("consumable", None, cfg)
        if "can_use" in c:
            v.expression(f"{p}.can_use", c["can_use"], scope_for("consumable", None, cfg, allow_impure=False))
        if "use" in c:
            _actions(v, f"{p}.use", c["use"], "consumable", None, cfg, scope)
            if "hand" in c:
                v.err(f"{p}.use", "a Planet card with a hand levels it up: no use of its own")
        elif "hand" not in c:
            v.err(p, "does nothing: give it a use (actions)")
        uses_selected = any(isinstance(a, dict) and isinstance(a.get("modify"), dict)
                            and a["modify"].get("target", "selected") == "selected" for a in c.get("use", []))
        if uses_selected and "targets" not in c:
            v.err(f"{p}.targets", "is needed: the use changes selected cards")

    for i, vo in enumerate(_items(v, pkg, "vouchers")):
        p = f"vouchers[{i}]"
        v.obj(p, vo, ITEM_FIELDS + ("cost", "config", "requires", "redeem"))
        _text(v, p, vo)
        _sprite(v, f"{p}.sprite", vo.get("sprite"), assets, "voucher")
        v.number(f"{p}.cost", vo.get("cost", 10), 1, 50, True)
        cfg = _config(v, f"{p}.config", vo.get("config"))
        _vars(v, f"{p}.vars", vo, "voucher", cfg)
        req = vo.get("requires", [])
        if v.array(f"{p}.requires", req, 4):
            for k, r in enumerate(req):
                v.string(f"{p}.requires[{k}]", r, 3, 64, re.compile(r"^v_[a-z0-9_]+$"))
        if "redeem" not in vo:
            v.err(p, "does nothing: give it a redeem (actions)")
        else:
            _actions(v, f"{p}.redeem", vo["redeem"], "voucher", None, cfg, scope_for("voucher", None, cfg))

    for i, d in enumerate(_items(v, pkg, "decks")):
        p = f"decks[{i}]"
        v.obj(p, d, ITEM_FIELDS + ("start", "jokers", "consumables", "vouchers", "cards"))
        _text(v, p, d)
        _sprite(v, f"{p}.sprite", d.get("sprite"), assets, "deck")
        _vars(v, f"{p}.vars", d, "deck", {})
        if "start" in d:
            _modifiers(v, f"{p}.start", d["start"], "start")
        for k, prefix in (("jokers", "j_"), ("consumables", "c_"), ("vouchers", "v_")):
            keys = d.get(k, [])
            if v.array(f"{p}.{k}", keys, 10):
                for n, key in enumerate(keys):
                    v.string(f"{p}.{k}[{n}]", key, 3, 64, re.compile(rf"^{prefix}[a-z0-9_]+$"))
        cards = d.get("cards")
        if cards is not None and v.obj(f"{p}.cards", cards, ("ranks", "no_ranks", "suits", "no_suits",
                                                            "enhancement", "edition", "seal")):
            for k, options in (("ranks", tuple(RANKS)), ("no_ranks", tuple(RANKS)), ("suits", SUITS),
                               ("no_suits", SUITS)):
                if k in cards and v.array(f"{p}.cards.{k}", cards[k], 13):
                    for n, x in enumerate(cards[k]):
                        v.one_of(f"{p}.cards.{k}[{n}]", x, options)
            if "enhancement" in cards:
                v.one_of(f"{p}.cards.enhancement", cards["enhancement"], ENHANCEMENTS)
            if "edition" in cards:
                v.one_of(f"{p}.cards.edition", cards["edition"], ("foil", "holo", "polychrome"))
            if "seal" in cards:
                v.one_of(f"{p}.cards.seal", cards["seal"], SEALS)

    for i, b in enumerate(_items(v, pkg, "blinds")):
        p = f"blinds[{i}]"
        v.obj(p, b, ITEM_FIELDS + ("mult", "dollars", "min_ante", "max_ante", "showdown", "colour", "debuff_card",
                                   "debuff_hand", "on_set", "on_hand"))
        _text(v, p, b)
        _sprite(v, f"{p}.sprite", b.get("sprite"), assets, "blind")
        v.number(f"{p}.mult", b.get("mult", 2), 0.1, 100)
        v.number(f"{p}.dollars", b.get("dollars", 5), 0, 50, True)
        v.number(f"{p}.min_ante", b.get("min_ante", 1), 1, 39, True)
        v.number(f"{p}.max_ante", b.get("max_ante", 10), 1, 39, True)
        if "showdown" in b:
            v.boolean(f"{p}.showdown", b["showdown"])
        if "colour" in b:
            v.string(f"{p}.colour", b["colour"], 7, 7, COLOUR)
        _vars(v, f"{p}.vars", b, "blind", {})
        if "debuff_card" in b:
            v.expression(f"{p}.debuff_card", b["debuff_card"], scope_for("blind_card", None, {}, allow_impure=False))
        if "debuff_hand" in b:
            v.expression(f"{p}.debuff_hand", b["debuff_hand"], scope_for("blind_hand", None, {}, allow_impure=False))
        for k in ("on_set", "on_hand"):
            if k in b:
                _blind_actions(v, f"{p}.{k}", b[k], k)
    return v.errors


BLIND_ACTIONS = {"on_set": ("hands", "discards", "hand_size", "dollars", "message"),
                 "on_hand": ("dollars", "message")}


def _blind_actions(v: _V, path: str, actions: Any, when: str) -> None:
    if not v.array(path, actions, MAX_ACTIONS):
        return
    scope = scope_for("blind_hand" if when == "on_hand" else "blind", None, {})
    for i, a in enumerate(actions):
        p = f"{path}[{i}]"
        if not v.obj(p, a) or len(a) != 1:
            v.err(p, "an action is an object with one field")
            continue
        (name, arg), = a.items()
        if name not in BLIND_ACTIONS[when]:
            v.err(f"{p}.{name}", f"a blind's {when} does {', '.join(BLIND_ACTIONS[when])}")
        elif name == "message":
            v.string(f"{p}.{name}", arg, 1, 40)
        elif name == "hand_size":
            v.number(f"{p}.{name}", arg, -10, 10, True)
        else:
            v.expression(f"{p}.{name}", arg, scope)


def _asset(v: _V, path: str, name: str, data: Any) -> None:
    if not ASSET_NAME.match(name):
        v.err(path, "an asset's name is lowercase letters, digits, _ . -")
    if not isinstance(data, str) or not data.startswith("data:image/png;base64,"):
        v.err(path, "must be a PNG image as a data URL (data:image/png;base64,...)")
        return
    try:
        raw = base64.b64decode(data[len("data:image/png;base64,"):], validate=True)
    except (binascii.Error, ValueError):
        v.err(path, "isn't valid base64")
        return
    if len(raw) > MAX_ASSET_BYTES:
        v.err(path, f"an image has at most {MAX_ASSET_BYTES // 1000} kB")
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 24 or raw[12:16] != b"IHDR":
        v.err(path, "isn't a PNG image")
        return
    w, h = int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    if not (8 <= w <= 1024 and 8 <= h <= 1024):
        v.err(path, f"is {w}x{h}: images are 8 to 1024 pixels wide and high")


# ---------------------------------------------------------------- keys
PREFIX = {"jokers": "j", "consumables": "c", "vouchers": "v", "decks": "b", "blinds": "bl"}


def full_key(mod_id: str, kind: str, key: str) -> str:
    """An item's key in the game: ``j_<mod id>_<key>`` (a joker), ``bl_...`` (a blind)."""
    return f"{PREFIX[kind]}_{mod_id}_{key}"


def references(pkg: dict[str, Any]) -> list[tuple[str, str]]:
    """The game keys a package names (path, key): they must exist when it is played."""
    out: list[tuple[str, str]] = []

    def actions(path: str, acts: Any) -> None:
        for i, a in enumerate(acts if isinstance(acts, list) else []):
            if isinstance(a, dict):
                c = a.get("create")
                if isinstance(c, dict) and isinstance(c.get("key"), str):
                    out.append((f"{path}[{i}].create.key", c["key"]))
                if isinstance(a.get("add_tag"), str):
                    out.append((f"{path}[{i}].add_tag", a["add_tag"]))

    for i, j in enumerate(pkg.get("jokers", [])):
        for k, eff in enumerate(j.get("effects", [])):
            actions(f"jokers[{i}].effects[{k}].do", eff.get("do"))
    for i, c in enumerate(pkg.get("consumables", [])):
        actions(f"consumables[{i}].use", c.get("use"))
    for i, vo in enumerate(pkg.get("vouchers", [])):
        actions(f"vouchers[{i}].redeem", vo.get("redeem"))
        for k, r in enumerate(vo.get("requires", [])):
            out.append((f"vouchers[{i}].requires[{k}]", r))
    for i, d in enumerate(pkg.get("decks", [])):
        for kind in ("jokers", "consumables", "vouchers"):
            for k, key in enumerate(d.get(kind, [])):
                out.append((f"decks[{i}].{kind}[{k}]", key))
    for i, b in enumerate(pkg.get("blinds", [])):
        s = b.get("sprite")
        if isinstance(s, dict) and isinstance(s.get("blind"), str):
            out.append((f"blinds[{i}].sprite.blind", s["blind"]))
    return out


def logic(pkg: dict[str, Any]) -> dict[str, Any]:
    """The package without its images: all the engine needs to play it."""
    return {k: v for k, v in pkg.items() if k != "assets"}
