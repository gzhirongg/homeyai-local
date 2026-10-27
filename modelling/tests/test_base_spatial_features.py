"""Tests for WGS84 ``lat``/``lon`` on the base engineered frame."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from modelling.features.base import SPATIAL_NUMERIC_FEATURES, engineer_base_features


@pytest.mark.parametrize(
    ("has_coords",),
    [(True,), (False,)],
)
def test_engineer_base_spatial_columns(has_coords: bool) -> None:
    rows = {
        "month": ["2020-06"],
        "town": ["TAMPINES"],
        "flat_type": ["4 ROOM"],
        "flat_model": ["MODEL A"],
        "storey_range": ["07 TO 09"],
        "floor_area_sqm": [92.0],
        "remaining_lease_years": [80],
        "lease_commence_date": [2000],
    }
    if has_coords:
        rows["lat"] = [1.35]
        rows["lon"] = [103.9]
    raw = pd.DataFrame(rows)

    out = engineer_base_features(raw, categorical_style="legacy")

    for c in SPATIAL_NUMERIC_FEATURES:
        assert c in out.columns
    assert "flat_type_encoded" in out.columns
    assert out["flat_type_encoded"].iloc[0] == pytest.approx(4.0)
    if has_coords:
        assert out["lat"].iloc[0] == pytest.approx(1.35)
        assert out["lon"].iloc[0] == pytest.approx(103.9)
    else:
        assert np.isnan(out["lat"].iloc[0])
        assert np.isnan(out["lon"].iloc[0])
