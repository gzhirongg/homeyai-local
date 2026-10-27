"""Ordinal flat_type encoding (``flat_type_encoded`` 1–7)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modelling.config.model_specs import build_sklearn_preprocessor
from modelling.features.base import FLAT_TYPE_ORDINAL, engineer_base_features, encode_flat_type_ordinal, _normalize_flat_type_series


def test_flat_type_ordinal_canonical_keys():
    assert FLAT_TYPE_ORDINAL["1 ROOM"] == 1
    assert FLAT_TYPE_ORDINAL["5 ROOM"] == 5
    assert FLAT_TYPE_ORDINAL["EXECUTIVE"] == 6
    assert FLAT_TYPE_ORDINAL["MULTI-GENERATION"] == 7
    assert len(FLAT_TYPE_ORDINAL) == 7


def test_encode_all_seven_categories():
    labels = list(FLAT_TYPE_ORDINAL.keys())
    s = pd.Series(labels)
    norm = _normalize_flat_type_series(s)
    out = encode_flat_type_ordinal(norm)
    assert list(out.astype(int)) == list(range(1, 8))


def test_multi_generation_alias():
    norm = _normalize_flat_type_series(pd.Series(["MULTI GENERATION", "multi generation"]))
    out = encode_flat_type_ordinal(norm)
    assert (out == 7).all()


def test_hyphen_variant_maps():
    norm = _normalize_flat_type_series(pd.Series(["1-ROOM", "4-ROOM"]))
    out = encode_flat_type_ordinal(norm)
    assert out.iloc[0] == 1
    assert out.iloc[1] == 4


def test_unknown_label_nan():
    norm = _normalize_flat_type_series(pd.Series(["STUDIO", "4 ROOM"]))
    out = encode_flat_type_ordinal(norm)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == 4


def test_engineer_base_features_emits_encoded_not_string_column():
    raw = pd.DataFrame(
        {
            "month": ["2020-01"],
            "town": ["TAMPINES"],
            "flat_type": ["4 ROOM"],
            "flat_model": ["MODEL A"],
            "storey_range": ["07 TO 09"],
            "floor_area_sqm": [92.0],
            "remaining_lease_years": [80.0],
            "lease_commence_date": [2000],
        }
    )
    out = engineer_base_features(raw, categorical_style="legacy")
    assert "flat_type_encoded" in out.columns
    assert out["flat_type_encoded"].iloc[0] == pytest.approx(4.0)
    assert "flat_type" not in out.columns


@pytest.mark.parametrize(
    "model_id",
    ["xgboost", "xgboost_grouped"],
)
def test_xgboost_preprocessor_has_no_flat_type_onehot_expansion(model_id: str):
    try:
        from modelling.config.model_specs import build_default_specs
    except ImportError:
        pytest.skip("model_specs unavailable")
    specs = build_default_specs(42)
    if model_id not in specs:
        pytest.skip(f"{model_id} not in specs (optional dependency)")
    spec = specs[model_id]
    assert spec.use_target_encoder
    # Minimal engineered column names for grouped vs legacy categoricals
    if model_id == "xgboost_grouped":
        categorical = ["town", "flat_model_grouped", "region"]
    else:
        categorical = ["town", "flat_model"]
    numeric = [
        "sale_year",
        "sale_month_sin",
        "sale_month_cos",
        "floor_area_sqm",
        "flat_type_encoded",
        "remaining_lease_years",
        "storey_mid",
        "lat",
        "lon",
    ]
    pre = build_sklearn_preprocessor(
        numeric_features=numeric,
        categorical_features=categorical,
        scale_numeric=False,
        spec=spec,
    )
    row = {**{c: 1.0 for c in numeric}, **{c: "TAMPINES" for c in categorical}}
    X = pd.DataFrame([row])
    pre.fit(X, pd.Series([400_000.0]))
    names = list(pre.get_feature_names_out())
    flat_type_cols = [n for n in names if str(n).startswith("flat_type")]
    assert set(flat_type_cols) == {"flat_type_encoded"}
