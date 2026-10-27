"""Named experiments = feature set + model + CV settings."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from modelling.data.flat_type_scope import FlatTypeScope

ModalProfile = Literal["cpu", "t4", "l40s"]


@dataclass(frozen=True)
class Experiment:
    id: str
    feature_set_id: str
    model_id: str
    description: str = ""
    test_fraction: float = 0.2
    cv_splits: int = 4
    max_train_rows: int | None = None
    rf_search_iter: int = 10
    nn_search_iter: int = 8
    random_state: int = 42
    # POI / parquet-only coordination paths (optional)
    merge_coords_csv: Path | None = None
    extra_engineer_kwargs: dict[str, Any] = field(default_factory=dict)
    # When set, overrides ModelSpec.search_iter for RandomizedSearchCV (Modal CPU timeout tuning).
    search_iter_override: int | None = None
    # Rolling resale window for SQL dataset build + metrics (overrides ``MRT_PIT_MIN_YEARS`` env when set).
    mrt_pit_min_years: int | None = None
    # Row filter applied before temporal split: ``core_35`` keeps 3/4/5 ROOM only (see ``apply_flat_type_scope``).
    flat_type_scope: FlatTypeScope = "all"
    # Prefect/Modal: which ``train_one_experiment_*_gen`` to invoke when ``MODAL_ENABLED=true``.
    modal_profile: ModalProfile = "cpu"


# Base experiment ids mirrored as ``{id}__core35`` (3/4/5 ROOM training subset).
CORE35_SOURCE_EXPERIMENT_IDS: tuple[str, ...] = (
    "xgboost__baseline",
    "xgboost__mrt",
    "xgboost_tuned__baseline",
    "xgboost_tuned__mrt",
    "xgboost_tuned__full_stack",
)


def effective_mrt_pit_min_years(exp: Experiment | None = None) -> int:
    """Training window years: experiment override, else ``MRT_PIT_MIN_YEARS`` env (default 5)."""
    from modelling.training_db import get_mrt_pit_min_years

    if exp is not None and exp.mrt_pit_min_years is not None:
        return int(exp.mrt_pit_min_years)
    return get_mrt_pit_min_years()


def resolve_modal_train_fn(exp: Experiment, *, use_gpu: bool) -> str:
    """Modal function name (streaming ``*_gen``) for this experiment and GPU flag.

    ``modal_profile=l40s`` always uses ``train_one_experiment_l40s_gen`` (CUDA class GPUs).
    ``use_gpu`` or ``modal_profile=t4`` uses legacy T4 ``train_one_experiment_gpu_gen``.
    """
    if exp.modal_profile == "l40s":
        return "train_one_experiment_l40s_gen"
    if exp.modal_profile == "t4" or use_gpu:
        return "train_one_experiment_gpu_gen"
    return "train_one_experiment_cpu_gen"


def default_experiments(project_root: Path) -> dict[str, Experiment]:
    root = project_root
    poi_coords = root / "data" / "pois" / "hdb_block_coords.csv"
    extras_poi = {}
    if poi_coords.is_file():
        extras_poi = {"merge_coords_csv": str(poi_coords)}

    experiments: dict[str, Experiment] = {
        "linear__baseline": Experiment(
            id="linear__baseline",
            feature_set_id="baseline_v1",
            model_id="linear",
            description="Linear regression on core HDB features (no MRT/POI).",
        ),
        "random_forest__baseline": Experiment(
            id="random_forest__baseline",
            feature_set_id="baseline_v1",
            model_id="random_forest",
            description="Random Forest baseline without MRT/POI.",
        ),
        "mlp__baseline": Experiment(
            id="mlp__baseline",
            feature_set_id="baseline_v1",
            model_id="mlp",
            description="MLP baseline without MRT/POI.",
        ),
        "xgboost__baseline": Experiment(
            id="xgboost__baseline",
            feature_set_id="baseline_v1",
            model_id="xgboost",
            description="XGBoost with TargetEncoder on high-card location fields.",
        ),
        "xgboost_tuned__baseline": Experiment(
            id="xgboost_tuned__baseline",
            feature_set_id="baseline_v1",
            model_id="xgboost_tuned",
            description="Wider XGBoost hyperparameter search on baseline.",
        ),
        "xgboost_tuned__mrt": Experiment(
            id="xgboost_tuned__mrt",
            feature_set_id="mrt_pit",
            model_id="xgboost_tuned",
            description="Wider XGBoost hyperparameter search + MRT.",
        ),
        "xgboost_tuned__macro_landuse_mrt": Experiment(
            id="xgboost_tuned__macro_landuse_mrt",
            feature_set_id="baseline_v1__macro__masterplan_landuse_pit__mrt_pit",
            model_id="xgboost_tuned",
            description="Tuned XGBoost: baseline + MRT + macro + land use (5y window via MRT_PIT_MIN_YEARS).",
            search_iter_override=12,
        ),
        "xgboost_tuned__mrt_landuse_primary_school": Experiment(
            id="xgboost_tuned__mrt_landuse_primary_school",
            feature_set_id="mrt_pit__masterplan_landuse_pit__primary_school",
            model_id="xgboost_tuned",
            description=(
                "Tuned XGBoost: baseline + MRT + masterplan land use + top-20 primary school annulus counts; "
                "5-year rolling window (no macro)."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
        ),
        "xgboost_tuned__core35_y5__mrt_primary_school": Experiment(
            id="xgboost_tuned__core35_y5__mrt_primary_school",
            feature_set_id="mrt_pit__primary_school",
            model_id="xgboost_tuned",
            description=(
                "Core 3/4/5 ROOM, 5-year MRT window: tuned XGBoost + MRT + primary-school annulus counts only "
                "(control arm for land-use / estate pack A/B; no macro)."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
        ),
        "xgboost_tuned_gpu__core35_y5__mrt_primary_school": Experiment(
            id="xgboost_tuned_gpu__core35_y5__mrt_primary_school",
            feature_set_id="mrt_pit__primary_school",
            model_id="xgboost_tuned_gpu",
            description=(
                "Core 3/4/5 ROOM, 5-year window: CUDA tuned XGBoost + MRT + primary-school annulus counts on Modal L40S "
                "(``modal_profile=l40s``; use_gpu body flag not required). "
                "Wall-clock not directly comparable to CPU ``xgboost_tuned``."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
            modal_profile="l40s",
        ),
        "xgboost_tuned_gpu__core35_y5__full_stack": Experiment(
            id="xgboost_tuned_gpu__core35_y5__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="xgboost_tuned_gpu",
            description=(
                "Core 3/4/5 ROOM, 5-year window: CUDA tuned XGBoost on Modal L40S — MRT + macro + masterplan "
                "proximity (no area_*; POI distances excluded) + top-20 primary-school count columns + estate "
                "maturity; no sale_year in model inputs (month sin/cos retained). See feature set docstring."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
            modal_profile="l40s",
        ),
        "xgboost_tuned_gpu__core35_y10__full_stack": Experiment(
            id="xgboost_tuned_gpu__core35_y10__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="xgboost_tuned_gpu",
            description=(
                "Core 3/4/5 ROOM, 10-year window: same stack as ``xgboost_tuned_gpu__core35_y5__full_stack`` "
                "(proximity + estate + primary_school counts; no POI distance numerics; no sale_year)."
            ),
            mrt_pit_min_years=10,
            search_iter_override=12,
            flat_type_scope="core_35",
            modal_profile="l40s",
        ),
        "xgboost_tuned_gpu__core35_y15__full_stack": Experiment(
            id="xgboost_tuned_gpu__core35_y15__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="xgboost_tuned_gpu",
            description=(
                "Core 3/4/5 ROOM, 15-year window: same stack as ``xgboost_tuned_gpu__core35_y5__full_stack``."
            ),
            mrt_pit_min_years=15,
            search_iter_override=12,
            flat_type_scope="core_35",
            modal_profile="l40s",
        ),
        "xgboost_tuned_gpu__core35_y20__full_stack": Experiment(
            id="xgboost_tuned_gpu__core35_y20__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="xgboost_tuned_gpu",
            description=(
                "Core 3/4/5 ROOM, 20-year window: same stack as ``xgboost_tuned_gpu__core35_y5__full_stack``."
            ),
            mrt_pit_min_years=20,
            search_iter_override=12,
            flat_type_scope="core_35",
            modal_profile="l40s",
        ),
        "linear__core35_y5__full_stack": Experiment(
            id="linear__core35_y5__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="linear",
            description=(
                "Core 3/4/5 ROOM, 5-year window: CPU linear regression — MRT + macro + masterplan "
                "proximity (no area_*; POI distances excluded) + top-20 primary-school count columns + "
                "estate maturity; no sale_year in model inputs (month sin/cos retained). "
                "Wall-clock not comparable to L40S XGBoost."
            ),
            mrt_pit_min_years=5,
            flat_type_scope="core_35",
        ),
        "linear__core35_y10__full_stack": Experiment(
            id="linear__core35_y10__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="linear",
            description=(
                "Core 3/4/5 ROOM, 10-year window: same stack as ``linear__core35_y5__full_stack``."
            ),
            mrt_pit_min_years=10,
            flat_type_scope="core_35",
        ),
        "linear__core35_y15__full_stack": Experiment(
            id="linear__core35_y15__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="linear",
            description=(
                "Core 3/4/5 ROOM, 15-year window: same stack as ``linear__core35_y5__full_stack``."
            ),
            mrt_pit_min_years=15,
            flat_type_scope="core_35",
        ),
        "linear__core35_y20__full_stack": Experiment(
            id="linear__core35_y20__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="linear",
            description=(
                "Core 3/4/5 ROOM, 20-year window: same stack as ``linear__core35_y5__full_stack``."
            ),
            mrt_pit_min_years=20,
            flat_type_scope="core_35",
        ),
        "mlp__core35_y5__full_stack": Experiment(
            id="mlp__core35_y5__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="mlp",
            description=(
                "Core 3/4/5 ROOM, 5-year window: CPU MLP — MRT + macro + masterplan "
                "proximity (no area_*; POI distances excluded) + top-20 primary-school count columns + "
                "estate maturity; no sale_year in model inputs (month sin/cos retained). "
                "Wall-clock not comparable to L40S XGBoost."
            ),
            mrt_pit_min_years=5,
            flat_type_scope="core_35",
        ),
        "mlp__core35_y10__full_stack": Experiment(
            id="mlp__core35_y10__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="mlp",
            description=(
                "Core 3/4/5 ROOM, 10-year window: same stack as ``mlp__core35_y5__full_stack``."
            ),
            mrt_pit_min_years=10,
            flat_type_scope="core_35",
        ),
        "mlp__core35_y15__full_stack": Experiment(
            id="mlp__core35_y15__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="mlp",
            description=(
                "Core 3/4/5 ROOM, 15-year window: same stack as ``mlp__core35_y5__full_stack``."
            ),
            mrt_pit_min_years=15,
            flat_type_scope="core_35",
        ),
        "mlp__core35_y20__full_stack": Experiment(
            id="mlp__core35_y20__full_stack",
            feature_set_id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            model_id="mlp",
            description=(
                "Core 3/4/5 ROOM, 20-year window: same stack as ``mlp__core35_y5__full_stack``."
            ),
            mrt_pit_min_years=20,
            flat_type_scope="core_35",
        ),
        "xgboost_tuned__core35_y5__mrt_primary_school__landuse": Experiment(
            id="xgboost_tuned__core35_y5__mrt_primary_school__landuse",
            feature_set_id="mrt_pit__masterplan_landuse_pit__primary_school",
            model_id="xgboost_tuned",
            description=(
                "Core 3/4/5 ROOM, 5-year window: adds masterplan land-use PIT vs "
                "xgboost_tuned__core35_y5__mrt_primary_school (no macro)."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
        ),
        "xgboost_tuned__core35_y5__mrt_primary_school__estate": Experiment(
            id="xgboost_tuned__core35_y5__mrt_primary_school__estate",
            feature_set_id="mrt_pit__primary_school__estate_maturity",
            model_id="xgboost_tuned",
            description=(
                "Core 3/4/5 ROOM, 5-year window: adds estate-maturity panel vs "
                "xgboost_tuned__core35_y5__mrt_primary_school (no macro, no land use)."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
        ),
        "xgboost_tuned__core35_y5__mrt_primary_school__landuse_estate": Experiment(
            id="xgboost_tuned__core35_y5__mrt_primary_school__landuse_estate",
            feature_set_id="mrt_pit__masterplan_landuse_pit__primary_school__estate_maturity",
            model_id="xgboost_tuned",
            description=(
                "Core 3/4/5 ROOM, 5-year window: land use + estate together vs control "
                "(batch `CORE35_Y5_MRT_PRIMARY_SCHOOL_PACK_AB_V1`)."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
        ),
        "xgboost_tuned__core35_y5__mrt_primary_school__masterplan_area": Experiment(
            id="xgboost_tuned__core35_y5__mrt_primary_school__masterplan_area",
            feature_set_id="mrt_pit__masterplan_area__primary_school",
            model_id="xgboost_tuned",
            description=(
                "Core 3/4/5 ROOM, 5-year window: masterplan **area** pack only (intersection areas), vs control."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
        ),
        "xgboost_tuned__core35_y5__mrt_primary_school__masterplan_proximity": Experiment(
            id="xgboost_tuned__core35_y5__mrt_primary_school__masterplan_proximity",
            feature_set_id="mrt_pit__masterplan_proximity__primary_school",
            model_id="xgboost_tuned",
            description=(
                "Core 3/4/5 ROOM, 5-year window: masterplan **proximity** pack (GPR, CBD/airport dist, "
                "derived scores, B2/business-park proximity columns), vs control."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
        ),
        "xgboost_tuned__core35_y5__mrt_primary_school__masterplan_area_proximity": Experiment(
            id="xgboost_tuned__core35_y5__mrt_primary_school__masterplan_area_proximity",
            feature_set_id="mrt_pit__masterplan_area_proximity__primary_school",
            model_id="xgboost_tuned",
            description=(
                "Core 3/4/5 ROOM, 5-year window: full masterplan (area + proximity packs); "
                "compare to `__masterplan_area` / `__masterplan_proximity` "
                "(batch `CORE35_Y5_MASTERPLAN_AREA_PROXIMITY_AB`)."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
        ),
        "xgboost_tuned__mrt_landuse_primary_school_estate__core35": Experiment(
            id="xgboost_tuned__mrt_landuse_primary_school_estate__core35",
            feature_set_id="mrt_pit__masterplan_landuse_pit__primary_school__estate_maturity",
            model_id="xgboost_tuned",
            description=(
                "Tuned XGBoost on core flat types (3/4/5 ROOM): baseline + MRT + land use + schools "
                "+ estate maturity; 5y window. Prefer `xgboost_tuned__core35_y5__mrt_primary_school__landuse_estate` "
                "for explicit pack A/B naming with the control trio."
            ),
            mrt_pit_min_years=5,
            search_iter_override=12,
            flat_type_scope="core_35",
        ),
        "xgboost_tuned__macro_only": Experiment(
            id="xgboost_tuned__macro_only",
            feature_set_id="baseline_v1__macro",
            model_id="xgboost_tuned",
            description="Ablation: macro pillar only (no MRT, no land use).",
            search_iter_override=12,
        ),
        "xgboost_tuned__landuse_only": Experiment(
            id="xgboost_tuned__landuse_only",
            feature_set_id="masterplan_landuse_pit",
            model_id="xgboost_tuned",
            description="Ablation: masterplan land-use pillar only.",
            search_iter_override=12,
        ),
        "xgboost_tuned__macro_mrt": Experiment(
            id="xgboost_tuned__macro_mrt",
            feature_set_id="mrt_pit__macro",
            model_id="xgboost_tuned",
            description="Ablation: MRT PIT + macro (no land use). Compare to mrt_pit control.",
            search_iter_override=12,
        ),
        "xgboost_tuned__macro_landuse": Experiment(
            id="xgboost_tuned__macro_landuse",
            feature_set_id="baseline_v1__macro__masterplan_landuse_pit",
            model_id="xgboost_tuned",
            description="Ablation: macro + land use, no MRT.",
            search_iter_override=12,
        ),
        "xgboost_tuned__macro_landuse_mrt_apply": Experiment(
            id="xgboost_tuned__macro_landuse_mrt_apply",
            feature_set_id="baseline_v1__macro__masterplan_landuse_pit__mrt_pit",
            model_id="xgboost_tuned",
            description="Ablation: 4-pillar stack with apply_recommended_drops (re-run with drops applied).",
            search_iter_override=12,
        ),
        "xgboost_tuned__full_stack": Experiment(
            id="xgboost_tuned__full_stack",
            feature_set_id="mrt_pit__poi_distancing__macro__masterplan_landuse_pit",
            model_id="xgboost_tuned",
            description="Wider XGBoost search on full pillar stack.",
            extra_engineer_kwargs=extras_poi,
        ),
        "extra_trees__baseline": Experiment(
            id="extra_trees__baseline",
            feature_set_id="baseline_v1",
            model_id="extra_trees",
            description="Extra Trees on baseline.",
        ),
        "extra_trees__mrt": Experiment(
            id="extra_trees__mrt",
            feature_set_id="mrt_pit",
            model_id="extra_trees",
            description="Extra Trees + MRT.",
        ),
        "lightgbm__baseline": Experiment(
            id="lightgbm__baseline",
            feature_set_id="baseline_v1",
            model_id="lightgbm",
            description="LightGBM on baseline.",
        ),
        "lightgbm__mrt": Experiment(
            id="lightgbm__mrt",
            feature_set_id="mrt_pit",
            model_id="lightgbm",
            description="LightGBM + MRT.",
        ),
        "lightgbm__full_stack": Experiment(
            id="lightgbm__full_stack",
            feature_set_id="mrt_pit__poi_distancing__macro__masterplan_landuse_pit",
            model_id="lightgbm",
            description="LightGBM on full pillar stack.",
            extra_engineer_kwargs=extras_poi,
        ),
        "ridge__baseline": Experiment(
            id="ridge__baseline",
            feature_set_id="baseline_v1",
            model_id="ridge",
            description="Ridge regression baseline.",
        ),
        "ridge__mrt": Experiment(
            id="ridge__mrt",
            feature_set_id="mrt_pit",
            model_id="ridge",
            description="Ridge + MRT.",
        ),
        "linear__mrt": Experiment(
            id="linear__mrt",
            feature_set_id="mrt_pit",
            model_id="linear",
            description="Linear regression + MRT PIT pack.",
        ),
        "random_forest__mrt": Experiment(
            id="random_forest__mrt",
            feature_set_id="mrt_pit",
            model_id="random_forest",
            description="Random Forest + MRT PIT pack.",
        ),
        "mlp__mrt": Experiment(
            id="mlp__mrt",
            feature_set_id="mrt_pit",
            model_id="mlp",
            description="MLP + MRT PIT pack.",
        ),
        "xgboost__mrt": Experiment(
            id="xgboost__mrt",
            feature_set_id="mrt_pit",
            model_id="xgboost",
            description="XGBoost + MRT PIT pack.",
        ),
        "xgboost__mrt_poi": Experiment(
            id="xgboost__mrt_poi",
            feature_set_id="mrt_pit__poi_distancing",
            model_id="xgboost",
            description="Full Colab-style stack (needs data/pois assets + coords).",
            extra_engineer_kwargs=extras_poi,
        ),
        "xgboost__primary_school": Experiment(
            id="xgboost__primary_school",
            feature_set_id="primary_school",
            model_id="xgboost",
            description="Top-20 primary school annulus counts only (AB pack); snapshot lat/lon + POI via feature set.",
        ),
        "xgboost__mrt_primary_school": Experiment(
            id="xgboost__mrt_primary_school",
            feature_set_id="mrt_pit__primary_school",
            model_id="xgboost",
            description="MRT PIT + top-20 primary school annulus counts (AB pack); snapshot lat/lon + POI via feature set.",
        ),
        "xgboost__mrt_primary_school__y10": Experiment(
            id="xgboost__mrt_primary_school__y10",
            feature_set_id="mrt_pit__primary_school",
            model_id="xgboost",
            description="Same as xgboost__mrt_primary_school with rolling 10-year training window (mrt_pit_min_years=10).",
            mrt_pit_min_years=10,
        ),
        "xgboost__mrt_primary_school__y15": Experiment(
            id="xgboost__mrt_primary_school__y15",
            feature_set_id="mrt_pit__primary_school",
            model_id="xgboost",
            description="Same as xgboost__mrt_primary_school with rolling 15-year training window (mrt_pit_min_years=15).",
            mrt_pit_min_years=15,
        ),
        "xgboost__mrt_primary_school__y20": Experiment(
            id="xgboost__mrt_primary_school__y20",
            feature_set_id="mrt_pit__primary_school",
            model_id="xgboost",
            description="Same as xgboost__mrt_primary_school with rolling 20-year training window (mrt_pit_min_years=20).",
            mrt_pit_min_years=20,
        ),
        "linear__mrt_primary_school": Experiment(
            id="linear__mrt_primary_school",
            feature_set_id="mrt_pit__primary_school",
            model_id="linear",
            description="Linear + MRT PIT + top-20 primary school annulus counts.",
        ),
        "random_forest__mrt_primary_school": Experiment(
            id="random_forest__mrt_primary_school",
            feature_set_id="mrt_pit__primary_school",
            model_id="random_forest",
            description="Random Forest + MRT PIT + top-20 primary school annulus counts.",
        ),
        "mlp__mrt_primary_school": Experiment(
            id="mlp__mrt_primary_school",
            feature_set_id="mrt_pit__primary_school",
            model_id="mlp",
            description="MLP + MRT PIT + top-20 primary school annulus counts.",
        ),
        "ridge__mrt_primary_school": Experiment(
            id="ridge__mrt_primary_school",
            feature_set_id="mrt_pit__primary_school",
            model_id="ridge",
            description="Ridge + MRT PIT + top-20 primary school annulus counts.",
        ),
        "extra_trees__mrt_primary_school": Experiment(
            id="extra_trees__mrt_primary_school",
            feature_set_id="mrt_pit__primary_school",
            model_id="extra_trees",
            description="Extra Trees + MRT PIT + top-20 primary school annulus counts.",
        ),
        "lightgbm__mrt_primary_school": Experiment(
            id="lightgbm__mrt_primary_school",
            feature_set_id="mrt_pit__primary_school",
            model_id="lightgbm",
            description="LightGBM + MRT PIT + top-20 primary school annulus counts.",
        ),
        "xgboost__baseline_macro": Experiment(
            id="xgboost__baseline_macro",
            feature_set_id="baseline_v1__macro",
            model_id="xgboost",
            description="Baseline + macro sentiment (build data/macro sidecar first).",
        ),
        "xgboost_eco__baseline": Experiment(
            id="xgboost_eco__baseline",
            feature_set_id="baseline_v1",
            model_id="xgboost_eco",
            description="Histogram XGBoost with n_jobs=1 for laptop-friendly training.",
        ),
        "xgboost_grouped__baseline": Experiment(
            id="xgboost_grouped__baseline",
            feature_set_id="baseline_grouped_v1",
            model_id="xgboost_grouped",
            description="Reference-style grouped flat_model + region encoding.",
        ),
        "linear__baseline_2015_trend": Experiment(
            id="linear__baseline_2015_trend",
            feature_set_id="baseline_v1__months_since_2015",
            model_id="linear",
            description="Adds months_since_2015 anchored trend for slice comparisons.",
        ),
        "xgboost__macro_landuse_full": Experiment(
            id="xgboost__macro_landuse_full",
            feature_set_id="baseline_v1__macro__masterplan_landuse_pit__mrt_pit",
            model_id="xgboost",
            description="Macro + Land Use parquet + MRT (heavy feature stack).",
        ),
        "xgboost__mrt_poi_macro_masterplan": Experiment(
            id="xgboost__mrt_poi_macro_masterplan",
            feature_set_id="mrt_pit__poi_distancing__macro__masterplan_landuse_pit",
            model_id="xgboost",
            description="All pillars (base+MRT+POI+macro+masterplan) with standard XGBoost.",
            extra_engineer_kwargs=extras_poi,
        ),
        "xgboost_eco__mrt_poi_macro_masterplan": Experiment(
            id="xgboost_eco__mrt_poi_macro_masterplan",
            feature_set_id="mrt_pit__poi_distancing__macro__masterplan_landuse_pit",
            model_id="xgboost_eco",
            description="All pillars with XGBoost-eco (hist tree, n_jobs=1).",
            extra_engineer_kwargs=extras_poi,
        ),
        "xgboost_grouped__mrt_poi_macro_masterplan": Experiment(
            id="xgboost_grouped__mrt_poi_macro_masterplan",
            feature_set_id="mrt_pit__poi_distancing__macro__masterplan_landuse_pit__grouped",
            model_id="xgboost_grouped",
            description="All pillars with grouped categoricals + XGBoost_grouped preprocessor.",
            extra_engineer_kwargs=extras_poi,
        ),
        "mrt_pit_baselines": Experiment(
            id="mrt_pit_baselines",
            feature_set_id="mrt_pit",
            model_id="linear",
            description="Meta: sequential linear+RF+MLP comparison (legacy notebook parity).",
        ),
    }

    core35_suffix = " Training restricted to 3/4/5 ROOM resale rows."
    for base_key in CORE35_SOURCE_EXPERIMENT_IDS:
        if base_key not in experiments:
            continue
        src = experiments[base_key]
        new_id = f"{base_key}__core35"
        desc = src.description.strip()
        merged_desc = (f"{desc} {core35_suffix}".strip()) if desc else core35_suffix.strip()
        experiments[new_id] = replace(
            src,
            id=new_id,
            flat_type_scope="core_35",
            description=merged_desc,
        )

    return experiments


def get_experiment(project_root: Path, name: str) -> Experiment:
    reg = default_experiments(project_root)
    if name not in reg:
        raise KeyError(f"Unknown experiment '{name}'. Options: {sorted(reg)}")
    return reg[name]
