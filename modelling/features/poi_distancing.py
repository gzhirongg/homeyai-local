"""POI distance, density, and gravity features (Colab ``areasv2`` notebook)."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import geopandas as gpd
except ImportError:  # pragma: no cover
    gpd = None  # type: ignore[assignment]

from sklearn.neighbors import BallTree

from modelling.features.mrt_pit import append_mrt_features
from modelling.features.base import engineer_base_features, repo_root

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_000

POI_FILENAMES = {
    "top_20_schools": "top_20_primary_schools.csv",
    "all_schools": "all_primary_schools.csv",
    "malls": "all_shopping_malls.csv",
    "supermarkets": "supermarkets.csv",
    "parks": "NParksParksandNatureReserves.geojson",
    "markets": "NEAMarketandFoodCentre.geojson",
    "pcn": "ParkConnectorLoop.geojson",
}

# DB ``poi_locations.poi_type`` values (see ingest_poi_assets.ASSET_KEY_TO_DB_TYPE)
POI_DB_TYPES = (
    "school_top20",
    "school_any",
    "mall",
    "supermarket",
    "park",
    "market",
    "pcn",
)

POI_DB_TYPE_TO_FRAME_KEY: dict[str, str] = {
    "school_top20": "top_20",
    "school_any": "schools",
    "mall": "malls",
    "supermarket": "supermarkets",
    "park": "parks",
    "market": "markets",
    "pcn": "pcn",
}

POI_NUMERIC_FEATURES = [
    "dist_cbd",
    "dist_airport",
    "dist_nearest_top20_school",
    "dist_nearest_any_school",
    "within_1km_top20_school",
    "within_1km_2km_top20_school",
    "within_1km_any_pri_school",
    "within_1km_2km_pri_school",
    "dist_nearest_mall",
    "malls_within_2km",
    "supermarkets_within_500m",
    "markets_within_500m",
    "dist_nearest_park",
    "is_park_200m",
    "dist_nearest_pcn",
    "gravity_malls",
    "gravity_schools",
    "gravity_parks",
    "gravity_markets",
]


def pois_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "pois"


def _require_geopandas() -> None:
    if gpd is None:
        raise ImportError("POI features need geopandas — pip install geopandas")


def haversine_vectorized(lat1, lon1, lat2, lon2) -> np.ndarray:
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def _ensure_lat_lon(df: pd.DataFrame) -> None:
    if "lat" not in df.columns or "lon" not in df.columns:
        raise ValueError(
            "POI feature engineering requires 'lat' and 'lon' columns. "
            "With --from-db, data must include onemap coordinates. "
            "Otherwise merge data/pois/hdb_block_coords.csv (columns: block, street_name, lat, lon)."
        )


def _normalize_props_dict(props: Any) -> dict[str, Any]:
    if props is None or not hasattr(props, "items"):
        return {}
    # GeoPandas/feature properties may expose non-str keys — stringify for lookups.
    return {str(k): v for k, v in dict(props).items()}


_GEOJSON_NAME_KEYS: tuple[str, ...] = (
    "NAME_OF_CENTRE",  # NEA markets / food centres
    "PARK",  # NParks park connector segment name
    "NAME",
    "Name",
    "name",
    "SCHOOLNAME",
    "SchoolName",
    "school_name",
    "POI_NAME",
    "TITLE",
    "Title",
    "title",
    "DESCRIPTION",
    "Description",
    "description",
    "LIC_NAME",
    "LICENSE_NAME",
    "BUILDING_N",
    "Building_N",
    "BUILDING_NO",
)


def pick_geojson_name_from_props(props: Any, *, maxlen: int = 2000) -> str:
    """Best-effort name from GeoJSON / GeoDataFrame attribute columns."""
    d = _normalize_props_dict(props)
    for k in _GEOJSON_NAME_KEYS:
        if k not in d:
            continue
        v = d[k]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        s = str(v).strip()
        if s:
            return s[:maxlen]
    return ""


def _geojson_names_for_gdf(gdf: Any) -> list[str]:
    geom_series = getattr(gdf, "geometry", None)
    geom_key = getattr(geom_series, "name", None) or "geometry"
    cols = [c for c in gdf.columns if c != geom_key]
    names: list[str] = []
    for _, feat in gdf.iterrows():
        props = feat[cols].to_dict() if cols else {}
        names.append(pick_geojson_name_from_props(props))
    return names


def merge_block_coordinates(
    df: pd.DataFrame,
    coords_path: Path,
    *,
    block_col: str = "block",
    street_col: str = "street_name",
) -> pd.DataFrame:
    """Left-merge lat/lon from CSV (uppercase block + street keys)."""
    if not coords_path.is_file():
        raise FileNotFoundError(
            f"Missing coordinate file: {coords_path}. "
            "Copy your teammate's hdb_with_features.csv (or equivalent) here "
            f"or place a deduped CSV at {coords_path}."
        )
    coords = pd.read_csv(coords_path)
    for c in (block_col, street_col, "lat", "lon"):
        if c not in coords.columns:
            raise ValueError(f"{coords_path} must contain column '{c}'")

    out = df.copy()
    for frame in (out, coords):
        frame[block_col] = frame[block_col].astype(str).str.upper().str.strip()
        frame[street_col] = frame[street_col].astype(str).str.upper().str.strip()

    coords = coords.drop_duplicates(subset=[block_col, street_col])
    merged = out.merge(
        coords[[block_col, street_col, "lat", "lon"]],
        on=[block_col, street_col],
        how="left",
    )
    return merged


def process_polygon_geojson(filepath: Path) -> pd.DataFrame:
    _require_geopandas()
    gdf = gpd.read_file(filepath).to_crs("EPSG:3414")
    centroids = gdf.geometry.centroid.to_crs("EPSG:4326")
    df = pd.DataFrame({"lat": centroids.y, "lon": centroids.x})
    df["name"] = _geojson_names_for_gdf(gdf)
    return df


def process_linestring_geojson_centroids(filepath: Path) -> pd.DataFrame:
    """One row per GeoJSON feature: linestring/MultiLineString centroid in WGS84 + ``name``."""
    _require_geopandas()
    gdf = gpd.read_file(filepath).to_crs("EPSG:3414")
    geom_col = gdf.geometry.name
    cols = [c for c in gdf.columns if c != geom_col]
    lats: list[float] = []
    lons: list[float] = []
    names: list[str] = []
    for _, feat in gdf.iterrows():
        geom = feat.geometry
        if geom is None or geom.is_empty:
            continue
        c = geom.centroid
        g4326 = gpd.GeoSeries([c], crs="EPSG:3414").to_crs("EPSG:4326")
        p = g4326.geometry.iloc[0]
        lats.append(float(p.y))
        lons.append(float(p.x))
        props = feat[cols].to_dict() if cols else {}
        names.append(pick_geojson_name_from_props(props))
    df = pd.DataFrame({"lat": lats, "lon": lons, "name": names})
    if df.empty:
        warnings.warn(f"No linestring features with centroids from {filepath}", stacklevel=2)
    return df


def process_linestring_geojson(filepath: Path, *, step_m: float = 100.0) -> pd.DataFrame:
    """Sample park connector vertices every ``step_m`` metres (EPSG:3414 length) to limit BallTree size."""
    _require_geopandas()
    gdf = gpd.read_file(filepath).to_crs("EPSG:3414")
    lats: list[float] = []
    lons: list[float] = []
    for geom in gdf.geometry:
        if geom is None:
            continue
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for line in lines:
            if line.is_empty or line.length == 0:
                continue
            d = 0.0
            while d <= line.length:
                pt = line.interpolate(d)
                g4326 = gpd.GeoSeries([pt], crs="EPSG:3414").to_crs("EPSG:4326")
                p = g4326.geometry.iloc[0]
                lats.append(float(p.y))
                lons.append(float(p.x))
                d += step_m
    out = pd.DataFrame({"lat": lats, "lon": lons}).drop_duplicates()
    if out.empty:
        warnings.warn(f"No PCN vertices sampled from {filepath}", stacklevel=2)
    return out


def get_nearest_dist(hdb_df: pd.DataFrame, poi_df: pd.DataFrame) -> np.ndarray:
    if poi_df.empty:
        return np.full(len(hdb_df), np.nan)
    tree = BallTree(np.deg2rad(poi_df[["lat", "lon"]].values), metric="haversine")
    dist, _ = tree.query(np.deg2rad(hdb_df[["lat", "lon"]].values), k=1)
    return dist.flatten() * EARTH_RADIUS_M


def get_count_in_radius(hdb_df: pd.DataFrame, poi_df: pd.DataFrame, radius_m: float) -> np.ndarray:
    if poi_df.empty:
        return np.zeros(len(hdb_df), dtype=int)
    tree = BallTree(np.deg2rad(poi_df[["lat", "lon"]].values), metric="haversine")
    return tree.query_radius(
        np.deg2rad(hdb_df[["lat", "lon"]].values), r=(radius_m / EARTH_RADIUS_M), count_only=True
    )


def calculate_gravity_component(
    hdb_df: pd.DataFrame,
    poi_df: pd.DataFrame,
    weight: float,
    k_nearest: int = 5,
) -> np.ndarray:
    if poi_df.empty or weight == 0:
        return np.zeros(len(hdb_df))
    hdb_rad = np.deg2rad(hdb_df[["lat", "lon"]].values)
    poi_rad = np.deg2rad(poi_df[["lat", "lon"]].values)
    tree = BallTree(poi_rad, metric="haversine")
    k = min(k_nearest, len(poi_df))
    distances, _ = tree.query(hdb_rad, k=k)
    distances_m = distances * EARTH_RADIUS_M
    decay_scores = weight * np.exp(-distances_m / 1000)
    return np.sum(decay_scores, axis=1)


def load_poi_tables(root: Path | None = None) -> dict[str, pd.DataFrame]:
    root = root or repo_root()
    base = pois_dir(root)
    missing = [name for name, fn in POI_FILENAMES.items() if not (base / fn).is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing POI asset(s) under data/pois: "
            + ", ".join(POI_FILENAMES[m] for m in missing)
            + f" — expected directory: {base}"
        )

    top_20_df = pd.read_csv(base / POI_FILENAMES["top_20_schools"])
    all_schools_df = pd.read_csv(base / POI_FILENAMES["all_schools"])
    all_malls_df = pd.read_csv(base / POI_FILENAMES["malls"])
    supermarkets_df = pd.read_csv(base / POI_FILENAMES["supermarkets"])
    if "name" not in all_malls_df.columns:
        all_malls_df["name"] = ""
    if "name" not in supermarkets_df.columns:
        supermarkets_df["name"] = ""

    if "lat" not in top_20_df.columns or top_20_df["lat"].isna().all():
        warnings.warn(
            "Top-20 schools CSV lacks coordinates; POI distances will be NaN until geocoded.",
            stacklevel=2,
        )
    if "lat" not in all_schools_df.columns or all_schools_df["lat"].isna().all():
        warnings.warn(
            "All-schools CSV lacks coordinates; POI distances may be invalid.",
            stacklevel=2,
        )

    top_20_df = top_20_df.dropna(subset=["lat", "lon"], how="any")
    all_schools_df = all_schools_df.dropna(subset=["lat", "lon"], how="any")

    parks_df = process_polygon_geojson(base / POI_FILENAMES["parks"])
    markets_df = process_polygon_geojson(base / POI_FILENAMES["markets"])
    pcn_df = process_linestring_geojson(base / POI_FILENAMES["pcn"])

    supermarkets_df = supermarkets_df[["name", "lat", "lon"]].copy()
    all_malls_df = all_malls_df[["name", "lat", "lon"]].copy()

    return {
        "top_20": top_20_df,
        "schools": all_schools_df,
        "malls": all_malls_df,
        "supermarkets": supermarkets_df,
        "parks": parks_df,
        "markets": markets_df,
        "pcn": pcn_df,
    }


def load_poi_tables_from_db(database_url: str) -> dict[str, pd.DataFrame]:
    """Load POI points from ``poi_locations`` (populated by ``ingest_poi_assets.py``)."""
    from sqlalchemy import create_engine, text

    eng = create_engine(database_url)
    try:
        df = pd.read_sql(
            text(
                """
                SELECT poi_type, COALESCE(name, '') AS name, lat, lon
                FROM poi_locations
                WHERE (valid_from IS NULL OR valid_from <= CURRENT_DATE)
                  AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
                """
            ),
            eng,
        )
    finally:
        eng.dispose()
    if df.empty:
        raise ValueError("poi_locations is empty — run backend/scripts/ingest_poi_assets.py first.")

    out: dict[str, pd.DataFrame] = {}
    for db_type, frame_key in POI_DB_TYPE_TO_FRAME_KEY.items():
        sub = df.loc[df["poi_type"] == db_type, ["name", "lat", "lon"]].copy()
        if sub.empty:
            raise ValueError(f"poi_locations has no rows for poi_type={db_type!r}")
        out[frame_key] = sub
    return out


def poi_locations_populated(database_url: str) -> bool:
    """True if ``poi_locations`` exists and has at least one row."""
    from sqlalchemy import create_engine, text

    eng = create_engine(database_url)
    try:
        with eng.connect() as conn:
            row = conn.execute(text("SELECT 1 FROM poi_locations LIMIT 1")).first()
            return row is not None
    except Exception:
        return False
    finally:
        eng.dispose()


def append_poi_features(
    hdb: pd.DataFrame,
    pois: dict[str, pd.DataFrame],
    *,
    gravity_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Expects ``hdb`` to contain ``lat`` and ``lon`` columns."""
    df = hdb.copy()
    _ensure_lat_lon(df)
    gw = gravity_weights or {}
    w_malls = float(gw.get("malls", 1.2))
    w_schools = float(gw.get("schools", 1.0))
    w_parks = float(gw.get("parks", 1.0))
    w_markets = float(gw.get("markets", 0.9))

    cbd = (1.2830, 103.8513)
    airport = (1.3644, 103.9915)
    df["dist_cbd"] = haversine_vectorized(df["lat"], df["lon"], cbd[0], cbd[1])
    df["dist_airport"] = haversine_vectorized(df["lat"], df["lon"], airport[0], airport[1])
    df["dist_cbd"] = df["dist_cbd"].fillna(df["dist_cbd"].mean())
    df["dist_airport"] = df["dist_airport"].fillna(df["dist_airport"].mean())

    top_20_df = pois["top_20"]
    all_schools_df = pois["schools"]
    all_malls_df = pois["malls"]
    supermarkets_df = pois["supermarkets"]
    parks_df = pois["parks"]
    markets_df = pois["markets"]
    pcn_df = pois["pcn"]

    dist_top20 = get_nearest_dist(df, top_20_df)
    df["dist_nearest_top20_school"] = dist_top20
    df["within_1km_top20_school"] = (dist_top20 <= 1000).astype(int)
    df["within_1km_2km_top20_school"] = ((dist_top20 > 1000) & (dist_top20 <= 2000)).astype(int)

    dist_any_pri = get_nearest_dist(df, all_schools_df)
    df["dist_nearest_any_school"] = dist_any_pri
    df["within_1km_any_pri_school"] = (dist_any_pri <= 1000).astype(int)
    df["within_1km_2km_pri_school"] = ((dist_any_pri > 1000) & (dist_any_pri <= 2000)).astype(int)

    df["dist_nearest_mall"] = get_nearest_dist(df, all_malls_df)
    df["malls_within_2km"] = get_count_in_radius(df, all_malls_df, 2000)
    df["supermarkets_within_500m"] = get_count_in_radius(df, supermarkets_df, 500)
    df["markets_within_500m"] = get_count_in_radius(df, markets_df, 500)

    dist_park = get_nearest_dist(df, parks_df)
    df["dist_nearest_park"] = dist_park
    df["is_park_200m"] = (dist_park <= 200).astype(int)
    df["dist_nearest_pcn"] = get_nearest_dist(df, pcn_df)

    df["gravity_malls"] = calculate_gravity_component(df, all_malls_df, weight=w_malls)
    df["gravity_schools"] = calculate_gravity_component(df, all_schools_df, weight=w_schools)
    df["gravity_parks"] = calculate_gravity_component(df, parks_df, weight=w_parks)
    df["gravity_markets"] = calculate_gravity_component(df, markets_df, weight=w_markets)

    return df


def _log_lat_lon_coverage(before: int, after: int) -> None:
    if before <= 0:
        return
    dropped_pct = 100.0 * (before - after) / before
    if dropped_pct > 5.0:
        logger.warning(
            "Dropped %.1f%% of rows missing lat/lon before POI engineering (%d → %d).",
            dropped_pct,
            before,
            after,
        )


def engineer_poi_frame(
    raw: pd.DataFrame,
    *,
    merge_coords_csv: Path | None = None,
    include_mrt: bool = False,
    categorical_style: str = "legacy",
    project_root: Path | None = None,
    use_db: bool = False,
    database_url: str | None = None,
    gravity_weights: dict[str, float] | None = None,
    include_macro: bool = False,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Base (+ optional MRT) engineer, then POI features on rows with coordinates.
    Rows missing lat/lon are dropped before BallTree (Colab behaviour).

    If ``use_db`` is True, POI points are read from Postgres ``poi_locations``; otherwise
    from ``data/pois/`` files. ``database_url`` must be set when ``use_db`` is True.
    Set ``include_macro=True`` for HDB-Valuation_ext macro numerics appended before POIs.
    """
    from modelling.training_log import log_phase, training_logger

    root = project_root or repo_root()
    flog = training_logger("feature_sets")
    source = "postgres_poi_locations" if use_db else "local_files"
    log_kw: dict[str, Any] = {"source": source}
    if not use_db:
        log_kw["pois_dir"] = str(pois_dir(root.resolve()))
    log_phase(flog, "poi_engineer_source", **log_kw)

    frame = raw.copy()
    n_before = len(frame)
    if merge_coords_csv is not None:
        frame = merge_block_coordinates(frame, merge_coords_csv)
    _ensure_lat_lon(frame)
    frame = frame.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    _log_lat_lon_coverage(n_before, len(frame))
    if frame.empty:
        raise ValueError("No rows left after dropping missing lat/lon — cannot engineer POI features.")

    base = engineer_base_features(
        frame,
        categorical_style=categorical_style,  # type: ignore[arg-type]
        include_months_since_2015=bool(kwargs.get("include_months_since_2015")),
    )
    merged = append_mrt_features(base, frame, project_root=root) if include_mrt else base
    if include_macro:
        from modelling.features.macro_sentiment import append_macro_features

        merged = append_macro_features(merged, frame, project_root=root)
    # Base engineering already attaches ``lat``/``lon``; avoid duplicate columns from concat.
    hdb_geo = merged

    if use_db:
        if not database_url or not str(database_url).strip():
            raise ValueError("engineer_poi_frame(..., use_db=True) requires a non-empty database_url.")
        pois = load_poi_tables_from_db(str(database_url).strip())
    else:
        pois = load_poi_tables(root)
    return append_poi_features(hdb_geo, pois, gravity_weights=gravity_weights)
