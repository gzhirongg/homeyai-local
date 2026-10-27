"""Subset training rows by HDB flat type (canonical labels after normalization)."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from modelling.features.base import _normalize_flat_type_series

FlatTypeScope = Literal["all", "core_35"]

# Canonical forms after `_normalize_flat_type_series` (see FLAT_TYPE_ORDINAL keys).
CORE_FLAT_TYPES_35 = frozenset({"3 ROOM", "4 ROOM", "5 ROOM"})


def apply_flat_type_scope(raw_df: pd.DataFrame, scope: FlatTypeScope) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Optionally keep only 3-, 4-, and 5-ROOM resale rows.

    Matching uses the same normalization as feature engineering (`MULTI GENERATION`,
    hyphenated variants, casing). Rows with unknown / null normalized labels are excluded
    when ``scope`` is ``core_35``.
    """
    rows_before = int(len(raw_df))
    if scope == "all":
        audit: dict[str, Any] = {
            "applied": False,
            "scope": scope,
            "rows_before": rows_before,
            "rows_after": rows_before,
            "rows_dropped": 0,
            "pct_kept": (100.0 if rows_before else None),
            "excluded_flat_types": [],
        }
        return raw_df, audit

    if scope != "core_35":
        raise ValueError(f"Unknown flat_type_scope {scope!r}; expected 'all' or 'core_35'")

    if "flat_type" not in raw_df.columns:
        raise RuntimeError("flat_type_scope=core_35 requires column 'flat_type' on the training frame")

    norm = _normalize_flat_type_series(raw_df["flat_type"])
    space_labels = norm.astype("string").str.replace("-", " ", regex=False)
    keep_mask = space_labels.isin(CORE_FLAT_TYPES_35)

    excluded_norm = norm.loc[~keep_mask]
    excluded_vc = excluded_norm.astype("string").value_counts(dropna=False)
    excluded_flat_types = [
        {"flat_type": str(label) if pd.notna(label) else "__null_or_unknown__", "count": int(cnt)}
        for label, cnt in excluded_vc.items()
    ]
    excluded_flat_types.sort(key=lambda x: -int(x["count"]))

    out = raw_df.loc[keep_mask].copy()
    rows_after = int(len(out))
    rows_dropped = rows_before - rows_after
    pct_kept = round(100.0 * float(rows_after) / float(rows_before), 4) if rows_before > 0 else None

    audit = {
        "applied": True,
        "scope": scope,
        "rows_before": rows_before,
        "rows_after": rows_after,
        "rows_dropped": rows_dropped,
        "pct_kept": pct_kept,
        "excluded_flat_types": excluded_flat_types,
    }
    return out, audit


__all__ = ["CORE_FLAT_TYPES_35", "FlatTypeScope", "apply_flat_type_scope"]
