"""Estate maturity (town × month) aggregates merged before training/engineering."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# Columns expected from SQL merge (training + valuation raw row).
ESTATE_MATURITY_MERGE_COLUMNS: list[str] = [
    "avg_residential_block_age_years",
    "town_completed_residential_units_stock",
    "town_land_area_km2",
    "town_dwelling_unit_density",
    "town_units_under_construction",
    "town_hdb_completed_units_roll36m",
    "town_supply_maturity_ratio",
]

ESTATE_MATURITY_ENGINEERED_EXTRA_NUMERIC: list[str] = [
    "town_bto_velocity_36m",
    "log1p_town_completed_residential_units_stock",
    "log1p_town_hdb_roll36_completed",
    "log1p_town_units_under_construction",
    "log1p_town_dwelling_unit_density",
    "log1p_town_supply_maturity_ratio",
]

ESTATE_MATURITY_NUMERIC_FEATURES: list[str] = list(ESTATE_MATURITY_MERGE_COLUMNS) + list(
    ESTATE_MATURITY_ENGINEERED_EXTRA_NUMERIC
)


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    """Stable float column; avoids ``pd.to_numeric(None)`` → numpy scalar (NumPy 2 ``.clip(lower=…)`` crashes)."""
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def engineer_estate_maturity_addon(base: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Copy estate columns from merged ``raw`` into engineered ``base`` (fill NaNs for tree stability)."""
    out = base.copy()
    vel = _numeric_series(raw, "town_hdb_completed_units_roll36m")
    out["town_bto_velocity_36m"] = vel

    for c in ESTATE_MATURITY_MERGE_COLUMNS:
        if c not in raw.columns:
            out[c] = np.nan
            continue
        s = pd.to_numeric(raw[c], errors="coerce")
        # Tree models tolerate NaN; downstream may impute — keep floats for densities/ratios
        out[c] = s

    dens = _numeric_series(out, "town_dwelling_unit_density")
    ratio = _numeric_series(out, "town_supply_maturity_ratio")
    stock = _numeric_series(out, "town_completed_residential_units_stock")

    # Optional bounded transforms (minimal v1 — document in KM)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["log1p_town_completed_residential_units_stock"] = np.log1p(stock.clip(lower=0).fillna(0))
        out["log1p_town_hdb_roll36_completed"] = np.log1p(vel.clip(lower=0).fillna(0))
        out["log1p_town_units_under_construction"] = np.log1p(
            _numeric_series(raw, "town_units_under_construction").clip(lower=0).fillna(0)
        )
        x = dens.replace([np.inf, -np.inf], np.nan).clip(lower=0, upper=1e6).fillna(0)
        out["log1p_town_dwelling_unit_density"] = np.log1p(x)
        xr = ratio.replace([np.inf, -np.inf], np.nan).clip(lower=0, upper=50).fillna(0)
        out["log1p_town_supply_maturity_ratio"] = np.log1p(xr)

    return out


def engineer_estate_maturity_bundle(
    base: pd.DataFrame,
    raw: pd.DataFrame,
    *,
    include_log1p: bool = True,
    **kwargs: Any,
) -> pd.DataFrame:
    """Public entry: base already base+macro/MRT/landuse features; ``raw`` still has SQL merges."""
    out = engineer_estate_maturity_addon(base, raw)
    if not include_log1p:
        out = out.drop(
            columns=[c for c in ESTATE_MATURITY_ENGINEERED_EXTRA_NUMERIC if c != "town_bto_velocity_36m"],
            errors="ignore",
        )
    return out
