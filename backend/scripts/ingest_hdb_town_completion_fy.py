#!/usr/bin/env python3
"""Ingest data.gov.sg *Completion Status of HDB Residential Units by Town/Estate* FY CSV."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
for p in (_HERE, _BACKEND, _REPO):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from db_env import load_repo_env, psycopg2_connect_dsn, resolve_admin_database_url  # noqa: E402

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

from hdb_resale_town_geo import normalize_hdb_town_label, singapore_fy_date_bounds  # noqa: E402
from modelling.storage.minio_io import ensure_bucket, object_exists, put_object_bytes  # noqa: E402
from minio import Minio  # noqa: E402
from minio.error import S3Error  # noqa: E402

DEFAULT_SOURCE = Path("data/CompletionStatusofHDBResidentialUnitsbyTownEstate.csv")
MINIO_KEY = "raw/datagovsg/CompletionStatusofHDBResidentialUnitsbyTownEstate.csv"
SOURCE_RESOURCE_ID = "d_9bbcd0c9b0351c7f41c9bfdcdc746668"


def _minio_client() -> Minio:
    host = (os.getenv("MINIO_HOST") or "").strip()
    ep = (os.getenv("MINIO_ENDPOINT") or "").strip() or (
        f"{host}:{os.getenv('MINIO_INNER_PORT', '9000')}" if host else "minio:9000"
    )
    return Minio(
        ep,
        access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "password123"),
        secure=False,
    )


def load_rows(csv_path: Path) -> list[tuple[Any, ...]]:
    import pandas as pd

    df = pd.read_csv(csv_path)
    need = {"financial_year", "town_or_estate", "hdb_or_dbss", "status", "no_of_units"}
    if not need.issubset(set(df.columns)):
        raise ValueError(f"CSV requires columns {need}; got {set(df.columns)}")

    out: list[tuple[Any, ...]] = []
    for _, row in df.iterrows():
        fy = int(row["financial_year"])
        fy0, fy1 = singapore_fy_date_bounds(fy)
        town = normalize_hdb_town_label(str(row["town_or_estate"]))
        scheme = str(row["hdb_or_dbss"]).strip().upper()
        status = str(row["status"]).strip()
        nu = int(row["no_of_units"])
        if nu < 0:
            raise ValueError(f"negative units row: {row.to_dict()}")
        out.append((fy, fy0, fy1, town, scheme, status, nu))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=None)
    ap.add_argument("--project-root", type=Path, default=_REPO)
    ap.add_argument("--skip-minio-upload", action="store_true")
    ap.add_argument("--force-minio", action="store_true")
    args = ap.parse_args(argv)
    root = args.project_root.resolve()
    src = (args.source or (root / DEFAULT_SOURCE)).expanduser().resolve()

    load_repo_env(root)

    if not src.is_file():
        print(f"ERROR: CSV not found: {src}", file=sys.stderr)
        return 1

    rows = load_rows(src)

    bucket = os.getenv("MINIO_DEFAULT_BUCKET", "datasets").strip() or "datasets"

    if not args.skip_minio_upload:
        try:
            cli = _minio_client()
            ensure_bucket(cli, bucket)
            if object_exists(bucket, MINIO_KEY, client=cli) and not args.force_minio:
                print(f"SKIP MinIO (exists): s3://{bucket}/{MINIO_KEY}")
            else:
                raw = src.read_bytes()
                put_object_bytes(
                    bucket, MINIO_KEY, raw, client=cli, content_type="text/csv;charset=utf-8"
                )
                print(f"PUT s3://{bucket}/{MINIO_KEY} ({len(raw)} bytes)")
        except S3Error as exc:
            print(f"WARN: MinIO upload skipped ({exc}); use --skip-minio-upload to silence.", file=sys.stderr)

    url = resolve_admin_database_url()
    ts = datetime.now(timezone.utc)
    sql = """
    INSERT INTO hdb_town_completion_fy (
        financial_year, fy_start_date, fy_end_date,
        town_normalized, scheme, status, n_units,
        source, source_resource_id, ingested_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, 'data.gov.sg', %s, %s
    )
    ON CONFLICT (financial_year, town_normalized, scheme, status) DO UPDATE SET
        fy_start_date = EXCLUDED.fy_start_date,
        fy_end_date = EXCLUDED.fy_end_date,
        n_units = EXCLUDED.n_units,
        source = EXCLUDED.source,
        source_resource_id = EXCLUDED.source_resource_id,
        ingested_at = EXCLUDED.ingested_at
    """
    conn = psycopg2.connect(psycopg2_connect_dsn(url))
    try:
        payload = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], SOURCE_RESOURCE_ID, ts) for r in rows]
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, sql, payload, page_size=500)
        conn.commit()
    finally:
        conn.close()

    print(f"Ingested {len(rows)} FY×town completion rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
