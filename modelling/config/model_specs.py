"""Model specifications for sklearn search + training."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scipy.stats import loguniform, randint
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from category_encoders import TargetEncoder


@dataclass(frozen=True)
class ModelSpec:
    id: str
    display_name: str
    estimator: Any
    scale_numeric: bool
    search_kind: str  # "grid" | "random"
    target_clip_inverse: bool
    param_grid: dict[str, Any]
    search_iter: int | None = None
    # XGBoost-style split preprocessing (optional)
    use_target_encoder: bool = False
    high_card_features: tuple[str, ...] = ()
    low_card_features: tuple[str, ...] = ()


def build_default_specs(random_state: int = 42) -> dict[str, ModelSpec]:
    try:
        from xgboost import XGBRegressor as _XGB
    except Exception:  # pragma: no cover — optional dependency / missing libomp
        _XGB = None

    specs: dict[str, ModelSpec] = {
        "linear": ModelSpec(
            id="linear",
            display_name="Linear Regression",
            estimator=LinearRegression(),
            scale_numeric=True,
            search_kind="grid",
            target_clip_inverse=True,
            param_grid={
                "preprocessor__categorical__onehot__min_frequency": [10, 25, 50],
                "model__regressor__fit_intercept": [True, False],
            },
        ),
        "random_forest": ModelSpec(
            id="random_forest",
            display_name="Random Forest",
            estimator=RandomForestRegressor(random_state=random_state, n_jobs=-1),
            scale_numeric=False,
            search_kind="random",
            target_clip_inverse=True,
            search_iter=10,
            param_grid={
                "preprocessor__categorical__onehot__min_frequency": [10, 25, 50],
                "model__regressor__n_estimators": randint(150, 401),
                "model__regressor__max_depth": [12, 18, 24, None],
                "model__regressor__min_samples_split": randint(2, 12),
                "model__regressor__min_samples_leaf": randint(1, 6),
                "model__regressor__max_features": ["sqrt", "log2", 0.7],
            },
        ),
        "mlp": ModelSpec(
            id="mlp",
            display_name="Neural Network",
            estimator=MLPRegressor(
                random_state=random_state,
                hidden_layer_sizes=(128, 64),
                early_stopping=True,
                learning_rate="adaptive",
                max_iter=300,
                n_iter_no_change=10,
            ),
            scale_numeric=True,
            search_kind="random",
            target_clip_inverse=True,
            search_iter=8,
            param_grid={
                "preprocessor__categorical__onehot__min_frequency": [10, 25, 50],
                "model__regressor__hidden_layer_sizes": [
                    (96, 48),
                    (128, 64),
                    (192, 96),
                    (256, 128),
                ],
                "model__regressor__alpha": loguniform(1e-5, 1e-2),
                "model__regressor__learning_rate_init": loguniform(1e-4, 1e-3),
                "model__regressor__batch_size": [256, 512, 1024],
            },
        ),
        "ridge": ModelSpec(
            id="ridge",
            display_name="Ridge Regression",
            estimator=Ridge(),
            scale_numeric=True,
            search_kind="random",
            target_clip_inverse=True,
            search_iter=10,
            param_grid={
                "preprocessor__categorical__onehot__min_frequency": [10, 25, 50],
                "model__regressor__alpha": loguniform(0.01, 1000.0),
                "model__regressor__fit_intercept": [True],
            },
        ),
        "extra_trees": ModelSpec(
            id="extra_trees",
            display_name="Extra Trees",
            estimator=ExtraTreesRegressor(random_state=random_state, n_jobs=-1),
            scale_numeric=False,
            search_kind="random",
            target_clip_inverse=True,
            search_iter=10,
            param_grid={
                "preprocessor__categorical__onehot__min_frequency": [10, 25, 50],
                "model__regressor__n_estimators": randint(200, 501),
                "model__regressor__max_depth": [16, 24, None],
                "model__regressor__min_samples_leaf": randint(1, 6),
                "model__regressor__max_features": ["sqrt", "log2", 0.6],
            },
        ),
    }
    if _XGB is not None:
        specs["xgboost"] = ModelSpec(
            id="xgboost",
            display_name="XGBoost",
            estimator=_XGB(n_estimators=300, random_state=random_state, n_jobs=-1),
            scale_numeric=False,
            search_kind="random",
            target_clip_inverse=False,
            search_iter=6,
            param_grid={
                "model__regressor__learning_rate": [0.05, 0.1],
                "model__regressor__max_depth": [6, 8],
                "model__regressor__subsample": [0.8, 1.0],
            },
            use_target_encoder=True,
            high_card_features=("town", "flat_model"),
        )
        specs["xgboost_grouped"] = ModelSpec(
            id="xgboost_grouped",
            display_name="XGBoost (grouped categoricals)",
            estimator=_XGB(n_estimators=300, random_state=random_state, n_jobs=-1),
            scale_numeric=False,
            search_kind="random",
            target_clip_inverse=False,
            search_iter=6,
            param_grid={
                "model__regressor__learning_rate": [0.05, 0.1],
                "model__regressor__max_depth": [6, 8],
                "model__regressor__subsample": [0.8, 1.0],
            },
            use_target_encoder=True,
            high_card_features=("town", "flat_model_grouped"),
            low_card_features=("region",),
        )
        specs["xgboost_eco"] = ModelSpec(
            id="xgboost_eco",
            display_name="XGBoost (eco histogram, 1 worker)",
            estimator=_XGB(
                n_estimators=400,
                random_state=random_state,
                n_jobs=1,
                tree_method="hist",
            ),
            scale_numeric=False,
            search_kind="random",
            target_clip_inverse=False,
            search_iter=6,
            param_grid={
                "model__regressor__learning_rate": [0.05, 0.1],
                "model__regressor__max_depth": [6, 8],
                "model__regressor__subsample": [0.8, 1.0],
            },
            use_target_encoder=True,
            high_card_features=("town", "flat_model"),
        )
        specs["xgboost_tuned"] = ModelSpec(
            id="xgboost_tuned",
            display_name="XGBoost (tuned)",
            estimator=_XGB(
                n_estimators=400,
                random_state=random_state,
                n_jobs=-1,
                tree_method="hist",
            ),
            scale_numeric=False,
            search_kind="random",
            target_clip_inverse=False,
            search_iter=15,
            param_grid={
                "model__regressor__learning_rate": [0.03, 0.05, 0.1],
                "model__regressor__max_depth": [4, 6, 8, 10],
                "model__regressor__subsample": [0.7, 0.8, 1.0],
                "model__regressor__colsample_bytree": [0.7, 0.8, 1.0],
                "model__regressor__min_child_weight": [1, 3, 5],
                "model__regressor__reg_alpha": [0, 0.1, 1.0],
                "model__regressor__reg_lambda": [1.0, 5.0, 10.0],
            },
            use_target_encoder=True,
            high_card_features=("town", "flat_model"),
        )
        specs["xgboost_tuned_gpu"] = ModelSpec(
            id="xgboost_tuned_gpu",
            display_name="XGBoost (tuned, CUDA)",
            estimator=_XGB(
                n_estimators=400,
                random_state=random_state,
                n_jobs=1,
                tree_method="hist",
                device="cuda",
            ),
            scale_numeric=False,
            search_kind="random",
            target_clip_inverse=False,
            search_iter=15,
            param_grid={
                "model__regressor__learning_rate": [0.03, 0.05, 0.1],
                "model__regressor__max_depth": [4, 6, 8, 10],
                "model__regressor__subsample": [0.7, 0.8, 1.0],
                "model__regressor__colsample_bytree": [0.7, 0.8, 1.0],
                "model__regressor__min_child_weight": [1, 3, 5],
                "model__regressor__reg_alpha": [0, 0.1, 1.0],
                "model__regressor__reg_lambda": [1.0, 5.0, 10.0],
            },
            use_target_encoder=True,
            high_card_features=("town", "flat_model"),
        )
    try:
        from lightgbm import LGBMRegressor as _LGBM

        specs["lightgbm"] = ModelSpec(
            id="lightgbm",
            display_name="LightGBM",
            estimator=_LGBM(
                n_estimators=500,
                random_state=random_state,
                n_jobs=-1,
                verbose=-1,
            ),
            scale_numeric=False,
            search_kind="random",
            target_clip_inverse=False,
            search_iter=15,
            param_grid={
                "model__regressor__learning_rate": [0.03, 0.05, 0.1],
                "model__regressor__num_leaves": [31, 63, 127],
                "model__regressor__max_depth": [-1, 8, 12],
                "model__regressor__subsample": [0.8, 1.0],
                "model__regressor__colsample_bytree": [0.8, 1.0],
                "model__regressor__reg_alpha": [0, 0.1],
                "model__regressor__reg_lambda": [1.0, 5.0],
            },
            use_target_encoder=True,
            high_card_features=("town", "flat_model"),
        )
    except Exception:  # pragma: no cover — optional dependency
        pass
    return specs


def get_model_spec(project_root: object, model_id: str, random_state: int = 42) -> ModelSpec:
    specs = build_default_specs(random_state)
    if model_id not in specs:
        raise KeyError(f"Unknown model '{model_id}'. Choose from {sorted(specs)}")
    return specs[model_id]


def build_sklearn_preprocessor(
    *,
    numeric_features: list[str],
    categorical_features: list[str],
    scale_numeric: bool,
    spec: ModelSpec | None = None,
) -> ColumnTransformer:
    numeric_steps: list[tuple[str, Any]] = [("imputer", SimpleImputer(strategy="median"))]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))

    if spec and spec.use_target_encoder and spec.high_card_features:
        high = [c for c in spec.high_card_features if c in categorical_features]
        low = [c for c in spec.low_card_features if c in categorical_features]
        legacy = [c for c in categorical_features if c not in high and c not in low]
        transformers: list[tuple[str, Any, list[str]]] = [
            ("numeric", Pipeline(steps=numeric_steps), numeric_features),
        ]
        if high:
            transformers.append(
                ("high_card", TargetEncoder(smoothing=20), high),
            )
        if low:
            transformers.append(
                (
                    "low_card",
                    Pipeline(
                        steps=[
                            ("imputer", SimpleImputer(strategy="most_frequent")),
                            (
                                "onehot",
                                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                            ),
                        ]
                    ),
                    low,
                )
            )
        if legacy:
            transformers.append(
                (
                    "legacy_cat",
                    Pipeline(
                        steps=[
                            ("imputer", SimpleImputer(strategy="most_frequent")),
                            (
                                "onehot",
                                OneHotEncoder(
                                    handle_unknown="infrequent_if_exist",
                                    min_frequency=25,
                                    sparse_output=False,
                                ),
                            ),
                        ]
                    ),
                    legacy,
                )
            )
        return ColumnTransformer(
            transformers=transformers,
            remainder="drop",
            verbose_feature_names_out=False,
        )

    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="infrequent_if_exist",
                    min_frequency=25,
                    sparse_output=False,
                ),
            ),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("numeric", Pipeline(steps=numeric_steps), numeric_features),
            ("categorical", categorical_pipeline, categorical_features),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
