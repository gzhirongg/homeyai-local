"""Core training routine shared by CLI runners and remote trainers (Modal / Prefect)."""

from __future__ import annotations

import json
import logging
import math
import os
import platform
import time
import warnings
from copy import copy
from dataclasses import asdict
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.exceptions import ConvergenceWarning  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import mean_squared_error  # noqa: E402
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV, TimeSeriesSplit  # noqa: E402

from modelling.config.experiments import Experiment
from modelling.config.feature_sets import get_feature_set
from modelling.data.flat_type_scope import apply_flat_type_scope
from modelling.config.model_specs import get_model_spec
from modelling.data.quality import (
    append_post_split_to_quality_summary,
    compute_feature_stats_all_columns,
    merge_raw_and_engineered_feature_stats,
)
from modelling.data.splits import make_temporal_split, restrict_training_window
from modelling.evaluation.metrics import TARGET_COLUMN, evaluate_regression_model
from modelling.feature_selection import (
    ADVISORY_ONLY,
    APPLY_RECOMMENDED_DROPS,
    apply_numeric_feature_drops,
    diagnostic_row_mask,
    resolve_feature_selection_policy,
    write_feature_selection_artifacts,
)
from modelling.feature_selection_plots import write_feature_selection_plot_pngs
from modelling.models.pipelines import build_preprocessor_only_pipeline, wrap_pipeline_with_feature_engineering
from modelling.targets.rpi_normalization import (
    TARGET_COLUMN_TRAIN_ADJUSTED,
    TARGET_NORMALIZATION_RPI_BASELINE_100,
    adjust_prices_to_baseline100,
    align_rpi_index_to_months,
    load_rpi_index_series,
    rescale_adjusted_to_nominal,
    validate_rpi_alignment,
)
from modelling.config.experiments import effective_mrt_pit_min_years
from modelling.training_log import log_phase, training_logger

logger = logging.getLogger(__name__)
tlog = training_logger("train_core")


def _cv_n_jobs() -> int:
    """Parallelism for CV / permutation importance. Modal defaults to 1 (slim image + nested fits)."""
    raw = (os.getenv("TRAINING_CV_N_JOBS") or "").strip()
    if raw:
        return int(raw)
    if (os.getenv("HOMEYAI_LOG_SOURCE") or "").upper() == "MODAL":
        return 1
    return -1


def make_nominal_rmse_scorer(rpi_levels_df: pd.DataFrame):
    """Sklearn CV scorer: same objective as test_metrics (nominal SGD RMSE).

    ``y`` in each fold is RPI-adjusted (baseline-100) dollars; ``estimator.predict(X)`` returns
    the same scale. Monthly RPI levels from ``rpi_levels_df`` rescale both to nominal SGD before RMSE.
    Returns negative RMSE (sklearn maximises the score).
    """

    def _scorer(estimator: Any, X: pd.DataFrame, y_adj: Any) -> float:
        y_pred_adj = estimator.predict(X)
        if "month" not in getattr(X, "columns", ()):
            y_t = np.asarray(y_adj, dtype=float)
            y_p = np.asarray(y_pred_adj, dtype=float)
            return -float(np.sqrt(mean_squared_error(y_t, y_p)))
        rpi = align_rpi_index_to_months(X["month"], rpi_levels_df)
        y_true_nom = rescale_adjusted_to_nominal(np.asarray(y_adj, dtype=float), rpi)
        y_pred_nom = rescale_adjusted_to_nominal(np.asarray(y_pred_adj, dtype=float), rpi)
        return -float(np.sqrt(mean_squared_error(y_true_nom, y_pred_nom)))

    return _scorer


def _align_target_to_engineered(
    engineered: pd.DataFrame,
    target: pd.Series,
    *,
    raw_row_count: int,
    context: str,
) -> pd.Series:
    """Match ``target`` index to ``engineered`` (feature steps may ``reset_index``)."""
    if len(engineered) != raw_row_count:
        raise RuntimeError(
            f"{context}: feature engineering changed row count "
            f"({raw_row_count} -> {len(engineered)}); cannot align targets by position."
        )
    if target.index.equals(engineered.index):
        return target
    return pd.Series(
        target.to_numpy(dtype=float),
        index=engineered.index,
        name=target.name,
    )


def _describe_target_series(y: pd.Series) -> dict[str, Any]:
    s = pd.to_numeric(y, errors="coerce").dropna()
    if len(s) == 0:
        return {}
    arr = s.to_numpy(dtype=float)
    return {
        "n": int(len(s)),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "p25": float(np.percentile(arr, 25)),
        "p75": float(np.percentile(arr, 75)),
        "p95": float(np.percentile(arr, 95)),
    }


def _numeric_summary_series(s: pd.Series) -> dict[str, Any] | None:
    sn = pd.to_numeric(s, errors="coerce").dropna()
    if len(sn) == 0:
        return None
    arr = sn.to_numpy(dtype=float)
    return {
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "p5": float(np.percentile(arr, 5)),
        "p95": float(np.percentile(arr, 95)),
        "n_non_null": int(len(arr)),
    }


def _compute_data_profile(raw_df: pd.DataFrame) -> dict[str, Any]:
    n = len(raw_df)
    prof: dict[str, Any] = {"n_rows": int(n)}
    if n == 0:
        return prof
    if "month" in raw_df.columns:
        prof["month_min"] = str(raw_df["month"].min())
        prof["month_max"] = str(raw_df["month"].max())
    if "town" in raw_df.columns:
        vc = raw_df["town"].astype(str).value_counts().head(10)
        prof["top_towns"] = [
            {"town": str(k), "count": int(v), "pct": round(100.0 * float(v) / float(n), 2)} for k, v in vc.items()
        ]
    if "flat_type" in raw_df.columns:
        vc = raw_df["flat_type"].astype(str).value_counts()
        prof["flat_type_breakdown"] = [
            {"flat_type": str(k), "count": int(v), "pct": round(100.0 * float(v) / float(n), 2)}
            for k, v in vc.items()
        ]
    storey_col = None
    if "storey_range" in raw_df.columns:
        storey_col = "storey_range"
    elif "storey_midpoint" in raw_df.columns:
        storey_col = "storey_midpoint"
    if storey_col:
        vc = raw_df[storey_col].astype(str).value_counts().head(15)
        prof["storey_breakdown"] = [{"bucket": str(k), "count": int(v)} for k, v in vc.items()]
    for col in ("floor_area_sqm", "remaining_lease_years"):
        if col in raw_df.columns:
            summ = _numeric_summary_series(raw_df[col])
            if summ:
                prof[col] = summ
    return prof


def _near_constant_numeric_columns(df: pd.DataFrame, *, limit: int = 80) -> list[str]:
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    out: list[str] = []
    for c in numeric_cols:
        s = df[c]
        if s.notna().sum() < 2:
            continue
        std = float(s.std(skipna=True))
        if std == 0.0 or (s.notna().sum() > 10 and std < 1e-12):
            out.append(str(c))
        if len(out) >= limit:
            break
    return out


def _by_month_residuals(X_test: pd.DataFrame, y_act: np.ndarray, y_pred: np.ndarray) -> list[dict[str, Any]]:
    if "month" not in X_test.columns:
        return []
    months = X_test["month"].astype(str)
    r = np.asarray(y_act, dtype=float).ravel() - np.asarray(y_pred, dtype=float).ravel()
    rows: list[dict[str, Any]] = []
    for m in sorted(months.dropna().unique()):
        mask = (months.values == m) & np.isfinite(r)
        if int(mask.sum()) < 5:
            continue
        rr = r[mask]
        rows.append(
            {
                "month": str(m),
                "n": int(mask.sum()),
                "residual_mean": float(np.mean(rr)),
                "residual_std": float(np.std(rr)),
            }
        )
    return rows


def _by_town_residuals(X_test: pd.DataFrame, y_act: np.ndarray, y_pred: np.ndarray) -> list[dict[str, Any]]:
    if "town" not in X_test.columns:
        return []
    tw = X_test["town"].astype(str)
    r = np.asarray(y_act, dtype=float).ravel() - np.asarray(y_pred, dtype=float).ravel()
    rows: list[dict[str, Any]] = []
    for cat in tw.dropna().unique():
        m = (tw.values == cat) & np.isfinite(r)
        if int(m.sum()) < 5:
            continue
        rr = r[m]
        rows.append(
            {
                "town": str(cat),
                "n": int(m.sum()),
                "residual_mean": float(np.mean(rr)),
                "residual_std": float(np.std(rr)),
                "residual_p95_abs": float(np.percentile(np.abs(rr), 95)),
            }
        )
    rows.sort(key=lambda x: -x["n"])
    return rows[:25]


def _by_flat_type_residuals(X_test: pd.DataFrame, y_act: np.ndarray, y_pred: np.ndarray) -> list[dict[str, Any]]:
    if "flat_type" not in X_test.columns:
        return []
    ft = X_test["flat_type"].astype(str)
    r = np.asarray(y_act, dtype=float).ravel() - np.asarray(y_pred, dtype=float).ravel()
    rows: list[dict[str, Any]] = []
    for cat in ft.dropna().unique():
        m = (ft.values == cat) & np.isfinite(r)
        if int(m.sum()) < 5:
            continue
        rr = r[m]
        rows.append(
            {
                "flat_type": str(cat),
                "n": int(m.sum()),
                "residual_mean": float(np.mean(rr)),
                "residual_std": float(np.std(rr)),
                "residual_p95_abs": float(np.percentile(np.abs(rr), 95)),
            }
        )
    rows.sort(key=lambda x: -x["n"])
    return rows[:25]


def _price_tier_calibration(y_act: np.ndarray, y_pred: np.ndarray) -> list[dict[str, Any]]:
    y = pd.Series(np.asarray(y_act, dtype=float).ravel())
    p = pd.Series(np.asarray(y_pred, dtype=float).ravel())
    mask = y.notna() & p.notna() & np.isfinite(y.to_numpy()) & np.isfinite(p.to_numpy())
    y = y[mask]
    p = p[mask]
    if len(y) < 30:
        return []
    try:
        tiers = pd.qcut(y.rank(method="first"), q=3, labels=["low", "mid", "high"], duplicates="drop")
    except ValueError:
        return []
    out: list[dict[str, Any]] = []
    for label in ("low", "mid", "high"):
        try:
            sel = tiers == label
        except Exception:
            continue
        if not sel.any():
            continue
        yy = y[sel].to_numpy(dtype=float)
        pp = p[sel].to_numpy(dtype=float)
        over = float(np.mean(pp > yy))
        under = float(np.mean(pp < yy))
        out.append({"tier": str(label), "n": int(sel.sum()), "over_predict_rate": over, "under_predict_rate": under})
    return out


def _cv_fold_rmse_lists(search: GridSearchCV | RandomizedSearchCV, cv_splits: int) -> tuple[list[float | None], list[float | None]]:
    """Per-fold negative-RMSE scores → RMSE for best estimator (test and train)."""
    test_out: list[float | None] = []
    train_out: list[float | None] = []
    cr = getattr(search, "cv_results_", None) or {}
    bi = int(search.best_index_)

    def _one_fold_rmse(split_key: str) -> float | None:
        if split_key not in cr:
            return None
        row = cr[split_key]
        try:
            score = row[bi]
            if score is None or (isinstance(score, float) and math.isnan(score)):
                return None
            return round(float(-score), 4)
        except Exception:
            return None

    for i in range(int(cv_splits)):
        test_out.append(_one_fold_rmse(f"split{i}_test_score"))
        train_out.append(_one_fold_rmse(f"split{i}_train_score"))
    return test_out, train_out


def _best_params_plain(best_params: dict[str, Any]) -> dict[str, Any]:
    """JSON-serializable hyperparameters for reports."""

    def _conv(v: Any) -> Any:
        if v is None or isinstance(v, (bool, str)):
            return v
        if isinstance(v, (int, float)) and math.isfinite(float(v)):
            return int(v) if isinstance(v, int) or (isinstance(v, float) and float(v).is_integer()) else float(v)
        try:
            import numpy as np

            if isinstance(v, (np.integer,)):
                return int(v)
            if isinstance(v, (np.floating,)):
                x = float(v)
                return x if math.isfinite(x) else str(v)
            if isinstance(v, np.ndarray):
                return v.tolist()
        except Exception:
            pass
        return str(v)

    return {str(k): _conv(v) for k, v in best_params.items()}


def _save_missingness_chart(raw_df: pd.DataFrame, out_png: Path, *, top_n: int = 45) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    if raw_df.shape[1] == 0:
        return
    miss = raw_df.isna().mean().sort_values(ascending=False).head(top_n)
    if miss.empty:
        return
    cols = list(miss.index)
    subset = raw_df.loc[:, cols]
    try:
        from modelling.eda.profile import configure_plot_style, plot_missingness

        configure_plot_style()
        plot_missingness(subset, save_path=str(out_png))
    except Exception:
        plt.close("all")


def train_from_frame(
    exp: Experiment,
    raw_df: pd.DataFrame,
    project_root: Path,
    out_dir: Path,
    *,
    loader_meta: dict[str, Any] | None = None,
    data_quality_summary: dict[str, Any] | None = None,
    dataset_version: str | None = None,
    engineered_preview_df: pd.DataFrame | None = None,
    feature_selection_policy: str | None = None,
) -> dict[str, Any]:
    """Fit experiment pipeline, write artefacts under ``out_dir``, return diagnostics dict."""
    t_train_wall_0 = time.perf_counter()
    dv = dataset_version or (loader_meta or {}).get("dataset_version") or ""
    log_phase(
        tlog,
        "train_start",
        experiment_id=exp.id,
        feature_set_id=exp.feature_set_id,
        model_id=exp.model_id,
        rows=len(raw_df),
        cols=len(raw_df.columns),
        dataset_version=dv or None,
        cuda_xgboost=bool(exp.model_id == "xgboost_tuned_gpu"),
    )

    data_profile_pre_filter: dict[str, Any] | None = None
    if exp.flat_type_scope != "all":
        data_profile_pre_filter = _compute_data_profile(raw_df)
    raw_df, flat_type_filter_audit = apply_flat_type_scope(raw_df, exp.flat_type_scope)
    rows_after_ft = int(flat_type_filter_audit.get("rows_after", len(raw_df)))
    if rows_after_ft == 0:
        raise RuntimeError("flat_type_scope filtering removed all rows; check flat_type column and scope")
    if flat_type_filter_audit.get("applied"):
        log_phase(
            tlog,
            "flat_type_scope_filtered",
            scope=flat_type_filter_audit.get("scope"),
            rows_before=flat_type_filter_audit.get("rows_before"),
            rows_after=rows_after_ft,
            rows_dropped=flat_type_filter_audit.get("rows_dropped"),
            pct_kept=flat_type_filter_audit.get("pct_kept"),
        )

    fs = copy(get_feature_set(project_root, exp.feature_set_id))
    fs.engineer_kwargs = {
        **dict(fs.engineer_kwargs),
        **exp.extra_engineer_kwargs,
        "project_root": project_root,
    }

    X_train, X_test, y_train, y_test = make_temporal_split(
        raw_df, target_column=TARGET_COLUMN, test_fraction=exp.test_fraction
    )
    n_train_before_cap = int(len(X_train))
    X_train, y_train = restrict_training_window(X_train, y_train, exp.max_train_rows)
    rpi_levels_df, rpi_source_label = load_rpi_index_series(project_root)
    if rpi_levels_df.empty:
        raise RuntimeError(
            "No HDB RPI levels loaded — ingest ``hdb_resale_price_index`` (backend/scripts/ingest_hdb_rpi.py) "
            "or provide MinIO manifest key macro_rpi_csv / network access to data.gov.sg."
        )
    if "month" not in X_train.columns or "month" not in X_test.columns:
        raise RuntimeError("RPI target normalization requires ``month`` on resale rows.")

    rpi_train = align_rpi_index_to_months(X_train["month"], rpi_levels_df)
    rpi_test = align_rpi_index_to_months(X_test["month"], rpi_levels_df)
    validate_rpi_alignment(rpi_train, context="train_rpi_alignment")
    validate_rpi_alignment(rpi_test, context="test_rpi_alignment")

    y_train_adj = pd.Series(
        adjust_prices_to_baseline100(y_train.to_numpy(dtype=float), rpi_train),
        index=y_train.index,
        name=TARGET_COLUMN_TRAIN_ADJUSTED,
    )

    n_train_after_cap = int(len(X_train))
    month_train_min = month_train_max = month_test_min = month_test_max = None
    if "month" in X_train.columns and n_train_after_cap:
        month_train_min = str(X_train["month"].min())
        month_train_max = str(X_train["month"].max())
    if "month" in X_test.columns and len(X_test):
        month_test_min = str(X_test["month"].min())
        month_test_max = str(X_test["month"].max())
    log_phase(
        tlog,
        "temporal_split",
        n_train=n_train_after_cap,
        n_test=int(len(X_test)),
        month_train_min=month_train_min,
        month_train_max=month_train_max,
        month_test_min=month_test_min,
        month_test_max=month_test_max,
    )
    if exp.max_train_rows and n_train_before_cap > n_train_after_cap:
        log_phase(
            tlog,
            "row_cap_applied",
            n_train_before=n_train_before_cap,
            n_train_after=n_train_after_cap,
            max_train_rows=exp.max_train_rows,
        )

    fs_policy = resolve_feature_selection_policy(cli_value=feature_selection_policy)
    numeric_before_apply: list[str] | None = None
    features_removed_apply: list[str] = []
    applied_drops = False
    diag_mask_true_count: int | None = None
    recommended_drop_count: int | None = None

    out_dir.mkdir(parents=True, exist_ok=True)
    eng_train: pd.DataFrame | None = None
    eng_train_columns_sorted: list[str] | None = None
    eng_train_nrows: int | None = None
    log_phase(tlog, "prefit_feature_selection_start")
    try:
        ek_fs = dict(fs.engineer_kwargs)
        ek_fs["project_root"] = project_root
        eng_train = fs.engineer(X_train.copy(), **ek_fs)
        eng_train_columns_sorted = sorted(map(str, eng_train.columns))
        eng_train_nrows = int(len(eng_train))
        row_mask = diagnostic_row_mask(X_train, y_train_adj, feature_set_id=exp.feature_set_id)
        diag_mask_true_count = int(row_mask.sum())
        numeric_before_apply = list(fs.numeric_features)
        write_feature_selection_artifacts(
            out_dir,
            eng_train,
            y_train_adj,
            row_mask=row_mask,
            registered_numeric=numeric_before_apply,
            write_features_dropped_json=True,
            features_dropped_extra={
                "feature_set_id": exp.feature_set_id,
                "n_train_rows": int(len(X_train)),
                "feature_selection_policy": fs_policy,
            },
            random_state=exp.random_state,
        )
        fd_path = out_dir / "features_dropped.json"
        fd = json.loads(fd_path.read_text(encoding="utf-8"))
        fd["numeric_features_before_apply"] = numeric_before_apply
        if fs_policy == APPLY_RECOMMENDED_DROPS:
            drops_set = set(fd.get("dropped") or [])
            features_removed_apply, applied_drops = apply_numeric_feature_drops(fs, drops_set)
            fd["applied_to_pipeline"] = applied_drops
            fd["columns_removed"] = features_removed_apply
        else:
            fd["applied_to_pipeline"] = False
            fd["columns_removed"] = []
        fd["numeric_features_after_apply"] = list(fs.numeric_features)
        fd_path.write_text(json.dumps(fd, indent=2), encoding="utf-8")
        recommended_drop_count = len(fd.get("dropped") or [])

        plots_dir_fs = out_dir / "plots"
        plots_dir_fs.mkdir(parents=True, exist_ok=True)
        try:
            vr_doc = json.loads((out_dir / "feature_variance.json").read_text(encoding="utf-8"))
            mi_doc = json.loads((out_dir / "feature_mi_scores.json").read_text(encoding="utf-8"))
            corr_doc = json.loads((out_dir / "correlated_pairs.json").read_text(encoding="utf-8"))
            write_feature_selection_plot_pngs(
                plots_dir=plots_dir_fs,
                variance_doc=vr_doc,
                mi_doc=mi_doc,
                correlated_pairs_doc=corr_doc,
            )
        except Exception:
            logger.exception("feature_selection plot PNGs skipped")
        log_phase(
            tlog,
            "prefit_feature_selection_done",
            engineered_cols=len(eng_train.columns),
            policy=fs_policy,
            diagnostic_rows=diag_mask_true_count,
            drops_applied=applied_drops,
        )
    except Exception:
        logger.exception("Pre-fit feature_selection artefacts skipped")
        log_phase(tlog, "prefit_feature_selection_skipped")
        if fs_policy != ADVISORY_ONLY:
            logger.warning("feature_selection_policy=%s but diagnostics failed; training continues advisory-only", fs_policy)

    ek_search = dict(fs.engineer_kwargs)
    ek_search["project_root"] = project_root
    if eng_train is None:
        eng_train = fs.engineer(X_train.copy(), **ek_search)
    eng_test = fs.engineer(X_test.copy(), **ek_search)

    ms = get_model_spec(project_root, exp.model_id, random_state=exp.random_state)
    pipe = build_preprocessor_only_pipeline(fs, ms)
    log_phase(
        tlog,
        "pipeline_built",
        n_numeric=len(fs.numeric_features),
        n_categorical=len(fs.categorical_features),
        search_kind=ms.search_kind,
    )

    data_quality_summary = (
        append_post_split_to_quality_summary(
            dict(data_quality_summary),
            n_train=int(len(X_train)),
            n_test=int(len(X_test)),
            project_root=project_root,
        )
        if data_quality_summary is not None
        else None
    )
    if data_quality_summary is not None:
        gates_ok = bool(data_quality_summary.get("gates_passed", False))
        pillars_failed = [
            str(p.get("pillar", "?"))
            for p in (data_quality_summary.get("pillar_results") or [])
            if not p.get("passed")
        ]
        log_phase(
            tlog,
            "data_quality_gates",
            gates_passed=gates_ok,
            pillars_failed=",".join(pillars_failed) if pillars_failed else None,
        )
        if not gates_ok:
            from modelling.data.quality import DataQualityError as _DQE

            fail_msgs: list[str] = []
            for p in data_quality_summary.get("pillar_results", []) or []:
                if not p.get("passed"):
                    pillar = str(p.get("pillar", "?"))
                    fail_msgs.extend([f"[{pillar}] {f}" for f in (p.get("failures") or [])])
            raise _DQE("Post-split data quality gates failed: " + ("; ".join(fail_msgs) or "gates_passed=false"))

    cv = TimeSeriesSplit(n_splits=exp.cv_splits)
    cv_n_jobs = _cv_n_jobs()
    n_iter = None if ms.search_kind == "grid" else (
        exp.search_iter_override if exp.search_iter_override is not None else (ms.search_iter or 8)
    )
    _cv_scorer = make_nominal_rmse_scorer(rpi_levels_df)

    if ms.search_kind == "grid":
        search = GridSearchCV(
            estimator=pipe,
            param_grid=ms.param_grid,
            scoring=_cv_scorer,
            n_jobs=cv_n_jobs,
            cv=cv,
            refit=True,
            return_train_score=True,
            error_score="raise",
            verbose=1,
        )
    else:
        assert n_iter is not None
        search = RandomizedSearchCV(
            estimator=pipe,
            param_distributions=ms.param_grid,
            n_iter=n_iter,
            random_state=exp.random_state,
            scoring=_cv_scorer,
            n_jobs=cv_n_jobs,
            cv=cv,
            refit=True,
            return_train_score=True,
            error_score="raise",
            verbose=1,
        )

    log_phase(
        tlog,
        "hyperparameter_search_start",
        search_kind=ms.search_kind,
        cv_splits=exp.cv_splits,
        n_iter=n_iter,
        n_jobs=cv_n_jobs,
    )
    y_train_fit = _align_target_to_engineered(
        eng_train,
        y_train_adj,
        raw_row_count=len(X_train),
        context="train",
    )
    t_fit_0 = time.perf_counter()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ConvergenceWarning)
        search.fit(eng_train, y_train_fit)
    fit_elapsed_s = round(time.perf_counter() - t_fit_0, 3)
    best_cv_rmse = float(-search.best_score_)
    bp_preview = _best_params_plain(dict(search.best_params_))
    preview_items = list(bp_preview.items())[:8]
    log_phase(
        tlog,
        "hyperparameter_search_done",
        best_cv_rmse=round(best_cv_rmse, 4),
        fit_elapsed_s=fit_elapsed_s,
        best_params_preview=str(dict(preview_items)),
        cv_target_space=(
            "Nominal SGD RMSE (CV matches test_metrics; per-fold rescale from month + RPI levels)"
        ),
    )

    best_partial = search.best_estimator_

    training_matrix_audit: dict[str, Any] | None = None
    try:
        pre = best_partial.named_steps["preprocessor"]
        pipe_names = [str(x) for x in pre.get_feature_names_out()]
        (out_dir / "pipeline_feature_names.json").write_text(
            json.dumps({"feature_names_out": pipe_names}, indent=2),
            encoding="utf-8",
        )
        n_pipe = len(pipe_names)
        names_head = pipe_names[:24]
        if n_pipe <= 24:
            names_tail: list[str] = []
        elif n_pipe <= 48:
            names_tail = pipe_names[24:]
        else:
            names_tail = pipe_names[-24:]
        raw_cols = sorted(map(str, X_train.columns))
        reg_num = [str(x) for x in fs.numeric_features]
        reg_cat = [str(x) for x in fs.categorical_features]
        eng_cols = eng_train_columns_sorted or []
        eng_set = set(eng_cols)
        reg_warnings: list[str] = []
        for c in reg_num + reg_cat:
            if c not in eng_set:
                reg_warnings.append(f"registered_not_in_engineered:{c}")
        for pname in pipe_names:
            ps = str(pname)
            if ps.startswith("flat_type") and "flat_type_encoded" not in ps:
                reg_warnings.append(f"unexpected_flat_type_onehot_in_pipeline:{ps}")
        training_matrix_audit = {
            "feature_selection_policy": fs_policy,
            "feature_selection": {
                "diagnostic_row_mask_true_count": diag_mask_true_count,
                "n_train_rows": int(len(X_train)),
                "recommended_drop_count": recommended_drop_count,
                "applied_to_pipeline": applied_drops,
                "columns_removed": features_removed_apply,
                "numeric_features_before_apply": numeric_before_apply,
                "numeric_features_after_apply": [str(x) for x in fs.numeric_features],
            },
            "raw_split_input": {
                "n_rows": int(len(X_train)),
                "n_columns": len(raw_cols),
                "columns": raw_cols,
            },
            "engineered": {
                "n_rows": eng_train_nrows,
                "n_columns": len(eng_cols),
                "columns": eng_cols,
            },
            "registered_feature_set": {
                "numeric_features": reg_num,
                "categorical_features": reg_cat,
                "n_numeric": len(reg_num),
                "n_categorical": len(reg_cat),
            },
            "preprocessor_output": {
                "n_features_out": n_pipe,
                "feature_names_head": names_head,
                "feature_names_tail": names_tail,
            },
            "model_encoding": {
                "flat_type": {
                    "raw_column_eda_only": "flat_type",
                    "model_column": "flat_type_encoded",
                    "encoding": "ordinal_1_7",
                },
            },
            "engineered_vs_registry_warnings": reg_warnings,
        }
    except Exception:
        logger.exception("training_matrix_audit / pipeline_feature_names skipped")

    y_pred_adj = best_partial.predict(eng_test)
    y_pred = np.asarray(
        rescale_adjusted_to_nominal(np.asarray(y_pred_adj, dtype=float), rpi_test),
        dtype=float,
    )

    metrics = evaluate_regression_model(y_test, y_pred)
    if isinstance(metrics, dict):
        log_phase(
            tlog,
            "test_evaluation",
            rmse=metrics.get("rmse"),
            mae=metrics.get("mae"),
            r2=metrics.get("r2"),
        )

    log_phase(tlog, "artefacts_writing", out_dir=str(out_dir.resolve()))
    plots = out_dir / "plots"
    plots.mkdir(exist_ok=True)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_test, y_pred, s=8, alpha=0.2)
    lims = [min(y_test.min(), y_pred.min()), max(y_test.max(), y_pred.max())]
    ax.plot(lims, lims, "k--")
    ax.set_xlabel("Actual")
    ax.set_ylabel("Predicted")
    ax.set_title(f"{exp.id} — preds vs actual")
    fig.tight_layout()
    fig.savefig(plots / "preds_vs_actual.png", dpi=120)
    plt.close(fig)

    resid = y_test.values - y_pred
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(resid, bins=50, color="#bc6c25", alpha=0.85)
    ax.set_title("Residuals (actual - pred)")
    fig.tight_layout()
    fig.savefig(plots / "residuals.png", dpi=120)
    plt.close(fig)

    best_full = wrap_pipeline_with_feature_engineering(best_partial, fs, project_root)

    joblib.dump(best_full, out_dir / "model.pkl")

    fi_path = plots / "feature_importance.png"
    top_imp_pairs: list[tuple[str, float]] = []
    try:
        fitted = best_partial.named_steps["model"].regressor_
        if hasattr(fitted, "feature_importances_"):
            pre = best_partial.named_steps["preprocessor"]
            names = pre.get_feature_names_out()
            imp = pd.Series(fitted.feature_importances_, index=names).nlargest(20)
            top_imp_pairs = [(str(k), float(v)) for k, v in imp.items()]
            fig, ax = plt.subplots(figsize=(8, 6))
            imp.sort_values().plot(kind="barh", ax=ax, color="#3498db")
            ax.set_title("Feature importance (top 20)")
            fig.tight_layout()
            fig.savefig(fi_path, dpi=120)
            plt.close(fig)
    except Exception:
        if fi_path.is_file():
            fi_path.unlink()

    def _perm_scorer(est: Any, X_eng: pd.DataFrame, y_ref: Any) -> float:
        y_adj_hat = np.asarray(est.predict(X_eng), dtype=float)
        y_nom_hat = np.asarray(rescale_adjusted_to_nominal(y_adj_hat, rpi_test), dtype=float)
        y_ref_arr = pd.Series(y_ref).astype(float).to_numpy(dtype=float)
        rmse = float(np.sqrt(mean_squared_error(y_ref_arr, y_nom_hat)))
        return -rmse

    try:
        perm = permutation_importance(
            best_partial,
            eng_test,
            y_test,
            n_repeats=10,
            random_state=exp.random_state,
            scoring=_perm_scorer,
            n_jobs=cv_n_jobs,
        )
        names = [str(c) for c in eng_test.columns]
        means = [float(x) for x in perm.importances_mean]
        stds = [float(x) for x in perm.importances_std]
        low = sorted(names[i] for i in range(len(names)) if means[i] <= 0)
        perm_doc: dict[str, Any] = {
            "scoring": "neg_root_mean_squared_error_nominal_price",
            "n_repeats": 10,
            "feature_names": names,
            "importances_mean": means,
            "importances_std": stds,
            "features_mean_le_zero": low,
        }
        (out_dir / "feature_permutation_importance.json").write_text(
            json.dumps(perm_doc, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Permutation importance artefact skipped")

    try:
        _save_missingness_chart(raw_df, plots / "missingness.png")
    except Exception:
        plt.close("all")

    feature_stats_full: dict[str, dict[str, Any]] = {}
    try:
        from modelling.data.quality import annotate_model_feature_stats, merge_raw_and_engineered_feature_stats

        eng_for_stats = eng_train if eng_train is not None and len(eng_train) else engineered_preview_df
        if eng_for_stats is not None:
            feature_stats_full = merge_raw_and_engineered_feature_stats(raw_df, eng_for_stats)
        else:
            feature_stats_full = compute_feature_stats_all_columns(raw_df)
        feature_stats_full = annotate_model_feature_stats(
            feature_stats_full,
            numeric_features=[str(x) for x in fs.numeric_features],
            categorical_features=[str(x) for x in fs.categorical_features],
        )
    except Exception:
        feature_stats_full = {}

    top_shap_features: list[dict[str, Any]] | None = None
    try:
        from modelling.training_shap import write_training_shap_artifacts

        sr = write_training_shap_artifacts(
            best_partial=best_partial,
            eng_frame=eng_test.copy(),
            plots_dir=plots,
            random_state=exp.random_state,
            max_rows=2000,
            top_n=20,
            feature_stats_full=feature_stats_full,
        )
        if sr:
            top_shap_features = sr
            log_phase(tlog, "training_shap_done", n_features=len(sr))
        else:
            log_phase(tlog, "training_shap_skipped")
    except Exception:
        logger.exception("training SHAP artefacts skipped")
        log_phase(tlog, "training_shap_skipped")

    lm = loader_meta or {}
    wall_elapsed_s = time.perf_counter() - t_train_wall_0
    training_context: dict[str, Any] = {
        "training_wall_seconds": round(float(wall_elapsed_s), 3),
        "flat_type_scope": exp.flat_type_scope,
        "flat_type_filter": flat_type_filter_audit,
        "mrt_pit_min_years": int(effective_mrt_pit_min_years(exp)),
        "test_fraction": float(exp.test_fraction),
        "cv_splits": int(exp.cv_splits),
        "max_train_rows": exp.max_train_rows,
        "training_source": str(lm.get("training_source") or ""),
        "from_db": bool(lm.get("from_db", True)),
        "dataset_path": str(lm.get("dataset_path", "")),
        "mrt_features_path": str(lm.get("mrt_features_path", "")),
        "masterplan_landuse_path": str(lm.get("masterplan_landuse_path", "")),
        "masterplan_source": str(lm.get("masterplan_source", "")),
        "merge_masterplan": bool(lm.get("merge_masterplan", False)),
        "min_tx_month": str(lm.get("min_tx_month", "") or ""),
        "dataset_version": dataset_version or lm.get("dataset_version") or "",
        "git_commit": os.getenv("GIT_COMMIT", ""),
        "app_version": os.getenv("APP_VERSION", ""),
        "target_normalization": TARGET_NORMALIZATION_RPI_BASELINE_100,
        "rpi_source": rpi_source_label,
        "train_target_adjusted_description": TARGET_COLUMN_TRAIN_ADJUSTED,
    }
    if "month" in raw_df.columns:
        training_context["dataset_month_min"] = str(raw_df["month"].min())
        training_context["dataset_month_max"] = str(raw_df["month"].max())
    if "month" in X_test.columns:
        training_context["temporal_split_first_test_month"] = str(X_test["month"].min())

    cv_fold_test, cv_fold_train = _cv_fold_rmse_lists(search, exp.cv_splits)
    training_context["cv_fold_rmse_list"] = cv_fold_test
    training_context["cv_fold_train_rmse_list"] = cv_fold_train

    median_test = None
    ts_train = _describe_target_series(y_train)
    ts_train_adj = _describe_target_series(y_train_adj)
    ts_test = _describe_target_series(y_test)
    if ts_test.get("median") is not None:
        median_test = float(ts_test["median"])

    rmse = metrics.get("rmse") if isinstance(metrics, dict) else None
    rmse_pct_median: float | None = None
    if median_test and rmse is not None:
        try:
            m = float(median_test)
            if m > 0:
                rmse_pct_median = round(100.0 * float(rmse) / m, 3)
        except (TypeError, ValueError):
            pass

    top_feature_importances: list[dict[str, Any]] = []
    for name, score in top_imp_pairs:
        st = feature_stats_full.get(name) if isinstance(feature_stats_full.get(name), dict) else {}
        nr = st.get("null_rate") if isinstance(st, dict) else None
        top_feature_importances.append(
            {"feature": name, "importance": score, "null_rate": float(nr) if nr is not None else None}
        )

    payload: dict[str, Any] = {
        "experiment_id": exp.id,
        "feature_set": exp.feature_set_id,
        "model": exp.model_id,
        "best_cv_rmse": float(-search.best_score_),
        "test_metrics": metrics,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "training_context": training_context,
        "target_normalization": TARGET_NORMALIZATION_RPI_BASELINE_100,
        "rpi_source": rpi_source_label,
        "train_target_adjusted_description": TARGET_COLUMN_TRAIN_ADJUSTED,
        "target_stats": {"train": ts_train, "train_adjusted_target": ts_train_adj, "test": ts_test},
        "data_profile": _compute_data_profile(raw_df),
        "feature_stats_full": feature_stats_full,
        "near_constant_numeric_columns": _near_constant_numeric_columns(raw_df),
        "residual_by_flat_type": _by_flat_type_residuals(X_test, y_test.values, y_pred),
        "residual_by_month": _by_month_residuals(X_test, y_test.values, y_pred),
        "residual_by_town": _by_town_residuals(X_test, y_test.values, y_pred),
        "residual_price_tier_calibration": _price_tier_calibration(y_test.values, y_pred),
        "performance_context": {
            "rmse_pct_of_test_median_price": rmse_pct_median,
            "best_cv_rmse_vs_test_rmse_ratio": (
                round(float(-search.best_score_) / float(rmse), 4)
                if rmse not in (None, 0) and search.best_score_ is not None
                else None
            ),
        },
        "top_feature_importances": top_feature_importances,
        "best_params_plain": _best_params_plain(dict(search.best_params_)),
    }
    if top_shap_features:
        payload["top_shap_features"] = top_shap_features
    if training_matrix_audit is not None:
        payload["training_matrix_audit"] = training_matrix_audit
    if data_quality_summary is not None:
        payload["data_quality_summary"] = data_quality_summary
    if data_profile_pre_filter is not None:
        payload["data_profile_pre_filter"] = data_profile_pre_filter
    (out_dir / "metrics.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (out_dir / "best_params.json").write_text(
        json.dumps({k: repr(v) for k, v in search.best_params_.items()}, indent=2),
        encoding="utf-8",
    )

    frozen = {
        "experiment": asdict(exp),
        "feature_set_description": fs.description,
        "model_display_name": ms.display_name,
        "dataset_rows": len(raw_df),
        "python": platform.python_version(),
        "target_normalization": TARGET_NORMALIZATION_RPI_BASELINE_100,
        "train_target_adjusted_description": TARGET_COLUMN_TRAIN_ADJUSTED,
        "rpi_source": rpi_source_label,
    }
    (out_dir / "config.json").write_text(json.dumps(frozen, indent=2, default=str), encoding="utf-8")

    raw_df.to_parquet(out_dir / "training_data.parquet", index=False)

    wall_total = round(time.perf_counter() - t_train_wall_0, 3)
    log_phase(
        tlog,
        "train_done",
        training_wall_seconds=wall_total,
        experiment_id=exp.id,
        metrics_path=str((out_dir / "metrics.json").resolve()),
        model_path=str((out_dir / "model.pkl").resolve()),
    )

    return {"metrics": metrics, "search": search, "estimator": best_full, "y_test": y_test, "y_pred": y_pred}
