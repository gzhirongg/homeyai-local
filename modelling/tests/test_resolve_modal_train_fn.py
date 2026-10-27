"""Modal train function resolution from Experiment.modal_profile."""

from __future__ import annotations

from pathlib import Path

from modelling.config.experiments import Experiment, resolve_modal_train_fn

_REPO = Path(__file__).resolve().parents[2]


def test_resolve_l40s_ignores_use_gpu_false() -> None:
    exp = Experiment(
        id="x",
        feature_set_id="mrt_pit__primary_school",
        model_id="xgboost_tuned_gpu",
        modal_profile="l40s",
    )
    assert resolve_modal_train_fn(exp, use_gpu=False) == "train_one_experiment_l40s_gen"


def test_resolve_t4_explicit_profile() -> None:
    exp = Experiment(
        id="x",
        feature_set_id="mrt_pit",
        model_id="xgboost_tuned",
        modal_profile="t4",
    )
    assert resolve_modal_train_fn(exp, use_gpu=False) == "train_one_experiment_gpu_gen"


def test_resolve_use_gpu_true_defaults_t4_path() -> None:
    exp = Experiment(
        id="x",
        feature_set_id="mrt_pit",
        model_id="xgboost_tuned",
    )
    assert resolve_modal_train_fn(exp, use_gpu=True) == "train_one_experiment_gpu_gen"


def test_resolve_cpu_default() -> None:
    exp = Experiment(
        id="x",
        feature_set_id="mrt_pit",
        model_id="xgboost_tuned",
    )
    assert resolve_modal_train_fn(exp, use_gpu=False) == "train_one_experiment_cpu_gen"


def test_registered_gpu_experiment_resolves_l40s() -> None:
    from modelling.config.experiments import get_experiment

    exp = get_experiment(_REPO, "xgboost_tuned_gpu__core35_y5__mrt_primary_school")
    assert exp.modal_profile == "l40s"
    assert resolve_modal_train_fn(exp, use_gpu=False) == "train_one_experiment_l40s_gen"


def test_registered_gpu_core35_full_stack_resolves_l40s() -> None:
    from modelling.config.experiments import get_experiment

    exp = get_experiment(_REPO, "xgboost_tuned_gpu__core35_y15__full_stack")
    assert exp.modal_profile == "l40s"
    assert resolve_modal_train_fn(exp, use_gpu=False) == "train_one_experiment_l40s_gen"
