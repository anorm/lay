"""ASCII diagrams of a computed layout.

Borders are accumulated as direction bitmasks on a character grid, so that
junctions between adjacent splits resolve to the right box-drawing glyph
(``┬``, ``┴``, ``├``, ``┤``, ``┼``) instead of overwriting one another.
"""

from __future__ import annotations

from .geometry import Cell, FitError, build
from .parser import COLS, Node

_N, _S, _E, _W = 1, 2, 4, 8

_CHARS = {
    0: " ",
    _N: "│",
    _S: "│",
    _E: "─",
    _W: "─",
    _N | _S: "│",
    _E | _W: "─",
    _N | _E: "└",
    _N | _W: "┘",
    _S | _E: "┌",
    _S | _W: "┐",
    _N | _S | _E: "├",
    _N | _S | _W: "┤",
    _N | _E | _W: "┴",
    _S | _E | _W: "┬",
    _N | _S | _E | _W: "┼",
}


class _Canvas:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.bits = [[0] * width for _ in range(height)]
        self.text: dict[tuple[int, int], str] = {}

    def h_line(self, row: int, x0: int, x1: int) -> None:
        for x in range(x0, x1 + 1):
            if x > x0:
                self.bits[row][x] |= _W
            if x < x1:
                self.bits[row][x] |= _E

    def v_line(self, col: int, y0: int, y1: int) -> None:
        for y in range(y0, y1 + 1):
            if y > y0:
                self.bits[y][col] |= _N
            if y < y1:
                self.bits[y][col] |= _S

    def label(self, x: int, y: int, value: str) -> None:
        for offset, char in enumerate(value):
            self.text[(y, x + offset)] = char

    def render(self) -> str:
        lines = []
        for y in range(self.height):
            row = [
                self.text.get((y, x)) or _CHARS[self.bits[y][x]]
                for x in range(self.width)
            ]
            lines.append("".join(row).rstrip())
        return "\n".join(lines)


def _draw_borders(cell: Cell, canvas: _Canvas) -> None:
    """Draw the border between each pair of adjacent children, recursively."""
    if cell.is_leaf:
        return
    for first in cell.children[:-1]:
        if cell.axis == COLS:
            # The border sits in the one-cell gap the geometry left behind,
            # and is extended by one cell at each end so that it joins the
            # enclosing border with a proper tee.
            col = first.x + first.width + 1
            canvas.v_line(col, cell.y, cell.y + cell.height + 1)
        else:
            row = first.y + first.height + 1
            canvas.h_line(row, cell.x, cell.x + cell.width + 1)
    for child in cell.children:
        _draw_borders(child, canvas)


def render_diagram(cell: Cell) -> str:
    """Draw ``cell`` as a box diagram with each pane's index inside it."""
    width, height = cell.width + 2, cell.height + 2
    canvas = _Canvas(width, height)

    canvas.h_line(0, 0, width - 1)
    canvas.h_line(height - 1, 0, width - 1)
    canvas.v_line(0, 0, height - 1)
    canvas.v_line(width - 1, 0, height - 1)

    _draw_borders(cell, canvas)

    for index, leaf in enumerate(cell.leaves()):
        text = str(index)
        if len(text) > leaf.width:
            continue
        x = leaf.x + 1 + (leaf.width - len(text)) // 2
        y = leaf.y + 1 + leaf.height // 2
        canvas.label(x, y, text)

    return canvas.render()


def fit(node: Node, width: int, height: int, max_width: int) -> Cell:
    """Build ``node`` scaled down to ``max_width`` while keeping cell aspect.

    Diagrams of a real 200-column window are unreadable, so shrink the
    geometry proportionally. If the layout has too many panes to survive the
    shrink, grow back towards the true size until it fits.
    """
    if width <= max_width:
        return build(node, width, height)

    scale = max_width / width
    target_width = max_width
    while target_width <= width:
        target_height = max(1, round(height * scale))
        try:
            return build(node, target_width, target_height)
        except FitError:
            target_width += 1
            scale = target_width / width
    return build(node, width, height)
