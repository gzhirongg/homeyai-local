"""Regression: estate maturity merge must not Cartesian-multiply training rows."""

from __future__ import annotations

import pandas as pd

from modelling.data.dataset_builder import _estate_merge_town_keys, _merge_left_features


def test_estate_merge_same_town_month_multiple_tx_keeps_row_count() -> None:
    """Many baseline rows sharing (town, month) × unique panel keys must stay 1:1 per tx row."""
    base = pd.DataFrame(
        {
            "enriched_addr_id": [1, 2, 3, 4],
            "month": ["2020-01", "2020-01", "2020-01", "2020-02"],
            "town": ["Ang Mo Kio", "Ang Mo Kio", "Ang Mo Kio", "Bishan"],
            "resale_price": [400_000, 410_000, 420_000, 500_000],
        }
    )
    base["_town_norm"] = _estate_merge_town_keys(base["town"])
    panel = pd.DataFrame(
        {
            "_town_norm": ["ANG MO KIO", "BISHAN"],
            "month": ["2020-01", "2020-02"],
            "town_supply_maturity_ratio": [0.1, 0.2],
            "avg_residential_block_age_years": [30.0, 25.0],
        }
    )
    out = _merge_left_features(
        base,
        panel,
        join_cols=["_town_norm", "month"],
        label="estate",
    )
    assert len(out) == 4
    assert list(out["town_supply_maturity_ratio"]) == [0.1, 0.1, 0.1, 0.2]


def test_estate_panel_duplicate_keys_would_expand_without_guard() -> None:
    """Document failure mode: non-unique right keys multiply left rows (caught in build_training_dataframe)."""
    base = pd.DataFrame(
        {
            "_town_norm": ["X", "X"],
            "month": ["2020-01", "2020-01"],
            "v": [1, 2],
        }
    )
    panel = pd.DataFrame(
        {
            "_town_norm": ["X", "X"],
            "month": ["2020-01", "2020-01"],
            "k": [1, 2],
        }
    )
    out = _merge_left_features(base, panel, join_cols=["_town_norm", "month"], label="estate")
    assert len(out) == 4
