"""Held-out relative-error intervals shared by local training and serving.

Calibration rows must not be used to fit the estimator. The finite-sample rank
is the split-conformal rank; chronological market data need not be exchangeable,
so later temporal coverage is reported rather than presented as a guarantee.
"""
from __future__ import annotations

import math
import numpy as np


def calibrate_relative_interval(y_true, y_pred, *, coverage: float = 0.9) -> dict:
    truth, predictions = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    if truth.ndim != 1 or predictions.shape != truth.shape or not len(truth):
        raise ValueError("Calibration requires equal nonempty one-dimensional arrays")
    if not (0 < coverage < 1) or not np.isfinite(truth).all() or not np.isfinite(predictions).all():
        raise ValueError("Invalid calibration values or coverage")
    if (truth <= 0).any() or (predictions <= 0).any():
        raise ValueError("Calibration prices must be positive")
    rank = math.ceil((len(truth) + 1) * coverage)
    if rank > len(truth):
        raise ValueError("Insufficient calibration rows for the requested coverage")
    scores = np.sort(np.abs(truth / predictions - 1))
    return {"method": "split_conformal_relative", "coverage": float(coverage),
            "relative_error_quantile": float(scores[rank - 1]), "calibration_count": len(truth)}


def relative_interval_bounds(prediction: float, calibration: dict) -> list[float]:
    radius = float(calibration["relative_error_quantile"])
    if not math.isfinite(prediction) or prediction <= 0 or not math.isfinite(radius) or radius < 0:
        raise ValueError("Invalid prediction or interval calibration")
    if calibration.get("method") != "split_conformal_relative" or not 0 < float(calibration["coverage"]) < 1:
        raise ValueError("Unsupported interval calibration")
    return [round(max(0.0, prediction * (1 - radius)), 2), round(prediction * (1 + radius), 2)]
