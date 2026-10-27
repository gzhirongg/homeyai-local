"""LOI proximity from URA Master Plan land-use polygons (LU_DESC).

Distance / ratio features (not polygon intersection areas in amenity buffers).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import geopandas as gpd
    from shapely.validation import make_valid
except ImportError:  # pragma: no cover
    gpd = None  # type: ignore[assignment]
    make_valid = None  # type: ignore[assignment]

# Columns written to ``masterplan_landuse_pit_scalars`` and merged at training time.
LOI_PROXIMITY_NUMERIC: list[str] = [
    "dist_to_nearest_b2_zone",
    "b2_zoning_ratio_1km",
    "dist_to_nearest_business_park",
    "dist_to_nearest_cemetery",
    "dist_to_nearest_special_use",
]

_B2_LABELS = frozenset({"BUSINESS 2", "BUSINESS 2 - WHITE"})
_BP_LABELS = frozenset({"BUSINESS PARK", "BUSINESS PARK - WHITE"})
_CEMETERY_LABELS = frozenset({"CEMETERY"})
_SPECIAL_USE_LABELS = frozenset({"SPECIAL USE"})
_BUFFER_1KM_M = 1000.0
_DISK_AREA_1KM = np.pi * _BUFFER_1KM_M**2


def _require_geopandas() -> None:
    if gpd is None:
        raise ImportError("LOI proximity features require geopandas and shapely.")


def _union_category(land_sv: Any, lu_upper: pd.Series | None, labels: frozenset[str]) -> Any:
    if lu_upper is None:
        return None
    subset = land_sv[lu_upper.isin(labels)]
    if subset.empty:
        return None
    geom_col = subset.geometry
    if geom_col is not None and make_valid is not None:
        subset = subset.copy()
        subset["geometry"] = geom_col.apply(
            lambda g: make_valid(g) if g is not None and not g.is_valid else g
        )
        geom_col = subset.geometry
    if hasattr(geom_col, "union_all"):
        return geom_col.union_all()
    return geom_col.unary_union  # pragma: no cover


def _planar_distance_km(pt_geom: Any, zone_union: Any | None, n: int) -> np.ndarray:
    """SVY21 distance from each point to ``zone_union`` boundary (km); NaN if union is missing."""
    if zone_union is None:
        return np.full(n, np.nan, dtype=float)
    return pt_geom.distance(zone_union).to_numpy(dtype=float) / 1000.0


def loi_proximity_for_unique_coords(
    unique_coords: pd.DataFrame,
    landuse_geojson_path: Path | str | None = None,
    *,
    land_use_gdf: Any | None = None,
) -> pd.DataFrame:
    """Distance to nearest LOI zoning polygons and B2 area ratio within 1 km.

    - ``dist_to_nearest_*``: km (SVY21 planar distance / 1000).
    - ``b2_zoning_ratio_1km``: intersection area of B2 union with 1 km disk / (π·1000²), in [0, 1].

    Rows align with ``unique_coords`` (same order after drop_duplicates on lat/lon).
    """
    _require_geopandas()
    uc = unique_coords[["lat", "lon"]].drop_duplicates().reset_index(drop=True)
    n = len(uc)

    if land_use_gdf is not None:
        land = land_use_gdf
    elif landuse_geojson_path is not None:
        land = gpd.read_file(landuse_geojson_path)
    else:
        raise ValueError("loi_proximity_for_unique_coords: pass landuse_geojson_path or land_use_gdf")
    lu_upper = None
    if "LU_DESC" in land.columns:
        lu_upper = land["LU_DESC"].astype("string").str.upper().str.strip()
    land_sv = land.to_crs(epsg=3414)

    b2_union = _union_category(land_sv, lu_upper, _B2_LABELS)
    bp_union = _union_category(land_sv, lu_upper, _BP_LABELS)
    cemetery_union = _union_category(land_sv, lu_upper, _CEMETERY_LABELS)
    special_use_union = _union_category(land_sv, lu_upper, _SPECIAL_USE_LABELS)

    gdf_pts = gpd.GeoDataFrame(
        uc,
        geometry=gpd.points_from_xy(uc.lon, uc.lat),
        crs="EPSG:4326",
    ).to_crs(epsg=3414)
    pt_geom = gdf_pts.geometry

    d_b2_km = _planar_distance_km(pt_geom, b2_union, n)
    if b2_union is None:
        b2_ratio = np.zeros(n, dtype=float)
    else:
        buff = pt_geom.buffer(_BUFFER_1KM_M)
        inter = buff.intersection(b2_union)
        b2_ratio = np.asarray(inter.area, dtype=float) / _DISK_AREA_1KM
        b2_ratio = np.clip(b2_ratio, 0.0, 1.0)

    out = uc.copy()
    out["dist_to_nearest_b2_zone"] = d_b2_km
    out["b2_zoning_ratio_1km"] = b2_ratio
    out["dist_to_nearest_business_park"] = _planar_distance_km(pt_geom, bp_union, n)
    out["dist_to_nearest_cemetery"] = _planar_distance_km(pt_geom, cemetery_union, n)
    out["dist_to_nearest_special_use"] = _planar_distance_km(pt_geom, special_use_union, n)
    return out
