"""Running ``$EDITOR`` over a layout expression.

The temp file, editor discovery and cleanup are all left to
:func:`click.edit`. What stays here is the bit that is specific to ``lay``:
the edit buffer allows ``#`` comments and may be spread over several lines,
neither of which is part of the layout language. Handling that here keeps the
grammar exactly as the README documents it.
"""

from __future__ import annotations

import sys

import click

from .parser import LayError

INSTRUCTIONS = """\

# Edit the layout, then save and exit. Lines starting with '#' are ignored,
# and emptying the file aborts without changing anything.
#
#   space   columns, side by side      1 2
#   /       rows, stacked              1 / 2
#   ( )     grouping                   (1 1) / 2
#   N:( )   weight a group             3:(1 1) 1
#
# '/' binds tighter than a space: '1 1 / 2' is a column beside a stack.
# Weights are relative, so '1 1' and '4 4' both mean two equal parts.
"""


class EditorError(LayError):
    """The edit was abandoned, or the editor could not be run."""

    exit_code = 1


def strip_comments(text: str) -> str:
    """Drop ``#`` comments and fold the remaining lines into one expression."""
    kept = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            kept.append(line)
    return " ".join(kept)


def edit(initial: str) -> str:
    """Open ``initial`` in an editor and return what came back.

    ``require_save`` is off on purpose: quitting without saving should return
    the expression untouched, which the caller then recognises as "unchanged"
    rather than treating it as an error.

    Raises :class:`EditorError` if the editor fails or the buffer is emptied.
    """
    if not sys.stdin.isatty():
        raise EditorError("cannot edit without a terminal")

    try:
        edited = click.edit(
            f"{initial}\n{INSTRUCTIONS}", extension=".lay", require_save=False
        )
    except click.ClickException as exc:
        raise EditorError(f"{exc.format_message()}, layout unchanged") from exc

    if edited is None:  # pragma: no cover - require_save is off
        raise EditorError("the editor returned nothing, layout unchanged")

    expression = strip_comments(edited)
    if not expression:
        raise EditorError("empty layout, nothing changed")
    return expression
