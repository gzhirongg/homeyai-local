"""Feature-set-aware valuation extras (macro + Land Use polygons) mirrored from training."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

from modelling.features.estate_maturity import ESTATE_MATURITY_MERGE_COLUMNS
from modelling.features.macro_sentiment import macro_inference_override
from modelling.features.masterplan_landuse_pit import (
    MASTERPLAN_PARQUET_VALUE_COLS,
    compute_land_use_row_from_minio,
)

logger = logging.getLogger(__name__)

_ESTATE_MATURITY_CACHE_LOCK = threading.Lock()
_ESTATE_MATURITY_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_ESTATE_MATURITY_CACHE_TTL_SEC = 300.0


def repo_root_from_inference() -> Path:
    """Project root when imported from backend (expects ``modelling/inference/…`` depth)."""
    return Path(__file__).resolve().parents[2]


def valuation_extra_raw_columns(
    feature_set_id: str | None,
    *,
    valuation_month: str,
    latitude: float | None,
    longitude: float | None,
    town: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Raw-column overrides merged into valuation row before sklearn ``FunctionTransformer``."""
    sid = (feature_set_id or "").strip()
    if not sid:
        return {}
    root = project_root or repo_root_from_inference()

    overrides: dict[str, Any] = {}

    if "__macro" in sid:
        overrides.update(macro_inference_override(valuation_month=valuation_month, project_root=root))

    if "masterplan" in sid.lower():
        if latitude is None or longitude is None:
            for col in MASTERPLAN_PARQUET_VALUE_COLS:
                overrides.setdefault(col, 0.0)
        else:
            lu = compute_land_use_row_from_minio(
                float(latitude), float(longitude), valuation_month=valuation_month, project_root=root
            )
            for col in MASTERPLAN_PARQUET_VALUE_COLS:
                if col in lu.columns:
                    overrides[col] = float(pd.to_numeric(lu[col].iloc[0], errors="coerce") or 0.0)

    if "estate_maturity" in sid.lower():
        try:
            from modelling.town_geo import normalize_hdb_town_label
            from modelling.training_db import get_training_engine

            tn = normalize_hdb_town_label(town)
            ym = (valuation_month or "").strip()[:7]
            if tn and ym:
                cache_key = (tn, ym)
                now_mono = time.monotonic()
                maturity_overrides: dict[str, Any] | None = None
                with _ESTATE_MATURITY_CACHE_LOCK:
                    ent = _ESTATE_MATURITY_CACHE.get(cache_key)
                    if ent is not None and ent[0] > now_mono:
                        maturity_overrides = dict(ent[1])

                if maturity_overrides is None:
                    eng = get_training_engine()
                    df = pd.read_sql(
                        text(
                            """
                            SELECT
                              avg_residential_block_age_years,
                              town_completed_residential_units_stock,
                              town_land_area_km2,
                              town_dwelling_unit_density,
                              town_units_under_construction,
                              town_hdb_completed_units_roll36m,
                              town_supply_maturity_ratio
                            FROM hdb_estate_maturity_by_town_month
                            WHERE town_normalized = :town
                              AND year_month = :ym
                            LIMIT 1
                            """
                        ),
                        eng,
                        params={"town": tn, "ym": ym},
                    )
                    maturity_overrides = {}
                    if not df.empty:
                        row0 = df.iloc[0]
                        for c in ESTATE_MATURITY_MERGE_COLUMNS:
                            if c not in row0.index:
                                continue
                            val = row0[c]
                            if pd.isna(val):
                                continue
                            maturity_overrides[c] = (
                                int(val)
                                if c
                                in (
                                    "town_completed_residential_units_stock",
                                    "town_units_under_construction",
                                    "town_hdb_completed_units_roll36m",
                                )
                                else float(val)
                            )
                    expire_at = now_mono + _ESTATE_MATURITY_CACHE_TTL_SEC
                    with _ESTATE_MATURITY_CACHE_LOCK:
                        _ESTATE_MATURITY_CACHE[cache_key] = (expire_at, dict(maturity_overrides))

                overrides.update(maturity_overrides)
        except Exception as exc:  # pragma: no cover - env without DB
            logger.warning("estate_maturity valuation extras skipped: %s", exc)

    return overrides
