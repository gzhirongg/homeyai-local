"""Smoke tests for feature-set registry composition."""

from __future__ import annotations

from copy import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modelling.config.feature_sets import get_feature_registry


def test_baseline_engineering_shape():
    root = Path(__file__).resolve().parents[2]
    reg = get_feature_registry(root)
    fs = copy(reg["baseline_v1"])
    raw = pd.DataFrame(
        {
            "month": ["2020-01", "2020-02"],
            "town": ["TAMPINES", "BEDOK"],
            "flat_type": ["4 ROOM", "3 ROOM"],
            "flat_model": ["Model A", "Improved"],
            "storey_range": ["10 TO 12", "04 TO 06"],
            "floor_area_sqm": [90, 75],
            "lease_commence_date": [1999, 1988],
            "remaining_lease_years": [79, 65],
            "lat": [1.3521, 1.3236],
            "lon": [103.9449, 103.9309],
        }
    )
    fs.engineer_kwargs = {"project_root": root}
    out = fs.engineer(raw, **fs.engineer_kwargs)
    assert set(fs.categorical_features).issubset(out.columns)
    assert "flat_type" not in fs.categorical_features
    assert "flat_type_encoded" in fs.numeric_features
    for c in fs.numeric_features:
        assert c in out.columns
    dropped = {
        "lease_commence_date",
        "remaining_lease_missing_flag",
        "flat_age_years",
        "flat_age_negative_flag",
    }
    assert not dropped.intersection(out.columns)
    assert "remaining_lease_years" in fs.numeric_features
    assert "storey_mid" in fs.numeric_features
    assert "sale_month_sin" in fs.numeric_features
    assert "sale_month_cos" in fs.numeric_features
    assert "sale_month" not in fs.numeric_features
    assert "storey_lower" not in fs.numeric_features
    assert "storey_upper" not in fs.numeric_features
    assert "sale_month" not in out.columns
    assert "storey_lower" not in out.columns
    assert "storey_upper" not in out.columns
    assert float(out["flat_type_encoded"].iloc[0]) == pytest.approx(4.0)
    assert float(out["flat_type_encoded"].iloc[1]) == pytest.approx(3.0)
    assert "lat" in fs.numeric_features
    assert "lon" in fs.numeric_features
    assert out["lat"].iloc[0] == pytest.approx(1.3521)
    assert out["lon"].iloc[1] == pytest.approx(103.9309)


def test_mrt_pit_includes_line_coverage_scalars_not_line_one_hots():
    root = Path(__file__).resolve().parents[2]
    reg = get_feature_registry(root)
    fs = reg["mrt_pit"]
    assert "num_unique_lines_within_1km" in fs.numeric_features
    assert "nearest_planned_mrt_dist" in fs.numeric_features
    assert "project_completion_fraction" in fs.numeric_features
    assert not any(str(c).startswith("is_nearest_line_") for c in fs.numeric_features)
    assert not any(str(c).startswith("is_mrt_line_") for c in fs.numeric_features)
    assert not any(str(c).startswith("is_planned_line_") for c in fs.numeric_features)

    raw = pd.DataFrame(
        {
            "month": ["2024-01"],
            "town": ["TAMPINES"],
            "flat_type": ["4 ROOM"],
            "flat_model": ["Model A"],
            "storey_range": ["10 TO 12"],
            "floor_area_sqm": [90.0],
            "lease_commence_date": [1999],
            "remaining_lease_years": [70],
            "lat": [1.3521],
            "lon": [103.9449],
            "nearest_op_lines": [["East-West Line"]],
            "nearest_planned_lines": [[]],
            "num_unique_lines_within_1km": [3],
            "nearest_planned_mrt_dist": [np.nan],
        }
    )
    fs.engineer_kwargs = {**fs.engineer_kwargs, "project_root": root}
    out = fs.engineer(raw, **fs.engineer_kwargs)
    for c in fs.numeric_features:
        assert c in out.columns
    assert float(out["num_unique_lines_within_1km"].iloc[0]) == pytest.approx(3.0)
    assert not any(str(c).startswith("is_nearest_line_") for c in out.columns)


def test_grouped_and_months_feature_sets():
    root = Path(__file__).resolve().parents[2]
    reg = get_feature_registry(root)

    raw = pd.DataFrame(
        {
            "month": ["2020-01"],
            "town": ["TAMPINES"],
            "flat_type": ["4 ROOM"],
            "flat_model": ["Model A"],
            "storey_range": ["10 TO 12"],
            "floor_area_sqm": [90.0],
            "lease_commence_date": [1999],
            "remaining_lease_years": [79],
        }
    )

    fs_g = reg["baseline_grouped_v1"]
    out_g = fs_g.engineer(raw.copy(), project_root=root)
    assert "region" in fs_g.categorical_features
    assert "flat_model_grouped" in out_g.columns

    fs_m = reg["baseline_v1__months_since_2015"]
    out_m = fs_m.engineer(raw.copy(), **{**fs_m.engineer_kwargs, "project_root": root})
    assert "months_since_2015" in out_m.columns
