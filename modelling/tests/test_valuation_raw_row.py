"""Tests for valuation raw-row builder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from modelling.inference.valuation_raw_row import (
    ValuationInferenceInput,
    build_valuation_raw_dataframe,
)


def test_build_baseline_raw_row_columns_and_numeric():
    inp = ValuationInferenceInput(
        postal_code="123456",
        town="CLEMENTI",
        flat_type="4 ROOM",
        flat_model_grouped="Model A",
        region="WEST REGION",
        storey_midpoint=8,
        floor_area_sqm=92.5,
        remaining_lease_years=85,
        latitude=1.31,
        longitude=103.76,
        lease_commence_year=1994,
    )
    df = build_valuation_raw_dataframe(inp, valuation_month="2024-06")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["month"] == "2024-06"
    assert row["town"] == "CLEMENTI"
    assert row["flat_type"] == "4 ROOM"
    assert row["flat_model"] == "MODEL A"
    assert row["storey_range"] == "07 TO 09"
    assert row["floor_area_sqm"] == pytest.approx(92.5)
    assert row["remaining_lease_years"] == 85
    assert "lease_commence_date" not in df.columns
    assert row["lat"] == pytest.approx(1.31)
    assert row["lon"] == pytest.approx(103.76)


def test_mrt_overrides_merge():
    inp = ValuationInferenceInput(
        postal_code="123456",
        town="TAMPINES",
        flat_type="5 ROOM",
        flat_model_grouped="Premium Apartment",
        region="EAST REGION",
        storey_midpoint=12,
        floor_area_sqm=110.0,
        remaining_lease_years=70,
        latitude=None,
        longitude=None,
        lease_commence_year=2005,
    )
    mrt = {
        "dist_to_nearest_op_mrt": 450.0,
        "travel_time_to_active_mrt": 12,
        "nearest_op_lines": ["EWL"],
        "nearest_planned_lines": [],
        "hdb_addr_id": 999,
        "tx_year_month": "2024-06",
    }
    df = build_valuation_raw_dataframe(
        inp, valuation_month="2024-06", mrt_feature_overrides=mrt
    )
    assert df.iloc[0]["dist_to_nearest_op_mrt"] == pytest.approx(450.0)
    assert "hdb_addr_id" not in df.columns
    assert "lat" not in df.columns
    assert "lon" not in df.columns
