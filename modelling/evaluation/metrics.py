"""Metrics and target transforms shared by pipelines."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    r2_score,
)

LOG_TARGET_MAX = 15.0
RANDOM_STATE = 42
TARGET_COLUMN = "resale_price"


def target_log_transform(values: np.ndarray) -> np.ndarray:
    """Apply log1p to non-negative prices; used by TransformedTargetRegressor."""
    clipped = np.clip(np.asarray(values, dtype=float), a_min=0.0, a_max=None)
    return np.log1p(clipped)


def target_clipped_inverse(values: np.ndarray) -> np.ndarray:
    """Inverse of log1p with an upper clip at e^15 ≈ S$3.27M.

    Used for linear and MLP models to prevent runaway extrapolation.
    XGBoost uses ``target_plain_inverse`` instead (tree outputs are bounded by training range).
    """
    clipped = np.clip(np.asarray(values, dtype=float), a_min=0.0, a_max=LOG_TARGET_MAX)
    return np.expm1(clipped)


def target_plain_inverse(values: np.ndarray) -> np.ndarray:
    """Inverse of log1p without clipping; suitable for bounded models such as XGBoost."""
    return np.expm1(np.asarray(values, dtype=float))


def evaluate_regression_model(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "mape": float(mean_absolute_percentage_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }
