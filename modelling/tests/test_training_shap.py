"""Batch SHAP helper used from ``train_core``."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def test_write_training_shap_artifacts_writes_png(tmp_path: Path) -> None:
    pytest.importorskip("shap")

    from modelling.training_shap import write_training_shap_artifacts

    rng = np.random.default_rng(0)
    n = 500
    X = pd.DataFrame({"x1": rng.normal(size=n), "x2": rng.normal(size=n)})
    y = rng.uniform(100_000.0, 500_000.0, size=n)

    pre = ColumnTransformer([("num", StandardScaler(), ["x1", "x2"])], remainder="drop")
    reg = RandomForestRegressor(n_estimators=20, random_state=0, max_depth=6)
    ttr = TransformedTargetRegressor(regressor=reg, func=np.log1p, inverse_func=np.expm1)
    best_partial = Pipeline([("preprocessor", pre), ("model", ttr)])
    best_partial.fit(X, y)

    plots = tmp_path / "plots"
    out = write_training_shap_artifacts(
        best_partial=best_partial,
        eng_frame=X,
        plots_dir=plots,
        random_state=42,
        max_rows=400,
        top_n=15,
        feature_stats_full={
            "x1": {"null_rate": 0.1},
            "x2": {"null_rate": 0.05},
        },
    )
    assert out is not None
    assert len(out) <= 15
    assert all("mean_abs_shap" in r and "feature" in r for r in out)

    png = plots / "shap_importance.png"
    assert png.is_file()
    assert png.stat().st_size > 200
