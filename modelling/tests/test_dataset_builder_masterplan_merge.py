"""Regression: masterplan land-use merge must not Cartesian-multiply training rows."""

from __future__ import annotations

import pandas as pd

from modelling.data.dataset_builder import _merge_left_features


def test_masterplan_merge_same_addr_month_multiple_tx_keeps_row_count_after_rhs_dedupe() -> None:
    """Two baseline rows sharing (enriched_addr_id, month) × duplicate mp keys must stay 2 rows after dedupe."""
    base = pd.DataFrame(
        {
            "enriched_addr_id": [1, 1],
            "month": ["2020-01", "2020-01"],
            "resale_price": [400_000, 410_000],
        }
    )
    mp_raw = pd.DataFrame(
        {
            "enriched_addr_id": [1, 1],
            "month": ["2020-01", "2020-01"],
            "landuse_mix_idx": [0.5, 0.5],
        }
    )
    mp = mp_raw.drop_duplicates(subset=["enriched_addr_id", "month"], keep="first")
    out = _merge_left_features(
        base,
        mp,
        join_cols=["enriched_addr_id", "month"],
        label="mp",
    )
    assert len(out) == 2
    assert list(out["landuse_mix_idx"]) == [0.5, 0.5]


def test_masterplan_duplicate_rhs_without_dedupe_multiplies_rows() -> None:
    """Document failure mode: duplicate right-hand keys multiply left rows (mitigated in build_training_dataframe)."""
    base = pd.DataFrame(
        {
            "enriched_addr_id": [1, 1],
            "month": ["2020-01", "2020-01"],
            "v": [1, 2],
        }
    )
    mp_raw = pd.DataFrame(
        {
            "enriched_addr_id": [1, 1],
            "month": ["2020-01", "2020-01"],
            "landuse_mix_idx": [0.3, 0.7],
        }
    )
    out = _merge_left_features(
        base,
        mp_raw,
        join_cols=["enriched_addr_id", "month"],
        label="mp",
    )
    assert len(out) == 4
