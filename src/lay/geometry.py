"""Turning a parsed layout tree into concrete cell geometry.

Every split consumes one column (or row) for the border tmux draws between
adjacent panes, so for ``n`` children along an axis of length ``L`` the
children share ``L - (n - 1)`` cells between them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .parser import COLS, ROWS, LayError, Leaf, Node, Split


class FitError(LayError):
    """The layout cannot be realised without a pane smaller than one cell."""

    exit_code = 3


@dataclass
class Cell:
    """A node of the layout tree with a concrete rectangle attached."""

    node: Node
    x: int
    y: int
    width: int
    height: int
    children: list[Cell] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def axis(self) -> str | None:
        return self.node.axis if isinstance(self.node, Split) else None

    def leaves(self) -> list[Cell]:
        """Return the leaf cells in depth-first, written order."""
        if self.is_leaf:
            return [self]
        found: list[Cell] = []
        for child in self.children:
            found.extend(child.leaves())
        return found

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def distribute(total: int, weights: Sequence[float]) -> list[int]:
    """Split ``total`` cells between ``weights``, largest remainder first.

    Ties are broken in favour of the earlier sibling, which is what tmux
    itself does when it halves an odd-width pane.
    """
    weight_sum = sum(weights)
    exact = [total * weight / weight_sum for weight in weights]
    sizes = [int(value) for value in exact]
    remainder = total - sum(sizes)
    if remainder:
        order = sorted(
            range(len(weights)),
            key=lambda i: (-(exact[i] - sizes[i]), i),
        )
        for i in order[:remainder]:
            sizes[i] += 1
    return sizes


def _axis_length(axis: str, width: int, height: int) -> int:
    return width if axis == COLS else height


def build(node: Node, width: int, height: int, x: int = 0, y: int = 0) -> Cell:
    """Lay ``node`` out inside the given rectangle."""
    if width < 1 or height < 1:
        raise FitError("layout does not fit: a pane would be smaller than 1 cell")

    if isinstance(node, Leaf):
        return Cell(node=node, x=x, y=y, width=width, height=height)

    assert isinstance(node, Split)
    count = len(node.children)
    length = _axis_length(node.axis, width, height)
    available = length - (count - 1)
    if available < count:
        raise FitError("layout does not fit: a pane would be smaller than 1 cell")

    sizes = distribute(available, [child.weight for child in node.children])

    cell = Cell(node=node, x=x, y=y, width=width, height=height)
    offset = 0
    for child, size in zip(node.children, sizes):
        if node.axis == COLS:
            cell.children.append(build(child, size, height, x + offset, y))
        else:
            cell.children.append(build(child, width, size, x, y + offset))
        offset += size + 1  # +1 for the border
    return cell


# --------------------------------------------------------------------------
# tmux layout strings
# --------------------------------------------------------------------------

_BRACKETS = {COLS: ("{", "}"), ROWS: ("[", "]")}


def checksum(body: str) -> int:
    """tmux's ``layout_checksum``: a 16 bit rotate-right-and-add."""
    total = 0
    for byte in body.encode():
        total = ((total >> 1) + ((total & 1) << 15)) & 0xFFFF
        total = (total + byte) & 0xFFFF
    return total


def _pane_token(pane_ids: list[str], index: int) -> str:
    """The numeric pane id tmux expects in a layout string.

    tmux writes ``lc->wp->id``, i.e. ``0`` rather than ``%0``, and parses it
    with ``%u`` -- a leading ``%`` makes the whole layout invalid. Anything
    that is not a plain number falls back to the leaf's ordinal, which is
    harmless because tmux ignores these values and assigns panes in order.
    """
    if index < len(pane_ids):
        raw = pane_ids[index].lstrip("%")
        if raw.isdigit():
            return raw
    return str(index)


def _render(cell: Cell, pane_ids: list[str], counter: list[int]) -> str:
    prefix = f"{cell.width}x{cell.height},{cell.x},{cell.y}"
    if cell.is_leaf:
        index = counter[0]
        counter[0] += 1
        return f"{prefix},{_pane_token(pane_ids, index)}"
    assert cell.axis is not None  # a cell with children is always a split
    open_b, close_b = _BRACKETS[cell.axis]
    inner = ",".join(_render(child, pane_ids, counter) for child in cell.children)
    return f"{prefix}{open_b}{inner}{close_b}"


def render(cell: Cell, pane_ids: list[str] | None = None) -> str:
    """Render ``cell`` as a checksummed tmux layout string.

    tmux ignores the pane identifiers when parsing a layout and assigns the
    window's panes to the leaves in order, but emitting the real ids keeps the
    output identical to what tmux would print for the same arrangement.
    """
    body = _render(cell, pane_ids or [], [0])
    return f"{checksum(body):04x},{body}"
