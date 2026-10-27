"""Tests for modelling.feature_selection."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modelling.config.feature_sets import FeatureSet
from modelling.feature_selection import (
    aggregate_recommended_drops,
    apply_numeric_feature_drops,
    correlation_analysis,
    diagnostic_row_mask,
    engineered_numeric_frame,
    mutual_information_report,
    resolve_feature_selection_policy,
    variance_report,
)


def test_variance_report_flags_constant_column():
    df = pd.DataFrame({"a": [1.0, 1.0, 1.0], "b": [1.0, 2.0, 3.0]})
    r = variance_report(df, var_threshold=1e-6)
    assert "a" in r["dropped_low_variance"]
    assert "b" not in r["dropped_low_variance"]


def test_correlation_pairs_recommends_drop():
    rng = np.random.default_rng(0)
    n = 100
    base = rng.normal(size=n)
    df = pd.DataFrame(
        {
            "x1": base,
            "x2": base + rng.normal(scale=0.01, size=n),
            "noise": rng.normal(size=n),
        }
    )
    y = pd.Series(np.exp(base + rng.normal(scale=0.1, size=n)) * 100_000)
    _, meta = correlation_analysis(df, y, r_threshold=0.85)
    assert meta["n_pairs_flagged"] >= 1
    pair = next(p for p in meta["pairs"] if {p["feature_a"], p["feature_b"]} == {"x1", "x2"})
    assert pair["recommended_drop"] in ("x1", "x2")


def test_mutual_information_ranked():
    rng = np.random.default_rng(1)
    n = 200
    signal = rng.uniform(size=n)
    df = pd.DataFrame({"good": signal, "junk": rng.normal(size=n)})
    y = pd.Series(300_000 + 50_000 * signal + rng.normal(scale=5_000, size=n))
    r = mutual_information_report(df, y, mi_floor_ratio=0.01, random_state=42)
    assert r["ranked"][0]["feature"] == "good"
    assert "junk" in r["scores"]


def test_engineered_numeric_frame_includes_float_columns():
    df = pd.DataFrame({"f": [1.0, 2.0], "s": ["a", "b"]})
    num = engineered_numeric_frame(df)
    assert list(num.columns) == ["f"]


def test_resolve_feature_selection_policy_aliases():
    assert resolve_feature_selection_policy(cli_value=None, env_var="__UNSET_TEST_VAR__") == "advisory_only"
    assert resolve_feature_selection_policy(cli_value="apply") == "apply_recommended_drops"
    assert resolve_feature_selection_policy(cli_value="advisory_only") == "advisory_only"
    with pytest.raises(ValueError):
        resolve_feature_selection_policy(cli_value="banana")


def test_aggregate_recommended_drops_intersects_registry_and_merges_reasons():
    var = {"dropped_low_variance": ["a", "ghost"]}
    corr = {"pairs": [{"recommended_drop": "b", "feature_a": "b", "feature_c": "c"}]}
    mi = {"flagged_low_mi": ["c", "ghost"]}
    out = aggregate_recommended_drops(var, corr, mi, registered_numeric=["a", "b", "c", "d"])
    assert set(out["dropped"]) == {"a", "b", "c"}
    assert out["reasons"]["a"] == ["low_variance"]
    assert set(out["reasons"]["b"]) == {"high_correlation_pair"}
    assert set(out["reasons"]["c"]) == {"low_mutual_information"}


def test_diagnostic_row_mask_finite_target_and_month():
    idx = pd.RangeIndex(4)
    raw = pd.DataFrame(
        {
            "month": ["2020-01", "bad-month", "2020-03", "2020-04"],
            "lat": [1.0, 1.0, np.nan, 1.2],
            "lon": [103.0, 103.0, 103.0, 103.7],
        },
        index=idx,
    )
    y = pd.Series([300_000.0, 310_000.0, np.nan, 330_000.0], index=idx)
    m = diagnostic_row_mask(raw, y, feature_set_id="baseline_v1")
    assert list(m) == [True, False, False, True]


def test_diagnostic_row_mask_poi_requires_coords():
    idx = pd.RangeIndex(3)
    raw = pd.DataFrame(
        {
            "month": ["2020-01", "2020-02", "2020-03"],
            "lat": [1.0, np.nan, 1.2],
            "lon": [103.0, 103.0, 103.7],
            "resale_price": [1, 2, 3],
        },
        index=idx,
    )
    y = pd.Series([300_000.0, 310_000.0, 320_000.0], index=idx)
    m = diagnostic_row_mask(raw, y, feature_set_id="mrt_pit__poi_test")
    assert list(m) == [True, False, True]


def test_diagnostic_row_mask_poi_without_lat_lon_all_false():
    raw = pd.DataFrame({"month": ["2020-01"], "resale_price": [1]})
    y = pd.Series([300_000.0])
    m = diagnostic_row_mask(raw, y, feature_set_id="poi_pack")
    assert not bool(m.any())


def test_apply_numeric_feature_drops_respects_floor():
    fs = FeatureSet(
        id="t",
        description="",
        categorical_features=[],
        numeric_features=["a", "b", "c"],
        engineer=lambda df, **kw: df,
        engineer_kwargs={},
    )
    removed, applied = apply_numeric_feature_drops(fs, {"a", "b"}, min_remaining=3)
    assert applied is False
    assert removed == []
    assert fs.numeric_features == ["a", "b", "c"]

    removed2, applied2 = apply_numeric_feature_drops(fs, {"a"}, min_remaining=2)
    assert applied2 is True
    assert removed2 == ["a"]
    assert fs.numeric_features == ["b", "c"]
