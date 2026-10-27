#!/usr/bin/env python3
"""Rebuild ``hdb_estate_maturity_by_town_month`` from Postgres sidecars."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
for p in (_HERE, _BACKEND, _REPO):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

import pandas as pd
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

from db_env import load_repo_env, psycopg2_connect_dsn, resolve_admin_database_url  # noqa: E402
from hdb_resale_town_geo import (  # noqa: E402
    normalize_hdb_town_label,
    singapore_fy_label_containing_calendar_month,
)


def iter_year_month(start_ym: str, end_ym: str):
    p = pd.Period(start_ym, freq="M")
    q = pd.Period(end_ym, freq="M")
    while p <= q:
        yield str(p)
        p += 1


def main(argv: list[str] | None = None) -> int:
    load_repo_env(_REPO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", type=Path, default=_REPO)
    ap.parse_args(argv)

    url = resolve_admin_database_url()

    towns: list[str] = []
    land: dict[str, float] = {}
    completed_units: dict[tuple[str, int], int] = {}
    uc_units: dict[tuple[str, int], int] = {}
    pit_stock: dict[tuple[str, int], tuple[float | None, float | None]] = {}
    start_ym, end_ym = "", ""

    conn = psycopg2.connect(psycopg2_connect_dsn(url))
    conn.autocommit = True

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT UPPER(BTRIM(town)) FROM hdb_resale_transactions WHERE town IS NOT NULL
                UNION
                SELECT DISTINCT UPPER(BTRIM(hdb_town)) FROM hdb_property_information
                ORDER BY 1
                """
            )
            towns = [normalize_hdb_town_label(row[0]) for row in cur.fetchall() if row[0]]

            cur.execute(
                "SELECT MIN(month)::text, MAX(month)::text FROM hdb_resale_transactions WHERE month ~ '^[0-9]{4}-[0-9]{2}$'"
            )
            row = cur.fetchone()
            start_ym, end_ym = str(row[0] or "").strip(), str(row[1] or "").strip()

            cur.execute("SELECT town_normalized, land_area_sq_km FROM hdb_resale_town_land_area_km2")
            for tn, sq in cur.fetchall():
                land[normalize_hdb_town_label(tn)] = float(sq)

            cur.execute(
                """
                SELECT financial_year, town_normalized, n_units
                  FROM hdb_town_completion_fy
                 WHERE scheme = 'HDB' AND status = 'Completed'
                """
            )
            for fy, town, nu in cur.fetchall():
                completed_units[(normalize_hdb_town_label(town), int(fy))] = int(nu)

            cur.execute(
                """
                SELECT financial_year, town_normalized, n_units
                  FROM hdb_town_completion_fy
                 WHERE scheme = 'HDB' AND status = 'Under Construction'
                """
            )
            for fy, town, nu in cur.fetchall():
                uc_units[(normalize_hdb_town_label(town), int(fy))] = int(nu)

        if not start_ym or not end_ym:
            print("WARN: No resale transactions; abort.")
            return 1

        years_needed = sorted(
            {int(pd.Period(ym, freq="M").year) for ym in iter_year_month(start_ym, end_ym)}
        )

        with conn.cursor() as cur:
            for y in years_needed:
                cur.execute(
                    """
                    SELECT UPPER(BTRIM(hdb_town)) AS tt,
                           COALESCE(SUM(total_dwelling_units), 0)::double precision AS sto,
                           COALESCE(AVG(%s::int - year_completed::double precision), NULL) AS avg_age
                      FROM hdb_property_information
                     WHERE residential = TRUE AND year_completed <= %s::int
                     GROUP BY 1
                    """,
                    (y, y),
                )
                for tt, sto, aa in cur.fetchall():
                    if not tt:
                        continue
                    tnorm = normalize_hdb_town_label(tt)
                    psto = float(sto or 0)
                    pit_stock[(tnorm, int(y))] = (
                        psto,
                        float(aa) if aa is not None else None,
                    )

    finally:
        conn.close()

    fy_labels = sorted({fy for (_, fy) in completed_units.keys()} | {fy for (_, fy) in uc_units.keys()})
    fy_end_period: dict[int, pd.Period] = {
        fy: pd.Period(year=int(fy), month=3, freq="M") for fy in fy_labels
    }

    batch: list[tuple] = []
    for ym in iter_year_month(start_ym, end_ym):
        tx_p = pd.Period(ym, freq="M")
        low_p = tx_p - 35
        cy = int(tx_p.year)
        cm = int(tx_p.month)

        fy_live = singapore_fy_label_containing_calendar_month(cy, cm)

        for tn in towns:
            roll36 = 0
            for fy_l in fy_labels:
                fy_p = fy_end_period[int(fy_l)]
                if low_p <= fy_p <= tx_p:
                    roll36 += completed_units.get((tn, int(fy_l)), 0)

            uc_cnt = uc_units.get((tn, fy_live), 0)
            sto_a2 = pit_stock.get((tn, cy))

            if sto_a2 is None:
                b1, a2 = None, None
            else:
                b1, a2 = sto_a2

            lk = land.get(tn)
            dens = (
                float(b1) / lk if b1 is not None and lk and lk > 0 else None
            )
            ratio = (
                float(uc_cnt) / float(b1) if b1 is not None and b1 > 0 else None
            )

            batch.append(
                (
                    tn,
                    ym,
                    a2,
                    int(b1) if b1 is not None else None,
                    lk,
                    dens,
                    int(uc_cnt),
                    int(roll36),
                    ratio,
                )
            )

    conn2 = psycopg2.connect(psycopg2_connect_dsn(url))
    try:
        with conn2.cursor() as cur:
            cur.execute("TRUNCATE hdb_estate_maturity_by_town_month")
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO hdb_estate_maturity_by_town_month (
                    town_normalized, year_month,
                    avg_residential_block_age_years,
                    town_completed_residential_units_stock,
                    town_land_area_km2,
                    town_dwelling_unit_density,
                    town_units_under_construction,
                    town_hdb_completed_units_roll36m,
                    town_supply_maturity_ratio
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                batch,
                page_size=800,
            )
        conn2.commit()
    finally:
        conn2.close()

    print(f"hdb_estate_maturity_by_town_month rebuilt: {len(batch)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
