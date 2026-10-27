#!/usr/bin/env python3
"""Ingest data.gov.sg HDB Property Information into Postgres and mirror CSV to MinIO.

Loads ``data/HDBPropertyInformation.csv`` (or ``--source``), computes canonical
``blk_street`` (same rule as [`address_normalize.normalize_street`](address_normalize.py) / OneMap
``query_sent``), resolves ``enriched_addr_id`` when enrichment
exists, and upserts ``hdb_property_information``.

Run order::

    cd backend && alembic upgrade head

    PYTHONPATH=. python scripts/ingest_hdb_property_information.py

Docker dev::

    ./scripts/docker_dev_backend.sh python /app/scripts/ingest_hdb_property_information.py

Requires admin DB URL and ``MINIO_*`` unless ``--skip-minio-upload``.
"""

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

from minio import Minio  # noqa: E402
from minio.error import S3Error  # noqa: E402

from address_normalize import _normalize_street  # noqa: E402
from hdb_contract_town_map import hdb_town_from_contract_code  # noqa: E402

from modelling.storage.minio_io import ensure_bucket, object_exists, put_object_bytes  # noqa: E402

DEFAULT_SOURCE = Path("data/HDBPropertyInformation.csv")
MINIO_KEY = "raw/datagovsg/HDBPropertyInformation.csv"
SOURCE_LABEL = "data.gov.sg"
SOURCE_RESOURCE_ID = "d_17f5382f26140b1fdae0ba2ef6239d2f"


def _blk_street(blk_no: str, street: str) -> str:
    blk = blk_no.strip().upper()
    return f"{blk} {_normalize_street(street)}"


def _yn(cell: Any) -> bool:
    raw = str(cell).strip().upper()
    if raw == "Y":
        return True
    if raw == "N":
        return False
    raise ValueError(f"Expected Y or N; got {raw!r}")


def _minio_endpoint() -> str:
    if not (os.getenv("MINIO_ENDPOINT") or "").strip():
        host = (os.getenv("MINIO_HOST") or "").strip()
        port = (os.getenv("MINIO_INNER_PORT") or "9000").strip()
        if host:
            os.environ["MINIO_ENDPOINT"] = f"{host}:{port}"
    return os.getenv("MINIO_ENDPOINT", "minio:9000")


def _minio_client() -> Minio:
    return Minio(
        _minio_endpoint(),
        access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "password123"),
        secure=False,
    )


def _load_normalized_rows(csv_path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    df = pd.read_csv(csv_path)
    expected = {
        "blk_no",
        "street",
        "max_floor_lvl",
        "year_completed",
        "residential",
        "commercial",
        "market_hawker",
        "miscellaneous",
        "multistorey_carpark",
        "precinct_pavilion",
        "bldg_contract_town",
        "total_dwelling_units",
        "1room_sold",
        "2room_sold",
        "3room_sold",
        "4room_sold",
        "5room_sold",
        "exec_sold",
        "multigen_sold",
        "studio_apartment_sold",
        "1room_rental",
        "2room_rental",
        "3room_rental",
        "other_room_rental",
    }
    cols = set(df.columns)
    if cols != expected:
        missing = expected - cols
        extra = cols - expected
        raise ValueError(f"CSV column mismatch missing={sorted(missing)!r} extra={sorted(extra)!r}")

    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        street = str(r["street"]).strip()
        blk_no_raw = str(r["blk_no"]).strip()
        street_norm = _normalize_street(street)
        bs = _blk_street(blk_no_raw, street)

        rental_sum = (
            int(r["1room_rental"])
            + int(r["2room_rental"])
            + int(r["3room_rental"])
            + int(r["other_room_rental"])
        )
        sold_sum = (
            int(r["1room_sold"])
            + int(r["2room_sold"])
            + int(r["3room_sold"])
            + int(r["4room_sold"])
            + int(r["5room_sold"])
            + int(r["exec_sold"])
            + int(r["multigen_sold"])
            + int(r["studio_apartment_sold"])
        )
        total_dw = int(r["total_dwelling_units"])
        if sold_sum + rental_sum != total_dw:
            raise ValueError(
                f"Row blk={blk_no_raw!r} street={street!r}: sold+rental {sold_sum}+{rental_sum} != total {total_dw}"
            )

        contract = str(r["bldg_contract_town"]).strip().upper()
        hdb_town = hdb_town_from_contract_code(contract)

        yr = int(r["year_completed"])
        if yr < 1937 or yr > 2100:
            raise ValueError(f"year_completed out of range: {yr} for blk_street={bs!r}")

        rows.append(
            {
                "blk_street": bs,
                "blk_no": blk_no_raw.upper(),
                "street": street,
                "street_norm": street_norm,
                "max_floor_lvl": int(r["max_floor_lvl"]) if pd.notna(r["max_floor_lvl"]) else None,
                "year_completed": yr,
                "residential": _yn(r["residential"]),
                "commercial": _yn(r["commercial"]),
                "market_hawker": _yn(r["market_hawker"]),
                "miscellaneous": _yn(r["miscellaneous"]),
                "multistorey_carpark": _yn(r["multistorey_carpark"]),
                "precinct_pavilion": _yn(r["precinct_pavilion"]),
                "bldg_contract_town": contract,
                "hdb_town": hdb_town,
                "total_dwelling_units": total_dw,
                "room_1_sold": int(r["1room_sold"]),
                "room_2_sold": int(r["2room_sold"]),
                "room_3_sold": int(r["3room_sold"]),
                "room_4_sold": int(r["4room_sold"]),
                "room_5_sold": int(r["5room_sold"]),
                "exec_sold": int(r["exec_sold"]),
                "multigen_sold": int(r["multigen_sold"]),
                "studio_apartment_sold": int(r["studio_apartment_sold"]),
                "room_1_rental": int(r["1room_rental"]),
                "room_2_rental": int(r["2room_rental"]),
                "room_3_rental": int(r["3room_rental"]),
                "other_room_rental": int(r["other_room_rental"]),
            }
        )

    uniq = {x["blk_street"] for x in rows}
    if len(uniq) != len(rows):
        raise ValueError("Duplicate blk_street values in CSV after normalization")
    return rows


def _enrichment_lookup(
    cur: Any, blk_streets: list[str], chunk: int = 500
) -> dict[str, int]:
    """Map normalized lower(trim(blk_street)) → MIN(one_map.id)."""
    out: dict[str, int] = {}
    norms = sorted({bs.strip().lower() for bs in blk_streets})
    for i in range(0, len(norms), chunk):
        part = norms[i : i + chunk]
        cur.execute(
            """
            SELECT LOWER(TRIM(query_sent)), MIN(id)
            FROM hdb_address_enrichment_onemap
            WHERE LOWER(TRIM(query_sent)) = ANY(%s)
            GROUP BY LOWER(TRIM(query_sent))
            """,
            (part,),
        )
        for k, oid in cur.fetchall():
            out[str(k)] = int(oid)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=f"CSV path (default: repo-root {DEFAULT_SOURCE})",
    )
    parser.add_argument("--project-root", type=Path, default=_REPO, help="Repository root.")
    parser.add_argument(
        "--skip-minio-upload",
        action="store_true",
        help="Only Postgres (no MinIO).",
    )
    parser.add_argument("--force-minio", action="store_true", help="Overwrite MinIO key if present.")
    parser.add_argument("--dry-run", action="store_true", help="Validate CSV only.")
    parser.add_argument(
        "--quiet-stats",
        action="store_true",
        help="Suppress post-ingest join statistics queries.",
    )
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    src = (args.source or (root / DEFAULT_SOURCE)).expanduser().resolve()

    load_repo_env(root)

    if not src.is_file():
        print(f"ERROR: source CSV not found: {src}", file=sys.stderr)
        return 1

    try:
        rows = _load_normalized_rows(src)
    except (ValueError, TypeError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Parsed {len(rows):,} property rows from {src.name}")

    if args.dry_run:
        print("[dry-run] OK — no DB or MinIO writes.")
        return 0

    if not args.skip_minio_upload:
        bucket_default = os.getenv("MINIO_DEFAULT_BUCKET", "datasets").strip() or "datasets"
        csv_bytes = src.read_bytes()
        try:
            client = _minio_client()
            ensure_bucket(client, bucket_default)
        except S3Error as e:
            print(f"ERROR: MinIO unavailable — use --skip-minio-upload. Cause: {e}", file=sys.stderr)
            return 1
        try:
            exists = object_exists(bucket_default, MINIO_KEY, client=client)
        except S3Error as e:
            print(f"ERROR: MinIO stat failed: {e}", file=sys.stderr)
            return 1
        if exists and not args.force_minio:
            print(f"SKIP MinIO (exists): s3://{bucket_default}/{MINIO_KEY}")
        else:
            put_object_bytes(
                bucket_default,
                MINIO_KEY,
                csv_bytes,
                client=client,
                content_type="text/csv;charset=utf-8",
            )
            print(f"PUT s3://{bucket_default}/{MINIO_KEY} ({len(csv_bytes)} bytes)")

    try:
        db_url = resolve_admin_database_url()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    ts = datetime.now(timezone.utc)
    blk_streets_list = [r["blk_street"] for r in rows]

    conn = psycopg2.connect(psycopg2_connect_dsn(db_url))
    unmatched_queries: list[str] = []

    try:
        with conn.cursor() as cur:
            enrich_map = _enrichment_lookup(cur, blk_streets_list)

            batch: list[tuple[Any, ...]] = []
            for r in rows:
                nk = r["blk_street"].strip().lower()
                eid = enrich_map.get(nk)
                if eid is None:
                    unmatched_queries.append(r["blk_street"])

                payload = (
                    r["blk_street"],
                    eid,
                    r["blk_no"],
                    r["street"],
                    r["street_norm"],
                    r["max_floor_lvl"],
                    r["year_completed"],
                    r["residential"],
                    r["commercial"],
                    r["market_hawker"],
                    r["miscellaneous"],
                    r["multistorey_carpark"],
                    r["precinct_pavilion"],
                    r["bldg_contract_town"],
                    r["hdb_town"],
                    r["total_dwelling_units"],
                    r["room_1_sold"],
                    r["room_2_sold"],
                    r["room_3_sold"],
                    r["room_4_sold"],
                    r["room_5_sold"],
                    r["exec_sold"],
                    r["multigen_sold"],
                    r["studio_apartment_sold"],
                    r["room_1_rental"],
                    r["room_2_rental"],
                    r["room_3_rental"],
                    r["other_room_rental"],
                    SOURCE_LABEL,
                    SOURCE_RESOURCE_ID,
                    ts,
                )
                batch.append(payload)

            tup_sql = """
        INSERT INTO hdb_property_information (
            blk_street, enriched_addr_id, blk_no, street, street_norm,
            max_floor_lvl, year_completed,
            residential, commercial, market_hawker, miscellaneous,
            multistorey_carpark, precinct_pavilion,
            bldg_contract_town, hdb_town,
            total_dwelling_units,
            room_1_sold, room_2_sold, room_3_sold, room_4_sold, room_5_sold,
            exec_sold, multigen_sold, studio_apartment_sold,
            room_1_rental, room_2_rental, room_3_rental, other_room_rental,
            source, source_resource_id, ingested_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s,
            %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (blk_street) DO UPDATE SET
            enriched_addr_id = COALESCE(EXCLUDED.enriched_addr_id, hdb_property_information.enriched_addr_id),
            blk_no = EXCLUDED.blk_no,
            street = EXCLUDED.street,
            street_norm = EXCLUDED.street_norm,
            max_floor_lvl = EXCLUDED.max_floor_lvl,
            year_completed = EXCLUDED.year_completed,
            residential = EXCLUDED.residential,
            commercial = EXCLUDED.commercial,
            market_hawker = EXCLUDED.market_hawker,
            miscellaneous = EXCLUDED.miscellaneous,
            multistorey_carpark = EXCLUDED.multistorey_carpark,
            precinct_pavilion = EXCLUDED.precinct_pavilion,
            bldg_contract_town = EXCLUDED.bldg_contract_town,
            hdb_town = EXCLUDED.hdb_town,
            total_dwelling_units = EXCLUDED.total_dwelling_units,
            room_1_sold = EXCLUDED.room_1_sold,
            room_2_sold = EXCLUDED.room_2_sold,
            room_3_sold = EXCLUDED.room_3_sold,
            room_4_sold = EXCLUDED.room_4_sold,
            room_5_sold = EXCLUDED.room_5_sold,
            exec_sold = EXCLUDED.exec_sold,
            multigen_sold = EXCLUDED.multigen_sold,
            studio_apartment_sold = EXCLUDED.studio_apartment_sold,
            room_1_rental = EXCLUDED.room_1_rental,
            room_2_rental = EXCLUDED.room_2_rental,
            room_3_rental = EXCLUDED.room_3_rental,
            other_room_rental = EXCLUDED.other_room_rental,
            source = EXCLUDED.source,
            source_resource_id = EXCLUDED.source_resource_id,
            ingested_at = EXCLUDED.ingested_at
        """
            psycopg2.extras.execute_batch(cur, tup_sql, batch)

            if not args.quiet_stats:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n,
                           COUNT(enriched_addr_id) AS enriched
                    FROM hdb_property_information
                    """
                )
                prow = cur.fetchone()
                prop_n, enriched_n = int(prow[0]), int(prow[1])

                cur.execute(
                    """
                    SELECT COUNT(*) AS total_tx,
                           COUNT(p.id) AS matched_via_block_street,
                           ROUND(100.0 * COUNT(p.id) / NULLIF(COUNT(*), 0)::numeric, 2) AS pct_block_street
                    FROM hdb_resale_transactions t
                    LEFT JOIN hdb_property_information p ON p.blk_street = t.block_street
                    """
                )
                srow = cur.fetchone()

                cur.execute(
                    """
                    SELECT COUNT(*) AS total_tx,
                           COUNT(p.id) AS matched_via_enriched_addr,
                           ROUND(100.0 * COUNT(p.id) / NULLIF(COUNT(*), 0)::numeric, 2) AS pct_enriched_addr_id
                    FROM hdb_resale_transactions t
                    LEFT JOIN hdb_property_information p ON p.enriched_addr_id IS NOT NULL
                      AND p.enriched_addr_id = t.enriched_addr_id
                    """
                )
                erow = cur.fetchone()

                print(
                    f"Post-ingest catalog: rows={prop_n:,} enriched_addr_id_populated={enriched_n:,} "
                    f"({100.0 * enriched_n / prop_n:.2f}%)" if prop_n else ""
                )
                if srow:
                    print(
                        f"Resale join via blk_street=block_street: matched={int(srow[1]):,} "
                        f"of {int(srow[0]):,} ({srow[2]}%)"
                    )
                if erow:
                    print(
                        "Resale join via enriched_addr_id: "
                        f"matched={int(erow[1]):,} of {int(erow[0]):,} ({erow[2]}%)"
                    )

        conn.commit()
    finally:
        conn.close()

    n_unmatched = len(unmatched_queries)
    pct_unmatched = (100.0 * n_unmatched / len(rows)) if rows else 0.0
    print(f"Catalog rows missing OneMap enrichment match: {n_unmatched:,} ({pct_unmatched:.2f}%)")
    if n_unmatched and n_unmatched <= 25:
        for q in sorted(unmatched_queries):
            print(f"  no enrichment: {q}")
    elif n_unmatched:
        print(f"  (showing first 15 unmatched blk_street values)")
        for q in sorted(unmatched_queries)[:15]:
            print(f"  no enrichment: {q}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
