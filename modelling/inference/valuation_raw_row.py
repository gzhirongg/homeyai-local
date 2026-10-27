"""Build a single-row raw HDB resale frame for sklearn Pipeline inference."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class ValuationInferenceInput:
    """Normalized inputs shared between API and raw-row builder."""

    postal_code: str
    town: str
    flat_type: str
    flat_model_grouped: str
    region: str
    storey_midpoint: int
    floor_area_sqm: float
    remaining_lease_years: float
    latitude: float | None
    longitude: float | None
    lease_commence_year: int | None


def _storey_range_from_midpoint(mid: int) -> str:
    """Approximate HDB ``storey_range`` band from a single storey level.

    Training data uses bands like ``07 TO 09``. Without an explicit band from the user,
    we expand ±1 floor around the midpoint (clamped so lower ≥ 1).
    """
    m = int(mid)
    lo = max(1, m - 1)
    hi = max(lo, m + 1)
    return f"{lo:02d} TO {hi:02d}"


def build_valuation_raw_dataframe(
    inp: ValuationInferenceInput,
    *,
    valuation_month: str,
    mrt_feature_overrides: dict[str, Any] | None = None,
    feature_overrides: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """One-row raw frame before ``feature_engineering`` in the trained Pipeline.

    * Uses **legacy** categoricals via ``flat_model`` populated from ``flat_model_grouped``
      (matches ``engineer_mrt_pit_frame(..., categorical_style='legacy')`` in training).
    * ``block`` / ``street_name`` are optional placeholders — unused by ``engineer_base_features``.
    """
    ym = (valuation_month or "").strip()
    if len(ym) < 7:
        ym = pd.Timestamp.utcnow().strftime("%Y-%m")

    row: dict[str, Any] = {
        "month": ym,
        "town": str(inp.town).upper().strip(),
        "flat_type": str(inp.flat_type).upper().strip(),
        "flat_model": str(inp.flat_model_grouped).upper().strip(),
        "block": "",
        "street_name": "",
        "storey_range": _storey_range_from_midpoint(inp.storey_midpoint),
        "floor_area_sqm": float(inp.floor_area_sqm),
        "remaining_lease_years": int(round(float(inp.remaining_lease_years))),
    }

    lat: float | None = None
    lon: float | None = None
    if inp.latitude is not None and inp.longitude is not None:
        try:
            lat = float(inp.latitude)
            lon = float(inp.longitude)
        except (TypeError, ValueError):
            lat = lon = None
        else:
            if not math.isfinite(lat) or not math.isfinite(lon):
                lat = lon = None
    if lat is not None and lon is not None:
        row["lat"] = lat
        row["lon"] = lon

    if mrt_feature_overrides:
        for k, v in mrt_feature_overrides.items():
            if k in {"hdb_addr_id", "tx_year_month", "computed_at"}:
                continue
            row[k] = v

    if feature_overrides:
        row.update(feature_overrides)

    return pd.DataFrame([row])
