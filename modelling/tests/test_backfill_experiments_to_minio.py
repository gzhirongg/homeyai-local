"""Tests for MinIO experiment backfill run_id resolution."""

from __future__ import annotations

from pathlib import Path

from modelling.runners.backfill_experiments_to_minio import _canonical_experiment_run_id


def test_canonical_mrt_pit_baseline_linear() -> None:
    root = Path("/repo/modelling/experiments/mrt_pit_baselines__20260510T041602Z/linear")
    assert (
        _canonical_experiment_run_id(root, "linear__mrt_pit_run__20260510T041602Z")
        == "mrt_pit_baselines__20260510T041602Z__linear"
    )


def test_canonical_mrt_pit_baseline_random_forest() -> None:
    root = Path(
        "/repo/modelling/experiments/mrt_pit_baselines__20260510T041602Z/random_forest"
    )
    assert (
        _canonical_experiment_run_id(root, "legacy_fallback")
        == "mrt_pit_baselines__20260510T041602Z__random_forest"
    )


def test_fallback_when_not_baseline_nested() -> None:
    p = Path("/repo/modelling/experiments/full_xgb__20260510T041602Z")
    assert _canonical_experiment_run_id(p, "full_xgb__20260510T041602Z") == "full_xgb__20260510T041602Z"


def test_fallback_when_parent_not_mrt_prefix() -> None:
    p = Path("/repo/modelling/experiments/some_other__20260101/linear")
    assert _canonical_experiment_run_id(p, "linear__foo__20260101") == "linear__foo__20260101"
