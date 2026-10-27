#!/usr/bin/env python3
"""Read-only report: MRT PIT snapshot coverage vs enrichment for inference months.

Uses read-only DB credentials (``DATABASE_URL_READ_ONLY`` / ``READ_ONLY_DB_*``).
No writes — safe to run in prod for diagnostics.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_COMPLETENESS_SQL = """
WITH ym AS (
    SELECT to_char((CURRENT_TIMESTAMP AT TIME ZONE 'utc'), 'YYYY-MM') AS tx_year_month
),
enrichment_coords AS (
    SELECT COUNT(DISTINCT ae.id)::bigint AS n
    FROM hdb_address_enrichment_onemap ae
    WHERE ae.latitude IS NOT NULL
      AND ae.longitude IS NOT NULL
),
resale_pairs AS (
    SELECT COUNT(DISTINCT r.enriched_addr_id)::bigint AS n
    FROM hdb_resale_transactions r
    CROSS JOIN ym
    WHERE r.enriched_addr_id IS NOT NULL
      AND r.month = ym.tx_year_month
),
union_pairs AS (
    SELECT COUNT(DISTINCT aid)::bigint AS n
    FROM (
        SELECT r.enriched_addr_id AS aid
        FROM hdb_resale_transactions r
        CROSS JOIN ym
        WHERE r.enriched_addr_id IS NOT NULL
          AND r.month = ym.tx_year_month
        UNION
        SELECT ae.id AS aid
        FROM hdb_address_enrichment_onemap ae
        WHERE ae.latitude IS NOT NULL
          AND ae.longitude IS NOT NULL
    ) u
),
snapshot_rows AS (
    SELECT COUNT(*)::bigint AS n
    FROM hdb_mrt_features_pit_snapshot s
    CROSS JOIN ym
    WHERE s.tx_year_month = ym.tx_year_month
),
enrichment_gap AS (
    SELECT COUNT(*)::bigint AS n
    FROM hdb_address_enrichment_onemap ae
    CROSS JOIN ym
    WHERE ae.latitude IS NOT NULL
      AND ae.longitude IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM hdb_mrt_features_pit_snapshot s
          WHERE s.hdb_addr_id = ae.id
            AND s.tx_year_month = ym.tx_year_month
      )
),
job_row AS (
    SELECT j.tx_year_month,
           j.pairs_total,
           j.pairs_inserted,
           j.status
    FROM mrt_pit_build_jobs j
    CROSS JOIN ym
    WHERE j.tx_year_month = ym.tx_year_month
)
SELECT
    ym.tx_year_month,
    ec.n AS enrichment_with_coords,
    rp.n AS resale_pairs_current_month,
    up.n AS union_pairs_resale_or_enrichment,
    sr.n AS snapshot_rows_current_month,
    eg.n AS enrichment_gap_no_snapshot,
    jr.pairs_total AS job_pairs_total,
    jr.pairs_inserted AS job_pairs_inserted,
    jr.status AS job_status
FROM ym
CROSS JOIN enrichment_coords ec
CROSS JOIN resale_pairs rp
CROSS JOIN union_pairs up
CROSS JOIN snapshot_rows sr
CROSS JOIN enrichment_gap eg
LEFT JOIN job_row jr ON TRUE;
"""

_RECENT_MONTHS_SQL = """
SELECT tx_year_month, COUNT(*)::bigint AS snapshot_rows
FROM hdb_mrt_features_pit_snapshot
GROUP BY tx_year_month
ORDER BY tx_year_month DESC
LIMIT :limit;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--month",
        default=None,
        help="Override inference month (YYYY-MM); default UTC current month via SQL",
    )
    parser.add_argument(
        "--recent",
        type=int,
        default=6,
        help="Also print snapshot row counts for the N most recent months (default 6)",
    )
    args = parser.parse_args()

    from sqlalchemy import text

    from modelling.training_db import create_training_engine, get_training_database_url

    try:
        get_training_database_url()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    eng = create_training_engine()
    try:
        with eng.connect() as conn:
            row = dict(conn.execute(text(_COMPLETENESS_SQL)).mappings().one())

            if args.month:
                # Re-run gap for explicit month (read-only spot check)
                spot = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)::bigint AS enrichment_gap
                        FROM hdb_address_enrichment_onemap ae
                        WHERE ae.latitude IS NOT NULL
                          AND ae.longitude IS NOT NULL
                          AND NOT EXISTS (
                              SELECT 1
                              FROM hdb_mrt_features_pit_snapshot s
                              WHERE s.hdb_addr_id = ae.id
                                AND s.tx_year_month = :ym
                          )
                        """
                    ),
                    {"ym": args.month},
                ).scalar_one()
                row["tx_year_month"] = args.month
                row["enrichment_gap_no_snapshot"] = int(spot)

            print("=== MRT PIT snapshot completeness (read-only) ===")
            print(f"inference_month:              {row['tx_year_month']}")
            print(f"enrichment_with_coords:       {row['enrichment_with_coords']:,}")
            print(f"resale_pairs_current_month:   {row['resale_pairs_current_month']:,}")
            print(f"union_pairs (resale|enrich):  {row['union_pairs_resale_or_enrichment']:,}")
            print(f"snapshot_rows_current_month:  {row['snapshot_rows_current_month']:,}")
            print(f"enrichment_gap_no_snapshot:   {row['enrichment_gap_no_snapshot']:,}")
            if row.get("job_status"):
                print(
                    f"mrt_pit_build_jobs:           status={row['job_status']} "
                    f"pairs_total={row['job_pairs_total']} pairs_inserted={row['job_pairs_inserted']}"
                )
            else:
                print("mrt_pit_build_jobs:           (no row for inference month)")

            gap = int(row["enrichment_gap_no_snapshot"] or 0)
            if gap == 0:
                print("\nOK: no enrichment addresses missing snapshot for inference month.")
            else:
                pct = 100.0 * gap / max(int(row["enrichment_with_coords"] or 1), 1)
                print(
                    f"\nGAP: {gap:,} enriched addresses ({pct:.1f}%) lack snapshot for "
                    f"{row['tx_year_month']} — valuations may use hdb_mrt_features_at fallback."
                )

            if args.recent > 0:
                print(f"\n--- Recent snapshot rows (last {args.recent} months) ---")
                recent = conn.execute(
                    text(_RECENT_MONTHS_SQL), {"limit": args.recent}
                ).mappings().all()
                for r in recent:
                    print(f"  {r['tx_year_month']}: {int(r['snapshot_rows']):,} rows")
    finally:
        eng.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
