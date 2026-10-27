"""Tests for PIT MRT scoring helpers and line registry validation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modelling import mrt_pit_helpers as h
from modelling.features.base import engineer_base_features
from modelling.features.mrt_pit import append_mrt_features, engineer_mrt_pit_frame
from modelling.modelling import _validate_mrt_line_registry, engineer_features


def _minimal_raw_row(**extra) -> pd.DataFrame:
    base = {
        "month": ["2024-01"],
        "town": ["TAMPINES"],
        "flat_type": ["4 ROOM"],
        "flat_model": ["Model A"],
        "storey_range": ["10 TO 12"],
        "floor_area_sqm": [90],
        "lease_commence_date": [1999],
        "remaining_lease_years": [70],
        "nearest_op_lines": [[]],
        "nearest_planned_lines": [[]],
    }
    base.update(extra)
    return pd.DataFrame(base)


def test_speculative_upside_temporal_ordering():
    """Far future opening ⇒ low score; imminent opening ⇒ high score."""
    s_2017 = h.speculative_upside_score(3650.0)  # ~10 years ahead
    s_2026 = h.speculative_upside_score(30.0)  # imminent
    assert s_2017 is not None and s_2026 is not None
    assert s_2017 < 0.2
    assert s_2026 > 0.8


def test_speculative_upside_none_when_unknown():
    assert h.speculative_upside_score(None) is None
    assert h.speculative_upside_score(float("nan")) is None


def test_line_tokens_handles_pg_array_like():
    raw = np.array(["North-South Line", "East-West Line"], dtype=object)
    assert "North-South Line" in h.line_tokens(raw)
    assert h.line_tokens(None) == set()


def test_assert_lines_in_vocab_raises_on_extra():
    vocab = {"North-South Line"}
    with pytest.raises(ValueError, match="registry"):
        h.assert_lines_in_vocab({"Thomson-East Coast Line"}, vocab)


def test_validate_mrt_registry_allows_subset():
    df = pd.DataFrame(
        {
            "nearest_op_lines": [["North-South Line"], None],
            "nearest_planned_lines": [None, ["Cross Island Line"]],
        }
    )
    _validate_mrt_line_registry(df)


def test_append_mrt_features_new_snapshot_columns_flow_through():
    raw = _minimal_raw_row(
        num_unique_lines_within_1km=[4],
        nearest_planned_mrt_dist=[1250.25],
    )
    base = engineer_base_features(raw, categorical_style="legacy")
    out = append_mrt_features(base, raw)
    assert float(out["num_unique_lines_within_1km"].iloc[0]) == pytest.approx(4.0)
    assert float(out["nearest_planned_mrt_dist"].iloc[0]) == pytest.approx(1250.25)


def test_append_mrt_features_missing_new_columns_are_nan():
    raw = _minimal_raw_row()
    base = engineer_base_features(raw, categorical_style="legacy")
    out = append_mrt_features(base, raw)
    assert np.isnan(out["num_unique_lines_within_1km"].iloc[0])
    assert np.isnan(out["nearest_planned_mrt_dist"].iloc[0])


def test_engineer_mrt_pit_frame_ignores_legacy_include_line_indicators_kwarg():
    root = Path(__file__).resolve().parents[2]
    raw = _minimal_raw_row()
    out = engineer_mrt_pit_frame(raw, project_root=root, include_line_indicators=False)
    assert "dist_to_nearest_op_mrt" in out.columns
    assert not any(c.startswith("is_nearest_line_") for c in out.columns)


def test_engineer_features_has_no_line_one_hots():
    raw = _minimal_raw_row(nearest_op_lines=[["East-West Line"]])
    out = engineer_features(raw)
    assert not any(str(c).startswith("is_nearest_line_") for c in out.columns)
    assert "num_unique_lines_within_1km" in out.columns
    assert "project_completion_fraction" in out.columns


def test_project_completion_fraction_mid_lifecycle():
    raw = _minimal_raw_row(
        days_since_mrt_announcement=[500.0],
        days_to_mrt_opening=[500.0],
        has_future_upside=[1],
    )
    base = engineer_base_features(raw, categorical_style="legacy")
    out = append_mrt_features(base, raw)
    assert float(out["project_completion_fraction"].iloc[0]) == pytest.approx(0.5)


def test_project_completion_fraction_imminent_opening():
    raw = _minimal_raw_row(
        days_since_mrt_announcement=[1825.0],
        days_to_mrt_opening=[30.0],
        has_future_upside=[1],
    )
    base = engineer_base_features(raw, categorical_style="legacy")
    out = append_mrt_features(base, raw)
    assert float(out["project_completion_fraction"].iloc[0]) == pytest.approx(1825.0 / 1855.0)


def test_project_completion_fraction_fresh_announcement():
    raw = _minimal_raw_row(
        days_since_mrt_announcement=[10.0],
        days_to_mrt_opening=[1825.0],
        has_future_upside=[1],
    )
    base = engineer_base_features(raw, categorical_style="legacy")
    out = append_mrt_features(base, raw)
    assert float(out["project_completion_fraction"].iloc[0]) == pytest.approx(10.0 / 1835.0)


def test_project_completion_fraction_missing_timers_is_nan():
    raw = _minimal_raw_row(
        days_since_mrt_announcement=[np.nan],
        days_to_mrt_opening=[np.nan],
        has_future_upside=[0],
    )
    base = engineer_base_features(raw, categorical_style="legacy")
    out = append_mrt_features(base, raw)
    assert np.isnan(out["project_completion_fraction"].iloc[0])
    assert float(out["has_future_upside"].iloc[0]) == pytest.approx(0.0)


def test_project_completion_fraction_both_zero_guarded_nan():
    raw = _minimal_raw_row(
        days_since_mrt_announcement=[0.0],
        days_to_mrt_opening=[0.0],
        has_future_upside=[1],
    )
    base = engineer_base_features(raw, categorical_style="legacy")
    out = append_mrt_features(base, raw)
    assert np.isnan(out["project_completion_fraction"].iloc[0])
