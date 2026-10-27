"""Load pinned valuation sklearn Pipeline from MinIO and run inference + optional SHAP."""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.pipeline import Pipeline as SkPipeline

from modelling.targets.rpi_normalization import (
    TARGET_NORMALIZATION_RPI_BASELINE_100,
    rescale_adjusted_to_nominal,
    rpi_index_for_valuation_month,
)
from services import model_store

logger = logging.getLogger(__name__)

PROJECT_ROOT_FOR_RPI = Path(__file__).resolve().parents[2]

_pipeline: Any = None
_feature_set_id: str | None = None
_manifest_meta: dict[str, Any] = {}
_load_error: str | None = None
_model_object_key: str | None = None


def registered_feature_set_ids() -> frozenset[str]:
    """Valid ``feature_set_id`` values from modelling registry (lazy)."""
    root = Path(__file__).resolve().parents[2]
    try:
        from modelling.config.feature_sets import build_feature_set_registry

        return frozenset(build_feature_set_registry(root).keys())
    except Exception as exc:
        logger.warning("Could not load modelling feature-set registry (%s)", exc)
        return frozenset({"baseline_v1", "mrt_pit"})


def _load_pipeline_from_key(key: str) -> tuple[Any, str, dict[str, Any]]:
    """Download pipeline + sidecars from ``key``; return ``(pipeline, feature_set_id, manifest_meta)``.

    Raises:
        ValueError: Missing feature set, unsupported feature set, or empty configuration.
        RuntimeError: MinIO / deserialization failure.
    """
    try:
        pipe = model_store.load_joblib_from_object(key, use_cache=True)
    except Exception as exc:
        raise RuntimeError(f"Failed to load model from MinIO ({key}): {exc}") from exc

    manifest = model_store.load_json_sidecar_from_object_key(key, "manifest.json") or {}
    metrics_path_key = os.getenv("VALUATION_METRICS_OBJECT_KEY", "").strip()
    if metrics_path_key:
        try:
            raw = model_store.get_object_bytes(metrics_path_key)
            metrics = json.loads(raw.decode("utf-8"))
        except Exception:
            metrics = {}
    else:
        metrics = model_store.load_json_sidecar_from_object_key(key, "metrics.json") or {}

    fs = (
        (manifest.get("feature_set_id") or manifest.get("feature_set") or "")
        or (metrics.get("feature_set") or "")
    )
    fs = str(fs).strip()
    if not fs:
        raise ValueError("Sidecar manifest/metrics missing feature_set — inference disabled.")

    if fs not in registered_feature_set_ids():
        raise ValueError(
            f"Unsupported feature_set '{fs}' (registered: {sorted(registered_feature_set_ids())})."
        )

    tc = metrics.get("training_context") if isinstance(metrics.get("training_context"), dict) else {}
    meta = {
        "feature_set_id": fs,
        "experiment_id": manifest.get("experiment_id") or metrics.get("experiment_id"),
        "model_id": manifest.get("model_id") or metrics.get("model"),
        "model_object_key": key,
        "target_normalization": manifest.get("target_normalization")
        or metrics.get("target_normalization")
        or tc.get("target_normalization"),
        "rpi_source": manifest.get("rpi_source") or metrics.get("rpi_source") or tc.get("rpi_source"),
        "prediction_interval": manifest.get("prediction_interval"),
    }
    return pipe, fs, meta


def init(explicit_key: str | None = None) -> None:
    global _pipeline, _feature_set_id, _manifest_meta, _load_error, _model_object_key
    _pipeline = None
    _feature_set_id = None
    _manifest_meta = {}
    _load_error = None
    _model_object_key = None

    key = (explicit_key or os.getenv("VALUATION_MODEL_OBJECT_KEY") or "").strip()
    if not key:
        _load_error = "VALUATION_MODEL_OBJECT_KEY is not set — valuation model disabled."
        logger.error("%s", _load_error)
        return

    try:
        pipe, fs, meta = _load_pipeline_from_key(key)
    except ValueError as exc:
        _load_error = str(exc)
        logger.error("%s", _load_error)
        return
    except RuntimeError as exc:
        _load_error = str(exc)
        logger.exception("%s", _load_error)
        return

    _pipeline = pipe
    _feature_set_id = fs
    _manifest_meta = meta
    _model_object_key = key
    logger.info("Valuation model ready: %s feature_set=%s", key, fs)


def init_from_key(key: str) -> dict[str, Any]:
    """Hot-reload inference from an explicit MinIO object key (process memory only)."""
    global _pipeline, _feature_set_id, _manifest_meta, _load_error, _model_object_key
    key = key.strip()
    if not key:
        raise ValueError("object_key is empty.")

    model_store.clear_cache()

    try:
        pipe, fs, meta = _load_pipeline_from_key(key)
    except ValueError:
        raise
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc

    _pipeline = pipe
    _feature_set_id = fs
    _manifest_meta = meta
    _model_object_key = key
    _load_error = None
    logger.info("Valuation model promoted: %s feature_set=%s", key, fs)
    return {
        "feature_set_id": fs,
        "model_object_key": key,
        "experiment_id": meta.get("experiment_id"),
        "model_id": meta.get("model_id"),
        "target_normalization": meta.get("target_normalization"),
        "rpi_source": meta.get("rpi_source"),
    }


def model_object_key() -> str | None:
    return _model_object_key


def holdout_rmse_from_loaded_model() -> float | None:
    """RMSE from ``metrics.json`` sidecar for the in-memory model (holdout / test set)."""
    key = _model_object_key
    if not key:
        return None
    m = model_store.load_json_sidecar_from_object_key(key, "metrics.json") or {}
    tm = m.get("test_metrics") or {}
    r = tm.get("rmse")
    if r is None:
        return None
    try:
        return float(r)
    except (TypeError, ValueError):
        return None


def admin_serving_status() -> dict[str, Any]:
    """Payload for ``GET /api/admin/model/status``."""
    return {
        "is_ready": is_ready(),
        "feature_set_id": _feature_set_id,
        "experiment_id": _manifest_meta.get("experiment_id"),
        "model_id": _manifest_meta.get("model_id"),
        "target_normalization": _manifest_meta.get("target_normalization"),
        "rpi_source": _manifest_meta.get("rpi_source"),
        "model_object_key": _model_object_key,
        "load_error": _load_error,
    }


def is_ready() -> bool:
    return _pipeline is not None


def prediction_interval_payload(predicted_price: float) -> dict[str, Any]:
    """Use calibration belonging to the loaded model; identify legacy heuristics."""
    from modelling.evaluation.prediction_intervals import relative_interval_bounds

    calibration = _manifest_meta.get("prediction_interval")
    if isinstance(calibration, dict):
        bounds = relative_interval_bounds(predicted_price, calibration)
        return {"confidence_interval": bounds, "confidence_interval_method": calibration["method"],
                "interval_coverage": calibration["coverage"], "interval_calibration": calibration}
    return {"confidence_interval": [round(predicted_price * .9, 2), round(predicted_price * 1.1, 2)],
            "confidence_interval_method": "fixed_percentage_band"}


def load_error_message() -> str | None:
    return _load_error


def feature_set_id() -> str | None:
    return _feature_set_id


def requires_coordinates_for_inference() -> bool:
    """True when the fitted preprocessor ingests ``lat`` and ``lon`` as input features."""
    pipe = _pipeline
    if pipe is None:
        return False
    try:
        pre = pipe.named_steps.get("preprocessor")
        if pre is None:
            return False
        names = {str(x) for x in pre.get_feature_names_out()}
        return "lat" in names and "lon" in names
    except Exception:
        logger.debug("requires_coordinates_for_inference: preprocessor introspection failed", exc_info=True)
        return False


def manifest_meta() -> dict[str, Any]:
    return dict(_manifest_meta)


def predict_raw(raw_df: pd.DataFrame, *, valuation_month: str | None = None) -> float:
    if not _pipeline:
        raise RuntimeError(_load_error or "Model not loaded")
    pred_adj = float(_pipeline.predict(raw_df)[0])
    tn = (_manifest_meta or {}).get("target_normalization")
    if tn == TARGET_NORMALIZATION_RPI_BASELINE_100:
        vm = (valuation_month or "").strip() or pd.Timestamp.utcnow().strftime("%Y-%m")
        rpi_val, _src = rpi_index_for_valuation_month(
            vm,
            project_root=PROJECT_ROOT_FOR_RPI,
            database_url=None,
        )
        if rpi_val is None or not math.isfinite(float(rpi_val)) or float(rpi_val) <= 0:
            raise RuntimeError(
                "RPI rescale failed: no index for valuation month — ensure hdb_resale_price_index "
                "is ingested or macro_rpi_csv / data.gov.sg fallback is reachable."
            )
        return float(rescale_adjusted_to_nominal(pred_adj, float(rpi_val)))
    return pred_adj


def compute_shap_top_features(
    raw_df: pd.DataFrame, *, top_n: int = 10, valuation_month: str | None = None
) -> dict[str, Any] | None:
    """SHAP on the inner regressor (log1p price space) with SGD marginal impacts.

    The pipeline uses ``TransformedTargetRegressor`` with ``log1p`` on resale price;
    the fitted regressor therefore predicts ``log1p(price)``. SHAP values are in that
    same log space. ``contribution_sgd`` approximates marginal SGD movement from the
    training-set baseline price if only coordinate *i* added ``contribution_log`` to
    the baseline log prediction:
    ``expm1(expected_value_log1p + φ_i) - expm1(expected_value_log1p)``.

    When the model is RPI-normalized (``target_normalization == rpi_baseline_100``),
    ``baseline_price_sgd`` and ``contribution_sgd`` are rescaled to **nominal SGD**
    for ``valuation_month`` via ``price × RPI / 100`` — matching ``predict_raw`` so
    the UI compares baseline and predicted in the same unit system. Raw log-space
    SHAP (``contribution_log``, ``expected_value_log1p``) is unchanged.
    """
    if not _pipeline:
        return None
    try:
        import numpy as np
        import shap
    except ImportError:
        logger.warning("shap not installed — skipping SHAP")
        return None

    pipe = _pipeline
    if not isinstance(pipe, SkPipeline):
        return None

    try:
        fe = pipe.named_steps["feature_engineering"]
        pre = pipe.named_steps["preprocessor"]
        model_step = pipe.named_steps["model"]
    except Exception:
        return None

    try:
        X_eng = fe.transform(raw_df)
        X_t = pre.transform(X_eng)
        if hasattr(X_t, "toarray"):
            X_t = X_t.toarray()
        X_t = np.asarray(X_t, dtype=float)
        names = list(pre.get_feature_names_out())

        inner = model_step.regressor_
        explainer = None
        tn = inner.__class__.__name__
        if tn in {
            "XGBRegressor",
            "RandomForestRegressor",
            "ExtraTreesRegressor",
            "GradientBoostingRegressor",
            "LGBMRegressor",
        }:
            explainer = shap.TreeExplainer(inner)
        elif tn in {"LinearRegression", "Ridge"}:
            explainer = shap.LinearExplainer(inner, X_t)
        else:
            try:
                explainer = shap.TreeExplainer(inner)
            except Exception:
                return None

        sv = explainer.shap_values(X_t)
        sv_arr = np.asarray(sv)
        if sv_arr.ndim == 1:
            sv_row = sv_arr.astype(float)
        else:
            sv_row = sv_arr[0].astype(float)

        ev_flat = np.asarray(explainer.expected_value, dtype=float).ravel()
        if ev_flat.size == 0:
            return None
        expected_value_log1p = float(ev_flat[0])

        yhat_inner = inner.predict(X_t)
        yhat_flat = np.asarray(yhat_inner, dtype=float).ravel()
        predicted_log1p = float(yhat_flat[0])

        baseline_price_sgd = float(np.expm1(expected_value_log1p))
        contribution_sgd = np.expm1(expected_value_log1p + sv_row) - baseline_price_sgd

        # Rescale to nominal SGD when the model was trained on RPI-adjusted target,
        # so baseline_price_sgd is comparable to the nominal predicted_price returned
        # by predict_raw. Otherwise the UI mixes 2009-base SGD (baseline) with
        # nominal SGD (predicted), inflating the apparent "gap" by the RPI multiplier.
        tn = (_manifest_meta or {}).get("target_normalization")
        if tn == TARGET_NORMALIZATION_RPI_BASELINE_100:
            vm = (valuation_month or "").strip() or pd.Timestamp.utcnow().strftime("%Y-%m")
            rpi_val, _src = rpi_index_for_valuation_month(
                vm,
                project_root=PROJECT_ROOT_FOR_RPI,
                database_url=None,
            )
            if rpi_val is not None and math.isfinite(float(rpi_val)) and float(rpi_val) > 0:
                rpi_factor = float(rpi_val) / 100.0
                baseline_price_sgd = float(baseline_price_sgd * rpi_factor)
                contribution_sgd = contribution_sgd * rpi_factor

        eng_cols = set(X_eng.columns)
        cat_sources = sorted(
            ["town", "flat_model", "flat_model_grouped", "region"],
            key=len,
            reverse=True,
        )

        def _serialize_feature_value(val: Any) -> Any:
            if val is None:
                return None
            try:
                if pd.isna(val):
                    return None
            except (TypeError, ValueError):
                pass
            if isinstance(val, (np.integer, np.floating)):
                f = float(val)
                return None if np.isnan(f) else f
            if isinstance(val, float):
                return None if np.isnan(val) else val
            if isinstance(val, (int, bool)):
                return val
            s = str(val).strip()
            return s if s else None

        def _source_and_value(name: str) -> tuple[str | None, Any]:
            if name in eng_cols:
                return name, _serialize_feature_value(X_eng.iloc[0][name])
            for src in cat_sources:
                prefix = f"{src}_"
                if name.startswith(prefix):
                    return src, _serialize_feature_value(X_eng.iloc[0].get(src))
            return None, None

        pairs = sorted(
            zip(names, sv_row, contribution_sgd),
            key=lambda x: abs(float(x[1])),
            reverse=True,
        )[: int(top_n)]

        contributions = []
        for name, phi, sgd_part in pairs:
            src_col, feat_val = _source_and_value(str(name))
            contributions.append(
                {
                    "feature": str(name),
                    "contribution": float(phi),
                    "contribution_log": float(phi),
                    "contribution_sgd": float(sgd_part),
                    "source_column": src_col,
                    "feature_value": feat_val,
                }
            )

        return {
            "baseline": {
                "expected_value_log1p": expected_value_log1p,
                "price_sgd": baseline_price_sgd,
            },
            "predicted_log1p": predicted_log1p,
            "contributions": contributions,
        }
    except Exception:
        logger.exception("SHAP computation failed")
        return None
