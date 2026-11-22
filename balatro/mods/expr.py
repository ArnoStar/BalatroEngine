"""The expression language of content mods: small, safe and deterministic.

A content mod (``balatro.mods.content``) is data, never code: what its jokers
check and compute is written as expressions such as::

    card.rank == 7 and is_suit(card, 'Hearts')
    self.mult + 2 * count_face(scoring)
    chance(1, 4)

Grammar (lowest precedence first)::

    expr    := or
    or      := and ('or' and)*
    and     := not ('and' not)*
    not     := 'not' not | compare
    compare := sum (('==' | '!=' | '<' | '<=' | '>' | '>=') sum)?
    sum     := product (('+' | '-') product)*
    product := unary (('*' | '/' | '%') unary)*
    unary   := '-' unary | power
    power   := postfix ('^' unary)?
    postfix := primary ('.' NAME)*
    primary := NUMBER | STRING | 'true' | 'false' | 'nil'
             | NAME '(' (expr (',' expr)*)? ')' | NAME | '(' expr ')'

Values are numbers, strings, booleans, nil and opaque references (a card, a
list of cards) that only functions and ``.field`` read.  As in Lua, only
``false`` and ``nil`` are false (``0`` is true: write ``self.count > 0``),
``and``/``or`` give one of their operands (``self.x or 0``), ``/`` divides
(by zero: inf or nan) and ``%`` is Lua's modulo.  A type mismatch (a number
plus a string, a field of nil) gives nil instead of an error, so an
expression never stops a run.

The game's front end has a twin of this file (TypeScript) for the values its
card descriptions show: keep both in step.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Iterable

from ..lua import lua_div, lua_mod, lua_pow

MAX_LENGTH = 500
MAX_DEPTH = 32

Node = tuple  # ("num", v) ("str", s) ("const", v) ("var", root, path) ("call", name, args) ...


class ExprError(ValueError):
    """An expression that doesn't parse, or names something that doesn't exist."""


_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==|!=|<=|>=|[<>+\-*/%^(),.])
""", re.VERBOSE)
_KEYWORDS = {"and", "or", "not", "true", "false", "nil"}
_COMPARE = {"==", "!=", "<", "<=", ">", ">="}


def _tokens(src: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if m is None:
            raise ExprError(f"unexpected {src[pos]!r} at {pos + 1}")
        pos = m.end()
        kind = m.lastgroup or ""
        if kind == "ws":
            continue
        text = m.group()
        if kind == "name" and text in _KEYWORDS:
            kind = "kw"
        out.append((kind, text))
    out.append(("end", ""))
    return out


def _unquote(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s[1:-1])


class _Parser:
    def __init__(self, src: str) -> None:
        self.toks = _tokens(src)
        self.i = 0
        self.depth = 0

    def peek(self) -> tuple[str, str]:
        return self.toks[self.i]

    def take(self) -> tuple[str, str]:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, text: str) -> None:
        kind, t = self.take()
        if t != text or kind not in ("op", "kw"):
            raise ExprError(f"expected {text!r}, found {t or 'the end'!r}")

    def nest(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError("the expression is nested too deeply")

    def parse(self) -> Node:
        node = self.or_()
        kind, t = self.peek()
        if kind != "end":
            raise ExprError(f"unexpected {t!r}")
        return node

    def or_(self) -> Node:
        node = self.and_()
        while self.peek() == ("kw", "or"):
            self.take()
            node = ("or", node, self.and_())
        return node

    def and_(self) -> Node:
        node = self.not_()
        while self.peek() == ("kw", "and"):
            self.take()
            node = ("and", node, self.not_())
        return node

    def not_(self) -> Node:
        if self.peek() == ("kw", "not"):
            self.take()
            self.nest()
            node = ("not", self.not_())
            self.depth -= 1
            return node
        return self.compare()

    def compare(self) -> Node:
        node = self.sum_()
        kind, t = self.peek()
        if kind == "op" and t in _COMPARE:
            self.take()
            node = ("bin", t, node, self.sum_())
            kind, t = self.peek()
            if kind == "op" and t in _COMPARE:
                raise ExprError("comparisons don't chain: use 'and'")
        return node

    def sum_(self) -> Node:
        node = self.product()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.product())
        return node

    def product(self) -> Node:
        node = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/", "%"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self) -> Node:
        if self.peek() == ("op", "-"):
            self.take()
            self.nest()
            node = ("neg", self.unary())
            self.depth -= 1
            return node
        return self.power()

    def power(self) -> Node:
        node = self.postfix()
        if self.peek() == ("op", "^"):
            self.take()
            self.nest()
            node = ("bin", "^", node, self.unary())
            self.depth -= 1
        return node

    def postfix(self) -> Node:
        node = self.primary()
        while self.peek() == ("op", "."):
            self.take()
            kind, name = self.take()
            if kind != "name":
                raise ExprError(f"expected a field name after '.', found {name or 'the end'!r}")
            if node[0] == "var":
                node = ("var", node[1], node[2] + (name,))
            else:
                node = ("field", node, name)
        return node

    def primary(self) -> Node:
        kind, t = self.take()
        if kind == "num":
            v = float(t)
            return ("num", int(v) if "." not in t else v)
        if kind == "str":
            return ("str", _unquote(t))
        if kind == "kw" and t in ("true", "false", "nil"):
            return ("const", {"true": True, "false": False, "nil": None}[t])
        if kind == "name":
            if self.peek() == ("op", "("):
                self.take()
                self.nest()
                args: list[Node] = []
                if self.peek() != ("op", ")"):
                    args.append(self.or_())
                    while self.peek() == ("op", ","):
                        self.take()
                        args.append(self.or_())
                self.expect(")")
                self.depth -= 1
                return ("call", t, tuple(args))
            return ("var", t, ())
        if (kind, t) == ("op", "("):
            self.nest()
            node = self.or_()
            self.expect(")")
            self.depth -= 1
            return node
        raise ExprError(f"unexpected {t or 'the end'!r}")


def parse(src: str) -> Node:
    """The expression's syntax tree (ExprError if it doesn't parse)."""
    if not isinstance(src, str):
        raise ExprError("an expression is a string")
    if len(src) > MAX_LENGTH:
        raise ExprError(f"an expression has at most {MAX_LENGTH} characters")
    if not src.strip():
        raise ExprError("the expression is empty")
    return _Parser(src).parse()


# ------------------------------------------------------------------ values
def truthy(v: Any) -> bool:
    return v is not None and v is not False


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _arith(op: str, a: Any, b: Any) -> Any:
    if not (is_number(a) and is_number(b)):
        return None
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return lua_div(a, b)
    if op == "%":
        return lua_mod(a, b)
    if op == "^":
        return lua_pow(a, b)
    return None


def _compare(op: str, a: Any, b: Any) -> Any:
    if op == "==":
        return _same(a, b)
    if op == "!=":
        return not _same(a, b)
    if not (is_number(a) and is_number(b)):
        return None
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    return a >= b


def _same(a: Any, b: Any) -> bool:
    if is_number(a) and is_number(b):
        return bool(a == b)
    if type(a) is not type(b):
        return False
    return bool(a == b) if isinstance(a, (str, bool)) or a is None else a is b


def _num(f: Callable[..., Any]) -> Callable[..., Any]:
    def g(*args: Any) -> Any:
        if not all(is_number(a) for a in args):
            return None
        return f(*args)
    return g


def _round(x: float) -> float:
    return math.floor(x + 0.5)


# name: (min args, max args, function); pure, the same in the front end
PURE_FUNCTIONS: dict[str, tuple[int, int, Callable[..., Any]]] = {
    "min": (1, 16, _num(min)),
    "max": (1, 16, _num(max)),
    "floor": (1, 1, _num(math.floor)),
    "ceil": (1, 1, _num(math.ceil)),
    "abs": (1, 1, _num(abs)),
    "round": (1, 1, _num(_round)),
    "clamp": (3, 3, _num(lambda x, lo, hi: max(lo, min(hi, x)))),
}
LAZY_FUNCTIONS = {"if": (3, 3)}


class Env:
    """What an expression can read: ``lookup(root, path)`` for names and
    fields, ``call(name, args)`` for the context's functions."""

    def lookup(self, root: str, path: tuple[str, ...]) -> Any:
        return None

    def field(self, value: Any, name: str) -> Any:
        return None

    def call(self, name: str, args: list[Any]) -> Any:
        return None


def evaluate(node: Node, env: Env) -> Any:
    tag = node[0]
    if tag in ("num", "str", "const"):
        return node[1]
    if tag == "var":
        return env.lookup(node[1], node[2])
    if tag == "field":
        base = evaluate(node[1], env)
        return None if base is None else env.field(base, node[2])
    if tag == "and":
        a = evaluate(node[1], env)
        return evaluate(node[2], env) if truthy(a) else a
    if tag == "or":
        a = evaluate(node[1], env)
        return a if truthy(a) else evaluate(node[2], env)
    if tag == "not":
        return not truthy(evaluate(node[1], env))
    if tag == "neg":
        v = evaluate(node[1], env)
        return -v if is_number(v) else None
    if tag == "bin":
        op = node[1]
        a, b = evaluate(node[2], env), evaluate(node[3], env)
        return _compare(op, a, b) if op in _COMPARE else _arith(op, a, b)
    if tag == "call":
        name, args = node[1], node[2]
        if name == "if":
            return evaluate(args[1], env) if truthy(evaluate(args[0], env)) else evaluate(args[2], env)
        values = [evaluate(a, env) for a in args]
        if name in PURE_FUNCTIONS:
            return PURE_FUNCTIONS[name][2](*values)
        return env.call(name, values)
    return None


# ------------------------------------------------------------------ checking
class Scope:
    """What an expression may name where it is written: its roots (with the
    fields each has, or None for any), the context's functions (name:
    (min args, max args)) and whether it may draw random numbers."""

    def __init__(self, roots: dict[str, Iterable[str] | None], functions: dict[str, tuple[int, int]],
                 impure: Iterable[str] = (), allow_impure: bool = True, refs: Iterable[str] = ()) -> None:
        self.roots = {k: (set(v) if v is not None else None) for k, v in roots.items()}
        self.refs = set(refs)  # (roots that are a thing themselves, a card: usable without a field)
        self.functions = dict(functions)
        self.impure = set(impure)
        self.allow_impure = allow_impure


def check(node: Node, scope: Scope) -> list[str]:
    """What is wrong with the expression in this scope (empty: nothing)."""
    errors: list[str] = []

    def walk(n: Node) -> None:
        tag = n[0]
        if tag == "var":
            root, path = n[1], n[2]
            if root not in scope.roots:
                errors.append(f"unknown name {root!r}")
                return
            fields = scope.roots[root]
            if fields is not None:
                if not path and fields and root not in scope.refs:
                    errors.append(f"{root!r} needs a field ({', '.join(sorted(fields))})")
                elif path and path[0] not in fields:
                    errors.append(f"{root!r} has no field {path[0]!r}"
                                  + (f" (it has {', '.join(sorted(fields))})" if fields else ""))
        elif tag == "field":
            walk(n[1])
        elif tag in ("and", "or"):
            walk(n[1])
            walk(n[2])
        elif tag in ("not", "neg"):
            walk(n[1])
        elif tag == "bin":
            walk(n[2])
            walk(n[3])
        elif tag == "call":
            name, args = n[1], n[2]
            if name in PURE_FUNCTIONS:
                lo, hi = PURE_FUNCTIONS[name][:2]
            elif name in LAZY_FUNCTIONS:
                lo, hi = LAZY_FUNCTIONS[name]
            elif name in scope.functions:
                lo, hi = scope.functions[name]
                if name in scope.impure and not scope.allow_impure:
                    errors.append(f"{name}() draws a random number: not allowed here (it would change the run "
                                  "where the game only looks)")
            else:
                errors.append(f"unknown function {name!r}")
                lo, hi = 0, len(args)
            if not lo <= len(args) <= hi:
                errors.append(f"{name}() takes {lo if lo == hi else f'{lo} to {hi}'} argument{'s' if hi != 1 else ''}")
            for a in args:
                walk(a)

    walk(node)
    return errors


def names_used(node: Node, root: str) -> set[str]:
    """The fields of ``root`` the expression reads (``self.mult`` -> {'mult'})."""
    out: set[str] = set()

    def walk(n: Node) -> None:
        tag = n[0]
        if tag == "var" and n[1] == root and n[2]:
            out.add(n[2][0])
        for child in n[1:]:
            if isinstance(child, tuple) and child and isinstance(child[0], str):
                walk(child)
            elif isinstance(child, tuple):
                for c in child:
                    if isinstance(c, tuple) and c and isinstance(c[0], str):
                        walk(c)

    walk(node)
    return out
