import pytest

from lay.geometry import COLS, ROWS, FitError, build, checksum, distribute, render
from lay.parser import parse


def test_checksum_matches_tmux():
    # Captured from a real `tmux display-message -p '#{window_layout}'`.
    body = "178x43,0,0{89x43,0,0,0,88x43,90,0,1}"
    assert f"{checksum(body):04x}" == "843f"


def test_distribute_totals_exactly():
    assert sum(distribute(98, [1, 1, 1])) == 98
    assert distribute(98, [1, 1, 1]) == [33, 33, 32]


def test_distribute_ties_favour_the_earlier_sibling():
    # tmux gives the left pane the extra column when halving an odd width.
    assert distribute(177, [1, 1]) == [89, 88]


def test_distribute_respects_ratios():
    assert distribute(100, [2, 3, 5]) == [20, 30, 50]
    assert distribute(100, [20, 30, 50]) == [20, 30, 50]


def test_two_equal_columns_match_tmux():
    cell = build(parse("1 1"), 178, 43)
    assert render(cell, ["0", "1"]) == "843f,178x43,0,0{89x43,0,0,0,88x43,90,0,1}"


def test_borders_are_accounted_for():
    cell = build(parse("1 1 1"), 100, 20)
    widths = [c.width for c in cell.children]
    assert sum(widths) + (len(widths) - 1) == 100


def test_rows_use_square_brackets():
    cell = build(parse("1 / 1"), 100, 21)
    out = render(cell, ["0", "1"])
    assert "[" in out and "{" not in out


def test_weighted_columns():
    cell = build(parse("1 2"), 100, 20)
    # available = 99, split 33/66
    assert [c.width for c in cell.children] == [33, 66]
    assert [c.x for c in cell.children] == [0, 34]


def test_group_weight_controls_outer_share():
    cell = build(parse("3:(1 1) 1"), 101, 20)
    # available = 100, weights 3:1 -> 75 / 25
    group, sidebar = cell.children
    assert (group.width, sidebar.width) == (75, 25)
    # the group's own 75 columns split into 37 / 37 with a border
    assert [c.width for c in group.children] == [37, 37]


def test_nested_group_is_not_the_same_as_a_flat_split():
    nested = build(parse("(1 1) 1"), 100, 20)
    flat = build(parse("1 1 1"), 100, 20)
    assert [c.width for c in nested.children] != [c.width for c in flat.children]


def test_leaf_order_is_depth_first():
    cell = build(parse("(1 / 1) 2"), 100, 20)
    leaves = cell.leaves()
    assert len(leaves) == 3
    # pane 0 and 1 stack on the left, pane 2 is the wide one on the right
    assert leaves[0].x == leaves[1].x == 0
    assert leaves[0].y < leaves[1].y
    assert leaves[2].x > 0
    assert leaves[2].width > leaves[0].width


def test_too_many_panes_for_the_space():
    with pytest.raises(FitError):
        build(parse(" ".join(["1"] * 60)), 100, 20)


def test_exactly_fitting_layout_is_allowed():
    # 50 columns of 1 cell each needs 50 + 49 borders = 99
    cell = build(parse(" ".join(["1"] * 50)), 99, 20)
    assert all(c.width == 1 for c in cell.children)


@pytest.mark.parametrize(
    "source",
    [
        "1 1 1",
        "1 2",
        "(4 4) / 1",
        "(1 / 1) 2",
        "1 / 1 / 1",
        "2 1 / 1",
        "(2 1) / 1",
        "3:(1 / 1 / 1) 1",
        "1 / (1 (1 / 1 / 1)) / 1",
        "2 3 5",
        "0.5 2.5 1",
    ],
)
@pytest.mark.parametrize("size", [(80, 24), (178, 43), (100, 20), (40, 12)])
def test_children_always_tile_their_parent_exactly(source, size):
    """Every split must satisfy sum(sizes) + borders == parent size."""
    try:
        cell = build(parse(source), *size)
    except FitError:
        # Genuinely too small for this layout; rejection is the correct answer.
        return
    for node in cell.walk():
        if node.is_leaf:
            continue
        count = len(node.children)
        if node.axis == COLS:
            assert all(c.height == node.height for c in node.children)
            assert sum(c.width for c in node.children) + count - 1 == node.width
            expected_x = node.x
            for child in node.children:
                assert child.x == expected_x
                expected_x += child.width + 1
        else:
            assert all(c.width == node.width for c in node.children)
            assert sum(c.height for c in node.children) + count - 1 == node.height
            expected_y = node.y
            for child in node.children:
                assert child.y == expected_y
                expected_y += child.height + 1
        assert all(c.width >= 1 and c.height >= 1 for c in node.children)
