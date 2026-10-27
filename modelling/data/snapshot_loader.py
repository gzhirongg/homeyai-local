"""Load versioned training snapshots from MinIO ``datasets/training_snapshots/``."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from modelling.data.dataset_builder import TRAINING_DATASET_PREFIX
from modelling.runners.export_training_snapshot import BUCKET_DATASETS, SNAPSHOT_PREFIX
from modelling.storage import minio_io
from modelling.training_log import log_phase, training_logger

_snap_log = training_logger("snapshot")

_LATEST_KEY = f"{SNAPSHOT_PREFIX}/_latest.json"


def snapshot_age_hours(*, client=None) -> tuple[float | None, str | None]:
    """Hours since ``_latest.json`` was written; version string when pointer exists."""
    if not minio_io.object_exists(BUCKET_DATASETS, _LATEST_KEY, client=client):
        return None, None
    raw = minio_io.get_object_bytes(BUCKET_DATASETS, _LATEST_KEY, client=client)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, None
    ver = str(doc.get("version") or "").strip() or None
    updated = str(doc.get("updated_at") or "").strip()
    if not updated:
        return None, ver
    try:
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return None, ver
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0
    return age_h, ver


_LEGACY_TS = re.compile(r"^\d{8}T\d{6}Z$")


def is_legacy_snapshot_dataset_version(version: str) -> bool:
    """True for exported snapshot folders ``YYYYMMDDTHHMMSSZ`` under ``training_snapshots/``."""
    return bool(_LEGACY_TS.fullmatch(str(version).strip()))


def load_training_frame_from_dataset_version(
    dataset_version: str,
    project_root: Path,
    *,
    client=None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load training frame from legacy snapshot layout or ``training_datasets/v2`` dynamic build."""
    ver = str(dataset_version).strip().strip("/")
    if not ver:
        raise ValueError("dataset_version is required")
    if is_legacy_snapshot_dataset_version(ver):
        return load_training_frame_from_snapshot(ver, project_root, client=client)

    parquet_key = f"{TRAINING_DATASET_PREFIX}/{ver}/dataset.parquet"
    log_phase(
        _snap_log,
        "dynamic_dataset_check_start",
        bucket=BUCKET_DATASETS,
        key=parquet_key,
        dataset_version=ver,
    )
    t0 = time.perf_counter()
    if not minio_io.object_exists(BUCKET_DATASETS, parquet_key, client=client):
        raise FileNotFoundError(
            f"No training dataset at {BUCKET_DATASETS}/{parquet_key} "
            f"(expected legacy snapshot timestamp or v2 cache key)"
        )
    df = minio_io.load_parquet_dataframe(BUCKET_DATASETS, parquet_key, client=client)
    manifest_key = f"{TRAINING_DATASET_PREFIX}/{ver}/manifest.json"
    manifest: dict[str, Any] = {}
    if minio_io.object_exists(BUCKET_DATASETS, manifest_key, client=client):
        try:
            manifest = json.loads(
                minio_io.get_object_bytes(BUCKET_DATASETS, manifest_key, client=client).decode("utf-8")
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            manifest = {}

    mr = manifest.get("row_count")
    if manifest.get("schema") == "training_dataset_v2" and mr is not None:
        try:
            expected_rows = int(mr)
        except (TypeError, ValueError):
            expected_rows = None
        if expected_rows is not None and len(df) != expected_rows:
            raise RuntimeError(
                f"Training dataset Parquet has {len(df)} rows but manifest.json declares row_count={expected_rows} "
                f"({BUCKET_DATASETS}/{parquet_key}; manifest {manifest_key})"
            )

    month_min = month_max = ""
    if "month" in df.columns and len(df):
        months = df["month"].astype(str)
        month_min, month_max = str(months.min()), str(months.max())

    loader_meta: dict[str, Any] = {
        "from_db": False,
        "training_source": f"minio_training_dataset_v2:{ver}",
        "dataset_path": f"minio:{BUCKET_DATASETS}/{parquet_key}",
        "mrt_features_path": "",
        "masterplan_landuse_path": "",
        "masterplan_source": "postgresql_normalized",
        "merge_masterplan": False,
        "min_tx_month": month_min,
        "dataset_version": ver,
        "snapshot_manifest": manifest,
    }
    if month_max:
        loader_meta["dataset_month_max"] = month_max
    _ = project_root
    log_phase(
        _snap_log,
        "dynamic_dataset_load_complete",
        dataset_version=ver,
        final_rows=len(df),
        final_cols=len(df.columns),
        elapsed_s=round(time.perf_counter() - t0, 3),
    )
    return df, loader_meta


def load_training_frame_from_snapshot(
    dataset_version: str,
    project_root: Path,
    *,
    client=None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load ``hdb_resale.parquet`` for ``dataset_version``; optional MRT sidecar merge."""
    ver = str(dataset_version).strip().strip("/")
    if not ver:
        raise ValueError("dataset_version is required")
    base_prefix = f"{SNAPSHOT_PREFIX}/{ver}/"
    resale_key = f"{base_prefix}hdb_resale.parquet"
    log_phase(_snap_log, "snapshot_resale_check_start", bucket=BUCKET_DATASETS, key=resale_key, dataset_version=ver)
    t0 = time.perf_counter()
    if not minio_io.object_exists(BUCKET_DATASETS, resale_key, client=client):
        raise FileNotFoundError(f"No snapshot at {BUCKET_DATASETS}/{resale_key}")

    log_phase(_snap_log, "snapshot_resale_load_start", key=resale_key)
    df = minio_io.load_parquet_dataframe(BUCKET_DATASETS, resale_key, client=client)
    log_phase(
        _snap_log,
        "snapshot_resale_loaded",
        rows=len(df),
        cols=len(df.columns),
        elapsed_s=round(time.perf_counter() - t0, 3),
    )
    mrt_key = f"{base_prefix}hdb_mrt_features.parquet"
    mrt_path_label = ""
    if minio_io.object_exists(BUCKET_DATASETS, mrt_key, client=client):
        t_mrt = time.perf_counter()
        mrt_df = minio_io.load_parquet_dataframe(BUCKET_DATASETS, mrt_key, client=client)
        mrt_path_label = f"minio:{BUCKET_DATASETS}/{mrt_key}"
        join_cols = [c for c in ("enriched_addr_id", "hdb_addr_id", "month", "tx_year_month") if c in df.columns and c in mrt_df.columns]
        if {"enriched_addr_id", "month"}.issubset(df.columns) and {"hdb_addr_id", "tx_year_month"}.issubset(mrt_df.columns):
            mrt_df = mrt_df.rename(columns={"hdb_addr_id": "enriched_addr_id", "tx_year_month": "month"})
            join_cols = ["enriched_addr_id", "month"]
        if join_cols:
            mrt_cols = [c for c in mrt_df.columns if c not in join_cols]
            df = df.merge(mrt_df[join_cols + mrt_cols], on=join_cols, how="left", suffixes=("", "_mrt_dup"))
            log_phase(
                _snap_log,
                "snapshot_mrt_merged",
                mrt_rows=len(mrt_df),
                join_cols=",".join(join_cols),
                elapsed_s=round(time.perf_counter() - t_mrt, 3),
            )
        else:
            log_phase(_snap_log, "snapshot_mrt_present_no_join", key=mrt_key)
    else:
        log_phase(_snap_log, "snapshot_mrt_skip", reason="object_missing")

    manifest_key = f"{base_prefix}manifest.json"
    manifest: dict[str, Any] = {}
    if minio_io.object_exists(BUCKET_DATASETS, manifest_key, client=client):
        try:
            manifest = json.loads(
                minio_io.get_object_bytes(BUCKET_DATASETS, manifest_key, client=client).decode("utf-8")
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            manifest = {}

    month_min = month_max = ""
    if "month" in df.columns and len(df):
        months = df["month"].astype(str)
        month_min, month_max = str(months.min()), str(months.max())

    loader_meta: dict[str, Any] = {
        "from_db": False,
        "training_source": f"minio_snapshot:{ver}",
        "dataset_path": f"minio:{BUCKET_DATASETS}/{resale_key}",
        "mrt_features_path": mrt_path_label,
        "masterplan_landuse_path": "",
        "masterplan_source": "postgresql_normalized",
        "merge_masterplan": False,
        "min_tx_month": month_min,
        "dataset_version": ver,
        "snapshot_manifest": manifest,
    }
    if month_max:
        loader_meta["dataset_month_max"] = month_max
    _ = project_root  # reserved for future manifest-relative paths
    key_cols = [c for c in ("month", "town", "resale_price") if c in df.columns]
    log_phase(
        _snap_log,
        "snapshot_load_complete",
        dataset_version=ver,
        final_rows=len(df),
        final_cols=len(df.columns),
        key_columns_present=",".join(sorted(set(key_cols))),
    )
    return df, loader_meta
