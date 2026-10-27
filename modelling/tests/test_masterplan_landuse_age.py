"""Land-use interaction derives flat age from remaining_lease_years."""

from __future__ import annotations

import pytest
import pandas as pd

from modelling.features.base import engineer_base_features
from modelling.features.masterplan_landuse_pit import append_masterplan_landuse_from_raw_columns


def test_density_age_interaction_from_remaining_lease_only():
    raw = pd.DataFrame(
        {
            "month": ["2020-01"],
            "town": ["TAMPINES"],
            "flat_type": ["4 ROOM"],
            "flat_model": ["Model A"],
            "storey_range": ["10 TO 12"],
            "floor_area_sqm": [90.0],
            "remaining_lease_years": [79],
            "nearby_high_density_score": [2.0],
            "lat": [1.35],
            "lon": [103.94],
        }
    )
    base = engineer_base_features(raw, categorical_style="legacy")
    out = append_masterplan_landuse_from_raw_columns(base, raw)
    assert out["density_age_interaction"].iloc[0] == pytest.approx(2.0 / (20.0 + 1.0))
