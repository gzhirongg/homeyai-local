"""Canonical experiment ID lists for scheduled / batch training.

Keep in sync with registered experiments in ``experiments.py``.
"""

from __future__ import annotations

# Performance-improvement plan (tuned XGBoost, Extra Trees, LightGBM, Ridge).
PERFORMANCE_PLAN_V1: tuple[str, ...] = (
    "xgboost__baseline",
    "xgboost__mrt",
    "xgboost_tuned__baseline",
    "xgboost_tuned__mrt",
    "xgboost_tuned__full_stack",
    "extra_trees__baseline",
    "extra_trees__mrt",
    "lightgbm__baseline",
    "lightgbm__mrt",
    "lightgbm__full_stack",
    "ridge__baseline",
    "ridge__mrt",
)

# Tuned XGBoost: baseline + MRT + land use + primary school (5y window; no macro).
MRT_LANDUSE_PRIMARY_SCHOOL_TUNED_V1: tuple[str, ...] = (
    "xgboost_tuned__mrt_landuse_primary_school",
)

# XGBoost + MRT + primary-school flags at 10 / 15 / 20 year rolling windows (see Experiment.mrt_pit_min_years).
MRT_PRIMARY_SCHOOL_WINDOW_GRID: tuple[str, ...] = (
    "xgboost__mrt_primary_school__y10",
    "xgboost__mrt_primary_school__y15",
    "xgboost__mrt_primary_school__y20",
)

# Targeted A/B: advisory_only vs apply_recommended_drops (Prefect batch `experiment_ids=`).
FEATURE_SELECTION_AB_V1: tuple[str, ...] = (
    "xgboost_tuned__mrt",
    "xgboost_tuned__full_stack",
    "lightgbm__full_stack",
    "xgboost_tuned__baseline",
)

# Pillar isolation ablations (macro vs masterplan vs MRT); compare to xgboost_tuned__mrt control.
PILLAR_ABLATION_V1: tuple[str, ...] = (
    "xgboost_tuned__macro_only",
    "xgboost_tuned__landuse_only",
    "xgboost_tuned__macro_mrt",
    "xgboost_tuned__macro_landuse",
    "xgboost_tuned__macro_landuse_mrt_apply",
)

# Tuned XGBoost on core 3/4/5 ROOM subset only (`flat_type_scope=core_35` experiments).
CORE35_XGBOOST_V1: tuple[str, ...] = (
    "xgboost__baseline__core35",
    "xgboost__mrt__core35",
    "xgboost_tuned__baseline__core35",
    "xgboost_tuned__mrt__core35",
    "xgboost_tuned__full_stack__core35",
)

# Matched four-arm pack lift test: MRT + primary school on core35, 5y window, land-use and/or estate.
CORE35_Y5_MRT_PRIMARY_SCHOOL_PACK_AB_V1: tuple[str, ...] = (
    "xgboost_tuned__core35_y5__mrt_primary_school",
    "xgboost_tuned__core35_y5__mrt_primary_school__landuse",
    "xgboost_tuned__core35_y5__mrt_primary_school__estate",
    "xgboost_tuned__core35_y5__mrt_primary_school__landuse_estate",
)

# Masterplan split: area-only vs proximity/scalars-only vs both (+ control).
CORE35_Y5_MASTERPLAN_AREA_PROXIMITY_AB: tuple[str, ...] = (
    "xgboost_tuned__core35_y5__mrt_primary_school",
    "xgboost_tuned__core35_y5__mrt_primary_school__masterplan_area",
    "xgboost_tuned__core35_y5__mrt_primary_school__masterplan_proximity",
    "xgboost_tuned__core35_y5__mrt_primary_school__masterplan_area_proximity",
)

# CUDA XGBoost on Modal L40S (see Experiment.modal_profile and ``train_one_experiment_l40s_gen``).
MODAL_L40S_XGBOOST_V1: tuple[str, ...] = (
    "xgboost_tuned_gpu__core35_y5__mrt_primary_school",
)

# Core35 L40S stack (MRT + macro + masterplan proximity + primary-school counts + estate) at 5/10/15/20y windows.
MODAL_L40S_CORE35_FULL_STACK_WINDOW_GRID_V1: tuple[str, ...] = (
    "xgboost_tuned_gpu__core35_y5__full_stack",
    "xgboost_tuned_gpu__core35_y10__full_stack",
    "xgboost_tuned_gpu__core35_y15__full_stack",
    "xgboost_tuned_gpu__core35_y20__full_stack",
)

# Core35 CPU linear + MLP on same full-stack feature set at 5/10/15/20y windows (Modal CPU path).
CORE35_LINEAR_MLP_FULL_STACK_WINDOW_GRID_V1: tuple[str, ...] = (
    "linear__core35_y5__full_stack",
    "linear__core35_y10__full_stack",
    "linear__core35_y15__full_stack",
    "linear__core35_y20__full_stack",
    "mlp__core35_y5__full_stack",
    "mlp__core35_y10__full_stack",
    "mlp__core35_y15__full_stack",
    "mlp__core35_y20__full_stack",
)

__all__ = [
    "CORE35_LINEAR_MLP_FULL_STACK_WINDOW_GRID_V1",
    "CORE35_XGBOOST_V1",
    "CORE35_Y5_MASTERPLAN_AREA_PROXIMITY_AB",
    "CORE35_Y5_MRT_PRIMARY_SCHOOL_PACK_AB_V1",
    "FEATURE_SELECTION_AB_V1",
    "MODAL_L40S_CORE35_FULL_STACK_WINDOW_GRID_V1",
    "MODAL_L40S_XGBOOST_V1",
    "MRT_LANDUSE_PRIMARY_SCHOOL_TUNED_V1",
    "MRT_PRIMARY_SCHOOL_WINDOW_GRID",
    "PERFORMANCE_PLAN_V1",
    "PILLAR_ABLATION_V1",
]
