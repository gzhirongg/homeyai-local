"""Registry + dataset cache keys for Experiment.mrt_pit_min_years."""

from __future__ import annotations

from pathlib import Path

from modelling.config.experiment_batches import (
    CORE35_LINEAR_MLP_FULL_STACK_WINDOW_GRID_V1,
    MODAL_L40S_CORE35_FULL_STACK_WINDOW_GRID_V1,
    MRT_PRIMARY_SCHOOL_WINDOW_GRID,
)
from modelling.config.experiments import (
    effective_mrt_pit_min_years,
    get_experiment,
    resolve_modal_train_fn,
)
from modelling.config.feature_modules import TAG_ESTATE_MATURITY, feature_modules_for_feature_set
from modelling.data.dataset_builder import dataset_cache_key


def test_y10_y15_y20_registered_and_distinct_cache_keys():
    root = Path(__file__).resolve().parents[2]
    from modelling.config.experiments import default_experiments

    reg = default_experiments(root)
    for y in (10, 15, 20):
        eid = f"xgboost__mrt_primary_school__y{y}"
        assert eid in reg
        exp = reg[eid]
        assert exp.feature_set_id == "mrt_pit__primary_school"
        assert exp.model_id == "xgboost"
        assert exp.mrt_pit_min_years == y

    k10 = dataset_cache_key("mrt_pit__primary_school", 10)
    k20 = dataset_cache_key("mrt_pit__primary_school", 20)
    assert k10 != k20


def test_effective_mrt_pit_min_years_prefers_experiment_field():
    root = Path(__file__).resolve().parents[2]
    exp = get_experiment(root, "xgboost__mrt_primary_school__y15")
    assert effective_mrt_pit_min_years(exp) == 15


def test_batch_window_grid_tuple():
    assert MRT_PRIMARY_SCHOOL_WINDOW_GRID == (
        "xgboost__mrt_primary_school__y10",
        "xgboost__mrt_primary_school__y15",
        "xgboost__mrt_primary_school__y20",
    )


def test_gpu_core35_full_stack_window_grid_registered():
    root = Path(__file__).resolve().parents[2]
    from modelling.config.experiments import default_experiments

    fs_id = "mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity"
    reg = default_experiments(root)
    expected_years = (5, 10, 15, 20)
    for eid, y in zip(MODAL_L40S_CORE35_FULL_STACK_WINDOW_GRID_V1, expected_years, strict=True):
        assert eid in reg
        exp = reg[eid]
        assert exp.feature_set_id == fs_id
        assert exp.model_id == "xgboost_tuned_gpu"
        assert exp.mrt_pit_min_years == y
        assert exp.flat_type_scope == "core_35"
        assert exp.modal_profile == "l40s"

    assert TAG_ESTATE_MATURITY in feature_modules_for_feature_set(fs_id)

    k5 = dataset_cache_key(fs_id, 5)
    k20 = dataset_cache_key(fs_id, 20)
    assert k5 != k20


def test_modal_l40s_core35_full_stack_window_grid_tuple():
    assert MODAL_L40S_CORE35_FULL_STACK_WINDOW_GRID_V1 == (
        "xgboost_tuned_gpu__core35_y5__full_stack",
        "xgboost_tuned_gpu__core35_y10__full_stack",
        "xgboost_tuned_gpu__core35_y15__full_stack",
        "xgboost_tuned_gpu__core35_y20__full_stack",
    )


def test_cpu_linear_mlp_core35_full_stack_window_grid_registered():
    root = Path(__file__).resolve().parents[2]
    from modelling.config.experiments import default_experiments

    fs_id = "mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity"
    reg = default_experiments(root)
    expected_years = (5, 10, 15, 20)
    linear_ids = [f"linear__core35_y{y}__full_stack" for y in expected_years]
    mlp_ids = [f"mlp__core35_y{y}__full_stack" for y in expected_years]

    for eid, y in zip(linear_ids, expected_years, strict=True):
        assert eid in reg
        exp = reg[eid]
        assert exp.feature_set_id == fs_id
        assert exp.model_id == "linear"
        assert exp.mrt_pit_min_years == y
        assert exp.flat_type_scope == "core_35"
        assert exp.modal_profile == "cpu"
        assert resolve_modal_train_fn(exp, use_gpu=False) == "train_one_experiment_cpu_gen"

    for eid, y in zip(mlp_ids, expected_years, strict=True):
        assert eid in reg
        exp = reg[eid]
        assert exp.feature_set_id == fs_id
        assert exp.model_id == "mlp"
        assert exp.mrt_pit_min_years == y
        assert exp.flat_type_scope == "core_35"
        assert exp.modal_profile == "cpu"
        assert resolve_modal_train_fn(exp, use_gpu=False) == "train_one_experiment_cpu_gen"

    k5 = dataset_cache_key(fs_id, 5)
    k20 = dataset_cache_key(fs_id, 20)
    assert k5 != k20


def test_core35_linear_mlp_full_stack_window_grid_tuple():
    assert CORE35_LINEAR_MLP_FULL_STACK_WINDOW_GRID_V1 == (
        "linear__core35_y5__full_stack",
        "linear__core35_y10__full_stack",
        "linear__core35_y15__full_stack",
        "linear__core35_y20__full_stack",
        "mlp__core35_y5__full_stack",
        "mlp__core35_y10__full_stack",
        "mlp__core35_y15__full_stack",
        "mlp__core35_y20__full_stack",
    )
