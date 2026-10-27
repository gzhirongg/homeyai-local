"""AB pack: top-20 primary school counts per distance band (no distance column)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from modelling.features.base import engineer_base_features, repo_root
from modelling.features.mrt_pit import append_mrt_features
from modelling.features.poi_distancing import (
    _ensure_lat_lon,
    _log_lat_lon_coverage,
    get_count_in_radius,
    load_poi_tables,
    load_poi_tables_from_db,
    merge_block_coordinates,
    pois_dir,
)

PRIMARY_SCHOOL_NUMERIC = [
    "count_top20_schools_within_1km",
    "count_top20_schools_within_1km_2km",
]


def append_primary_school_features(
    hdb: pd.DataFrame,
    pois: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Append counts of top-20 schools in ``[0, 1 km]`` and ``(1 km, 2 km]`` annuli."""
    df = hdb.copy()
    _ensure_lat_lon(df)

    top_20_df = pois["top_20"]
    c_1k = get_count_in_radius(df, top_20_df, 1000.0)
    c_2k = get_count_in_radius(df, top_20_df, 2000.0)
    df["count_top20_schools_within_1km"] = c_1k.astype(int)
    df["count_top20_schools_within_1km_2km"] = np.maximum(
        np.asarray(c_2k, dtype=np.int64) - np.asarray(c_1k, dtype=np.int64),
        0,
    ).astype(int)

    return df


def engineer_primary_school_frame(
    raw: pd.DataFrame,
    *,
    merge_coords_csv: Path | None = None,
    include_mrt: bool = False,
    categorical_style: str = "legacy",
    project_root: Path | None = None,
    use_db: bool = False,
    database_url: str | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Baseline (+ optional MRT), then two top-20 school count columns.

    Does **not** expose ``dist_nearest_top20_school``. Counts are always computed
    from POI points (``data/pois/`` or ``poi_locations``); ``hdb_poi_features``
    stores binaries only and is not blended here.
    """
    from modelling.training_log import log_phase, training_logger

    root = project_root or repo_root()
    flog = training_logger("feature_sets")
    source = "postgres_poi_locations" if use_db else "local_files"
    log_kw: dict[str, Any] = {"source": source, "pack": "primary_school"}
    if not use_db:
        log_kw["pois_dir"] = str(pois_dir(root.resolve()))
    log_phase(flog, "primary_school_engineer_source", **log_kw)

    frame = raw.copy()
    n_before = len(frame)
    if merge_coords_csv is not None:
        frame = merge_block_coordinates(frame, merge_coords_csv)
    _ensure_lat_lon(frame)
    frame = frame.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    _log_lat_lon_coverage(n_before, len(frame))
    if frame.empty:
        raise ValueError("No rows left after dropping missing lat/lon — cannot engineer primary_school.")

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

    if use_db:
        if not database_url or not str(database_url).strip():
            raise ValueError(
                "engineer_primary_school_frame(..., use_db=True) requires a non-empty database_url."
            )
        pois = load_poi_tables_from_db(str(database_url).strip())
    else:
        pois = load_poi_tables(root)

    out = append_primary_school_features(merged, pois)
    if "enriched_addr_id" in out.columns:
        out = out.drop(columns=["enriched_addr_id"])
    return out


def engineer_mrt_landuse_primary_school_frame(
    raw: pd.DataFrame,
    *,
    merge_coords_csv: Path | None = None,
    categorical_style: str = "legacy",
    project_root: Path | None = None,
    use_db: bool = False,
    database_url: str | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Baseline + masterplan land-use PIT + MRT PIT + top-20 school counts (no macro)."""
    from modelling.features.masterplan_landuse_pit import append_masterplan_landuse_from_raw_columns
    from modelling.training_log import log_phase, training_logger

    root = project_root or repo_root()
    flog = training_logger("feature_sets")
    source = "postgres_poi_locations" if use_db else "local_files"
    log_kw: dict[str, Any] = {"source": source, "pack": "mrt_landuse_primary_school"}
    if not use_db:
        log_kw["pois_dir"] = str(pois_dir(root.resolve()))
    log_phase(flog, "primary_school_engineer_source", **log_kw)

    frame = raw.copy()
    n_before = len(frame)
    if merge_coords_csv is not None:
        frame = merge_block_coordinates(frame, merge_coords_csv)
    _ensure_lat_lon(frame)
    frame = frame.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    _log_lat_lon_coverage(n_before, len(frame))
    if frame.empty:
        raise ValueError(
            "No rows left after dropping missing lat/lon — cannot engineer mrt_landuse_primary_school."
        )

    addr_col = frame["enriched_addr_id"] if "enriched_addr_id" in frame.columns else None

    base = engineer_base_features(
        frame,
        categorical_style=categorical_style,  # type: ignore[arg-type]
        include_months_since_2015=bool(kwargs.get("include_months_since_2015")),
    )
    merged = append_masterplan_landuse_from_raw_columns(base, frame, require_columns=False)
    merged = append_mrt_features(merged, frame, project_root=root)

    if addr_col is not None:
        merged = merged.copy()
        merged["enriched_addr_id"] = addr_col.values

    if use_db:
        if not database_url or not str(database_url).strip():
            raise ValueError(
                "engineer_mrt_landuse_primary_school_frame(..., use_db=True) requires database_url."
            )
        pois = load_poi_tables_from_db(str(database_url).strip())
    else:
        pois = load_poi_tables(root)

    out = append_primary_school_features(merged, pois)
    if "enriched_addr_id" in out.columns:
        out = out.drop(columns=["enriched_addr_id"])
    return out
