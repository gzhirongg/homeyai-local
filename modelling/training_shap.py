"""Batch SHAP for training transparency (mean |SHAP| over a holdout/engineered slice).

Mirrors explainer-class selection logic in ``backend/services/ml_service.compute_shap_top_features``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TREE_CLASS_NAMES = frozenset(
    {
        "XGBRegressor",
        "RandomForestRegressor",
        "ExtraTreesRegressor",
        "GradientBoostingRegressor",
        "LGBMRegressor",
    }
)
_LINEAR_CLASS_NAMES = frozenset({"LinearRegression", "Ridge"})


def write_training_shap_artifacts(
    *,
    best_partial: Any,
    eng_frame: Any,
    plots_dir: Path,
    random_state: int,
    max_rows: int = 2000,
    top_n: int = 20,
    feature_stats_full: dict[str, dict[str, Any]] | None = None,
    filename_png: str = "shap_importance.png",
) -> list[dict[str, Any]] | None:
    """Compute mean-|SHAP| on a sampled engineered frame (test split); save bar PNG.

    Uses ``best_partial.named_steps[\"preprocessor\"]`` + ``[\"model\"].regressor_`` (TransformedTargetRegressor inner).
    Returns rows for ``metrics.json`` ``top_shap_features``, or ``None`` on skip/failure.

    Null rates are joined from ``feature_stats_full`` by exact preprocessor-output name when possible
    (often matches engineered column naming for numeric features).
    """

    plots_dir = Path(plots_dir)
    plots_dir.mkdir(parents=True, exist_ok=True)
    png_path = plots_dir / filename_png

    try:
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        import shap

        df = pd.DataFrame(eng_frame)
        if len(df) < 2:
            logger.info("training_shap skipped: insufficient rows (%s)", len(df))
            if png_path.is_file():
                png_path.unlink(missing_ok=True)
            return None

        rng = np.random.default_rng(random_state)
        idx = rng.choice(df.index.values, size=min(max_rows, len(df)), replace=False)
        X_sub = df.loc[idx]

        pre = best_partial.named_steps["preprocessor"]
        model_step = best_partial.named_steps["model"]
        inner = getattr(model_step, "regressor_", None)
        if inner is None:
            logger.info("training_shap skipped: no inner regressor_")
            if png_path.is_file():
                png_path.unlink(missing_ok=True)
            return None

        X_t = pre.transform(X_sub)
        if hasattr(X_t, "toarray"):
            X_t = X_t.toarray()
        X_t = np.asarray(X_t, dtype=float)
        names = [str(x) for x in pre.get_feature_names_out()]

        explainer = None
        tn = inner.__class__.__name__
        if tn in _TREE_CLASS_NAMES:
            explainer = shap.TreeExplainer(inner)
        elif tn in _LINEAR_CLASS_NAMES:
            explainer = shap.LinearExplainer(inner, X_t)
        else:
            try:
                explainer = shap.TreeExplainer(inner)
            except Exception:
                logger.info("training_shap skipped: estimator %s not supported", tn)
                if png_path.is_file():
                    png_path.unlink(missing_ok=True)
                return None

        sv = explainer.shap_values(X_t)
        sv_arr = np.asarray(sv, dtype=float)
        if sv_arr.ndim == 1:
            sv_arr = sv_arr.reshape(-1, 1)
        if sv_arr.shape[1] != len(names):
            logger.warning(
                "training_shap skipped: shap shape %s vs n_features_out=%s",
                sv_arr.shape,
                len(names),
            )
            if png_path.is_file():
                png_path.unlink(missing_ok=True)
            return None

        mean_abs = np.mean(np.abs(sv_arr), axis=0)
        order = np.argsort(-mean_abs)[:top_n]

        fst = feature_stats_full if isinstance(feature_stats_full, dict) else {}
        rows: list[dict[str, Any]] = []
        for j in order:
            fname = names[int(j)]
            st = fst.get(fname) if isinstance(fst.get(fname), dict) else {}
            nr = st.get("null_rate")
            rows.append(
                {
                    "feature": fname,
                    "mean_abs_shap": float(mean_abs[int(j)]),
                    "null_rate": float(nr) if nr is not None else None,
                }
            )

        ma_top = np.array([r["mean_abs_shap"] for r in rows], dtype=float)
        labels = [str(r["feature"])[:52] for r in rows]

        fig, ax = plt.subplots(figsize=(8, max(3.5, 0.32 * len(labels))))
        idx_sort = np.argsort(ma_top)
        labels_s = [labels[i] for i in idx_sort]
        vals_s = [ma_top[i] for i in idx_sort]
        ax.barh(labels_s, vals_s, color="#8e44ad")
        ax.set_xlabel("Mean |SHAP| (test sample, adjusted-target model inner)")
        ax.set_title(f"SHAP attribution — top {len(rows)} features")
        fig.tight_layout()
        fig.savefig(png_path, dpi=120)
        plt.close(fig)

        return rows

    except Exception:
        logger.exception("training_shap failed")
        if png_path.is_file():
            try:
                png_path.unlink()
            except OSError:
                pass
        return None


__all__ = ["write_training_shap_artifacts"]
