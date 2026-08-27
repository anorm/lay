"""CLI behaviour that does not need a tmux server."""

import pytest

from lay.cli import run


def call(words, **kwargs):
    options = {
        "target": None,
        "create": False,
        "dry_run": False,
        "verbose": False,
    }
    options.update(kwargs)
    return run(tuple(words), **options)


def test_no_layout_edits_the_current_one(capsys, monkeypatch):
    """With nothing to parse, `lay` goes straight to the editor path."""
    monkeypatch.delenv("TMUX", raising=False)
    # Exit 4 from tmux, not a usage error, which proves it took the edit path.
    assert call([]) == 4
    assert "not inside a tmux session" in capsys.readouterr().err


def test_blank_layout_edits_the_current_one(capsys, monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    assert call(["  "]) == 4
    assert "not inside a tmux session" in capsys.readouterr().err


def test_parse_error_exits_1_with_a_caret(capsys):
    assert call(["1 & 1"]) == 1
    err = capsys.readouterr().err
    assert "unexpected character" in err
    assert "^" in err


def test_zero_weight_is_rejected(capsys):
    assert call(["0 1"]) == 1
    assert "greater than zero" in capsys.readouterr().err


def test_words_are_joined_with_spaces(capsys, monkeypatch):
    """`lay 1 1 1` and `lay '1 1 1'` must mean the same thing."""
    monkeypatch.delenv("TMUX", raising=False)
    # Both fail at the tmux step, not the parser, which proves they parsed.
    assert call(["1", "1", "1"]) == 4
    assert call(["1 1 1"]) == 4


def test_outside_tmux_exits_4(capsys, monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    assert call(["1 1"]) == 4
    assert "not inside a tmux session" in capsys.readouterr().err


def test_dry_run_still_needs_tmux_for_the_window_size(capsys, monkeypatch):
    """A dry run reads no panes, but it still has to measure the window."""
    monkeypatch.delenv("TMUX", raising=False)
    assert call(["1 1"], dry_run=True) == 4
    assert "not inside a tmux session" in capsys.readouterr().err


def test_parse_errors_are_reported_before_tmux_is_consulted(capsys, monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    # Exit 1, not the exit 4 we would get if tmux were reached first.
    assert call(["1 & 1"], dry_run=True) == 1


@pytest.mark.parametrize("source", ["(1 1", "1 1)", "1:", "1:2", "/ 1", "()"])
def test_malformed_expressions_exit_1(source):
    assert call([source]) == 1
