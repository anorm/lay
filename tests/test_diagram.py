from lay.diagram import fit, render_diagram
from lay.geometry import build
from lay.parser import parse


def draw(source: str, width: int = 46, height: int = 12) -> str:
    return render_diagram(build(parse(source), width, height))


def test_single_pane_is_a_plain_box():
    art = draw("1", 8, 3).splitlines()
    assert art[0] == "┌────────┐"
    assert art[-1] == "└────────┘"
    assert "0" in art[2]


def test_diagram_size_includes_the_outer_border():
    art = draw("1 1", 20, 5).splitlines()
    assert len(art) == 7                    # 5 + 2
    assert len(art[0]) == 22                # 20 + 2


def test_column_split_draws_tee_junctions():
    art = draw("1 1", 20, 5).splitlines()
    assert "┬" in art[0]
    assert "┴" in art[-1]


def test_row_split_draws_side_junctions():
    art = draw("1 / 1", 20, 5).splitlines()
    joined = "\n".join(art)
    assert "├" in joined and "┤" in joined


def test_nested_split_draws_a_cross():
    # Four quadrants meet in the middle.
    art = draw("(1 / 1) (1 / 1)", 21, 7)
    assert "┼" in art


def test_every_pane_is_numbered():
    art = draw("(4 4) / 1", 40, 11)
    for index in range(3):
        assert str(index) in art


def test_panes_are_numbered_in_written_order():
    #  '1 / 1 2' -> 0 and 1 stacked left, 2 right
    art = draw("1 / 1 2", 40, 11).splitlines()
    left_rows = [i for i, row in enumerate(art) if "0" in row or "1" in row]
    row_with_0 = next(i for i, row in enumerate(art) if "0" in row)
    row_with_1 = next(i for i, row in enumerate(art) if "1" in row)
    assert row_with_0 < row_with_1
    assert left_rows


def test_fit_scales_a_large_window_down():
    cell = fit(parse("1 1 1"), 400, 100, 60)
    assert cell.width <= 60
    assert cell.height < 100


def test_fit_leaves_small_windows_alone():
    cell = fit(parse("1 1"), 40, 10, 60)
    assert (cell.width, cell.height) == (40, 10)


def test_fit_grows_until_a_dense_layout_survives():
    # Too many panes to render at 20 columns; fit() must widen rather than fail.
    cell = fit(parse(" ".join(["1"] * 30)), 200, 50, 20)
    assert all(leaf.width >= 1 for leaf in cell.leaves())


def test_diagram_rows_have_no_trailing_whitespace():
    for line in draw("(4 4) / 1", 40, 11).splitlines():
        assert line == line.rstrip()
