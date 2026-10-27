#!/usr/bin/env python3
"""Populate ``hdb_resale_town_planning_area`` and ``hdb_resale_town_land_area_km2`` via URA PA union."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

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

from hdb_resale_town_geo import normalize_hdb_town_label, planning_area_labels_for_resale_town  # noqa: E402


def _distinct_towns(cur) -> list[str]:
    cur.execute(
        """
        SELECT DISTINCT UPPER(BTRIM(town)) AS t FROM hdb_resale_transactions WHERE town IS NOT NULL
        UNION
        SELECT DISTINCT UPPER(BTRIM(hdb_town)) FROM hdb_property_information
        ORDER BY 1
        """
    )
    return [normalize_hdb_town_label(row[0]) for row in cur.fetchall() if row and row[0]]


def main() -> None:
    load_repo_env(_REPO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print rows only.")
    args = ap.parse_args()
    url = resolve_admin_database_url()
    dsn = psycopg2_connect_dsn(url)

    towns = []
    with psycopg2.connect(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            towns = _distinct_towns(cur)

    rows: list[tuple[str, str]] = []
    for t in towns:
        if not t:
            continue
        for pa in planning_area_labels_for_resale_town(t):
            rows.append((t, pa))

    if args.dry_run:
        for r in rows[:50]:
            print(r)
        print("...", len(rows), "pairs")
        return

    with psycopg2.connect(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("TRUNCATE hdb_resale_town_planning_area")
            cur.execute("TRUNCATE hdb_resale_town_land_area_km2")
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO hdb_resale_town_planning_area (town_normalized, pln_area_n) VALUES %s",
                rows,
            )
            cur.execute(
                """
                INSERT INTO hdb_resale_town_land_area_km2 (town_normalized, land_area_sq_km)
                SELECT m.town_normalized,
                       (ST_Area(
                           geography(
                               ST_UnaryUnion(ST_Collect(pa.geom::geometry))
                           )
                       ) / 1e6)::double precision AS km2
                FROM hdb_resale_town_planning_area m
                INNER JOIN ura_mp19_planning_areas_no_sea pa
                  ON UPPER(BTRIM(pa.pln_area_n)) = m.pln_area_n
                GROUP BY m.town_normalized
                HAVING ST_Area(
                    geography(
                        ST_UnaryUnion(ST_Collect(pa.geom::geometry))
                    )
                ) > 0
                """
            )
            cur.execute("SELECT COUNT(*) FROM hdb_resale_town_land_area_km2")
            n = cur.fetchone()[0]
            print(f"hdb_resale_town_land_area_km2 rows: {n}")


if __name__ == "__main__":
    main()
