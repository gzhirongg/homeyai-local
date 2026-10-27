"""Pre-fit feature diagnostics: variance, correlation clusters, mutual information.

Used by ``train_from_frame`` and ``runners/run_feature_selection.py``.
Operates on an **engineered** training frame (numeric columns only for steps 1–3).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_regression

from modelling.config.feature_sets import FeatureSet

logger = logging.getLogger(__name__)

ADVISORY_ONLY = "advisory_only"
APPLY_RECOMMENDED_DROPS = "apply_recommended_drops"


def resolve_feature_selection_policy(
    *,
    cli_value: str | None = None,
    env_var: str = "HOMEYAI_FEATURE_SELECTION_POLICY",
) -> str:
    """Return ``advisory_only`` or ``apply_recommended_drops`` (aliases: ``apply`` → apply mode)."""
    raw = (cli_value if cli_value is not None else os.getenv(env_var, "")).strip().lower()
    if not raw:
        return ADVISORY_ONLY
    if raw in ("apply_recommended_drops", "apply", "recommended_drops"):
        return APPLY_RECOMMENDED_DROPS
    if raw in ("advisory_only", "advisory", "none", "off", "0", "false"):
        return ADVISORY_ONLY
    raise ValueError(
        f"Unknown feature selection policy {raw!r}; use advisory_only or apply_recommended_drops"
    )


def diagnostic_row_mask(
    raw_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    feature_set_id: str,
) -> pd.Series:
    """Rows to include in variance/correlation/MI (same index as ``raw_train`` / ``y_train``).

    Requires finite target; parseable ``month`` when present; for POI feature sets, non-null lat/lon.
    """
    idx = raw_train.index
    mask = pd.Series(True, index=idx, dtype=bool)
    ynum = pd.to_numeric(y_train.reindex(idx), errors="coerce")
    mask &= ynum.notna() & np.isfinite(ynum.to_numpy(dtype=float))

    if "month" in raw_train.columns:
        mt = pd.to_datetime(raw_train["month"], format="%Y-%m", errors="coerce")
        mask &= mt.notna()

    if "poi" in feature_set_id:
        if {"lat", "lon"}.issubset(raw_train.columns):
            mask &= raw_train["lat"].notna() & raw_train["lon"].notna()
        else:
            mask &= False

    return mask


def aggregate_recommended_drops(
    variance_doc: dict[str, Any],
    corr_doc: dict[str, Any],
    mi_doc: dict[str, Any],
    *,
    registered_numeric: list[str],
) -> dict[str, Any]:
    """Union diagnostic recommendations intersected with registered numeric feature names."""
    reg = frozenset(str(x) for x in registered_numeric)
    reasons: dict[str, list[str]] = {}

    def _tag(col: str, tag: str) -> None:
        if col not in reg:
            return
        reasons.setdefault(col, []).append(tag)

    for c in variance_doc.get("dropped_low_variance") or []:
        _tag(str(c), "low_variance")

    for p in corr_doc.get("pairs") or []:
        if isinstance(p, dict) and p.get("recommended_drop"):
            _tag(str(p["recommended_drop"]), "high_correlation_pair")

    for c in mi_doc.get("flagged_low_mi") or []:
        _tag(str(c), "low_mutual_information")

    dropped_sorted = sorted(reasons.keys())
    return {
        "dropped": dropped_sorted,
        "reasons": {k: sorted(set(v)) for k, v in sorted(reasons.items())},
        "n_registered_numeric": len(reg),
        "n_recommended_drop": len(dropped_sorted),
    }


def apply_numeric_feature_drops(
    fs: FeatureSet,
    drops: set[str],
    *,
    min_remaining: int = 3,
) -> tuple[list[str], bool]:
    """Remove ``drops`` from ``fs.numeric_features`` in place if enough columns remain.

    Returns ``(columns_removed, applied)``. If applying would violate ``min_remaining``,
    logs a warning and leaves ``fs`` unchanged (``applied`` False).
    """
    nums = fs.numeric_features
    if not nums:
        return [], False
    to_drop = {str(x) for x in drops if str(x) in set(map(str, nums))}
    kept = [c for c in nums if str(c) not in to_drop]
    if len(kept) < int(min_remaining):
        logger.warning(
            "Skipping feature-selection drops: would leave %s numeric features (< min_remaining=%s). "
            "Recommended drop count=%s.",
            len(kept),
            min_remaining,
            len(to_drop),
        )
        return [], False
    removed = [c for c in nums if str(c) in to_drop]
    fs.numeric_features = kept
    return removed, True


def engineered_numeric_frame(engineered: pd.DataFrame) -> pd.DataFrame:
    """Numeric columns only (excludes bool/object); bool is often stored as float 0/1 here."""
    num = engineered.select_dtypes(include=[np.number]).copy()
    return num


def variance_report(df_num: pd.DataFrame, *, var_threshold: float = 1e-6) -> dict[str, Any]:
    """Flag near-constant numeric columns by population variance."""
    variances: dict[str, float | None] = {}
    dropped: list[str] = []
    for c in df_num.columns:
        s = df_num[c]
        if s.notna().sum() < 2:
            variances[str(c)] = None
            dropped.append(str(c))
            continue
        v = float(s.var(skipna=True, ddof=0))
        variances[str(c)] = v
        if not np.isfinite(v) or v < var_threshold:
            dropped.append(str(c))
    return {
        "var_threshold": float(var_threshold),
        "n_numeric_columns": int(len(df_num.columns)),
        "variances": variances,
        "dropped_low_variance": sorted(set(dropped)),
    }


def correlation_analysis(
    df_num: pd.DataFrame,
    y: pd.Series,
    *,
    r_threshold: float = 0.85,
    min_periods: int = 30,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Pearson correlation matrix + pairs above ``|r_threshold|`` with drop heuristic."""
    if df_num.shape[1] == 0:
        return pd.DataFrame(), {"r_threshold": r_threshold, "pairs": [], "n_pairs_flagged": 0}

    corr = df_num.corr(method="pearson", min_periods=min_periods)
    y_price = pd.to_numeric(y, errors="coerce").astype(float)
    target_log = np.log1p(np.clip(y_price.to_numpy(dtype=float), a_min=0.0, a_max=None))

    spearman_abs: dict[str, float] = {}
    for c in df_num.columns:
        xv = pd.to_numeric(df_num[c], errors="coerce").astype(float).to_numpy()
        mask = np.isfinite(xv) & np.isfinite(target_log)
        if int(mask.sum()) < min_periods:
            spearman_abs[str(c)] = 0.0
            continue
        s = pd.Series(xv[mask]).corr(pd.Series(target_log[mask]), method="spearman")
        spearman_abs[str(c)] = float(abs(s)) if pd.notna(s) else 0.0

    cols = list(corr.columns)
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            r = corr.loc[a, b]
            if pd.isna(r):
                continue
            rf = float(r)
            if abs(rf) < r_threshold:
                continue
            sa = spearman_abs.get(str(a), 0.0)
            sb = spearman_abs.get(str(b), 0.0)
            drop = str(a) if sa < sb else str(b)
            pairs.append(
                {
                    "feature_a": str(a),
                    "feature_b": str(b),
                    "pearson_r": rf,
                    "spearman_abs_target_a": sa,
                    "spearman_abs_target_b": sb,
                    "recommended_drop": drop,
                    "reason": "lower_abs_spearman_vs_log1p_price",
                }
            )

    meta: dict[str, Any] = {
        "r_threshold": float(r_threshold),
        "min_periods": int(min_periods),
        "n_pairs_flagged": len(pairs),
        "pairs": pairs,
    }
    return corr, meta


def mutual_information_report(
    df_num: pd.DataFrame,
    y: pd.Series,
    *,
    mi_floor_ratio: float = 0.02,
    random_state: int = 42,
) -> dict[str, Any]:
    """``mutual_info_regression`` vs ``log1p(price)`` after median imputation (analysis only)."""
    if df_num.shape[1] == 0:
        return {
            "mi_floor_ratio": float(mi_floor_ratio),
            "mi_floor_absolute": 0.0,
            "scores": {},
            "ranked": [],
            "flagged_low_mi": [],
            "note": "no_numeric_columns",
        }

    X = df_num.copy()
    medians = X.median(numeric_only=True)
    X = X.fillna(medians)

    y_price = pd.to_numeric(y, errors="coerce").astype(float)
    mask = y_price.notna()
    X = X.loc[mask]
    y_arr = np.log1p(np.clip(y_price.loc[mask].to_numpy(dtype=float), a_min=0.0, a_max=None))

    if len(y_arr) < 50:
        return {
            "mi_floor_ratio": float(mi_floor_ratio),
            "mi_floor_absolute": 0.0,
            "scores": {},
            "ranked": [],
            "flagged_low_mi": [],
            "note": "insufficient_rows_after_target_dropna",
            "n_rows_used": int(len(y_arr)),
        }

    mi = mutual_info_regression(X, y_arr, random_state=random_state)
    scores = {str(c): float(mi[i]) for i, c in enumerate(X.columns)}
    top = float(np.max(mi)) if len(mi) else 0.0
    floor = top * mi_floor_ratio if top > 0 else 0.0
    flagged = [c for c, s in scores.items() if s < floor]
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])

    return {
        "mi_floor_ratio": float(mi_floor_ratio),
        "mi_floor_absolute": float(floor),
        "scores": scores,
        "ranked": [{"feature": k, "mi": v} for k, v in ranked],
        "flagged_low_mi": sorted(flagged),
        "n_rows_used": int(len(y_arr)),
        "note": "median_imputed_for_mi_only",
    }


def write_feature_selection_artifacts(
    out_dir: Path,
    engineered_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    row_mask: pd.Series | None = None,
    var_threshold: float = 1e-6,
    r_threshold: float = 0.85,
    mi_floor_ratio: float = 0.02,
    random_state: int = 42,
    registered_numeric: list[str] | None = None,
    write_features_dropped_json: bool = False,
    features_dropped_extra: dict[str, Any] | None = None,
) -> None:
    """Write variance JSON, correlation CSV + pairs JSON, MI JSON under ``out_dir``.

    When ``row_mask`` is set, diagnostics use aligned subsets (same index).
    Optional ``features_dropped.json`` aggregates recommendations vs registry numerics.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    eng = engineered_train
    y = y_train
    if row_mask is not None:
        m = row_mask.reindex(eng.index).fillna(False).astype(bool)
        eng = eng.loc[m]
        y = y_train.reindex(eng.index)

    df_num = engineered_numeric_frame(eng)

    vr = variance_report(df_num, var_threshold=var_threshold)
    (out_dir / "feature_variance.json").write_text(json.dumps(vr, indent=2), encoding="utf-8")

    corr_mat, corr_meta = correlation_analysis(df_num, y, r_threshold=r_threshold)
    if not corr_mat.empty:
        corr_mat.to_csv(out_dir / "feature_correlation_matrix.csv")
    else:
        pd.DataFrame().to_csv(out_dir / "feature_correlation_matrix.csv")
    (out_dir / "correlated_pairs.json").write_text(json.dumps(corr_meta, indent=2), encoding="utf-8")

    mi_doc = mutual_information_report(
        df_num,
        y,
        mi_floor_ratio=mi_floor_ratio,
        random_state=random_state,
    )
    (out_dir / "feature_mi_scores.json").write_text(json.dumps(mi_doc, indent=2), encoding="utf-8")

    if write_features_dropped_json and registered_numeric is not None:
        agg = aggregate_recommended_drops(vr, corr_meta, mi_doc, registered_numeric=registered_numeric)
        payload: dict[str, Any] = {
            **agg,
            "diagnostic_engineered_rows": int(len(eng)),
            "diagnostic_row_mask_true_rate": float(row_mask.mean()) if row_mask is not None and len(row_mask) else None,
        }
        if features_dropped_extra:
            payload.update(features_dropped_extra)
        (out_dir / "features_dropped.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
