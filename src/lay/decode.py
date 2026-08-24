"""Reading a tmux layout string back into a ``lay`` expression.

This is the inverse of :func:`lay.geometry.render`. tmux stores the full tree
in ``#{window_layout}``, so the structure comes back exactly; what has to be
recovered is the *weights*, because the geometry only holds rounded cell
counts. A 178 column window split ``1 1`` is stored as ``89`` and ``88``, so
naively reading the sizes as weights would produce ``lay '89 88'``.

:func:`recover_weights` therefore looks for the simplest integer weights that
reproduce the observed sizes exactly when fed back through
:func:`lay.geometry.distribute`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import reduce
from math import gcd

from .geometry import distribute
from .parser import COLS, ROWS, LayError, Leaf, Node, Split, format_weight

#: Largest denominator tried when looking for simple weights.
MAX_DENOMINATOR = 128

_HEAD = re.compile(r"(\d+)x(\d+),(\d+),(\d+)")
_PANE = re.compile(r"\d+")
_BRACKETS = {"{": (COLS, "}"), "[": (ROWS, "]")}


class DecodeError(LayError):
    """tmux returned a layout string that could not be understood."""

    exit_code = 4


@dataclass(frozen=True)
class Box:
    """A node of a tmux layout string: a rectangle and its children."""

    axis: str | None  # None for a leaf
    width: int
    height: int
    children: tuple["Box", ...] = ()

    @property
    def is_leaf(self) -> bool:
        return self.axis is None

    def extent(self, axis: str) -> int:
        return self.width if axis == COLS else self.height


def parse_layout_string(layout: str) -> Box:
    """Parse ``843f,178x43,0,0{...}`` into a :class:`Box` tree.

    The leading checksum is optional and pane ids are discarded: tmux ignores
    them when parsing a layout and assigns panes to leaves in order, so the
    leaf order is the only mapping that matters.
    """
    body = layout.strip()
    if not _HEAD.match(body):
        _, _, body = body.partition(",")
    if not body:
        raise DecodeError("empty layout string")

    position = 0

    def node() -> Box:
        nonlocal position
        head = _HEAD.match(body, position)
        if head is None:
            raise DecodeError(f"malformed layout string at offset {position}")
        width, height = int(head.group(1)), int(head.group(2))
        position = head.end()

        if position < len(body) and body[position] in _BRACKETS:
            axis, closer = _BRACKETS[body[position]]
            position += 1
            children = [node()]
            while position < len(body) and body[position] == ",":
                position += 1
                children.append(node())
            if position >= len(body) or body[position] != closer:
                raise DecodeError(f"expected {closer!r} at offset {position}")
            position += 1
            return Box(axis, width, height, tuple(children))

        # A leaf: ",<pane id>".
        if position >= len(body) or body[position] != ",":
            raise DecodeError(f"expected a pane id at offset {position}")
        position += 1
        pane = _PANE.match(body, position)
        if pane is None:
            raise DecodeError(f"expected a pane id at offset {position}")
        position = pane.end()
        return Box(None, width, height)

    root = node()
    if position != len(body):
        raise DecodeError(f"trailing junk at offset {position}")
    return root


def recover_weights(available: int, sizes: list[int]) -> list[int]:
    """Smallest integer weights that reproduce ``sizes`` exactly.

    Falls back to the sizes themselves, which are always an exact solution,
    so this never fails -- but a layout tmux built itself (a mouse drag, or
    ``select-layout tiled``) may genuinely have no simple ratio.
    """
    for denominator in range(1, MAX_DENOMINATOR + 1):
        weights = [
            max(1, round(size * denominator / available)) for size in sizes
        ]
        divisor = reduce(gcd, weights)
        weights = [weight // divisor for weight in weights]
        if distribute(available, weights) == sizes:
            return weights
    return list(sizes)


def _weigh(box: Box, weight: float) -> Node:
    if box.is_leaf:
        return Leaf(weight=weight)
    assert box.axis is not None
    sizes = [child.extent(box.axis) for child in box.children]
    weights = recover_weights(sum(sizes), sizes)
    children = tuple(
        _weigh(child, child_weight)
        for child, child_weight in zip(box.children, weights)
    )
    return Split(weight=weight, axis=box.axis, children=children)


def to_tree(layout: str) -> Node:
    """Decode a tmux layout string into a weighted layout tree."""
    return _weigh(parse_layout_string(layout), 1.0)


def to_expression(node: Node, parent: str | None = None) -> str:
    """Render a layout tree as a ``lay`` expression.

    Parentheses are added only where the grammar needs them: ``/`` binds
    tighter than a space, so a column of rows needs none (``1 / 1 2``) but a
    row containing columns does (``(1 1) / 2``).
    """
    if isinstance(node, Leaf):
        return format_weight(node.weight)

    assert isinstance(node, Split)
    separator = " " if node.axis == COLS else " / "
    inner = separator.join(
        to_expression(child, node.axis) for child in node.children
    )

    if node.weight != 1:
        # There is no way to weight a bare column, so it has to become a group.
        return f"{format_weight(node.weight)}:({inner})"
    if parent is None:
        return inner
    if parent == ROWS or node.axis == COLS:
        return f"({inner})"
    return inner


def decode(layout: str) -> str:
    """Turn a tmux layout string straight into a ``lay`` expression."""
    return to_expression(to_tree(layout))
