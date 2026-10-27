#!/usr/bin/env python3
"""Pre-compute POI distance features for every geocoded HDB enrichment row into ``hdb_poi_features``.

Uses the same BallTree logic as ``modelling.features.poi_distancing.append_poi_features``,
reading POIs from ``poi_locations`` (run ``ingest_poi_assets.py`` first).

Admin DB: ``DATABASE_URL_ADMIN`` **or** ``DATABASE_URL`` **or** ``ADMIN_DB_*`` + host + ``DB_NAME`` **or** ``PGUSER`` / ``PGPASSWORD`` / ``PGHOST`` / ``PGDATABASE``.

Usage::

    PYTHONPATH=. python backend/scripts/build_poi_features.py
    PYTHONPATH=. python backend/scripts/build_poi_features.py --limit 5000
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from db_env import load_repo_env, psycopg2_connect_dsn, resolve_admin_database_url  # noqa: E402

from modelling.features.poi_distancing import append_poi_features, load_poi_tables_from_db  # noqa: E402


def _sql_float(x: Any) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _sql_int(x: Any) -> int | None:
    v = _sql_float(x)
    if v is None:
        return None
    return int(round(v))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build hdb_poi_features from poi_locations + addresses.")
    parser.add_argument("--limit", type=int, default=0, help="Max addresses (0 = all).")
    args = parser.parse_args(argv)

    load_repo_env(_REPO)
    try:
        raw_url = resolve_admin_database_url()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    db_url = psycopg2_connect_dsn(raw_url)

    conn = psycopg2.connect(db_url)
    try:
        lim_sql = f"LIMIT {int(args.limit)}" if args.limit and args.limit > 0 else ""
        addr_sql = f"""
            SELECT id AS hdb_addr_id, latitude AS lat, longitude AS lon
            FROM hdb_address_enrichment_onemap
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            ORDER BY id
            {lim_sql}
        """
        addrs = pd.read_sql(addr_sql, conn)
        if addrs.empty:
            print("No geocoded addresses found.")
            return 0

        addrs["storey_mid"] = 0.0
        pois = load_poi_tables_from_db(raw_url)
        out = append_poi_features(addrs, pois)

        insert_sql = """
            INSERT INTO hdb_poi_features (
                hdb_addr_id,
                dist_cbd, dist_airport,
                dist_nearest_top20_school, dist_nearest_any_school,
                within_1km_top20_school, within_1km_2km_top20_school,
                within_1km_any_pri_school, within_1km_2km_pri_school,
                dist_nearest_mall, malls_within_2km,
                supermarkets_within_500m, markets_within_500m,
                dist_nearest_park, is_park_200m, dist_nearest_pcn,
                gravity_malls, gravity_schools, gravity_parks, gravity_markets
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (hdb_addr_id) DO UPDATE SET
                dist_cbd = EXCLUDED.dist_cbd,
                dist_airport = EXCLUDED.dist_airport,
                dist_nearest_top20_school = EXCLUDED.dist_nearest_top20_school,
                dist_nearest_any_school = EXCLUDED.dist_nearest_any_school,
                within_1km_top20_school = EXCLUDED.within_1km_top20_school,
                within_1km_2km_top20_school = EXCLUDED.within_1km_2km_top20_school,
                within_1km_any_pri_school = EXCLUDED.within_1km_any_pri_school,
                within_1km_2km_pri_school = EXCLUDED.within_1km_2km_pri_school,
                dist_nearest_mall = EXCLUDED.dist_nearest_mall,
                malls_within_2km = EXCLUDED.malls_within_2km,
                supermarkets_within_500m = EXCLUDED.supermarkets_within_500m,
                markets_within_500m = EXCLUDED.markets_within_500m,
                dist_nearest_park = EXCLUDED.dist_nearest_park,
                is_park_200m = EXCLUDED.is_park_200m,
                dist_nearest_pcn = EXCLUDED.dist_nearest_pcn,
                gravity_malls = EXCLUDED.gravity_malls,
                gravity_schools = EXCLUDED.gravity_schools,
                gravity_parks = EXCLUDED.gravity_parks,
                gravity_markets = EXCLUDED.gravity_markets,
                computed_at = NOW()
        """

        batch: list[tuple[Any, ...]] = []
        for _, row in out.iterrows():
            batch.append(
                (
                    int(row["hdb_addr_id"]),
                    _sql_float(row.get("dist_cbd")),
                    _sql_float(row.get("dist_airport")),
                    _sql_float(row.get("dist_nearest_top20_school")),
                    _sql_float(row.get("dist_nearest_any_school")),
                    _sql_int(row.get("within_1km_top20_school")),
                    _sql_int(row.get("within_1km_2km_top20_school")),
                    _sql_int(row.get("within_1km_any_pri_school")),
                    _sql_int(row.get("within_1km_2km_pri_school")),
                    _sql_float(row.get("dist_nearest_mall")),
                    _sql_int(row.get("malls_within_2km")),
                    _sql_int(row.get("supermarkets_within_500m")),
                    _sql_int(row.get("markets_within_500m")),
                    _sql_float(row.get("dist_nearest_park")),
                    _sql_int(row.get("is_park_200m")),
                    _sql_float(row.get("dist_nearest_pcn")),
                    _sql_float(row.get("gravity_malls")),
                    _sql_float(row.get("gravity_schools")),
                    _sql_float(row.get("gravity_parks")),
                    _sql_float(row.get("gravity_markets")),
                )
            )

        cur = conn.cursor()
        execute_batch(cur, insert_sql, batch, page_size=500)
        conn.commit()
        print(f"Upserted {len(batch):,} rows into hdb_poi_features.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
