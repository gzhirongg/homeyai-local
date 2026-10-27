"""Dataset profiling helpers (ported from the percent-format notebook)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from modelling.evaluation.metrics import TARGET_COLUMN


def infer_column_role(df: pd.DataFrame, column: str) -> str:
    if column == "month":
        return "datetime_like"
    if column == "storey_range":
        return "ordered_category"
    if column == "remaining_lease_years":
        return "mixed_duration_text"
    if pd.api.types.is_numeric_dtype(df[column]):
        return "numeric"
    return "categorical"


def build_column_profile(df: pd.DataFrame) -> pd.DataFrame:
    profile = pd.DataFrame(
        {
            "dtype": df.dtypes.astype(str),
            "non_null_count": df.notna().sum(),
            "missing_count": df.isna().sum(),
            "missing_pct": (df.isna().mean() * 100).round(2),
            "unique_count": df.nunique(dropna=False),
        }
    )
    profile["role"] = [infer_column_role(df, column) for column in df.columns]
    return profile.sort_values(["missing_pct", "unique_count"], ascending=[False, False])


def configure_plot_style() -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams["figure.dpi"] = 120


def plot_missingness(df: pd.DataFrame, save_path=None) -> None:
    configure_plot_style()
    missing_pct = (df.isna().mean() * 100).sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(10, 4))
    sns.barplot(x=missing_pct.index, y=missing_pct.values, ax=ax, color="#4c78a8")
    ax.set_title("Column Missingness")
    ax.set_ylabel("Missing (%)")
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
        plt.close(fig)
    else:
        plt.show()


def plot_target_distribution(df: pd.DataFrame, save_path=None) -> None:
    configure_plot_style()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    sns.histplot(df[TARGET_COLUMN], bins=50, kde=True, ax=axes[0], color="#2a9d8f")
    axes[0].set_title("Resale Price Distribution")
    axes[0].set_xlabel(TARGET_COLUMN)

    sns.histplot(np.log1p(df[TARGET_COLUMN]), bins=50, kde=True, ax=axes[1], color="#e76f51")
    axes[1].set_title("log1p(Resale Price) Distribution")
    axes[1].set_xlabel(f"log1p({TARGET_COLUMN})")
    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
        plt.close(fig)
    else:
        plt.show()


def profile_to_csv(profile: pd.DataFrame, path) -> None:
    profile.to_csv(path)
