"""Parsing of the ``lay`` layout expression language.

Grammar (from the README)::

    layout  = cols ;
    cols    = rows , { rows } ;          (* whitespace separated *)
    rows    = item , { "/" , item } ;
    item    = number
            | group
            | number , ":" , group ;
    group   = "(" , layout , ")" ;
    number  = ? decimal > 0 ? ;
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

COLS = "cols"
ROWS = "rows"

#: Human readable names for the two split axes.
AXIS_NAMES = {COLS: "columns", ROWS: "rows"}


class LayError(Exception):
    """Base class for every error ``lay`` reports."""

    exit_code = 1


class ParseError(LayError):
    """The layout expression is not valid."""

    exit_code = 1

    def __init__(self, message: str, source: str = "", pos: int | None = None):
        super().__init__(message)
        self.message = message
        self.source = source
        self.pos = pos

    def caret(self) -> str | None:
        """Return a two line ``source``/caret excerpt, or ``None``."""
        if not self.source or self.pos is None:
            return None
        return f"    {self.source}\n    {' ' * self.pos}^"


@dataclass(frozen=True)
class Node:
    """Base class for layout tree nodes. ``weight`` is relative to siblings."""

    weight: float = 1.0

    @property
    def leaf_count(self) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class Leaf(Node):
    """A single pane."""

    @property
    def leaf_count(self) -> int:
        return 1

    def describe(self) -> str:
        return f"pane(w={format_weight(self.weight)})"


@dataclass(frozen=True)
class Split(Node):
    """A row or column split holding two or more children."""

    axis: str = COLS
    children: tuple[Node, ...] = field(default_factory=tuple)

    @property
    def leaf_count(self) -> int:
        return sum(child.leaf_count for child in self.children)

    def describe(self) -> str:
        inner = " ".join(child.describe() for child in self.children)
        return f"{AXIS_NAMES[self.axis]}(w={format_weight(self.weight)}: {inner})"


def format_weight(value: float) -> str:
    """Render a weight without a pointless trailing ``.0``."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


# --------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<number>\d+\.\d*|\.\d+|\d+)
  | (?P<lparen>\()
  | (?P<rparen>\))
  | (?P<slash>/)
  | (?P<colon>:)
  | (?P<bad>.)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    pos: int


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    for match in _TOKEN_RE.finditer(source):
        kind = match.lastgroup
        assert kind is not None
        if kind == "space":
            continue
        if kind == "bad":
            raise ParseError(
                f"unexpected character {match.group()!r}", source, match.start()
            )
        tokens.append(Token(kind, match.group(), match.start()))
    tokens.append(Token("end", "", len(source)))
    return tokens


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

_ITEM_START = {"number", "lparen"}

_DESCRIBE = {
    "number": "a number",
    "lparen": "'('",
    "rparen": "')'",
    "slash": "'/'",
    "colon": "':'",
    "end": "end of input",
}


class _Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = tokenize(source)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def error(self, message: str, token: Token | None = None) -> ParseError:
        token = token or self.current
        return ParseError(message, self.source, token.pos)

    # -- productions ------------------------------------------------------

    def parse(self) -> Node:
        if self.current.kind == "end":
            raise self.error("empty layout expression")
        node = self.parse_cols()
        if self.current.kind != "end":
            raise self.error(f"unexpected {_DESCRIBE[self.current.kind]}")
        return node

    def parse_cols(self) -> Node:
        items = [self.parse_rows()]
        while self.current.kind in _ITEM_START:
            items.append(self.parse_rows())
        if len(items) == 1:
            return items[0]
        return Split(weight=1.0, axis=COLS, children=tuple(items))

    def parse_rows(self) -> Node:
        parts = [self.parse_item()]
        while self.current.kind == "slash":
            self.advance()
            parts.append(self.parse_item())
        if len(parts) == 1:
            return parts[0]
        return Split(weight=1.0, axis=ROWS, children=tuple(parts))

    def parse_item(self) -> Node:
        token = self.current
        if token.kind not in _ITEM_START:
            raise self.error(
                f"expected a number or '(', found {_DESCRIBE[token.kind]}"
            )
        if token.kind == "lparen":
            # A bare group always has weight 1, whatever it contains.
            return self.parse_group()
        number_token = self.advance()
        weight = self.parse_number(number_token)
        if self.current.kind == "colon":
            self.advance()
            if self.current.kind != "lparen":
                raise self.error(
                    f"expected '(' after ':', found {_DESCRIBE[self.current.kind]}"
                )
            group = self.parse_group()
            return replace(group, weight=weight)
        return Leaf(weight=weight)

    def parse_group(self) -> Node:
        self.advance()  # '('
        if self.current.kind == "rparen":
            raise self.error("empty group '()'")
        inner = self.parse_cols()
        if self.current.kind != "rparen":
            raise self.error(
                f"expected ')', found {_DESCRIBE[self.current.kind]}"
            )
        self.advance()
        # Normalise: a group's own weight never depends on its contents.
        return replace(inner, weight=1.0)

    def parse_number(self, token: Token) -> float:
        try:
            value = float(token.text)
        except ValueError:  # pragma: no cover - regex already constrains this
            raise self.error(f"invalid number {token.text!r}", token) from None
        if value <= 0:
            raise self.error("weights must be greater than zero", token)
        return value


def parse(source: str) -> Node:
    """Parse ``source`` into a layout tree, or raise :class:`ParseError`."""
    return _Parser(source).parse()
