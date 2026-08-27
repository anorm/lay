"""Command line entry point for ``lay``."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

import click

from . import diagram as diagram_mod
from . import editor, geometry, tmux
from .decode import decode as decode_layout
from .parser import AXIS_NAMES, LayError, Node, ParseError, parse

try:
    __version__ = _version("lay")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0+dev"


class CountMismatch(LayError):
    """The layout wants a different number of panes than the window has."""

    exit_code = 2


#: Widest diagram `-n` will draw before scaling the geometry down.
DIAGRAM_WIDTH = 72


def _fail(message: str) -> None:
    click.echo(f"lay: {message}", err=True)


def _describe_cells(cell: geometry.Cell, depth: int = 0, counter=None) -> list[str]:
    counter = counter if counter is not None else [0]
    pad = "  " * (depth + 1)
    box = f"{cell.width}x{cell.height}+{cell.x}+{cell.y}"
    field = f"{pad}{box}".ljust(28)
    if cell.is_leaf:
        line = f"{field}pane {counter[0]}"
        counter[0] += 1
        return [line]
    assert cell.axis is not None  # a cell with children is always a split
    lines = [f"{field}{AXIS_NAMES[cell.axis]}"]
    for child in cell.children:
        lines.extend(_describe_cells(child, depth + 1, counter))
    return lines


def _report(window, tree, cell: geometry.Cell) -> None:
    if window.panes_known:
        plural = "" if window.pane_count == 1 else "s"
        ids = " ".join(window.pane_ids) or "none"
        where = f" ({window.pane_count} pane{plural}: {ids})"
    else:
        where = ""
    click.echo(f"window: {window.width}x{window.height}{where}", err=True)
    click.echo(f"tree:   {tree.describe()}", err=True)
    click.echo("cells:", err=True)
    for line in _describe_cells(cell):
        click.echo(line, err=True)


def _parse_or_report(source: str) -> tuple[Node | None, int]:
    """Parse ``source``, reporting any error. Returns ``(tree, exit_code)``."""
    try:
        return parse(source), 0
    except ParseError as exc:
        _fail(exc.message)
        excerpt = exc.caret()
        if excerpt:
            click.echo(excerpt, err=True)
        return None, exc.exit_code


def run(
    words: tuple[str, ...],
    target: str | None,
    create: bool,
    dry_run: bool,
    verbose: bool,
) -> int:
    source = " ".join(words).strip()

    # No layout means edit the window's current one in $EDITOR; that is
    # deferred until the window has been measured, so ``tree`` stays None.
    tree: Node | None = None
    if source:
        tree, code = _parse_or_report(source)
        if tree is None:
            return code

    try:
        server = tmux.connect()
        # A dry run reads the window size and nothing else.
        window = tmux.measure(server, target)

        if tree is None:
            current = decode_layout(tmux.current_layout(server, window))
            if verbose:
                click.echo(f"current: {current}", err=True)
            edited = editor.edit(current)
            if edited == current:
                click.echo("lay: layout unchanged", err=True)
                return 0
            tree, code = _parse_or_report(edited)
            if tree is None:
                return code

        wanted = tree.leaf_count

        short = 0
        if not dry_run:
            window = tmux.load_panes(server, window)
            short = wanted - window.pane_count
            if short != 0 and not (create and short > 0):
                raise CountMismatch(
                    f"layout needs {wanted} panes, window has {window.pane_count}"
                )

        # Compute the geometry before touching anything: a layout that cannot
        # fit must not leave a trail of freshly split panes behind it.
        cell = geometry.build(tree, window.width, window.height)

        if verbose:
            _report(window, tree, cell)

        if dry_run:
            scaled = diagram_mod.fit(
                tree, window.width, window.height, DIAGRAM_WIDTH
            )
            click.echo(diagram_mod.render_diagram(scaled))
            return 0

        if short > 0:
            window = tmux.create_panes(server, window, short)
            if window.pane_count != wanted:
                raise CountMismatch(
                    f"layout needs {wanted} panes, "
                    f"window has {window.pane_count}"
                )

        tmux.apply(server, window, geometry.render(cell, window.pane_ids))
        return 0

    except LayError as exc:
        _fail(str(exc))
        return exc.exit_code


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Arrange the panes of a tmux window from a layout expression.\n\n"
    "With no layout, the window's current one is opened in $EDITOR.\n\n"
    "Examples:\n\n"
    "  lay                  edit the current layout in $EDITOR\n\n"
    "  lay '1 1 1'          three equal columns\n\n"
    "  lay '(4 4) / 1'      two columns above one full-width pane\n\n"
    "  lay '3:(1 / 1) 1'    a tall stacked column at 75%, sidebar at 25%",
)
@click.argument("words", nargs=-1)
@click.option("-t", "target", metavar="<target>", default=None,
              help="Target window, in tmux target-window form.")
@click.option("-c", "--create", is_flag=True,
              help="Split to create missing panes instead of failing.")
@click.option("-n", "--dry-run", is_flag=True,
              help="Print an ASCII diagram of the layout without applying it.")
@click.option("-v", "--verbose", is_flag=True,
              help="Report the parsed tree and the computed cell geometry.")
@click.version_option(__version__, "-V", "--version", prog_name="lay")
def cli(words, target, create, dry_run, verbose):
    raise SystemExit(run(words, target, create, dry_run, verbose))


def main() -> None:
    try:
        cli.main(standalone_mode=False)
    except click.UsageError as exc:
        _fail(exc.format_message())
        sys.exit(1)
    except click.Abort:
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
