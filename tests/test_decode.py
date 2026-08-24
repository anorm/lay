"""Reading tmux layout strings back into lay expressions."""

import random

import pytest

from lay.decode import (
    DecodeError,
    decode,
    parse_layout_string,
    recover_weights,
    to_expression,
)
from lay.geometry import build, distribute, render
from lay.parser import parse

# Captured from a live tmux server.
REAL = {
    "a8fd,120x30,0,0,0": "1",
    "843f,178x43,0,0{89x43,0,0,0,88x43,90,0,1}": "1 1",
    "3ea5,178x43,0,0[178x21,0,0{89x21,0,0,0,88x21,90,0,1},178x21,0,22,2]":
        "(1 1) / 1",
    "aa80,178x43,0,0{133x43,0,0[133x14,0,0,0,133x14,0,15,1,133x13,0,30,2],"
    "44x43,134,0,3}": "3:(1 / 1 / 1) 1",
    "55bd,178x43,0,0{89x43,0,0{44x43,0,0,1,44x43,45,0,2},88x43,90,0,3}":
        "(1 1) 1",
    "eab9,178x43,0,0[178x14,0,0{89x14,0,0,0,88x14,90,0,1},178x28,0,15,2]":
        "(1 1) / 2",
}


@pytest.mark.parametrize("layout,expected", sorted(REAL.items()))
def test_real_layout_strings_decode_to_expressions(layout, expected):
    assert decode(layout) == expected


def test_checksum_is_optional():
    with_sum = "843f,178x43,0,0{89x43,0,0,0,88x43,90,0,1}"
    without = "178x43,0,0{89x43,0,0,0,88x43,90,0,1}"
    assert decode(with_sum) == decode(without)


def test_columns_and_rows_use_the_right_brackets():
    assert decode("178x43,0,0{89x43,0,0,0,88x43,90,0,1}") == "1 1"
    assert decode("178x43,0,0[178x21,0,0,0,178x21,0,22,1]") == "1 / 1"


def test_structure_is_preserved_not_flattened():
    # A nested column group must not collapse into three equal columns.
    nested = "178x43,0,0{89x43,0,0{44x43,0,0,1,44x43,45,0,2},88x43,90,0,3}"
    assert decode(nested) == "(1 1) 1"


@pytest.mark.parametrize(
    "layout",
    [
        "",
        "nonsense",
        "178x43",
        "178x43,0,0",
        "178x43,0,0{89x43,0,0,0",
        "178x43,0,0{89x43,0,0,0,88x43,90,0,1]",
        "178x43,0,0{89x43,0,0,0,88x43,90,0,1}trailing",
    ],
)
def test_malformed_layout_strings_are_rejected(layout):
    with pytest.raises(DecodeError):
        decode(layout)


# --------------------------------------------------------------------------
# Weight recovery
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "available,sizes,expected",
    [
        (177, [89, 88], [1, 1]),           # 1:1 rounded on an odd width
        (177, [118, 59], [2, 1]),
        (176, [35, 53, 88], [2, 3, 5]),
        (177, [44, 89, 44], [1, 2, 1]),
        (42, [14, 14, 14], [1, 1, 1]),
        (41, [31, 10], [3, 1]),
        (177, [36, 36, 35, 35, 35], [1, 1, 1, 1, 1]),
    ],
)
def test_recover_weights_finds_the_simple_ratio(available, sizes, expected):
    assert recover_weights(available, sizes) == expected


def test_recovered_weights_always_reproduce_the_sizes():
    random.seed(3)
    for _ in range(2000):
        count = random.randint(2, 6)
        available = random.randint(count, 200)
        weights = [random.randint(1, 12) for _ in range(count)]
        sizes = distribute(available, weights)
        if min(sizes) < 1:
            continue
        recovered = recover_weights(available, sizes)
        assert distribute(available, recovered) == sizes


def test_raw_sizes_are_always_a_valid_fallback():
    # An arbitrary split with no simple ratio still round-trips.
    sizes = [37, 41, 43]
    assert distribute(sum(sizes), sizes) == sizes


# --------------------------------------------------------------------------
# Expression rendering
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "1",
        "1 1",
        "1 2",
        "1 / 2",
        "1 1 / 2",
        "1 / 1 2",
        "(1 / 1) 2",
        "(1 1) / 2",
        "(1 1) 1",
        "3:(1 / 1 / 1) 1",
        "2:(1 1) / 2",
        "1 / (1 (1 / 1 / 1)) / 1",
        "(4 4) / 1",
    ],
)
def test_to_expression_round_trips_through_parse(source):
    """The rendered text must describe exactly the same tree."""
    tree = parse(source)
    assert parse(to_expression(tree)) == tree


@pytest.mark.parametrize(
    "source",
    [
        "1",
        "1 1",
        "1 2",
        "1 / 2",
        "1 1 / 2",
        "1 / 1 2",
        "(1 1) / 2",
        "(1 1) 1",
        "3:(1 / 1 / 1) 1",
        "2:(1 1) / 2",
        "(4 4) / 1",
    ],
)
def test_canonical_expressions_render_unchanged(source):
    assert to_expression(parse(source)) == source


@pytest.mark.parametrize(
    "source,canonical",
    [
        # Redundant parentheses are dropped: '/' already binds tighter.
        ("1 / (1 (1 / 1 / 1)) / 1", "1 / (1 1 / 1 / 1) / 1"),
        ("(1 / 1) 2", "1 / 1 2"),
        # A weight of 1 is what a bare group means anyway.
        ("1:(1 1) / 2", "(1 1) / 2"),
        # Authored weights are kept as written; only decoding normalises them.
        ("(1 / 1) 4 4", "1 / 1 4 4"),
    ],
)
def test_expressions_are_canonicalised(source, canonical):
    assert to_expression(parse(source)) == canonical
    # ...and canonicalising twice changes nothing.
    assert to_expression(parse(canonical)) == canonical


def test_decoding_normalises_weights_to_their_simplest_form():
    """'(4 4) / 1' and '(1 1) / 1' lay out identically, so both decode alike."""
    for source in ("(4 4) / 1", "(1 1) / 1", "(50 50) / 1"):
        layout = render(build(parse(source), 178, 43))
        assert decode(layout) == "(1 1) / 1"


def test_columns_inside_rows_get_parentheses():
    assert to_expression(parse("(1 1) / 2")) == "(1 1) / 2"


def test_rows_inside_columns_do_not():
    # '/' binds tighter than a space, so no parentheses are needed here.
    assert to_expression(parse("1 / 1 2")) == "1 / 1 2"


def test_weighted_group_keeps_its_prefix():
    assert to_expression(parse("3:(1 1) 1")) == "3:(1 1) 1"


# --------------------------------------------------------------------------
# The property that matters: decoding must be layout-preserving
# --------------------------------------------------------------------------


def round_trip(source: str, width: int, height: int) -> tuple[str, str]:
    """Render, decode, re-render. Both strings must be identical."""
    first = render(build(parse(source), width, height))
    again = render(build(parse(decode(first)), width, height))
    return first, again


EXPRESSIONS = [
    "1", "1 1", "1 2", "1 1 1", "2 3 5", "1 / 1", "1 / 1 / 1", "(4 4) / 1",
    "(1 / 1) 2", "1 / 1 2", "2 1 / 1", "(2 1) / 1", "3:(1 / 1 / 1) 1",
    "1 1 / 2", "(1 1) / 2", "2:(1 1) / 2", "3:(1 1) 1",
    "1 / (1 (1 / 1 / 1)) / 1", "0.5 2.5 1", "(1 1) 1", "1 2 1",
    "(1 / 1) (1 / 1)", "1 / 1 1 / 1", "1 / 2 / 3 / 4",
    "1 / (2 3) / (1 (1 / 1))", "5:(1 1 1) 2 3",
]


@pytest.mark.parametrize("source", EXPRESSIONS)
@pytest.mark.parametrize("size", [(178, 43), (120, 30), (80, 24), (200, 60)])
def test_decoding_preserves_the_layout_exactly(source, size):
    first, again = round_trip(source, *size)
    assert first == again


def test_decoding_preserves_random_deep_trees():
    random.seed(11)

    def grow(depth=0):
        if depth >= 3 or random.random() < 0.35:
            return str(random.randint(1, 4))
        parts = [grow(depth + 1) for _ in range(random.randint(2, 4))]
        joiner = " / " if random.random() < 0.5 else " "
        return "(" + joiner.join(parts) + ")"

    checked = 0
    for _ in range(400):
        source = grow()
        for width, height in [(178, 43), (120, 40)]:
            try:
                first, again = round_trip(source, width, height)
            except Exception as exc:  # unfittable at this size
                if "does not fit" in str(exc):
                    continue
                raise
            assert first == again, source
            checked += 1
    assert checked > 200
