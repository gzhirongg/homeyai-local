"""Exploratory price trend charts (research question 1 from Colab notebook)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from modelling.eda.profile import configure_plot_style
from modelling.evaluation.metrics import TARGET_COLUMN
from modelling.features.base import REGION_TOWN_MAPPING


def _prep_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Uses raw df with resale_price, month, town + optionally region columns."""
    out = df.copy()
    out["transaction_date"] = pd.to_datetime(out["month"], format="%Y-%m", errors="coerce")
    out["price_per_sqm"] = out[TARGET_COLUMN] / pd.to_numeric(out["floor_area_sqm"], errors="coerce")
    inv_map = {town: region for region, towns in REGION_TOWN_MAPPING.items() for town in towns}
    out["region"] = out["town"].astype(str).str.upper().str.strip().map(inv_map)
    return out.sort_values("transaction_date")


def plot_quarterly_price_trend(df: pd.DataFrame, save_path=None) -> None:
    configure_plot_style()
    d = _prep_price_frame(df)
    quarterly = d.groupby(pd.Grouper(key="transaction_date", freq="QE"))["price_per_sqm"].mean().reset_index()
    fig, ax = plt.subplots(figsize=(14, 6))
    sns.lineplot(data=quarterly, x="transaction_date", y="price_per_sqm", marker="o", color="#2c3e50", ax=ax)
    ax.set_title("Singapore HDB Resale Price Trend (Quarterly, $/sqm)")
    ax.grid(True, linestyle="--", alpha=0.7)
    plt.xticks(rotation=45)
    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
        plt.close(fig)
    else:
        plt.show()


def plot_regional_quarterly_trend(df: pd.DataFrame, save_path=None) -> None:
    configure_plot_style()
    d = _prep_price_frame(df)
    qr = d.groupby([pd.Grouper(key="transaction_date", freq="QE"), "region"])["price_per_sqm"].mean().reset_index()
    fig, ax = plt.subplots(figsize=(14, 6))
    sns.lineplot(data=qr, x="transaction_date", y="price_per_sqm", hue="region", marker="o", ax=ax)
    ax.set_title("Price/sqm by Region (Quarterly)")
    ax.grid(True, linestyle="--", alpha=0.7)
    plt.xticks(rotation=45)
    plt.legend(title="Region", bbox_to_anchor=(1.02, 1))
    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
        plt.close(fig)
    else:
        plt.show()
