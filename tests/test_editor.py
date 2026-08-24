"""The $EDITOR round-trip, which is delegated to click.edit."""

import pathlib
import shlex
import sys

import pytest

from lay.editor import EditorError, edit, strip_comments


@pytest.fixture(autouse=True)
def pretend_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)


@pytest.fixture
def scripted_editor(monkeypatch, tmp_path):
    """Install a real editor process that rewrites the file it is given."""

    def install(
        body: str | None,
        record: pathlib.Path | None = None,
        variable: str = "EDITOR",
    ) -> None:
        script = tmp_path / f"fake_{variable.lower()}.py"
        lines = ["import sys, pathlib", "target = pathlib.Path(sys.argv[1])"]
        if record is not None:
            lines.append(
                f"pathlib.Path({str(record)!r}).write_text(target.read_text())"
            )
        if body is not None:
            lines.append(f"target.write_text({body!r})")
        script.write_text("\n".join(lines) + "\n")
        monkeypatch.setenv(
            variable,
            f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}",
        )

    return install


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1 1", "1 1"),
        ("1 1\n", "1 1"),
        ("# comment\n1 1\n", "1 1"),
        ("1 1  # trailing\n", "1 1"),
        ("1 1\n/ 2\n", "1 1 / 2"),          # folded onto one line
        ("\n\n  1 / 2  \n\n", "1 / 2"),
        ("# only comments\n", ""),
        ("", ""),
    ],
)
def test_strip_comments(text, expected):
    assert strip_comments(text) == expected


def test_edit_returns_the_edited_expression(scripted_editor):
    scripted_editor("1 / 2 / 3\n")
    assert edit("1 1") == "1 / 2 / 3"


def test_edit_keeps_the_original_when_untouched(scripted_editor):
    # An editor that writes nothing leaves the seeded expression in place.
    scripted_editor(None)
    assert edit("3:(1 1) 1") == "3:(1 1) 1"


def test_edit_folds_multiple_lines(scripted_editor):
    scripted_editor("1 1\n/ 2\n/ 3\n")
    assert edit("1") == "1 1 / 2 / 3"


def test_edit_strips_the_instruction_block(scripted_editor):
    scripted_editor(None)
    assert "#" not in edit("1 2")


def test_visual_takes_precedence_over_editor(scripted_editor):
    scripted_editor("1 1\n", variable="EDITOR")
    scripted_editor("9 9\n", variable="VISUAL")
    assert edit("1") == "9 9"


def test_emptying_the_buffer_aborts(scripted_editor):
    scripted_editor("\n\n")
    with pytest.raises(EditorError, match="empty layout"):
        edit("1 1")


def test_deleting_everything_but_comments_aborts(scripted_editor):
    scripted_editor("# changed my mind\n")
    with pytest.raises(EditorError, match="empty layout"):
        edit("1 1")


def test_editor_failure_aborts(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "false")
    with pytest.raises(EditorError, match="Editing failed"):
        edit("1 1")


def test_missing_editor_is_reported(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "definitely-not-an-editor-xyz")
    with pytest.raises(EditorError, match="Editing failed"):
        edit("1 1")


def test_editing_without_a_terminal_is_refused(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(EditorError, match="without a terminal"):
        edit("1 1")


def test_temporary_file_is_cleaned_up(scripted_editor, tmp_path):
    record = tmp_path / "seen"
    scripted_editor("1 1\n", record=record)
    assert edit("1") == "1 1"
    # click.edit unlinks the buffer in a finally block.
    assert record.read_text().startswith("1")


def test_buffer_is_seeded_with_the_expression_and_instructions(
    scripted_editor, tmp_path
):
    record = tmp_path / "seen"
    scripted_editor("1 1\n", record=record)
    edit("3:(1 / 1) 2")
    seeded = record.read_text()
    assert seeded.startswith("3:(1 / 1) 2")
    assert "# Edit the layout" in seeded
