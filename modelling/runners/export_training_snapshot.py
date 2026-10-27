"""Export read-only DB training frame to MinIO Parquet snapshots (``datasets`` bucket)."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from minio import Minio

from modelling.features.mrt_pit import validate_mrt_line_registry as _validate_mrt_lines
from modelling.storage import minio_io
from modelling.training_db import load_hdb_mrt_pit_snapshot_dataframe, load_hdb_resale_dataframe_from_db

BUCKET_DATASETS = "datasets"
SNAPSHOT_PREFIX = "training_snapshots"


def _utc_version() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def export_training_snapshot_to_minio(
    project_root: Path,
    *,
    version: str | None = None,
    include_mrt_pit_snapshot: bool = True,
    dataframe: Any | None = None,
    skip_mrt_line_validate: bool = False,
    minio_client: Minio | None = None,
    include_local_mrt_parquet: bool | None = None,
) -> dict[str, Any]:
    """
    Load full HDB resale frame from Postgres (read-only), validate MRT registry,
    upload ``hdb_resale.parquet`` plus optional ``hdb_mrt_features.parquet`` sidecar derived from Postgres
    (``hdb_mrt_features_pit_snapshot``), write ``manifest.json``, update ``training_snapshots/_latest.json``.

    If ``dataframe`` is provided (e.g. limited bootstrap for Modal smoke tests), DB load is skipped.
    Legacy ``include_local_mrt_parquet`` maps onto ``include_mrt_pit_snapshot``.
    """
    if include_local_mrt_parquet is not None:
        include_mrt_pit_snapshot = bool(include_local_mrt_parquet)
    root = project_root.resolve()
    if dataframe is None:
        df = load_hdb_resale_dataframe_from_db()
    else:
        df = dataframe
    if not skip_mrt_line_validate:
        _validate_mrt_lines(df, root)

    ver = (version or _utc_version()).strip().strip("/")
    base_prefix = f"{SNAPSHOT_PREFIX}/{ver}/"

    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    resale_bytes = buf.getvalue()
    resale_sha = hashlib.sha256(resale_bytes).hexdigest()

    sale_span: dict[str, str] = {}
    if "month" in df.columns and len(df):
        months = df["month"].astype(str)
        sale_span = {"month_min": str(months.min()), "month_max": str(months.max())}

    manifest: dict[str, Any] = {
        "version": ver,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "row_count": int(len(df)),
        "hdb_resale_sha256": resale_sha,
        "sale_span": sale_span,
        "includes_mrt_sidecar": False,
    }

    c = minio_client or minio_io.minio_client()
    minio_io.put_object_bytes(BUCKET_DATASETS, f"{base_prefix}hdb_resale.parquet", resale_bytes, client=c)

    if include_mrt_pit_snapshot:
        try:
            snap_df = load_hdb_mrt_pit_snapshot_dataframe()
            mbuf = io.BytesIO()
            snap_df.to_parquet(mbuf, index=False)
            mrt_bytes = mbuf.getvalue()
            minio_io.put_object_bytes(
                BUCKET_DATASETS,
                f"{base_prefix}hdb_mrt_features.parquet",
                mrt_bytes,
                client=c,
            )
            manifest["includes_mrt_sidecar"] = True
            manifest["hdb_mrt_features_sha256"] = hashlib.sha256(mrt_bytes).hexdigest()
        except Exception as exc:  # noqa: BLE001
            manifest["includes_mrt_sidecar"] = False
            manifest["mrt_snapshot_export_error"] = str(exc)

    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    minio_io.put_object_bytes(BUCKET_DATASETS, f"{base_prefix}manifest.json", manifest_bytes, client=c)

    pointer = {
        "version": ver,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": manifest["row_count"],
    }
    minio_io.put_object_bytes(
        BUCKET_DATASETS,
        f"{SNAPSHOT_PREFIX}/_latest.json",
        json.dumps(pointer, indent=2).encode("utf-8"),
        client=c,
    )
    return manifest
