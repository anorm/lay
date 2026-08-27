"""End-to-end tests against a real tmux server on a private socket.

These are the tests that matter most: they assert that the layout string
``lay`` generates is byte-for-byte what tmux reports back after applying it,
checksum included.
"""

from __future__ import annotations

import itertools
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import uuid

import pytest

from lay import tmux as lay_tmux
from lay.cli import run
from lay.decode import decode
from lay.editor import strip_comments
from lay.geometry import build, render
from lay.parser import parse

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux is not installed"
)

WIDTH, HEIGHT = 178, 43

#: A leaf is the only node with a fourth number before its delimiter.
_LEAF = re.compile(r"(\d+x\d+,\d+,\d+,)\d+")


def normalise(layout: str) -> str:
    """Drop the checksum and renumber pane ids, leaving only the geometry."""
    body = layout.split(",", 1)[1]
    ordinals = itertools.count()
    return _LEAF.sub(lambda m: f"{m.group(1)}{next(ordinals)}", body)


class TmuxFixture:
    def __init__(self, socket: str):
        self.socket = socket
        # Filled in once the server is up; see the tmux_process fixture.
        self.socket_path = ""

    def tmux(self, *args: str) -> str:
        # -f /dev/null keeps the developer's ~/.tmux.conf out of the picture.
        # No test is known to fail without it, but options such as
        # main-pane-width do alter the layout strings compared here, so the
        # server starts bare rather than relying on that staying true.
        result = subprocess.run(
            ["tmux", "-L", self.socket, "-f", "/dev/null", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip()

    def reset(self) -> None:
        """Return the window to a single pane.

        Killing the session would take the whole server down with it and race
        against the next new-session, so trim panes instead: `kill-pane -a`
        removes every pane except the one named.
        """
        panes = self.tmux("list-panes", "-t", "t", "-F", "#{pane_id}").splitlines()
        if panes:
            if len(panes) > 1:
                self.tmux("kill-pane", "-a", "-t", panes[0])
            return
        self.tmux(
            "new-session", "-d", "-x", str(WIDTH), "-y", str(HEIGHT), "-s", "t"
        )

    @property
    def layout(self) -> str:
        return self.tmux("display-message", "-p", "#{window_layout}")

    @property
    def pane_count(self) -> int:
        return len(self.tmux("list-panes", "-F", "#{pane_id}").splitlines())

    @property
    def active_pane(self) -> str:
        return self.tmux("display-message", "-p", "#{pane_id}")


@pytest.fixture(scope="session")
def tmux_process():
    """One tmux server for the whole session.

    Starting a server per test cost far more than the tests themselves: each
    start forks a daemon and (before -f /dev/null) sourced the user's config.
    Every test already opens with ``tmux_server.reset()``, which trims the
    window back to a single pane, so one server is enough to keep them apart.
    """
    socket = f"laytest-{uuid.uuid4().hex[:8]}"
    fixture = TmuxFixture(socket)
    fixture.tmux(
        "new-session", "-d", "-x", str(WIDTH), "-y", str(HEIGHT), "-s", "t"
    )
    fixture.socket_path = fixture.tmux("display-message", "-p", "#{socket_path}")
    try:
        yield fixture
    finally:
        fixture.tmux("kill-server")


@pytest.fixture
def tmux_server(tmux_process, monkeypatch):
    """The shared server, with $TMUX pointed at it for this test only.

    The env var stays function-scoped on purpose: test_cli.py deletes TMUX to
    check the outside-tmux paths, and test_parser.py sorts after this module.
    Neither should inherit a live server from a session-scoped setenv.
    """
    monkeypatch.setenv("TMUX", f"{tmux_process.socket_path},0,0")
    return tmux_process


def invoke(args: list[str]) -> int:
    """Run the CLI the way the console script does."""
    words = tuple(a for a in args if not a.startswith("-"))
    flags = {a for a in args if a.startswith("-")}
    return run(
        words,
        target=None,
        dry_run="-n" in flags,
        verbose="-v" in flags,
    )


LAYOUTS = [
    "1",
    "1 1",
    "1 2",
    "1 1 1",
    "2 3 5",
    "1 / 1",
    "1 / 1 / 1",
    "(4 4) / 1",
    "(1 / 1) 2",
    "1 / 1 2",
    "2 1 / 1",
    "(2 1) / 1",
    "3:(1 / 1 / 1) 1",
    "1 1 / 2",
    "(1 1) / 2",
    "2:(1 1) / 2",
    "3:(1 1) 1",
    "1 / (1 (1 / 1 / 1)) / 1",
    "0.5 2.5 1",
    "(1 1) 1",
    "1 2 1",
    "(1 / 1) (1 / 1)",
    "1 / 1 1 / 1",
    "1 / 2 / 3 / 4",
]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_applied_layout_is_byte_identical_to_what_lay_renders(tmux_server, layout):
    """Our layout string must match tmux's own dump exactly, checksum included."""
    tmux_server.reset()
    assert invoke([layout]) == 0

    applied = tmux_server.layout
    pane_ids = tmux_server.tmux("list-panes", "-F", "#{pane_id}").splitlines()
    rendered = render(build(parse(layout), WIDTH, HEIGHT), pane_ids)

    assert rendered == applied


@pytest.mark.parametrize("layout", LAYOUTS)
def test_applied_geometry_survives_a_round_trip(tmux_server, layout):
    """Whatever tmux reports back must describe the geometry we asked for."""
    tmux_server.reset()
    assert invoke([layout]) == 0
    expected = render(build(parse(layout), WIDTH, HEIGHT))
    assert normalise(tmux_server.layout) == normalise(expected)


def test_surplus_panes_exit_2(tmux_server, capsys):
    tmux_server.reset()
    assert invoke(["1 1 1"]) == 0
    assert invoke(["1 1"]) == 2
    assert "layout needs 2 panes, window has 3" in capsys.readouterr().err


def test_extra_panes_are_never_killed(tmux_server, capsys):
    tmux_server.reset()
    assert invoke(["1 1 1"]) == 0
    # Asking for fewer panes is a mismatch, not a licence to kill.
    assert invoke(["1 1"]) == 2
    assert tmux_server.pane_count == 3


def test_missing_panes_are_created_by_default(tmux_server):
    tmux_server.reset()
    assert invoke(["1 1 1"]) == 0
    assert tmux_server.pane_count == 3


def test_exactly_the_missing_panes_are_made(tmux_server):
    tmux_server.reset()
    assert invoke(["3:(1 / 1 / 1) 1"]) == 0
    assert tmux_server.pane_count == 4


def test_unfittable_layout_creates_nothing(tmux_server, capsys):
    tmux_server.reset()
    huge = " ".join(["1"] * 200)
    assert invoke([huge]) == 3
    assert "does not fit" in capsys.readouterr().err
    # The window must be untouched.
    assert tmux_server.pane_count == 1


def test_dry_run_does_not_touch_the_window(tmux_server, capsys):
    tmux_server.reset()
    before = tmux_server.layout
    assert invoke(["-n", "1 1 1"]) == 0
    assert capsys.readouterr().out.strip()
    assert tmux_server.layout == before
    assert tmux_server.pane_count == 1


def test_dry_run_prints_a_diagram_not_a_layout_string(tmux_server, capsys):
    tmux_server.reset()
    assert invoke(["-n", "(4 4) / 1"]) == 0
    out = capsys.readouterr().out
    assert "┌" in out and "┘" in out and "┴" in out
    # A tmux layout string would look like '3ea5,178x43,0,0[...'
    assert "x43," not in out
    for index in range(3):
        assert str(index) in out


def test_dry_run_ignores_pane_count(tmux_server, capsys):
    """Without -n this is exit 2; a dry run never counts panes."""
    tmux_server.reset()
    assert tmux_server.pane_count == 1
    assert invoke(["-n", "1 1 1"]) == 0
    assert "┬" in capsys.readouterr().out


def test_dry_run_reads_only_the_window_size(tmux_server, capsys, monkeypatch):
    """The single display-message is all a dry run is allowed to do."""

    def forbidden(*args, **kwargs):
        raise AssertionError("dry run touched tmux beyond the window size")

    monkeypatch.setattr(lay_tmux, "load_panes", forbidden)
    monkeypatch.setattr(lay_tmux, "create_panes", forbidden)
    monkeypatch.setattr(lay_tmux, "apply", forbidden)

    tmux_server.reset()
    assert invoke(["-n", "1 1 1"]) == 0
    assert capsys.readouterr().out.strip()


def test_dry_run_still_rejects_a_layout_that_cannot_fit(tmux_server, capsys):
    tmux_server.reset()
    assert invoke(["-n", " ".join(["1"] * 200)]) == 3
    assert "does not fit" in capsys.readouterr().err


def test_dry_run_scales_the_diagram_to_a_readable_width(tmux_server, capsys):
    tmux_server.reset()
    assert invoke(["-n", "1 1"]) == 0
    lines = capsys.readouterr().out.splitlines()
    # The window is 178 columns; the diagram must be scaled well below that.
    assert max(len(line) for line in lines) < 100


def test_panes_keep_their_indices_and_only_move(tmux_server):
    tmux_server.reset()
    assert invoke(["1 1 1"]) == 0
    before = tmux_server.tmux("list-panes", "-F", "#{pane_id}").splitlines()
    assert invoke(["1 / 1 / 1"]) == 0
    after = tmux_server.tmux("list-panes", "-F", "#{pane_id}").splitlines()
    assert before == after


def test_nth_leaf_gets_nth_pane(tmux_server):
    """'1 / 1 2' must stack panes 0 and 1 on the left, pane 2 on the right."""
    tmux_server.reset()
    assert invoke(["1 / 1 2"]) == 0
    rows = tmux_server.tmux(
        "list-panes", "-F", "#{pane_index} #{pane_left} #{pane_top} #{pane_width}"
    ).splitlines()
    geom = {int(r.split()[0]): tuple(map(int, r.split()[1:])) for r in rows}
    assert geom[0][0] == geom[1][0] == 0        # same left edge
    assert geom[0][1] < geom[1][1]              # 0 above 1
    assert geom[2][0] > 0                       # 2 is on the right
    assert geom[2][2] > geom[0][2]              # and is the wider one


def test_creating_panes_keeps_the_active_pane(tmux_server):
    """Splitting in the panes a layout needs must not steal the focus."""
    tmux_server.reset()
    before = tmux_server.active_pane
    assert invoke(["1 1 1"]) == 0
    assert tmux_server.pane_count == 3
    assert tmux_server.active_pane == before


def test_creating_panes_keeps_the_active_pane_when_it_is_not_the_first(
    tmux_server,
):
    """The remembered pane is the active one, not simply pane 0."""
    tmux_server.reset()
    assert invoke(["1 1"]) == 0
    panes = tmux_server.tmux("list-panes", "-F", "#{pane_id}").splitlines()
    tmux_server.tmux("select-pane", "-t", panes[1])
    assert tmux_server.active_pane == panes[1]

    assert invoke(["1 1 1 1"]) == 0
    assert tmux_server.pane_count == 4
    assert tmux_server.active_pane == panes[1]


def test_a_layout_that_creates_nothing_keeps_the_active_pane(tmux_server):
    tmux_server.reset()
    assert invoke(["1 1 1"]) == 0
    panes = tmux_server.tmux("list-panes", "-F", "#{pane_id}").splitlines()
    tmux_server.tmux("select-pane", "-t", panes[2])

    assert invoke(["1 / 1 / 1"]) == 0
    assert tmux_server.active_pane == panes[2]


# --------------------------------------------------------------------------
# editing (no layout argument)
# --------------------------------------------------------------------------


@pytest.fixture
def scripted_editor(monkeypatch, tmp_path):
    """An editor that replaces the buffer with a fixed expression."""

    def install(body: str, record: pathlib.Path | None = None) -> None:
        script = tmp_path / "fake_editor.py"
        lines = ["import sys, pathlib", "target = pathlib.Path(sys.argv[1])"]
        if record is not None:
            lines.append(
                f"pathlib.Path({str(record)!r}).write_text(target.read_text())"
            )
        if body is not None:
            lines.append(f"target.write_text({body!r})")
        script.write_text("\n".join(lines) + "\n")
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setenv(
            "EDITOR", f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
        )
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)

    return install


@pytest.mark.parametrize("layout", LAYOUTS)
def test_edit_is_seeded_with_the_current_layout(
    tmux_server, scripted_editor, tmp_path, layout
):
    """What the editor opens must describe the window as it actually is."""
    tmux_server.reset()
    assert invoke([layout]) == 0
    before = tmux_server.layout

    seen = tmp_path / "seen"
    scripted_editor(None, record=seen)
    assert invoke([]) == 0

    seeded = strip_comments(seen.read_text())
    # The seeded expression must reproduce the live layout exactly.
    assert normalise(render(build(parse(seeded), WIDTH, HEIGHT))) == normalise(before)


def test_edit_applies_the_edited_layout(tmux_server, scripted_editor):
    tmux_server.reset()
    assert invoke(["1 1 1"]) == 0
    scripted_editor("1 / 1 / 1\n")
    assert invoke([]) == 0

    expected = render(build(parse("1 / 1 / 1"), WIDTH, HEIGHT))
    assert normalise(tmux_server.layout) == normalise(expected)


def test_edit_without_changes_does_nothing(tmux_server, scripted_editor, capsys):
    tmux_server.reset()
    assert invoke(["1 2"]) == 0
    before = tmux_server.layout
    scripted_editor(None)          # editor leaves the buffer untouched
    assert invoke([]) == 0
    assert tmux_server.layout == before
    assert "unchanged" in capsys.readouterr().err


def test_edit_reports_a_bad_expression(tmux_server, scripted_editor, capsys):
    tmux_server.reset()
    scripted_editor("1 & 1\n")
    assert invoke([]) == 1
    assert "unexpected character" in capsys.readouterr().err


def test_edit_that_removes_a_leaf_is_a_mismatch(
    tmux_server, scripted_editor, capsys
):
    tmux_server.reset()
    assert invoke(["1 1 1"]) == 0
    scripted_editor("1 1\n")
    assert invoke([]) == 2
    assert "layout needs 2 panes, window has 3" in capsys.readouterr().err


def test_edit_that_adds_a_leaf_creates_the_pane(tmux_server, scripted_editor):
    tmux_server.reset()
    assert invoke(["1 1"]) == 0
    scripted_editor("1 1 1 1\n")
    assert invoke([]) == 0
    assert tmux_server.pane_count == 4


def test_edit_aborts_when_the_buffer_is_emptied(
    tmux_server, scripted_editor, capsys
):
    tmux_server.reset()
    assert invoke(["1 2"]) == 0
    before = tmux_server.layout
    scripted_editor("\n")
    assert invoke([]) == 1
    assert "empty layout" in capsys.readouterr().err
    assert tmux_server.layout == before


def test_edit_works_on_a_window_lay_never_touched(tmux_server, scripted_editor):
    """Reconstruction must cope with a layout tmux built by itself."""
    tmux_server.reset()
    tmux_server.tmux("split-window", "-h", "-t", "t")
    tmux_server.tmux("split-window", "-v", "-t", "t")
    tmux_server.tmux("select-layout", "-t", "t", "main-vertical")
    before = tmux_server.layout

    scripted_editor(None)
    assert invoke([]) == 0
    # Untouched by an empty edit, and decodable without error.
    assert tmux_server.layout == before


@pytest.mark.parametrize(
    "preset",
    ["tiled", "main-vertical", "main-horizontal", "even-horizontal",
     "even-vertical"],
)
def test_tmux_preset_layouts_survive_a_decode_and_reapply(tmux_server, preset):
    """A layout tmux built itself must come back byte-identical.

    tmux rounds differently from lay (it gives the spare cell to the *last*
    pane, lay to the first), so these decode to exact-but-ugly weights such as
    '10 10 10 10 10 11'. Ugly is fine; wrong is not.
    """
    tmux_server.reset()
    for _ in range(5):
        tmux_server.tmux("split-window", "-t", "t")
        tmux_server.tmux("select-layout", "-t", "t", "tiled")
    tmux_server.tmux("select-layout", "-t", "t", preset)

    before = tmux_server.layout
    expression = decode(before)

    assert invoke([expression]) == 0
    assert tmux_server.layout == before


def test_edit_dry_run_previews_without_applying(
    tmux_server, scripted_editor, capsys
):
    tmux_server.reset()
    assert invoke(["1 1"]) == 0
    before = tmux_server.layout
    scripted_editor("1 / 1\n")
    assert invoke(["-n"]) == 0
    assert "┌" in capsys.readouterr().out
    assert tmux_server.layout == before
