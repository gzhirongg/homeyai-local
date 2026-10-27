"""Join pre-materialised Land Use PIT polygon scalars (+ derived interactions)."""

from __future__ import annotations

import io
import os
import threading
import time as time_module
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from modelling.features.base import engineer_base_features, repo_root
from modelling.features.land_use_revision import DEFAULT_BUCKET, revision_key_for_tx_month
from modelling.features.macro_sentiment import append_macro_features
from modelling.features.masterplan_landuse_geometry import combine_landuseScalars_for_unique_coords
from modelling.features.masterplan_loi_proximity import LOI_PROXIMITY_NUMERIC, loi_proximity_for_unique_coords
from modelling.features.mrt_pit import append_mrt_features
from modelling.features.poi_distancing import haversine_vectorized

from modelling.storage.minio_io import get_object_bytes

# Process-local GeoDataFrame cache for valuation inference (avoid re-download/re-parse GeoJSON).
_MASTERPLAN_LAND_USE_CACHE_LOCK = threading.Lock()
_MASTERPLAN_LAND_USE_GDF_CACHE: dict[tuple[str, str], tuple[float, Any]] = {}
_MASTERPLAN_LAND_USE_CACHE_TTL_SEC = float(
    os.getenv("HOMEYAI_MASTERPLAN_LANDUSE_CACHE_TTL_SEC", "3600")
)
_MASTERPLAN_ROW_CACHE: dict[tuple[Any, ...], tuple[float, pd.DataFrame]] = {}


def _cached_landuse_gdf_for_minio(bucket: str, object_key: str) -> Any:
    """Load URA Master Plan land-use polygons from MinIO; cache GeoDataFrame in-process."""

    ck = (bucket, object_key)
    now_mono = time_module.monotonic()

    try:
        import geopandas as gpd_load  # type: ignore[import-not-found]
    except ImportError:
        raise ImportError("Master Plan inference requires geopandas") from None

    with _MASTERPLAN_LAND_USE_CACHE_LOCK:
        ent = _MASTERPLAN_LAND_USE_GDF_CACHE.get(ck)
        if ent is not None and ent[0] > now_mono:
            return ent[1]

    blob = get_object_bytes(bucket, object_key)
    land_gdf = gpd_load.read_file(io.BytesIO(blob))

    ttl = max(30.0, _MASTERPLAN_LAND_USE_CACHE_TTL_SEC)
    expire_at = now_mono + ttl
    with _MASTERPLAN_LAND_USE_CACHE_LOCK:
        _MASTERPLAN_LAND_USE_GDF_CACHE[ck] = (expire_at, land_gdf)
    return land_gdf


AREA_CATEGORIES = ("comm", "park", "sports", "health", "worship")
RADII_M = (500, 1000, 1500)

# Pack 1: polygon intersection areas only (m² in buffers).
MASTERPLAN_AREA_NUMERIC: list[str] = [f"area_{c}_{r}m" for c in AREA_CATEGORIES for r in RADII_M]

# Pack 2: GPR / reference distances / derived scalars / B2-BP proximity (everything except area_* columns).
_MASTERPLAN_PROXIMITY_NON_DERIVED: list[str] = (
    ["nearby_high_density_score", "dist_cbd", "dist_airport"] + list(LOI_PROXIMITY_NUMERIC)
)
MASTERPLAN_DERIVED_NUMERIC = ["density_age_interaction", "hub_score"]

MASTERPLAN_PROXIMITY_NUMERIC: list[str] = _MASTERPLAN_PROXIMITY_NON_DERIVED + MASTERPLAN_DERIVED_NUMERIC

# DB snapshot / parquet columns (no derived interactions).
MASTERPLAN_SNAPSHOT_SCALAR_COLS: list[str] = ["nearby_high_density_score"] + [
    f"area_{c}_{r}m" for c in AREA_CATEGORIES for r in RADII_M
]

MASTERPLAN_PARQUET_VALUE_COLS: list[str] = (
    MASTERPLAN_SNAPSHOT_SCALAR_COLS + ["dist_cbd", "dist_airport"] + list(LOI_PROXIMITY_NUMERIC)
)

# Backward-compat: full masterplan model numerics = area + proximity packs.
MASTERPLAN_LAND_USE_NUMERIC: list[str] = MASTERPLAN_AREA_NUMERIC + MASTERPLAN_PROXIMITY_NUMERIC


def _infer_dist_cbd_airport(coords: pd.DataFrame) -> pd.DataFrame:
    out = coords.copy()
    cbd = (1.2830, 103.8513)
    airport = (1.3644, 103.9915)
    out["dist_cbd"] = haversine_vectorized(out["lat"], out["lon"], cbd[0], cbd[1])
    out["dist_airport"] = haversine_vectorized(out["lat"], out["lon"], airport[0], airport[1])
    return out


def infer_dist_cbd_airport(coords: pd.DataFrame) -> pd.DataFrame:
    """Public helper for scripts / inference builds."""
    return _infer_dist_cbd_airport(coords)


def _float_series(frame: pd.DataFrame, column: str) -> pd.Series:
    """Float column aligned to ``frame.index`` (never a bare numpy scalar — NumPy 2 rejects ``.clip(lower=…)``)."""
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _flat_age_years_for_interaction(
    merged: pd.DataFrame,
    raw_frame: pd.DataFrame,
    *,
    assumed_total_lease_years: float = 99.0,
) -> pd.Series:
    """Flat age for ``density_age_interaction`` (not a model feature)."""
    if "flat_age_years" in merged.columns:
        legacy = pd.to_numeric(merged["flat_age_years"], errors="coerce")
        if legacy.notna().any():
            return legacy.clip(lower=0.0).fillna(0.0)

    rem = _float_series(merged, "remaining_lease_years")
    if not rem.notna().any():
        rem = _float_series(raw_frame, "remaining_lease_years")
    age = (assumed_total_lease_years - rem).clip(lower=0.0)

    if age.notna().any():
        return age.fillna(0.0)

    if "sale_year" in merged.columns:
        sale_year = pd.to_numeric(merged["sale_year"], errors="coerce")
        lcd = _float_series(raw_frame, "lease_commence_date")
        return (sale_year - lcd).clip(lower=0.0).fillna(0.0)

    return pd.Series(0.0, index=merged.index, dtype=float)


def append_masterplan_landuse_from_raw_columns(
    base: pd.DataFrame,
    raw_frame: pd.DataFrame,
    *,
    require_columns: bool = False,
) -> pd.DataFrame:
    """Populate masterplan numeric blocks from parquet/DB merges on ``raw_frame``."""
    merged = base.copy()
    snap_no_derived = MASTERPLAN_SNAPSHOT_SCALAR_COLS + ["dist_cbd", "dist_airport"] + list(LOI_PROXIMITY_NUMERIC)

    missing = [c for c in snap_no_derived if c not in raw_frame.columns]
    if missing and require_columns:
        raise ValueError(f"raw_frame missing masterplan snapshot columns {missing}")

    for col in MASTERPLAN_SNAPSHOT_SCALAR_COLS:
        if col in raw_frame.columns:
            merged[col] = pd.to_numeric(raw_frame[col], errors="coerce").fillna(0.0)
        else:
            merged[col] = 0.0

    dist_ok = {"lat", "lon"}.issubset(raw_frame.columns)
    if (
        ("dist_cbd" in raw_frame.columns and raw_frame["dist_cbd"].notna().any())
        or ("dist_airport" in raw_frame.columns and raw_frame["dist_airport"].notna().any())
    ):
        merged["dist_cbd"] = pd.to_numeric(raw_frame.get("dist_cbd"), errors="coerce")
        merged["dist_airport"] = pd.to_numeric(raw_frame.get("dist_airport"), errors="coerce")
    elif dist_ok:
        dxy = _infer_dist_cbd_airport(raw_frame[["lat", "lon"]])
        merged["dist_cbd"] = dxy["dist_cbd"].to_numpy(dtype=float)
        merged["dist_airport"] = dxy["dist_airport"].to_numpy(dtype=float)
    else:
        merged["dist_cbd"] = np.nan
        merged["dist_airport"] = np.nan

    for col in LOI_PROXIMITY_NUMERIC:
        if col in raw_frame.columns:
            merged[col] = pd.to_numeric(raw_frame[col], errors="coerce")
        else:
            merged[col] = np.nan

    gpr = merged["nearby_high_density_score"].astype(float)
    flat_age = _flat_age_years_for_interaction(merged, raw_frame)
    merged["density_age_interaction"] = gpr / (flat_age + 1.0)

    dist_adj = merged["dist_cbd"].astype(float).replace({0.0: np.nan})
    med = float(np.nanmedian(dist_adj.to_numpy()))
    med = med if np.isfinite(med) else 12.0
    dist_adj = dist_adj.fillna(med)
    if "area_comm_500m" in merged.columns:
        comm_area = pd.to_numeric(merged["area_comm_500m"], errors="coerce").fillna(0.0)
    elif "area_comm_500m" in raw_frame.columns:
        comm_area = pd.to_numeric(raw_frame["area_comm_500m"], errors="coerce").fillna(0.0)
    else:
        comm_area = pd.Series(0.0, index=merged.index)
    merged["hub_score"] = comm_area.astype(float) / (dist_adj.astype(float) + 0.5)

    merged = merged.replace([np.inf, -np.inf], np.nan)
    return merged


def compute_land_use_row_from_minio(
    lat: float,
    lon: float,
    *,
    valuation_month: str,
    project_root: Path | None = None,
    bucket: str = DEFAULT_BUCKET,
) -> pd.DataFrame:
    """Single-row GPR/areas + distances + LOI proximity for valuation (cold path)."""
    ym = valuation_month[:7]
    key = revision_key_for_tx_month(ym)
    if key is None:
        z = pd.DataFrame([{"nearby_high_density_score": 0.0}])
        for col in MASTERPLAN_SNAPSHOT_SCALAR_COLS[1:]:
            z[col] = 0.0
        for col in LOI_PROXIMITY_NUMERIC:
            z[col] = np.nan
        z = z.assign(dist_cbd=0.0, dist_airport=0.0, density_age_interaction=0.0, hub_score=0.0)
        return z

    row_ck = (round(float(lat), 5), round(float(lon), 5), ym, bucket, key)
    now_mono = time_module.monotonic()
    with _MASTERPLAN_LAND_USE_CACHE_LOCK:
        row_ent = _MASTERPLAN_ROW_CACHE.get(row_ck)
        if row_ent is not None and row_ent[0] > now_mono:
            return row_ent[1].copy()

    land_gdf = _cached_landuse_gdf_for_minio(bucket, key)
    coords = pd.DataFrame([{"lat": lat, "lon": lon}])
    feats = combine_landuseScalars_for_unique_coords(coords, land_use_gdf=land_gdf)
    loi = loi_proximity_for_unique_coords(coords, land_use_gdf=land_gdf)
    dist = _infer_dist_cbd_airport(coords[["lat", "lon"]]).iloc[0]
    row = feats.iloc[0:1].copy()
    for c in LOI_PROXIMITY_NUMERIC:
        row[c] = loi[c].iloc[0]
    row["dist_cbd"] = float(dist["dist_cbd"])
    row["dist_airport"] = float(dist["dist_airport"])
    gpr = pd.to_numeric(row["nearby_high_density_score"], errors="coerce").iloc[0] or 0.0
    comm = float(pd.to_numeric(row["area_comm_500m"], errors="coerce").iloc[0]) if "area_comm_500m" in row.columns else 0.0
    dcbd = float(row["dist_cbd"].iloc[0])
    row["density_age_interaction"] = gpr
    row["hub_score"] = comm / (max(dcbd, 1e-6) + 0.5)
    ttl = max(30.0, _MASTERPLAN_LAND_USE_CACHE_TTL_SEC)
    expire_at = now_mono + ttl
    with _MASTERPLAN_LAND_USE_CACHE_LOCK:
        _MASTERPLAN_ROW_CACHE[row_ck] = (expire_at, row.copy())
    return row


def engineer_masterplan_landuse_pit_only(
    raw: pd.DataFrame,
    *,
    categorical_style: str = "legacy",
    project_root: Path | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    base = engineer_base_features(
        raw,
        categorical_style=categorical_style,  # type: ignore[arg-type]
        include_months_since_2015=bool(kwargs.get("include_months_since_2015")),
    )
    return append_masterplan_landuse_from_raw_columns(base, raw, require_columns=False)


def engineer_macro_masterplan_landuse_pit_frame(
    raw: pd.DataFrame,
    *,
    categorical_style: str = "legacy",
    project_root: Path | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    out = engineer_masterplan_landuse_pit_only(
        raw, categorical_style=categorical_style, project_root=project_root, **kwargs
    )
    root = project_root or repo_root()
    return append_macro_features(out, raw, project_root=root)


def engineer_mrt_macro_masterplan_frame(
    raw: pd.DataFrame,
    *,
    categorical_style: str = "legacy",
    project_root: Path | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    base = engineer_macro_masterplan_landuse_pit_frame(
        raw, categorical_style=categorical_style, project_root=project_root, **kwargs
    )
    root = project_root or repo_root()
    return append_mrt_features(base, raw, project_root=root)
