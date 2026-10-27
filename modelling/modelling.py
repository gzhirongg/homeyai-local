"""Backward-compatible exports, legacy CLI, and percent-format notebook entry.

Prefer `python modelling/runners/run_experiment.py` for new work.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from IPython.display import Markdown, display
except ImportError:
    Markdown = None  # type: ignore[misc, assignment]
    display = None  # type: ignore[misc, assignment]

try:
    from IPython import get_ipython
except ImportError:
    get_ipython = None  # type: ignore[misc, assignment]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "data" / "hdb_resale_full.parquet"
MRT_FEATURES_PATH = PROJECT_ROOT / "data" / "hdb_mrt_features.parquet"
TARGET_COLUMN = "resale_price"
RANDOM_STATE = 42
LOG_TARGET_MAX = 15.0

from modelling.data.loaders import LoaderConfig, load_training_frame as _load_frame  # noqa: E402
from modelling.eda.profile import (  # noqa: E402
    build_column_profile,
    configure_plot_style,
    plot_missingness,
    plot_target_distribution,
)
from modelling.evaluation.metrics import (  # noqa: E402
    evaluate_regression_model,
    target_clipped_inverse,
    target_log_transform,
)
from modelling.features.base import (  # noqa: E402
    base_categorical_columns,
    base_numeric_columns,
    parse_remaining_lease_to_years,
)
from modelling.features.mrt_pit import (  # noqa: E402
    MRT_BINARY_NUMERIC_FEATURES,
    MRT_SCALAR_NUMERIC_FEATURES,
    engineer_mrt_pit_frame,
    mrt_numeric_feature_names,
    validate_mrt_line_registry as _validate_mrt_line_registry_impl,
)
from modelling.features.line_vocab import (  # noqa: E402
    assert_lines_in_vocab,
    expanded_line_vocab_from_frame,
    line_tokens,
    mrt_line_feature_slug,
    mrt_nearest_line_indicator_suffix,
)
CATEGORICAL_FEATURES = list(base_categorical_columns("legacy"))
_BASE_NUMERIC_FEATURES = base_numeric_columns("legacy")
NUMERIC_FEATURES = _BASE_NUMERIC_FEATURES + mrt_numeric_feature_names(PROJECT_ROOT)
MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES


def engineer_features(frame):
    """Compact modelling frame with baseline + PIT MRT pack (legacy tests)."""
    return engineer_mrt_pit_frame(frame, categorical_style="legacy", project_root=PROJECT_ROOT)


def _validate_mrt_line_registry(frame):  # noqa: D401
    """Ensure PIT snapshot line tokens ⊆ ``_mrt_lines.json``."""
    return _validate_mrt_line_registry_impl(frame, PROJECT_ROOT)


def is_notebook_environment() -> bool:
    if get_ipython is None:
        return False
    shell = get_ipython()
    return shell is not None and shell.__class__.__name__ == "ZMQInteractiveShell"


IS_NOTEBOOK = is_notebook_environment()


def show_markdown(text: str) -> None:
    cleaned = text.strip()
    if IS_NOTEBOOK and display is not None and Markdown is not None:
        display(Markdown(cleaned))
    else:
        print(cleaned)


def show_frame(frame, max_rows: int = 10) -> None:
    if IS_NOTEBOOK and display is not None:
        display(frame)
        return
    print(frame.head(max_rows).to_string())


def show_plot() -> None:
    import matplotlib.pyplot as plt

    backend = plt.get_backend().lower()
    if IS_NOTEBOOK or "agg" not in backend:
        plt.show()
    else:
        plt.close()


@dataclass
class RunConfig:
    parquet_minio: bool = False
    test_fraction: float = 0.2
    cv_splits: int = 4
    max_train_rows: int | None = None
    rf_search_iter: int = 10
    nn_search_iter: int = 8
    random_state: int = RANDOM_STATE


def load_training_frame(config: RunConfig):
    loader = LoaderConfig(
        project_root=PROJECT_ROOT,
        parquet_minio=config.parquet_minio,
        use_database=not config.parquet_minio,
    )
    return _load_frame(loader)


def infer_column_role(df, column: str) -> str:
    from modelling.eda.profile import infer_column_role as _infer

    return _infer(df, column)


def preview_engineered_features(df):
    preview = engineer_features(df.head(5))
    return __import__("pandas").concat(
        [df.head(5).reset_index(drop=True), preview.reset_index(drop=True)], axis=1
    )


def make_temporal_split(df, target_column: str = TARGET_COLUMN, test_fraction: float = 0.2):
    from modelling.data.splits import make_temporal_split as _split

    return _split(df, target_column, test_fraction)


def restrict_training_window(X_train, y_train, max_train_rows: int | None):
    from modelling.data.splits import restrict_training_window as _win

    return _win(X_train, y_train, max_train_rows)


# Legacy ModelSpec used only by removed inlines — kept name for accidental imports
@dataclass
class ModelSpec:
    name: str
    estimator: Any
    scale_numeric: bool
    search_kind: str
    param_grid: dict[str, Any]
    search_iter: int | None = None


def build_preprocessor(scale_numeric: bool):
    from modelling.config.model_specs import build_sklearn_preprocessor

    return build_sklearn_preprocessor(
        numeric_features=NUMERIC_FEATURES,
        categorical_features=CATEGORICAL_FEATURES,
        scale_numeric=scale_numeric,
        spec=None,
    )


def build_pipeline(spec: ModelSpec):
    """Rebuild sklearn pipeline using **legacy** `engineer_features` + column lists."""
    from sklearn.compose import TransformedTargetRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import FunctionTransformer

    pre = build_preprocessor(scale_numeric=spec.scale_numeric)
    model = TransformedTargetRegressor(
        regressor=spec.estimator,
        func=target_log_transform,
        inverse_func=target_clipped_inverse,
    )
    return Pipeline(
        steps=[
            ("feature_engineering", FunctionTransformer(engineer_features, validate=False)),
            ("preprocessor", pre),
            ("model", model),
        ]
    )


def build_model_specs(random_state: int) -> list[ModelSpec]:
    from scipy.stats import loguniform, randint
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.neural_network import MLPRegressor

    return [
        ModelSpec(
            name="Linear Regression",
            estimator=LinearRegression(),
            scale_numeric=True,
            search_kind="grid",
            param_grid={
                "preprocessor__categorical__onehot__min_frequency": [10, 25, 50],
                "model__regressor__fit_intercept": [True, False],
            },
        ),
        ModelSpec(
            name="Random Forest",
            estimator=RandomForestRegressor(random_state=random_state, n_jobs=-1),
            scale_numeric=False,
            search_kind="random",
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
        ModelSpec(
            name="Neural Network",
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
    ]


def tune_one_model(
    spec: ModelSpec,
    X_train,
    y_train,
    cv,
    random_state: int,
    rf_search_iter: int,
    nn_search_iter: int,
):
    from sklearn.model_selection import GridSearchCV, RandomizedSearchCV
    import warnings
    from sklearn.exceptions import ConvergenceWarning

    pipeline = build_pipeline(spec)
    if spec.name == "Random Forest":
        search_iter = rf_search_iter
    elif spec.name == "Neural Network":
        search_iter = nn_search_iter
    else:
        search_iter = spec.search_iter

    common = {
        "estimator": pipeline,
        "scoring": "neg_root_mean_squared_error",
        "n_jobs": -1,
        "cv": cv,
        "refit": True,
        "return_train_score": True,
        "error_score": "raise",
    }
    if spec.search_kind == "grid":
        search = GridSearchCV(param_grid=spec.param_grid, **common)
    else:
        search = RandomizedSearchCV(
            param_distributions=spec.param_grid,
            n_iter=search_iter or 8,
            random_state=random_state,
            **common,
        )
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ConvergenceWarning)
        search.fit(X_train, y_train)
    return {
        "name": spec.name,
        "search": search,
        "best_estimator": search.best_estimator_,
        "best_params": search.best_params_,
        "best_cv_rmse": float(-search.best_score_),
    }


def train_and_compare_models(X_train, y_train, X_test, y_test, config: RunConfig):
    from sklearn.model_selection import TimeSeriesSplit
    import pandas as pd

    specs = build_model_specs(random_state=config.random_state)
    cv = TimeSeriesSplit(n_splits=config.cv_splits)
    search_results = {}
    comparison_rows = []
    for spec in specs:
        show_markdown(f"### Tuning {spec.name}")
        result = tune_one_model(
            spec=spec,
            X_train=X_train,
            y_train=y_train,
            cv=cv,
            random_state=config.random_state,
            rf_search_iter=config.rf_search_iter,
            nn_search_iter=config.nn_search_iter,
        )
        best_estimator = result["best_estimator"]
        test_predictions = best_estimator.predict(X_test)
        metrics = evaluate_regression_model(y_test, test_predictions)
        result["test_predictions"] = test_predictions
        result["test_metrics"] = metrics
        search_results[spec.name] = result
        comparison_rows.append({"model": spec.name, "cv_rmse": result["best_cv_rmse"], **metrics})
        show_markdown(
            "\n".join(
                [
                    f"Best CV RMSE: `{result['best_cv_rmse']:,.2f}`",
                    f"Test RMSE: `{metrics['rmse']:,.2f}`",
                    f"Test MAE: `{metrics['mae']:,.2f}`",
                    f"Test R²: `{metrics['r2']:.4f}`",
                ]
            )
        )
    comparison = pd.DataFrame(comparison_rows).sort_values("rmse").reset_index(drop=True)
    return comparison, search_results


def plot_model_comparison(results):
    import matplotlib.pyplot as plt
    import seaborn as sns

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    sns.barplot(data=results, x="model", y="rmse", ax=axes[0], color="#4c78a8")
    axes[0].set_title("Test RMSE By Model")
    axes[0].tick_params(axis="x", rotation=20)
    sns.barplot(data=results, x="model", y="r2", ax=axes[1], color="#59a14f")
    axes[1].set_title("Test R² By Model")
    axes[1].tick_params(axis="x", rotation=20)
    plt.tight_layout()
    show_plot()


def plot_predictions_vs_actual(y_true, predictions):
    import matplotlib.pyplot as plt
    import seaborn as sns

    model_names = list(predictions)
    fig, axes = plt.subplots(1, len(model_names), figsize=(6 * len(model_names), 5))
    if len(model_names) == 1:
        axes = [axes]
    for ax, model_name in zip(axes, model_names):
        y_pred = predictions[model_name]["test_predictions"]
        sns.scatterplot(x=y_true, y=y_pred, s=10, alpha=0.25, ax=ax, color="#457b9d")
        price_min = min(y_true.min(), y_pred.min())
        price_max = max(y_true.max(), y_pred.max())
        ax.plot([price_min, price_max], [price_min, price_max], linestyle="--", color="black")
        ax.set_title(model_name)
        ax.set_xlabel("Actual price")
        ax.set_ylabel("Predicted price")
    plt.tight_layout()
    show_plot()


def plot_residuals(y_true, predictions):
    import matplotlib.pyplot as plt
    import seaborn as sns

    model_names = list(predictions)
    fig, axes = plt.subplots(1, len(model_names), figsize=(6 * len(model_names), 4))
    if len(model_names) == 1:
        axes = [axes]
    for ax, model_name in zip(axes, model_names):
        residuals = y_true - predictions[model_name]["test_predictions"]
        sns.histplot(residuals, bins=40, kde=True, ax=ax, color="#bc6c25")
        ax.set_title(f"{model_name} residuals")
        ax.set_xlabel("Actual - predicted")
    plt.tight_layout()
    show_plot()


def run_notebook_workflow(config: RunConfig):
    configure_plot_style()
    show_markdown(
        """
        ## Load Dataset
        """
    )
    raw_df = load_training_frame(config)
    profile = build_column_profile(raw_df)
    show_frame(profile)
    plot_missingness(raw_df)
    plot_target_distribution(raw_df)
    show_markdown("## Preview engineered features")
    show_frame(preview_engineered_features(raw_df))
    X_train, X_test, y_train, y_test = make_temporal_split(
        raw_df, target_column=TARGET_COLUMN, test_fraction=config.test_fraction
    )
    X_train, y_train = restrict_training_window(X_train, y_train, config.max_train_rows)
    show_markdown(
        f"## Train/Test split — train {len(X_train):,}, test {len(X_test):,}"
    )
    comparison, search_results = train_and_compare_models(
        X_train, y_train, X_test, y_test, config
    )
    show_markdown("## Model comparison")
    show_frame(comparison)
    plot_model_comparison(comparison)
    plot_predictions_vs_actual(y_test, search_results)
    plot_residuals(y_test, search_results)
    return comparison, search_results


def parse_args():
    parser = argparse.ArgumentParser(description="Legacy HDB modelling entry (notebook workflow).")
    parser.add_argument(
        "--from-parquet-minio",
        action="store_true",
        help="Notebook workflow loads resale + sidecars from HOMEYAI_MINIO_SOURCES_JSON (default: Postgres read-only).",
    )
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--cv-splits", type=int, default=4)
    parser.add_argument("--max-train-rows", type=int, default=None)
    parser.add_argument("--rf-search-iter", type=int, default=10)
    parser.add_argument("--nn-search-iter", type=int, default=8)
    parser.add_argument("--random-state", type=int, default=RANDOM_STATE)
    parser.add_argument(
        "--runner",
        action="store_true",
        help="Delegate to modelling/runners/run_experiment.py mrt_pit_baselines (faster batch).",
    )
    args, _rest = parser.parse_known_args()
    return args


def main():
    args = parse_args()
    if args.runner:
        from modelling.runners import run_experiment

        argv = [
            "--name",
            "mrt_pit_baselines",
            "--project-root",
            str(PROJECT_ROOT),
            "--test-fraction",
            str(args.test_fraction),
            "--cv-splits",
            str(args.cv_splits),
            "--rf-search-iter",
            str(args.rf_search_iter),
            "--nn-search-iter",
            str(args.nn_search_iter),
            "--random-state",
            str(args.random_state),
        ]
        if args.max_train_rows is not None:
            argv.extend(["--max-train-rows", str(args.max_train_rows)])
        if args.from_parquet_minio:
            argv.append("--from-parquet-minio")
        return run_experiment.main(argv)

    max_train = None if args.max_train_rows in (None, 0) else args.max_train_rows
    config = RunConfig(
        parquet_minio=args.from_parquet_minio,
        test_fraction=args.test_fraction,
        cv_splits=args.cv_splits,
        max_train_rows=max_train,
        rf_search_iter=args.rf_search_iter,
        nn_search_iter=args.nn_search_iter,
        random_state=args.random_state,
    )
    return run_notebook_workflow(config)


if __name__ == "__main__":
    main()
