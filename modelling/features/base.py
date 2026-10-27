"""Base structured features (time, lease, storey, categoricals) shared across feature sets."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

CATEGORICAL_LEGACY = ["town", "flat_model"]
CATEGORICAL_GROUPED = ["town", "flat_model_grouped", "region"]

# Ordinal 1–7 after normalizing HDB flat_type strings (space-separated, e.g. ``4 ROOM``).
FLAT_TYPE_ORDINAL: dict[str, int] = {
    "1 ROOM": 1,
    "2 ROOM": 2,
    "3 ROOM": 3,
    "4 ROOM": 4,
    "5 ROOM": 5,
    "EXECUTIVE": 6,
    "MULTI-GENERATION": 7,
}

# WGS84 block centroids from OneMap enrichment (`lat`, `lon` on training frames).
SPATIAL_NUMERIC_FEATURES: tuple[str, ...] = ("lat", "lon")

REGION_TOWN_MAPPING = {
    "CENTRAL REGION": [
        "BISHAN",
        "BUKIT MERAH",
        "BUKIT TIMAH",
        "GEYLANG",
        "MARINE PARADE",
        "QUEENSTOWN",
        "TOA PAYOH",
        "CENTRAL AREA",
        "KALLANG/WHAMPOA",
    ],
    "EAST REGION": ["BEDOK", "PASIR RIS", "TAMPINES"],
    "NORTH REGION": ["LIM CHU KANG", "SEMBAWANG", "WOODLANDS", "YISHUN"],
    "NORTH-EAST REGION": ["ANG MO KIO", "HOUGANG", "PUNGGOL", "SENGKANG", "SERANGOON"],
    "WEST REGION": [
        "BUKIT BATOK",
        "BUKIT PANJANG",
        "CHOA CHU KANG",
        "CLEMENTI",
        "JURONG EAST",
        "JURONG WEST",
    ],
}


def parse_remaining_lease_to_years(value: object) -> float:
    """Convert mixed lease strings like '61 years 04 months' or '68' to years."""
    if pd.isna(value):
        return math.nan

    text = str(value).strip().lower()
    if not text:
        return math.nan

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)

    years_match = re.search(r"(\d+)\s+year", text)
    months_match = re.search(r"(\d+)\s+month", text)
    if not years_match and not months_match:
        return math.nan

    years = int(years_match.group(1)) if years_match else 0
    months = int(months_match.group(1)) if months_match else 0
    return years + (months / 12.0)


def _flat_model_grouped(series: pd.Series) -> pd.Series:
    counts = series.astype("string").value_counts(normalize=True)
    minorities = counts[counts < 0.02].index
    return series.astype("string").replace(minorities, "OTHERS")


def _region_from_town(town_series: pd.Series) -> pd.Series:
    inv = {town: region for region, towns in REGION_TOWN_MAPPING.items() for town in towns}
    return town_series.astype("string").str.upper().str.strip().map(inv).astype("string")


def _normalize_flat_type_series(series: pd.Series) -> pd.Series:
    """Uppercase, strip, and canonicalize ``MULTI GENERATION`` → ``MULTI-GENERATION``."""
    return (
        series.astype("string")
        .str.upper()
        .str.strip()
        .str.replace("MULTI GENERATION", "MULTI-GENERATION", regex=False)
    )


def encode_flat_type_ordinal(normalized_flat_type: pd.Series) -> pd.Series:
    """
    Map canonical HDB flat types to integers 1–7.

    Accepts output of :func:`_normalize_flat_type_series`. Unknown labels become NaN
    (median-imputed in the sklearn numeric branch). Hyphenated variants (e.g. ``1-ROOM``)
    are aligned to space form before lookup.
    """
    first = normalized_flat_type.map(FLAT_TYPE_ORDINAL)
    alt = normalized_flat_type.str.replace("-", " ", regex=False).map(FLAT_TYPE_ORDINAL)
    out = first.where(first.notna(), alt)
    # sklearn's numeric imputer expects IEEE NaN, not pandas' nullable pd.NA.
    # Recent pandas versions preserve a nullable integer dtype after this map.
    return pd.Series(pd.to_numeric(out, errors="coerce").to_numpy(dtype=float, na_value=math.nan),
                     index=out.index, name=out.name)


def engineer_base_features(
    frame: pd.DataFrame,
    *,
    categorical_style: Literal["legacy", "grouped"] = "legacy",
    include_months_since_2015: bool = False,
) -> pd.DataFrame:
    """
    Core tabular features without MRT or POI packs.

    * legacy: ``town``, ``flat_model``, plus ordinal ``flat_type_encoded`` (1–7) from raw ``flat_type``.
    * grouped: adds ``region`` and ``flat_model_grouped`` (Colab-style); omits raw ``flat_model``.
    * Numeric baseline: ``sale_year``, cyclical ``sale_month_*``, ``storey_mid``, optional ``lat``/``lon`` when present on the raw frame (else NaN).
    * ``months_since_2015``: anchored trend term matching ``HDB-Valuation_ext`` training slice parity.
    """
    month_date = pd.to_datetime(frame["month"], format="%Y-%m", errors="coerce")
    sale_year = month_date.dt.year.astype(float)
    sale_month = month_date.dt.month.astype(float)

    storey_bounds = frame["storey_range"].astype("string").str.extract(
        r"(?i)(?P<storey_lower>\d+)\s+TO\s+(?P<storey_upper>\d+)"
    )
    storey_bounds = storey_bounds.astype(float)
    storey_mid = storey_bounds.mean(axis=1)

    if "remaining_lease_years" in frame.columns:
        remaining_lease_years = pd.to_numeric(frame["remaining_lease_years"], errors="coerce")
    elif "remaining_lease" in frame.columns:
        remaining_lease_years = frame["remaining_lease"].map(parse_remaining_lease_to_years)
    else:
        remaining_lease_years = pd.Series(np.nan, index=frame.index, dtype=float)

    out = pd.DataFrame(index=frame.index)
    out["sale_year"] = sale_year
    out["sale_month_sin"] = np.sin(2 * np.pi * (sale_month - 1) / 12.0)
    out["sale_month_cos"] = np.cos(2 * np.pi * (sale_month - 1) / 12.0)
    out["floor_area_sqm"] = pd.to_numeric(frame["floor_area_sqm"], errors="coerce")
    out["remaining_lease_years"] = remaining_lease_years
    out["storey_mid"] = storey_mid

    if include_months_since_2015:
        out["months_since_2015"] = (sale_year - 2015.0) * 12.0 + sale_month

    town_upper = frame["town"].astype("string").str.upper().str.strip()
    flat_type_norm = _normalize_flat_type_series(frame["flat_type"])
    out["flat_type_encoded"] = encode_flat_type_ordinal(flat_type_norm)
    flat_model_upper = (
        frame["flat_model"]
        .astype("string")
        .str.upper()
        .str.strip()
        .str.replace("MULTI GENERATION", "MULTI-GENERATION", regex=False)
    )

    if categorical_style == "legacy":
        out["town"] = town_upper
        out["flat_model"] = flat_model_upper
    else:
        out["town"] = town_upper
        out["flat_model_grouped"] = _flat_model_grouped(flat_model_upper)
        out["region"] = _region_from_town(frame["town"])

    for col in SPATIAL_NUMERIC_FEATURES:
        if col in frame.columns:
            out[col] = pd.to_numeric(frame[col], errors="coerce").astype(float)
        else:
            out[col] = np.nan

    return out


def base_numeric_columns(
    _style: Literal["legacy", "grouped"],
    *,
    include_months_since_2015: bool = False,
) -> list[str]:
    cols = [
        "sale_year",
        "sale_month_sin",
        "sale_month_cos",
        "floor_area_sqm",
        "flat_type_encoded",
        "remaining_lease_years",
        "storey_mid",
    ]
    if include_months_since_2015:
        cols.append("months_since_2015")
    cols.extend(SPATIAL_NUMERIC_FEATURES)
    return cols


def base_categorical_columns(style: Literal["legacy", "grouped"]) -> list[str]:
    return list(CATEGORICAL_LEGACY) if style == "legacy" else list(CATEGORICAL_GROUPED)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
