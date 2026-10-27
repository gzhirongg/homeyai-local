"""Assemble sklearn pipelines from feature-set + model-spec."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sklearn.compose import TransformedTargetRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer

from modelling.config.feature_sets import FeatureSet, get_feature_set
from modelling.config.model_specs import ModelSpec, build_sklearn_preprocessor
from modelling.evaluation.metrics import target_clipped_inverse, target_log_transform, target_plain_inverse


def engineering_dispatch(
    raw_df: Any,
    *,
    feature_set_id: str,
    project_root_str: str,
    engineer_kwargs: dict[str, Any] | None = None,
):
    """Pickle-safe global entrypoint for ``FunctionTransformer`` (no closures)."""
    root = Path(project_root_str)
    fs = get_feature_set(root, feature_set_id)
    kw = dict(engineer_kwargs or {})
    kw["project_root"] = root
    return fs.engineer(raw_df, **kw)


def _pickle_safe_kw(fs: FeatureSet, project_root: Path) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    for k, v in fs.engineer_kwargs.items():
        if isinstance(v, Path):
            kw[k] = str(v)
        else:
            kw[k] = v
    return {
        "feature_set_id": fs.id,
        "project_root_str": str(project_root.resolve()),
        "engineer_kwargs": kw,
    }


def build_full_pipeline(feature_set: FeatureSet, model_spec: ModelSpec, project_root: Path) -> Pipeline:
    inverse = target_clipped_inverse if model_spec.target_clip_inverse else target_plain_inverse
    preprocessor = build_sklearn_preprocessor(
        numeric_features=feature_set.numeric_features,
        categorical_features=feature_set.categorical_features,
        scale_numeric=model_spec.scale_numeric,
        spec=model_spec,
    )
    ttr = TransformedTargetRegressor(
        regressor=model_spec.estimator,
        func=target_log_transform,
        inverse_func=inverse,
    )
    return Pipeline(
        steps=[
            (
                "feature_engineering",
                FunctionTransformer(
                    engineering_dispatch,
                    validate=False,
                    kw_args=_pickle_safe_kw(feature_set, project_root),
                ),
            ),
            ("preprocessor", preprocessor),
            ("model", ttr),
        ]
    )


def build_preprocessor_only_pipeline(feature_set: FeatureSet, model_spec: ModelSpec) -> Pipeline:
    """Pipeline without feature_engineering step — receives pre-engineered frames."""
    inverse = target_clipped_inverse if model_spec.target_clip_inverse else target_plain_inverse
    preprocessor = build_sklearn_preprocessor(
        numeric_features=feature_set.numeric_features,
        categorical_features=feature_set.categorical_features,
        scale_numeric=model_spec.scale_numeric,
        spec=model_spec,
    )
    ttr = TransformedTargetRegressor(
        regressor=model_spec.estimator,
        func=target_log_transform,
        inverse_func=inverse,
    )
    return Pipeline(steps=[("preprocessor", preprocessor), ("model", ttr)])


def wrap_pipeline_with_feature_engineering(
    preprocessor_only_fitted: Pipeline,
    feature_set: FeatureSet,
    project_root: Path,
) -> Pipeline:
    """Prepend the standard engineering step to a fitted preprocessor+model pipeline (inference / ``model.pkl``)."""
    return Pipeline(
        steps=[
            (
                "feature_engineering",
                FunctionTransformer(
                    engineering_dispatch,
                    validate=False,
                    kw_args=_pickle_safe_kw(feature_set, project_root),
                ),
            ),
            ("preprocessor", preprocessor_only_fitted.named_steps["preprocessor"]),
            ("model", preprocessor_only_fitted.named_steps["model"]),
        ]
    )
