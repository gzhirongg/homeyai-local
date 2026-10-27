"""Slim POI pack: primary schools, hawkers (NEA markets), malls — no parks/PCN/gravity/CBD."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import bindparam, create_engine, text

from modelling.features.base import engineer_base_features, repo_root
from modelling.features.mrt_pit import append_mrt_features
from modelling.features.poi_distancing import (
    _ensure_lat_lon,
    _log_lat_lon_coverage,
    get_count_in_radius,
    get_nearest_dist,
    load_poi_tables,
    load_poi_tables_from_db,
    merge_block_coordinates,
    pois_dir,
)

logger = logging.getLogger(__name__)

POI_AMENITY_V2_NUMERIC_FEATURES = [
    "dist_nearest_primary_school",
    "is_within_1km_primary_school",
    "is_within_2km_primary_school",
    "dist_nearest_hawker",
    "hawker_count_within_1km",
    "dist_nearest_mall",
    "mall_count_within_1_5km",
]

# Columns read from ``hdb_poi_features`` (same BallTree logic as ``append_poi_features``).
_HDB_POI_FEATURES_MERGE_COLS = (
    "dist_nearest_any_school",
    "within_1km_any_pri_school",
    "within_1km_2km_pri_school",
    "dist_nearest_mall",
)


def fetch_hdb_poi_features_amenity_subset(database_url: str, addr_ids: list[Any]) -> pd.DataFrame:
    """Load precomputed school/mall scalars keyed by ``hdb_addr_id`` (chunks IN queries)."""
    ids = sorted({int(x) for x in addr_ids if x is not None and not (isinstance(x, float) and np.isnan(x))})
    if not ids:
        return pd.DataFrame(columns=["hdb_addr_id", *_HDB_POI_FEATURES_MERGE_COLS])

    eng = create_engine(database_url)
    cols_sql = ", ".join(["hdb_addr_id", *_HDB_POI_FEATURES_MERGE_COLS])
    stmt = text(
        f"SELECT {cols_sql} FROM hdb_poi_features WHERE hdb_addr_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))

    chunk_size = 4000
    parts: list[pd.DataFrame] = []
    try:
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            part = pd.read_sql(stmt, eng, params={"ids": chunk})
            if not part.empty:
                parts.append(part)
    finally:
        eng.dispose()

    if not parts:
        return pd.DataFrame(columns=["hdb_addr_id", *_HDB_POI_FEATURES_MERGE_COLS])
    return pd.concat(parts, ignore_index=True).drop_duplicates(subset=["hdb_addr_id"])


def _within_2km_from_db_rows(within_1km: pd.Series, within_band: pd.Series) -> pd.Series:
    """Match ``dist <= 2000`` given legacy DB flags (within 1 km OR (1 km, 2 km] band)."""
    a = pd.to_numeric(within_1km, errors="coerce").fillna(0).astype(int)
    b = pd.to_numeric(within_band, errors="coerce").fillna(0).astype(int)
    return ((a > 0) | (b > 0)).astype(int)


def append_poi_amenity_v2_features(
    hdb: pd.DataFrame,
    pois: dict[str, pd.DataFrame],
    *,
    hdb_poi_lookup: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Append seven numerics; optionally blend school/mall distance columns from ``hdb_poi_features``."""
    df = hdb.copy()
    _ensure_lat_lon(df)

    schools_df = pois["schools"]
    markets_df = pois["markets"]
    malls_df = pois["malls"]

    dist_pri = get_nearest_dist(df, schools_df)
    dist_hawker = get_nearest_dist(df, markets_df)
    hawker_1k = get_count_in_radius(df, markets_df, 1000.0)
    dist_mall_bt = get_nearest_dist(df, malls_df)
    mall_15k = get_count_in_radius(df, malls_df, 1500.0)

    df["dist_nearest_primary_school"] = dist_pri
    df["is_within_1km_primary_school"] = (dist_pri <= 1000).astype(int)
    df["is_within_2km_primary_school"] = (dist_pri <= 2000).astype(int)
    df["dist_nearest_hawker"] = dist_hawker
    df["hawker_count_within_1km"] = hawker_1k
    df["dist_nearest_mall"] = dist_mall_bt
    df["mall_count_within_1_5km"] = mall_15k

    if hdb_poi_lookup is None or hdb_poi_lookup.empty or "enriched_addr_id" not in df.columns:
        return df

    addr_key = pd.to_numeric(df["enriched_addr_id"], errors="coerce").astype("Int64")
    side = pd.DataFrame({"_addr_key": addr_key}).merge(
        hdb_poi_lookup,
        left_on="_addr_key",
        right_on="hdb_addr_id",
        how="left",
    )
    assert len(side) == len(df), "hdb_poi_features merge must be 1:1 on enriched_addr_id"

    has_pc = side["dist_nearest_any_school"].notna()
    if has_pc.any():
        df.loc[has_pc, "dist_nearest_primary_school"] = pd.to_numeric(
            side.loc[has_pc, "dist_nearest_any_school"], errors="coerce"
        ).to_numpy()

    w1 = pd.to_numeric(side["within_1km_any_pri_school"], errors="coerce")
    w2 = pd.to_numeric(side["within_1km_2km_pri_school"], errors="coerce")
    has_sw = w1.notna()
    if has_sw.any():
        df.loc[has_sw, "is_within_1km_primary_school"] = w1.fillna(0).astype(int).loc[has_sw].to_numpy()

    combined_2k = _within_2km_from_db_rows(w1, w2)
    has_2k = w1.notna() | w2.notna()
    if has_2k.any():
        df.loc[has_2k, "is_within_2km_primary_school"] = combined_2k.loc[has_2k].astype(int).to_numpy()

    d_mall_db = pd.to_numeric(side["dist_nearest_mall"], errors="coerce")
    has_m = d_mall_db.notna()
    if has_m.any():
        df.loc[has_m, "dist_nearest_mall"] = d_mall_db.loc[has_m].to_numpy()

    matched = has_pc | has_sw | has_m | has_2k
    if bool(matched.any()):
        logger.info(
            "POI amenity v2: blended school/mall scalars from hdb_poi_features for %d / %d rows.",
            int(matched.sum()),
            len(df),
        )

    return df


def engineer_poi_amenity_v2_frame(
    raw: pd.DataFrame,
    *,
    merge_coords_csv: Path | None = None,
    include_mrt: bool = False,
    categorical_style: str = "legacy",
    project_root: Path | None = None,
    use_db: bool = False,
    database_url: str | None = None,
    prefer_hdb_poi_features: bool = True,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Baseline (+ optional MRT), then seven amenity numerics.

    When ``use_db`` is True and ``prefer_hdb_poi_features`` is True, loads
    ``hdb_poi_features.dist_nearest_any_school``, ``within_1km_any_pri_school``,
    ``within_1km_2km_pri_school``, ``dist_nearest_mall`` for rows with
    ``enriched_addr_id`` (training frames from DB). Hawker distance/count and
    ``mall_count_within_1_5km`` are always computed from ``poi_locations`` BallTrees
    (not stored in ``hdb_poi_features``).
    """
    from modelling.training_log import log_phase, training_logger

    root = project_root or repo_root()
    flog = training_logger("feature_sets")
    source = "postgres_poi_locations" if use_db else "local_files"
    log_kw: dict[str, Any] = {"source": source, "pack": "poi_amenity_v2"}
    if not use_db:
        log_kw["pois_dir"] = str(pois_dir(root.resolve()))
    log_phase(flog, "poi_amenity_v2_engineer_source", **log_kw)

    frame = raw.copy()
    n_before = len(frame)
    if merge_coords_csv is not None:
        frame = merge_block_coordinates(frame, merge_coords_csv)
    _ensure_lat_lon(frame)
    frame = frame.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    _log_lat_lon_coverage(n_before, len(frame))
    if frame.empty:
        raise ValueError("No rows left after dropping missing lat/lon — cannot engineer POI amenity v2.")

    addr_col = frame["enriched_addr_id"] if "enriched_addr_id" in frame.columns else None

    base = engineer_base_features(
        frame,
        categorical_style=categorical_style,  # type: ignore[arg-type]
        include_months_since_2015=bool(kwargs.get("include_months_since_2015")),
    )
    merged = append_mrt_features(base, frame, project_root=root) if include_mrt else base

    if addr_col is not None:
        merged = merged.copy()
        merged["enriched_addr_id"] = addr_col.values

    hdb_lookup: pd.DataFrame | None = None
    if (
        prefer_hdb_poi_features
        and use_db
        and database_url
        and str(database_url).strip()
        and addr_col is not None
    ):
        try:
            hdb_lookup = fetch_hdb_poi_features_amenity_subset(
                str(database_url).strip(),
                addr_col.dropna().tolist(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("hdb_poi_features merge skipped: %s", exc)
            hdb_lookup = None

    if use_db:
        if not database_url or not str(database_url).strip():
            raise ValueError(
                "engineer_poi_amenity_v2_frame(..., use_db=True) requires a non-empty database_url."
            )
        pois = load_poi_tables_from_db(str(database_url).strip())
    else:
        pois = load_poi_tables(root)

    out = append_poi_amenity_v2_features(merged, pois, hdb_poi_lookup=hdb_lookup)
    if "enriched_addr_id" in out.columns:
        out = out.drop(columns=["enriched_addr_id"])
    return out
