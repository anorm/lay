"""Talking to tmux through libtmux.

Everything goes through :meth:`libtmux.Server.cmd` so that tmux itself
resolves ``-t`` targets, which keeps ``lay -t dev:2`` behaving exactly like
any other tmux command.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

from libtmux import Server
from libtmux.exc import LibTmuxException

from .parser import LayError


class TmuxError(LayError):
    """tmux is unavailable, or the target window does not exist."""

    exit_code = 4


@dataclass
class Window:
    """The facts about a target window that ``lay`` needs.

    ``pane_ids`` is ``None`` until :func:`load_panes` has been called, which
    is different from a window with no panes. A dry run never loads them.
    """

    target: str
    width: int
    height: int
    pane_ids: list[str] | None = None

    @property
    def panes_known(self) -> bool:
        return self.pane_ids is not None

    @property
    def pane_count(self) -> int:
        """Only meaningful once :func:`load_panes` has run."""
        return len(self.pane_ids or [])


def connect() -> Server:
    """Return a Server bound to the socket of the surrounding tmux, if any."""
    tmux_env = os.environ.get("TMUX")
    try:
        if tmux_env:
            socket_path = tmux_env.split(",")[0]
            if socket_path:
                return Server(socket_path=socket_path)
        return Server()
    except LibTmuxException as exc:  # pragma: no cover - depends on host
        raise TmuxError(f"cannot reach tmux: {exc}") from exc


def _run(server: Server, *args: str) -> list[str]:
    try:
        result = server.cmd(*args)
    except LibTmuxException as exc:
        raise TmuxError(str(exc)) from exc
    if result.stderr:
        raise TmuxError("; ".join(result.stderr))
    return list(result.stdout)


def measure(server: Server, target: str | None) -> Window:
    """Read just the geometry of ``target`` (default: the current window).

    This is the only tmux call a dry run is allowed to make, so it must not
    reach for the pane list.
    """
    if target is None and not os.environ.get("TMUX"):
        raise TmuxError("not inside a tmux session (use -t to name a window)")

    scope = ["-t", target] if target else []

    # The format goes in the message argument rather than behind -F, which is
    # a much newer flag than the rest of what lay relies on.
    fields = _run(
        server,
        "display-message",
        "-p",
        *scope,
        "#{window_width}\t#{window_height}\t#{window_id}",
    )
    if not fields or not fields[0].strip():
        raise TmuxError(f"no such window: {target}" if target else "no current window")

    width_text, height_text, window_id = fields[0].split("\t")
    return Window(
        # Pin the window by id so a later split or select-layout cannot drift
        # onto a different window if the active one changes underneath us.
        target=target or window_id,
        width=int(width_text),
        height=int(height_text),
    )


def load_panes(server: Server, window: Window) -> Window:
    """Return ``window`` with its pane list filled in."""
    panes = _run(server, "list-panes", "-t", window.target, "-F", "#{pane_id}")
    return replace(
        window, pane_ids=[line.strip() for line in panes if line.strip()]
    )


def active_pane(server: Server, window: Window) -> str:
    """Return the id of the pane that is currently active in ``window``."""
    lines = _run(
        server, "display-message", "-p", "-t", window.target, "#{pane_id}"
    )
    if not lines or not lines[0].strip():
        raise TmuxError("could not read the active pane")
    return lines[0].strip()


def current_layout(server: Server, window: Window) -> str:
    """Read the window's current tmux layout string.

    Kept out of :func:`measure` on purpose: a dry run must issue exactly one
    tmux command, and only the editing path needs this one.
    """
    lines = _run(
        server, "display-message", "-p", "-t", window.target, "#{window_layout}"
    )
    if not lines or not lines[0].strip():
        raise TmuxError("could not read the current window layout")
    return lines[0].strip()


def create_panes(server: Server, window: Window, needed: int) -> Window:
    """Split ``needed`` extra panes into the window, keeping room as we go.

    ``split-window`` focuses whatever it just made, so the pane the user was
    working in is noted first and selected again once the splitting is done.
    Filling out a layout must not move them somewhere else.
    """
    focused = active_pane(server, window)
    for _ in range(needed):
        _run(server, "split-window", "-t", window.target)
        # Re-tile between splits, otherwise tmux runs out of room to divide.
        _run(server, "select-layout", "-t", window.target, "tiled")
    _run(server, "select-pane", "-t", focused)
    return load_panes(server, window)


def apply(server: Server, window: Window, layout: str) -> None:
    """Apply a custom layout string in a single call."""
    _run(server, "select-layout", "-t", window.target, layout)
