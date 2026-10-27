"""Land Use polygon feature engineering (GPR buffer mean + category intersection areas)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:
    import geopandas as gpd
    from shapely.validation import make_valid
except ImportError:  # pragma: no cover
    gpd = None  # type: ignore[assignment]
    make_valid = None  # type: ignore[assignment]


def _require_geopandas() -> None:
    if gpd is None:
        raise ImportError("Master Plan land-use features require geopandas and shapely.")


def gpr_buffer_means_km(
    unique_coords: pd.DataFrame,
    landuse: Any,
    *,
    buffer_m: float = 500.0,
) -> pd.Series:
    """Mean GPR inside ``buffer_m`` (metres) around each (lat, lon) in ``unique_coords``."""
    _require_geopandas()
    uc = unique_coords[["lat", "lon"]].drop_duplicates().reset_index(drop=True)

    relevant_landuses = [
        "RESIDENTIAL",
        "COMMERCIAL",
        "COMMERCIAL & RESIDENTIAL",
        "RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY",
        "WHITE SITE",
    ]
    if "LU_DESC" in landuse.columns:
        lu = landuse["LU_DESC"].astype("string").str.upper()
        landuse_filtered = landuse[lu.isin(relevant_landuses)].copy()
    else:
        landuse_filtered = landuse.copy()
    if "GPR" in landuse_filtered.columns:
        landuse_filtered["GPR_clean"] = pd.to_numeric(landuse_filtered["GPR"], errors="coerce").fillna(0)
    else:
        landuse_filtered["GPR_clean"] = 0.0

    gdf_unique = gpd.GeoDataFrame(
        uc,
        geometry=gpd.points_from_xy(uc.lon, uc.lat),
        crs="EPSG:4326",
    ).to_crs(epsg=3414)

    land_poly = landuse_filtered.to_crs(epsg=3414)
    gdf_unique = gdf_unique.copy()
    buff = gdf_unique.geometry.buffer(buffer_m)
    joined = gpd.sjoin(
        gdf_unique.set_geometry(buff),
        land_poly[["geometry", "GPR_clean"]],
        how="left",
        predicate="intersects",
    )
    gpr_mean = joined.groupby(joined.index)["GPR_clean"].mean().reindex(gdf_unique.index).fillna(0.0)
    return gpr_mean.astype(float)


def amenity_intersection_areas_sqm(
    unique_coords: pd.DataFrame,
    landuse: Any,
) -> pd.DataFrame:
    """Column per (category, radius) ``area_<cat>_<r>m`` in m² inside SVY21."""
    _require_geopandas()
    uc = unique_coords[["lat", "lon"]].drop_duplicates().reset_index(drop=True)

    # LU_DESC values follow URA Master Plan land-use layer (data.gov.sg GeoJSON).
    category_map = {
        "comm": ["COMMERCIAL", "COMMERCIAL & RESIDENTIAL", "WHITE SITE", "HOTEL"],
        "park": ["PARK", "OPEN SPACE", "BEACH AREA", "GARDEN"],
        "sports": ["SPORTS & RECREATION"],
        "health": ["HEALTH & MEDICAL CARE"],
        "worship": ["PLACE OF WORSHIP"],
    }

    land = landuse.copy()
    lu_desc = land["LU_DESC"].astype("string").str.upper() if "LU_DESC" in land.columns else None

    geom_col = land.geometry
    if geom_col is not None and make_valid is not None:
        land = land.copy()
        land["geometry"] = geom_col.apply(lambda g: make_valid(g) if g is not None and not g.is_valid else g)

    gdf_unique = gpd.GeoDataFrame(
        uc,
        geometry=gpd.points_from_xy(uc.lon, uc.lat),
        crs="EPSG:4326",
    ).to_crs(epsg=3414)
    land_sv = land.to_crs(epsg=3414)

    super_polys: dict[str, Any] = {}
    for cat, labels in category_map.items():
        if lu_desc is not None:
            subset = land_sv[lu_desc.isin(labels)]
        else:
            subset = land_sv.iloc[0:0]
        if subset.empty:
            super_polys[cat] = None
        elif hasattr(subset.geometry, "union_all"):
            super_polys[cat] = subset.geometry.union_all()
        else:  # pragma: no cover
            super_polys[cat] = subset.geometry.unary_union

    radii = [500, 1000, 1500]
    out_uc = uc.copy()
    pt_geom = gdf_unique.geometry

    for r in radii:
        buffered_geom = pt_geom.buffer(r)
        for cat_name, poly in super_polys.items():
            col_name = f"area_{cat_name}_{r}m"
            if poly is None:
                out_uc[col_name] = 0.0
            else:
                vals = buffered_geom.intersection(poly).area
                out_uc[col_name] = np.asarray(vals, dtype=float)
    return out_uc


def combine_landuseScalars_for_unique_coords(
    unique_coords: pd.DataFrame,
    landuse_geojson_path: Path | str | None = None,
    *,
    land_use_gdf: Any | None = None,
) -> pd.DataFrame:
    """GPR mean + intersection areas merged back on ``lat``, ``lon``.

    Provide either ``landuse_geojson_path`` or a loaded ``land_use_gdf`` GeoDataFrame
    (avoids parsing GeoJSON repeatedly when serving valuations).
    """
    _require_geopandas()
    uc = unique_coords[["lat", "lon"]].drop_duplicates().reset_index(drop=True)
    if land_use_gdf is not None:
        land = land_use_gdf
    elif landuse_geojson_path is not None:
        land = gpd.read_file(landuse_geojson_path)
    else:
        raise ValueError("combine_landuseScalars_for_unique_coords: pass landuse_geojson_path or land_use_gdf")
    gpr = gpr_buffer_means_km(uc, land)
    areas_blk = amenity_intersection_areas_sqm(uc, land)
    feats = areas_blk.copy()
    feats["nearby_high_density_score"] = gpr.to_numpy(dtype=float)
    return feats
