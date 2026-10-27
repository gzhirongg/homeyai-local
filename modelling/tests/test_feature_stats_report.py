"""Training-report feature stats align with ordinal flat_type encoding."""

from __future__ import annotations

from modelling.data.quality import (
    annotate_model_feature_stats,
    finalize_feature_stats_for_model_report,
    merge_raw_and_engineered_feature_stats,
)


def test_finalize_drops_raw_flat_type_when_encoded_present():
    stats = {
        "flat_type": {"null_rate": 0.0, "nunique": 7, "kind": "categorical"},
        "flat_type_encoded": {"null_rate": 0.0, "nunique": 7, "kind": "numeric", "min": 1.0, "max": 7.0},
        "town": {"null_rate": 0.0, "nunique": 26, "kind": "categorical"},
    }
    out = finalize_feature_stats_for_model_report(stats)
    assert "flat_type" not in out
    assert out["flat_type_encoded"]["encoding"] == "ordinal_1_7"
    assert out["flat_type_encoded"]["in_model"] is True


def test_merge_raw_engineered_includes_encoded_not_raw_flat_type():
    import pandas as pd

    from modelling.features.base import engineer_base_features

    raw = pd.DataFrame(
        {
            "month": ["2020-01"],
            "town": ["TAMPINES"],
            "flat_type": ["4 ROOM"],
            "flat_model": ["MODEL A"],
            "storey_range": ["07 TO 09"],
            "floor_area_sqm": [90.0],
            "remaining_lease_years": [80.0],
            "lease_commence_date": [2000],
        }
    )
    eng = engineer_base_features(raw, categorical_style="legacy")
    merged = merge_raw_and_engineered_feature_stats(raw, eng)
    assert "flat_type" not in merged
    assert "flat_type_encoded" in merged
    tagged = annotate_model_feature_stats(
        merged,
        numeric_features=["flat_type_encoded", "floor_area_sqm"],
        categorical_features=["town", "flat_model"],
    )
    assert tagged["flat_type_encoded"]["in_model"] is True
    assert tagged["town"]["in_model"] is True
    assert tagged["month"]["in_model"] is False
