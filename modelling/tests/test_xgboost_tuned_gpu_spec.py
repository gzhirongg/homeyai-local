"""xgboost_tuned_gpu uses CUDA device when XGBoost is installed."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    importlib.util.find_spec("xgboost") is None,
    reason="xgboost not installed",
)
def test_xgboost_tuned_gpu_spec_uses_cuda_device() -> None:
    from modelling.config.model_specs import get_model_spec

    ms = get_model_spec(_REPO_ROOT, "xgboost_tuned_gpu", random_state=42)
    assert ms.estimator.get_params().get("device") == "cuda"
    assert ms.estimator.get_params().get("tree_method") == "hist"
    assert ms.estimator.get_params().get("n_jobs") == 1
