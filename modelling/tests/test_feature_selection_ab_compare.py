"""Tests for modelling.feature_selection_ab_compare."""

from __future__ import annotations

from modelling.feature_selection_ab_compare import (
    metrics_row_for_compare,
    pair_latest_advisory_vs_apply,
    split_run_folder,
)


def test_split_run_folder():
    assert split_run_folder("xgboost_tuned__mrt__20250517T120000Z") == ("xgboost_tuned__mrt", "20250517T120000Z")
    assert split_run_folder("no_stamp_here") == ("no_stamp_here", None)


def test_metrics_row_for_compare():
    m = {
        "best_cv_rmse": 41000.0,
        "test_metrics": {"rmse": 42000.0},
        "training_context": {"dataset_version": "v2/foo"},
        "training_matrix_audit": {
            "feature_selection_policy": "apply_recommended_drops",
            "feature_selection": {
                "columns_removed": ["a", "b"],
                "applied_to_pipeline": True,
                "recommended_drop_count": 2,
            },
        },
    }
    r = metrics_row_for_compare(m, run_folder="xgboost_tuned__mrt__20250517T120000Z")
    assert r["logical_experiment_id"] == "xgboost_tuned__mrt"
    assert r["run_timestamp"] == "20250517T120000Z"
    assert r["feature_selection_policy"] == "apply_recommended_drops"
    assert r["test_rmse"] == 42000.0
    assert r["n_removed"] == 2
    assert r["applied_to_pipeline"] is True


def test_pair_latest_advisory_vs_apply():
    rows = [
        {
            "logical_experiment_id": "exp_a",
            "run_folder": "exp_a__20250102T000000Z",
            "run_timestamp": "20250102T000000Z",
            "feature_selection_policy": "advisory_only",
            "dataset_version": "snap1",
            "test_rmse": 100.0,
            "n_removed": 0,
            "applied_to_pipeline": False,
        },
        {
            "logical_experiment_id": "exp_a",
            "run_folder": "exp_a__20250103T000000Z",
            "run_timestamp": "20250103T000000Z",
            "feature_selection_policy": "advisory_only",
            "dataset_version": "snap1",
            "test_rmse": 99.0,
            "n_removed": 0,
            "applied_to_pipeline": False,
        },
        {
            "logical_experiment_id": "exp_a",
            "run_folder": "exp_a__20250104T000000Z",
            "run_timestamp": "20250104T000000Z",
            "feature_selection_policy": "apply_recommended_drops",
            "dataset_version": "snap1",
            "test_rmse": 98.0,
            "n_removed": 2,
            "applied_to_pipeline": True,
        },
    ]
    pairs = pair_latest_advisory_vs_apply(rows)
    assert len(pairs) == 1
    p = pairs[0]
    assert p["advisory_run"].endswith("20250103T000000Z")
    assert p["apply_run"].endswith("20250104T000000Z")
    assert p["test_rmse_delta_apply_minus_advisory"] == -1.0
