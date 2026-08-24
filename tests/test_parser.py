import pytest

from lay.parser import COLS, ROWS, Leaf, ParseError, Split, parse


def test_single_pane():
    assert parse("1") == Leaf(weight=1.0)


def test_columns_are_space_separated():
    tree = parse("1 2")
    assert tree == Split(1.0, COLS, (Leaf(1.0), Leaf(2.0)))


def test_slash_binds_tighter_than_space():
    # '1 1 / 1' reads as '1 (1 / 1)'
    tree = parse("1 1 / 1")
    assert isinstance(tree, Split) and tree.axis == COLS
    assert len(tree.children) == 2
    assert tree.children[0] == Leaf(1.0)
    assert tree.children[1] == Split(1.0, ROWS, (Leaf(1.0), Leaf(1.0)))


def test_a_row_of_columns_needs_parentheses():
    tree = parse("(1 1) / 1")
    assert isinstance(tree, Split) and tree.axis == ROWS
    assert tree.children[0] == Split(1.0, COLS, (Leaf(1.0), Leaf(1.0)))
    assert tree.children[1] == Leaf(1.0)


def test_adjacent_row_chains_stay_separate():
    # Each row chain ends where the next item begins, so no parentheses
    # are needed to put two stacked pairs side by side.
    tree = parse("1 / 1 1 / 1")
    assert tree.axis == COLS
    stack = Split(1.0, ROWS, (Leaf(1.0), Leaf(1.0)))
    assert tree.children == (stack, stack)


def test_decimal_weights():
    tree = parse("0.5 2.5")
    assert [c.weight for c in tree.children] == [0.5, 2.5]


def test_bare_group_has_weight_one_regardless_of_contents():
    tree = parse("(4 4) 1")
    assert tree.children[0].weight == 1.0
    assert tree.children[1].weight == 1.0


def test_group_weight_prefix():
    tree = parse("3:(1 1) 1")
    group, sidebar = tree.children
    assert group.weight == 3.0
    assert sidebar.weight == 1.0
    assert [c.weight for c in group.children] == [1.0, 1.0]


def test_parenthesised_single_number_loses_its_weight():
    # A group's weight never depends on what is inside it.
    assert parse("(5)") == Leaf(weight=1.0)
    assert parse("3:(5)") == Leaf(weight=3.0)


def test_implicit_column_group_equivalence():
    # The README states these two are identical.
    assert parse("1 / 1 2") == parse("1:(1 / 1) 2")


def test_nesting_is_not_flattened():
    # '(1 1) 1' is 50/50 with a nested pair, not three equal columns.
    assert parse("(1 1) 1") != parse("1 1 1")


def test_deep_nesting():
    tree = parse("1 / (1 (1 / 1 / 1)) / 1")
    assert tree.axis == ROWS
    # 1 + (1 + 3) + 1
    assert tree.leaf_count == 6


@pytest.mark.parametrize(
    "source",
    [
        "",
        "   ",
        "()",
        "1 1 /",
        "/ 1",
        "(1 1",
        "1 1)",
        "1:",
        "1:2",
        "0",
        "0 1",
        "-1 1",
        "1 & 1",
        "1 :: 1",
    ],
)
def test_invalid_expressions_raise(source):
    with pytest.raises(ParseError):
        parse(source)


def test_leaf_count():
    assert parse("1").leaf_count == 1
    assert parse("1 1 1").leaf_count == 3
    assert parse("(4 4) / 1").leaf_count == 3
    assert parse("3:(1 / 1 / 1) 1").leaf_count == 4


def test_error_carries_position():
    with pytest.raises(ParseError) as info:
        parse("1 1 & 1")
    assert info.value.pos == 4
    assert "^" in info.value.caret()
