"""Distance/ratio LOI features for B2 and business park from Master Plan polygons."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from modelling.features.masterplan_loi_proximity import LOI_PROXIMITY_NUMERIC, loi_proximity_for_unique_coords

pytest.importorskip("geopandas")


def test_loi_proximity_distances_and_ratio(tmp_path: Path) -> None:
    """Point east of a B2 patch: finite B2 distance, BP farther, ratio in (0,1)."""
    b2 = box(30000, 30000, 30100, 30100)
    bp = box(30500, 30000, 30600, 30100)
    gdf = gpd.GeoDataFrame(
        {
            "LU_DESC": ["BUSINESS 2", "BUSINESS PARK"],
            "geometry": [b2, bp],
        },
        crs="EPSG:3414",
    )
    path = tmp_path / "lu.geojson"
    gdf.to_file(path, driver="GeoJSON")

    pt_east = (30150.0, 30050.0)
    pt_g = gpd.GeoDataFrame(geometry=[Point(pt_east)], crs="EPSG:3414").to_crs(4326)
    lat = float(pt_g.geometry.iloc[0].y)
    lon = float(pt_g.geometry.iloc[0].x)

    uc = pd.DataFrame([{"lat": lat, "lon": lon}])
    out = loi_proximity_for_unique_coords(uc, path)
    for c in LOI_PROXIMITY_NUMERIC:
        assert c in out.columns
    assert 0.0 < float(out["dist_to_nearest_b2_zone"].iloc[0]) < 0.5
    assert 0.0 < float(out["b2_zoning_ratio_1km"].iloc[0]) < 1.0
    assert float(out["dist_to_nearest_business_park"].iloc[0]) > float(
        out["dist_to_nearest_b2_zone"].iloc[0]
    )


def test_loi_proximity_cemetery_and_special_use(tmp_path: Path) -> None:
    cemetery = box(30000, 30000, 30100, 30100)
    special = box(30200, 30000, 30300, 30100)
    gdf = gpd.GeoDataFrame(
        {
            "LU_DESC": ["CEMETERY", "SPECIAL USE"],
            "geometry": [cemetery, special],
        },
        crs="EPSG:3414",
    )
    path = tmp_path / "lu_cemetery.geojson"
    gdf.to_file(path, driver="GeoJSON")
    pt_g = gpd.GeoDataFrame(geometry=[Point(30050.0, 30050.0)], crs="EPSG:3414").to_crs(4326)
    uc = pd.DataFrame(
        [{"lat": float(pt_g.geometry.iloc[0].y), "lon": float(pt_g.geometry.iloc[0].x)}]
    )
    out = loi_proximity_for_unique_coords(uc, path)
    assert float(out["dist_to_nearest_cemetery"].iloc[0]) == 0.0
    assert 0.1 < float(out["dist_to_nearest_special_use"].iloc[0]) < 0.5


def test_loi_proximity_empty_b2_yields_nan_distance_zero_ratio(tmp_path: Path) -> None:
    gdf = gpd.GeoDataFrame(
        {"LU_DESC": ["BUSINESS PARK"], "geometry": [box(30000, 30000, 30100, 30100)]},
        crs="EPSG:3414",
    )
    path = tmp_path / "lu2.geojson"
    gdf.to_file(path, driver="GeoJSON")
    pt_g = gpd.GeoDataFrame(geometry=[Point(30050, 30050)], crs="EPSG:3414").to_crs(4326)
    uc = pd.DataFrame([{"lat": float(pt_g.geometry.iloc[0].y), "lon": float(pt_g.geometry.iloc[0].x)}])
    out = loi_proximity_for_unique_coords(uc, path)
    assert out["dist_to_nearest_b2_zone"].isna().all()
    assert float(out["b2_zoning_ratio_1km"].iloc[0]) == 0.0
    assert not out["dist_to_nearest_business_park"].isna().all()
