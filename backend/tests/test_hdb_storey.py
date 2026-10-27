import pytest

from hdb_storey import (
    STOREY_PAIR_RE_PANDAS,
    parse_storey_range_bounds,
    storey_midpoint_from_bounds,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("01 TO 03", (1, 3)),
        ("10 TO 12", (10, 12)),
        ("01 to 03", (1, 3)),
        ("  04 TO 06  ", (4, 6)),
        ("03 TO 01", (1, 3)),
        ("25–27", (25, 27)),
        ("25-27", (25, 27)),
        ("15", (15, 15)),
    ],
)
def test_parse_storey_range_bounds(raw, expected):
    assert parse_storey_range_bounds(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "n/a", "LOW", "99 TO 200", "0 TO 5"],
)
def test_parse_storey_range_bounds_rejects(raw):
    assert parse_storey_range_bounds(raw) is None


def test_storey_midpoint_from_bounds():
    assert storey_midpoint_from_bounds(1, 3) == 2
    assert storey_midpoint_from_bounds(10, 12) == 11


def test_storey_pair_regex_pandas_matches_series():
    import pandas as pd

    s = pd.Series(["01 TO 03", "bad", "16 TO 18"])
    out = s.astype("string").str.extract(STOREY_PAIR_RE_PANDAS)
    assert out.iloc[0]["storey_lower"] == "01"
    assert out.iloc[0]["storey_upper"] == "03"
    assert pd.isna(out.iloc[1]["storey_lower"])
    assert out.iloc[2]["storey_upper"] == "18"
