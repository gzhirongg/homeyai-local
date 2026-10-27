"""Build narrow training Parquet datasets on the Prefect worker and upload to MinIO."""

from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.engine import Engine

from modelling.config.feature_modules import (
    TAG_ESTATE_MATURITY,
    TAG_MASTERPLAN_LANDUSE,
    TAG_MRT_PIT,
    TAG_RESALE_BASELINE,
    feature_modules_for_feature_set,
)
from modelling.runners.export_training_snapshot import BUCKET_DATASETS
from modelling.storage import minio_io
from modelling.town_geo import normalize_hdb_town_label
from modelling.training_db import (
    create_training_engine,
    get_mrt_pit_min_years,
    get_training_window_summary,
    query_baseline_resale_dataframe,
    query_estate_maturity_window_dataframe,
    query_masterplan_landuse_window_dataframe,
    query_mrt_pit_features_window_dataframe,
)
from sqlalchemy import text

TRAINING_DATASET_PREFIX = "training_datasets/v2"


def dataset_cache_key(feature_set_id: str, min_years: int) -> str:
    """Stable MinIO folder name for a feature_set + rolling window definition."""
    payload = f"{feature_set_id}|mrt_years={min_years}|build=v2".encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def _estate_merge_town_keys(town: pd.Series) -> pd.Series:
    """Align resale ``town`` strings with ``hdb_estate_maturity_by_town_month.town_normalized``."""
    return town.map(lambda v: normalize_hdb_town_label(None if pd.isna(v) else v))


def _merge_left_features(
    base: pd.DataFrame,
    extra: pd.DataFrame,
    *,
    join_cols: list[str],
    label: str,
) -> pd.DataFrame:
    if extra.empty:
        return base
    dup_cols = [c for c in extra.columns if c in base.columns and c not in join_cols]
    if dup_cols:
        extra = extra.drop(columns=dup_cols, errors="ignore")
    feat_cols = [c for c in extra.columns if c not in join_cols]
    return base.merge(extra[join_cols + feat_cols], on=join_cols, how="left", suffixes=("", f"_{label}_dup"))


def build_training_dataframe(
    _project_root: Path,
    engine: Engine,
    feature_set_id: str,
    *,
    min_years: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Query only the SQL pillars needed for ``feature_set_id`` and merge into one frame."""
    tags = feature_modules_for_feature_set(feature_set_id)
    my = int(min_years) if min_years is not None else get_mrt_pit_min_years()
    join_cols = ["enriched_addr_id", "month"]

    if TAG_RESALE_BASELINE not in tags:
        raise RuntimeError("Internal error: resale_baseline missing from feature module tags")

    df = query_baseline_resale_dataframe(engine, min_years=my)

    skip_eligible = os.environ.get("TRAINING_SKIP_ELIGIBLE_ROW_CHECK", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if not skip_eligible:
        summary = get_training_window_summary(engine, min_years=my)
        n_eligible = int(summary["n_eligible_tx"])
        if len(df) != n_eligible:
            raise RuntimeError(
                f"Training dataset baseline row count ({len(df):,}) != n_eligible_tx ({n_eligible:,}); "
                "baseline SQL and window summary disagree—fix joins or window logic before merging pillars."
            )
    n_tx = len(df)

    if TAG_MRT_PIT in tags:
        mrt = query_mrt_pit_features_window_dataframe(engine, min_years=my)
        df = _merge_left_features(df, mrt, join_cols=join_cols, label="mrt")

    if TAG_MASTERPLAN_LANDUSE in tags:
        mp = query_masterplan_landuse_window_dataframe(engine, min_years=my)
        n_before_mp = len(df)
        if not mp.empty:
            missing_mp = [c for c in join_cols if c not in mp.columns]
            if missing_mp:
                raise RuntimeError(
                    f"Masterplan frame missing join columns {missing_mp}; cannot merge land-use features."
                )
            mp = mp.drop_duplicates(subset=join_cols, keep="first")
        df = _merge_left_features(df, mp, join_cols=join_cols, label="mp")
        if not mp.empty and len(df) != n_before_mp:
            raise RuntimeError(
                f"Masterplan merge changed row count ({n_before_mp} -> {len(df)}); "
                "right-hand join keys must be unique per (enriched_addr_id, month)."
            )

    if TAG_ESTATE_MATURITY in tags:
        n_before_estate = len(df)
        if "town" not in df.columns:
            raise RuntimeError("Estate maturity merge requires column 'town' on the baseline frame.")
        df = df.copy()
        df["_town_norm"] = _estate_merge_town_keys(df["town"])
        em = query_estate_maturity_window_dataframe(engine, min_years=my)
        em_merge = em.rename(columns={"town_normalized": "_town_norm"})
        df = _merge_left_features(df, em_merge, join_cols=["_town_norm", "month"], label="estate")
        df = df.drop(columns=["_town_norm"])
        if len(df) != n_before_estate:
            raise RuntimeError(
                f"Estate maturity merge changed row count ({n_before_estate} -> {len(df)}); "
                "right-hand join keys must be unique (panel grain)."
            )

    if len(df) != n_tx:
        raise RuntimeError(
            f"Feature merges changed row count ({n_tx} -> {len(df)}); "
            "check for duplicate join keys on the right-hand side of pillar merges."
        )

    window_start = window_end = ""
    max_tx_month = ""
    if "month" in df.columns and len(df):
        months = df["month"].astype(str)
        window_start = str(months.min())
        window_end = max_tx_month = str(months.max())

    manifest: dict[str, Any] = {
        "schema": "training_dataset_v2",
        "feature_set_id": feature_set_id,
        "build_modules": list(tags),
        "mrt_pit_min_years": my,
        "row_count": int(len(df)),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "column_count": int(len(df.columns)),
        "columns": [str(c) for c in df.columns],
        "max_tx_month": max_tx_month,
        "window_start_month": window_start,
        "window_end_month": window_end,
    }
    return df, manifest


def upload_training_dataset_to_minio(
    df: pd.DataFrame,
    manifest: dict[str, Any],
    dataset_key: str,
    *,
    client=None,
) -> None:
    """Write ``dataset.parquet`` + ``manifest.json`` under ``training_datasets/v2/{dataset_key}/``."""
    prefix = f"{TRAINING_DATASET_PREFIX}/{dataset_key.strip().strip('/')}/"
    parquet_key = f"{prefix}dataset.parquet"
    manifest_key = f"{prefix}manifest.json"

    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    raw_pq = buf.getvalue()
    minio_io.put_object_bytes(BUCKET_DATASETS, parquet_key, raw_pq, content_type="application/octet-stream", client=client)

    manifest_bytes = json.dumps(manifest, indent=2, default=str).encode("utf-8")
    minio_io.put_object_bytes(BUCKET_DATASETS, manifest_key, manifest_bytes, content_type="application/json", client=client)


def dynamic_dataset_manifest_age_hours(dataset_key: str, *, client=None) -> float | None:
    """Hours since ``training_datasets/v2/{key}/manifest.json`` was written."""
    key = f"{TRAINING_DATASET_PREFIX}/{dataset_key.strip().strip('/')}/manifest.json"
    if not minio_io.object_exists(BUCKET_DATASETS, key, client=client):
        return None
    try:
        doc = json.loads(minio_io.get_object_bytes(BUCKET_DATASETS, key, client=client).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    updated = str(doc.get("created_at") or "").strip()
    if not updated:
        return None
    try:
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0


def fetch_dynamic_dataset_manifest(dataset_key: str, *, client=None) -> dict[str, Any] | None:
    """Load ``manifest.json`` for a v2 cache key, or ``None`` if missing/unreadable."""
    key = f"{TRAINING_DATASET_PREFIX}/{dataset_key.strip().strip('/')}/manifest.json"
    if not minio_io.object_exists(BUCKET_DATASETS, key, client=client):
        return None
    try:
        return json.loads(minio_io.get_object_bytes(BUCKET_DATASETS, key, client=client).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def query_db_max_resale_tx_month(engine: Engine) -> str | None:
    """Latest ``hdb_resale_transactions.month`` as ``YYYY-MM`` text (cheap cache invalidation probe)."""
    with engine.connect() as conn:
        row = conn.execute(text("SELECT MAX(month)::text AS m FROM hdb_resale_transactions")).fetchone()
    if not row or row[0] is None:
        return None
    return str(row[0]).strip()


def training_dataset_parquet_object_key(dataset_version: str) -> str:
    """MinIO object key (inside ``datasets`` bucket) for training parquet (legacy or v2)."""
    from modelling.data.snapshot_loader import is_legacy_snapshot_dataset_version
    from modelling.runners.export_training_snapshot import SNAPSHOT_PREFIX

    ver = str(dataset_version).strip().strip("/")
    if is_legacy_snapshot_dataset_version(ver):
        return f"{SNAPSHOT_PREFIX}/{ver}/hdb_resale.parquet"
    return f"{TRAINING_DATASET_PREFIX}/{ver}/dataset.parquet"


def build_upload_resolve_dataset_key(
    project_root: Path,
    feature_set_id: str,
    *,
    force_rebuild: bool = False,
    client=None,
    min_years: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build dataframe, upload to MinIO, return cache key and manifest.

    ``force_rebuild`` documents intent for callers (always runs SQL + overwrites the cache key).
    """
    _ = force_rebuild
    my = int(min_years) if min_years is not None else get_mrt_pit_min_years()
    key = dataset_cache_key(feature_set_id, my)
    engine = create_training_engine()
    try:
        df, manifest = build_training_dataframe(project_root, engine, feature_set_id, min_years=my)
        upload_training_dataset_to_minio(df, manifest, key, client=client)
        return key, manifest
    finally:
        engine.dispose()


__all__ = [
    "TRAINING_DATASET_PREFIX",
    "build_training_dataframe",
    "build_upload_resolve_dataset_key",
    "dataset_cache_key",
    "dynamic_dataset_manifest_age_hours",
    "fetch_dynamic_dataset_manifest",
    "query_db_max_resale_tx_month",
    "training_dataset_parquet_object_key",
    "upload_training_dataset_to_minio",
]
