"""Unit tests for MRT temporal ingest helpers (pure Python semantics)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"
for p in (BACKEND, BACKEND / "scripts"):
    sys.path.insert(0, str(p))

from ingest_mrt_temporal import compute_derived_state, parse_date  # noqa: E402


def test_parse_exact_date():
    d, conf = parse_date("2022-08-28", False)
    assert d == date(2022, 8, 28)
    assert conf == "EXACT"


@pytest.mark.parametrize(
    ("raw_ann",),
    [
        ("2015",),
        ("February 2020",),
    ],
)
def test_parse_non_exact_announcement_confidence_levels(raw_ann: str):
    _, conf = parse_date(raw_ann, is_announcement=True)
    assert conf in {"YEAR", "MID", "HALF"}


@pytest.mark.parametrize(
    ("opening", "exp", "ann", "as_of", "expected"),
    [
        (date(2010, 1, 1), None, None, date(2020, 1, 1), "OPERATIONAL"),
        (date(2030, 1, 1), None, date(2020, 1, 1), date(2025, 1, 1), "COMMITTED_DATED"),
        (None, date(2031, 6, 1), None, date(2026, 1, 1), "COMMITTED_ESTIMATED"),
        (None, None, date(2021, 1, 1), date(2022, 1, 1), "ANNOUNCED_UNDATED"),
        (None, None, None, date(2022, 1, 1), "UNKNOWN"),
    ],
)
def test_derived_state_machine(opening, exp, ann, as_of, expected: str):
    assert compute_derived_state(opening, exp, ann, as_of=as_of) == expected


def test_interchange_physical_group_placeholder():
    """
    Mirrors the Postgres aggregation idea: interchange iff distinct lines per physical_station_id>=2.

    Implemented here with tiny pandas dataframe logic for regression safety without DBSCAN.
    """
    import pandas as pd

    rows = pd.DataFrame(
        [
            {"physical_station_id": 10, "network_line": "North-South Line"},
            {"physical_station_id": 10, "network_line": "East-West Line"},
            {"physical_station_id": 11, "network_line": "Circle Line"},
        ]
    )
    grp = (
        rows.groupby("physical_station_id")["network_line"]
        .apply(lambda s: s.astype(str).str.strip().nunique())
        .reset_index(name="distinct_lines")
    )
    expected = {10: True, 11: False}
    for _, r in grp.iterrows():
        assert (r["distinct_lines"] >= 2) == expected[int(r["physical_station_id"])]
