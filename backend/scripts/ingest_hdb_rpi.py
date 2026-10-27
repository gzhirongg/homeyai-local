#!/usr/bin/env python3
"""Archive HDB RPI CSV to MinIO (manifest + sentiment cache paths) and upsert Postgres.

Loads ``data/HDBResalePriceIndex1Q2009100Quarterly.csv`` (or ``--source``), writes canonical
``data/macro/hdb_rpi.csv``, uploads to MinIO when both standard keys are missing (unless
``--force-minio``), and upserts ``hdb_resale_price_index``.

Requires admin DB URL (same as other ingest scripts) and ``MINIO_*`` unless
``--skip-minio-upload``.

Run order::

    cd backend && alembic upgrade head

    PYTHONPATH=. python backend/scripts/ingest_hdb_rpi.py

Docker dev::

    ./scripts/docker_dev_backend.sh python /app/scripts/ingest_hdb_rpi.py
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from minio import Minio
from minio.error import S3Error

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from db_env import load_repo_env, psycopg2_connect_dsn, resolve_admin_database_url  # noqa: E402

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

from modelling.config.minio_sources import load_minio_sources_dict, resolve_object  # noqa: E402
from modelling.storage.minio_io import ensure_bucket, object_exists, put_object_bytes  # noqa: E402

from rpi_parse import dataframe_to_normalized_csv_bytes, load_normalized_rpi_rows  # noqa: E402

DEFAULT_SOURCE = Path("data/HDBResalePriceIndex1Q2009100Quarterly.csv")
STAGING_MACRO = Path("data/macro/hdb_rpi.csv")
RAW_RPI_MIRROR_KEY = "raw/hdb_rpi.csv"
ARCHIVE_NAME = "HDBResalePriceIndex1Q2009100Quarterly.csv"
RPI_SOURCE = "data.gov.sg"
RPI_RESOURCE_ID = "d_14f63e595975691e7c24a27ae4c07c79"
RPI_BASE_REF = "2009-Q1=100"


def _minio_endpoint() -> str:
    if not (os.getenv("MINIO_ENDPOINT") or "").strip():
        host = (os.getenv("MINIO_HOST") or "").strip()
        port = (os.getenv("MINIO_INNER_PORT") or "9000").strip()
        if host:
            os.environ["MINIO_ENDPOINT"] = f"{host}:{port}"
    return os.getenv("MINIO_ENDPOINT", "minio:9000")


def _minio_client_build() -> Minio:
    return Minio(
        _minio_endpoint(),
        access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "password123"),
        secure=False,
    )


def _upload_if_needed(
    client: Minio,
    bucket: str,
    key: str,
    data: bytes,
    *,
    force: bool,
    exists: bool,
    content_type: str = "text/csv;charset=utf-8",
) -> None:
    if exists and not force:
        print(f"SKIP upload (already exists): s3://{bucket}/{key}")
        return
    put_object_bytes(bucket, key, data, client=client, content_type=content_type)
    print(f"PUT s3://{bucket}/{key} ({len(data)} bytes)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=f"CSV path (default: repo-root {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_REPO,
        help="Repository root.",
    )
    parser.add_argument(
        "--skip-minio-upload",
        action="store_true",
        help="Only Postgres (no MinIO); use when object store is unreachable.",
    )
    parser.add_argument("--force-minio", action="store_true", help="Overwrite MinIO keys if they exist.")
    parser.add_argument("--dry-run", action="store_true", help="Validate + plan; no MinIO or DB writes.")

    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    src = (args.source or (root / DEFAULT_SOURCE)).expanduser().resolve()

    load_repo_env(root)

    if not src.is_file():
        print(f"ERROR: source CSV not found: {src}", file=sys.stderr)
        return 1

    try:
        rows, normalized_df = load_normalized_rpi_rows(src)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    n = len(rows)
    csv_bytes = dataframe_to_normalized_csv_bytes(normalized_df)
    staging = root / STAGING_MACRO

    print(f"Parsed {n} quarterly rows from {src.name}")
    if args.dry_run:
        try:
            cfg = load_minio_sources_dict(root)
            bk = resolve_object(cfg, "macro_rpi_csv")
            print("[dry-run] MinIO canonical keys:")
            print(f"  macro_rpi: s3://{bk.bucket}/{bk.key}")
            print(f"  mirror:    s3://{(cfg.get('default_bucket') or 'datasets').strip()}/{RAW_RPI_MIRROR_KEY}")
            print(f"  archive:   s3://{(cfg.get('default_bucket') or 'datasets').strip()}/raw/hdb_rpi/{ARCHIVE_NAME}")
        except (FileNotFoundError, KeyError, OSError, ValueError) as e:
            print(f"[dry-run] MinIO manifest not resolved: {e}")
        print("[dry-run] Would write staging CSV and run MinIO preflight + Postgres upsert.")
        return 0

    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(csv_bytes)
    print(f"Wrote canonical staging CSV: {staging}")

    bucket_default = "datasets"
    bk_train_bucket = bk_train_key = ""

    client: Minio | None = None

    if not args.skip_minio_upload:
        try:
            cfg = load_minio_sources_dict(root)
            bucket_default = (cfg.get("default_bucket") or "datasets").strip()
            bk = resolve_object(cfg, "macro_rpi_csv")
            bk_train_bucket, bk_train_key = bk.bucket, bk.key
        except (FileNotFoundError, KeyError, OSError, ValueError) as e:
            print(f"ERROR: MinIO manifest resolve failed: {e}", file=sys.stderr)
            return 1

        try:
            client = _minio_client_build()
            ensure_bucket(client, bk_train_bucket)
            if bk_train_bucket != bucket_default:
                ensure_bucket(client, bucket_default)
        except (S3Error, OSError, ValueError) as e:
            print(
                "ERROR: MinIO connection failed — fix MINIO_ENDPOINT / VPN or pass "
                "--skip-minio-upload.",
                file=sys.stderr,
            )
            print(f"Cause: {e}", file=sys.stderr)
            return 1

        train_exists = raw_exists = archive_exists = False
        archive_key = f"raw/hdb_rpi/{ARCHIVE_NAME}"
        try:
            train_exists = object_exists(bk_train_bucket, bk_train_key, client=client)
            raw_exists = object_exists(bucket_default, RAW_RPI_MIRROR_KEY, client=client)
            archive_exists = object_exists(bucket_default, archive_key, client=client)
        except S3Error as e:
            print(f"ERROR: MinIO stat failed: {e}", file=sys.stderr)
            return 1

        print(
            "MinIO preflight:",
            f"macro_rpi s3://{bk_train_bucket}/{bk_train_key} exists={train_exists}; "
            f"{RAW_RPI_MIRROR_KEY} exists={raw_exists}; {archive_key} exists={archive_exists}.",
        )

        if train_exists ^ raw_exists and not args.force_minio:
            print(
                "NOTE: Only one of the two canonical RPI keys exists; use --force-minio "
                "to write both mirrors.",
            )

        upload_standard = args.force_minio or (not train_exists and not raw_exists)
        if not upload_standard:
            print("SKIP normalized CSV upload (at least one canonical key exists; use --force-minio).")
        archive_bytes = src.read_bytes()
        if upload_standard or args.force_minio:
            _upload_if_needed(
                client,
                bk_train_bucket,
                bk_train_key,
                csv_bytes,
                force=args.force_minio,
                exists=train_exists,
            )
            _upload_if_needed(
                client,
                bucket_default,
                RAW_RPI_MIRROR_KEY,
                csv_bytes,
                force=args.force_minio,
                exists=raw_exists,
            )
        _upload_if_needed(
            client,
            bucket_default,
            archive_key,
            archive_bytes,
            force=args.force_minio,
            exists=archive_exists,
        )

    try:
        db_url = resolve_admin_database_url()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    insert_sql = """
        INSERT INTO hdb_resale_price_index (
            quarter_label, year, quarter_num, period_start, index_value,
            base_reference, source, source_resource_id, ingested_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (period_start) DO UPDATE SET
            index_value = EXCLUDED.index_value,
            quarter_label = EXCLUDED.quarter_label,
            year = EXCLUDED.year,
            quarter_num = EXCLUDED.quarter_num,
            base_reference = EXCLUDED.base_reference,
            source = EXCLUDED.source,
            source_resource_id = EXCLUDED.source_resource_id,
            ingested_at = EXCLUDED.ingested_at
        """
    ts = datetime.now(timezone.utc)
    payload = [
        (
            r.quarter_label,
            r.year,
            r.quarter_num,
            r.period_start,
            r.index_value,
            RPI_BASE_REF,
            RPI_SOURCE,
            RPI_RESOURCE_ID,
            ts,
        )
        for r in rows
    ]

    conn = psycopg2.connect(psycopg2_connect_dsn(db_url))
    lo, hi = rows[0].period_start, rows[-1].period_start
    tail = rows[-1]
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, insert_sql, payload)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM hdb_resale_price_index
                 WHERE period_start BETWEEN %s AND %s
                """,
                (lo, hi),
            )
            span_cnt = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM hdb_resale_price_index",
            )
            total_cnt = cur.fetchone()[0]
            cur.execute(
                """
                SELECT quarter_label,
                       CAST(index_value AS FLOAT)
                  FROM hdb_resale_price_index
                 ORDER BY period_start DESC
                 LIMIT 1
                """
            )
            latest = cur.fetchone()
            cur.execute(
                """
                SELECT quarter_label, CAST(index_value AS FLOAT)
                  FROM hdb_resale_price_index
                 WHERE period_start = %s
                """,
                (rows[0].period_start,),
            )
            first_row = cur.fetchone()

        print(f"Postgres upsert OK: rows in span [{lo.isoformat()}, {hi.isoformat()}]={span_cnt}, table total={total_cnt}")

        if int(span_cnt or 0) != n:
            print(
                f"ERROR: expected exactly {n} rows for this contiguous series in Postgres, "
                f"COUNT in span got {span_cnt}",
                file=sys.stderr,
            )
            return 1

        if latest and (latest[0] != tail.quarter_label or abs(float(latest[1]) - tail.index_value) > 1e-6):
            print(
                f"WARN: latest DB row ({latest}) vs file tail ({tail.quarter_label}, {tail.index_value})",
                file=sys.stderr,
            )

        head_lbl = rows[0].quarter_label
        head_idx = rows[0].index_value
        if not first_row or first_row[0] != head_lbl or abs(float(first_row[1]) - head_idx) > 1e-6:
            print(f"WARN: first row mismatch DB={first_row} file=({head_lbl}, {head_idx})", file=sys.stderr)

        print(
            "Reconciliation: span_count matches file;",
            f"latest={latest[0] if latest else 'n/a'} idx={latest[1] if latest else 'n/a'}",
        )
    except psycopg2.Error as e:
        conn.rollback()
        print(f"ERROR: Postgres ingest failed (run alembic upgrade head?): {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
