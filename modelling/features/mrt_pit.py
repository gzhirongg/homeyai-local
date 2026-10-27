"""Point-in-time MRT feature columns appended to the base engineered frame."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from modelling.features.base import engineer_base_features, repo_root
from modelling.features.line_vocab import (
    assert_lines_in_vocab,
    expanded_line_vocab_from_frame,
    load_mrt_line_vocab,
)

MRT_SCALAR_INPUT_COLS = [
    "dist_to_nearest_op_mrt",
    "travel_time_to_active_mrt",
    "pt_time_savings_vs_walk",
    "line_connectivity_index",
    "num_unique_lines_within_1km",
    "nearest_planned_mrt_dist",
    "days_since_mrt_announcement",
    "speculative_upside_score",
    "days_to_mrt_opening",
    "has_future_upside",
    "is_proximity_nuisance",
]

MRT_SCALAR_NUMERIC_FEATURES = [
    "dist_to_nearest_op_mrt",
    "travel_time_to_active_mrt",
    "pt_time_savings_vs_walk",
    "line_connectivity_index",
    "num_unique_lines_within_1km",
    "days_since_mrt_announcement",
    "speculative_upside_score",
    "days_to_mrt_opening",
    "nearest_planned_mrt_dist",
    "project_completion_fraction",
]

# Snapshot / parquet columns only; ``project_completion_fraction`` is derived in ``append_mrt_features``.
_MRT_SCALAR_FROM_RAW = frozenset(MRT_SCALAR_NUMERIC_FEATURES) - frozenset({"project_completion_fraction"})

MRT_BINARY_NUMERIC_FEATURES = [
    "has_future_upside",
    "is_proximity_nuisance",
]


def mrt_numeric_feature_names(project_root: Path | None = None) -> list[str]:
    """MRT pack numeric column names registered for modelling."""
    return list(MRT_SCALAR_NUMERIC_FEATURES + MRT_BINARY_NUMERIC_FEATURES)


def validate_mrt_line_registry(frame: pd.DataFrame, project_root: Path | None = None) -> None:
    """Ensure network_line literals from Postgres are subset of modelling/_mrt_lines.json."""
    root = project_root or repo_root()
    vocab = load_mrt_line_vocab(root)
    if not vocab:
        warnings.warn(
            "modelling/_mrt_lines.json is empty — run backend/scripts/build_mrt_pit_snapshot.py "
            "against Postgres to rebuild the line vocabulary used for audits.",
            stacklevel=2,
        )
        return
    if "nearest_op_lines" not in frame.columns and "nearest_planned_lines" not in frame.columns:
        return
    found_list = expanded_line_vocab_from_frame(
        frame["nearest_op_lines"] if "nearest_op_lines" in frame.columns else None,
        frame["nearest_planned_lines"] if "nearest_planned_lines" in frame.columns else None,
    )
    if not found_list:
        return
    assert_lines_in_vocab(set(found_list), set(vocab))


def append_mrt_features(
    base: pd.DataFrame,
    raw_frame: pd.DataFrame,
    *,
    project_root: Path | None = None,
) -> pd.DataFrame:
    """Mutates a copy of ``base`` with MRT/PIT columns aligned to ``raw_frame``."""
    del project_root  # reserved for API symmetry with other append_* helpers
    out = base.copy()

    for col in _MRT_SCALAR_FROM_RAW:
        if col in raw_frame.columns:
            out[col] = pd.to_numeric(raw_frame[col], errors="coerce")
        else:
            out[col] = np.nan

    idx = raw_frame.index
    ann = (
        pd.to_numeric(raw_frame["days_since_mrt_announcement"], errors="coerce")
        if "days_since_mrt_announcement" in raw_frame.columns
        else pd.Series(np.nan, index=idx, dtype=float)
    )
    opn = (
        pd.to_numeric(raw_frame["days_to_mrt_opening"], errors="coerce")
        if "days_to_mrt_opening" in raw_frame.columns
        else pd.Series(np.nan, index=idx, dtype=float)
    )
    total = ann + opn
    denom = total.where(total > 0)
    frac = ann.where(total.notna() & (total > 0)) / denom
    # Force pandas Series: numpy scalars / ndarray use NumPy 2 ``.clip``, which does not accept ``lower=/upper=``.
    out["project_completion_fraction"] = pd.Series(frac, index=idx, dtype="float64").clip(
        lower=0.0, upper=1.0
    )

    for col in MRT_BINARY_NUMERIC_FEATURES:
        if col in raw_frame.columns:
            out[col] = pd.to_numeric(raw_frame[col], errors="coerce").fillna(0.0).astype(float)
        else:
            out[col] = 0.0

    return out


def engineer_mrt_pit_frame(
    raw: pd.DataFrame,
    *,
    categorical_style: str = "legacy",
    project_root: Path | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    kwargs.pop("include_line_indicators", None)  # removed — line one-hots dropped from MRT pack
    base = engineer_base_features(
        raw,
        categorical_style=categorical_style,  # type: ignore[arg-type]
        include_months_since_2015=bool(kwargs.get("include_months_since_2015")),
    )
    root = project_root or repo_root()
    return append_mrt_features(base, raw, project_root=root)
