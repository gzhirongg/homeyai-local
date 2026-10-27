#!/usr/bin/env python3
"""
Backfill ``hdb_resale_transactions.enriched_addr_id`` from existing
``hdb_address_enrichment_onemap`` rows by matching the canonical
OneMap query key:

    query_sent == f"{block} {_normalize_street(street_name)}"

(block is taken as stored in resale data; normalization matches ``address_normalize`` — same helper as ``engineer_postal_codes`` / property ingest.)

Only ``enriched_addr_id`` is updated. If ``block_street`` is a generated column in your database, it is left to the DB.

Requires PostgreSQL (``DATABASE_URL_ADMIN`` or ``DATABASE_URL`` or ``ADMIN_DB_*`` + host; see ``scripts/db_env.py``).

Usage::
    cd backend && export DATABASE_URL_ADMIN=postgresql://...
    python scripts/backfill_enriched_addr_id.py
    python scripts/backfill_enriched_addr_id.py --dry-run

See also: engineer_postal_codes.py (Prefect flow for new OneMap lookups).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: backend + scripts dirs before ``address_normalize`` / ``db_env`` imports.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPT_DIR))

from scripts.db_env import load_repo_env, psycopg2_connect_dsn, resolve_admin_database_url  # noqa: E402

load_repo_env(_BACKEND_DIR.parent)

import psycopg2  # noqa: E402

try:
    DATABASE_URL = psycopg2_connect_dsn(resolve_admin_database_url())
except RuntimeError as e:
    sys.exit(f"ERROR: {e}")
if "postgresql" not in DATABASE_URL.lower():
    sys.exit("ERROR: Admin database URL must be PostgreSQL.")

from address_normalize import _normalize_street  # noqa: E402

CHUNK_SIZE = 500
LOG_REL = Path("logs") / "backfill_unmatched.json"


def _expected_query_sent(block: str, street_name: str) -> str:
    """Matches ``resolve_postal_code`` / ``batch_update_postal_codes``."""
    norm_street = _normalize_street(street_name)
    return f"{block} {norm_street}"


def fetch_distinct_pairs(cur) -> list[tuple[str, str]]:
    cur.execute(
        """
        SELECT DISTINCT ON (t.block, t.street_name)
            t.block::text, t.street_name::text
        FROM hdb_resale_transactions t
        WHERE t.enriched_addr_id IS NULL
        ORDER BY t.block, t.street_name
        """
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def lookup_query_ids(cur, queries: list[str]) -> dict[str, int]:
    if not queries:
        return {}
    cur.execute(
        """
        SELECT query_sent, MIN(id) AS id
        FROM hdb_address_enrichment_onemap
        WHERE query_sent = ANY(%s)
        GROUP BY query_sent
        """,
        (queries,),
    )
    return {str(row[0]): int(row[1]) for row in cur.fetchall()}


def run_backfill(*, dry_run: bool) -> dict[str, Any]:
    log_path = _BACKEND_DIR / LOG_REL
    log_path.parent.mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    total_pairs = 0
    matched = 0
    unmatched: list[dict[str, str]] = []

    try:
        with conn.cursor() as cur:
            pairs = fetch_distinct_pairs(cur)
            total_pairs = len(pairs)

            for i in range(0, len(pairs), CHUNK_SIZE):
                chunk = pairs[i : i + CHUNK_SIZE]
                chunk_rows: list[tuple[str, str, str]] = []
                queries: list[str] = []

                for block, street in chunk:
                    q = _expected_query_sent(block, street)
                    chunk_rows.append((block, street, q))
                    queries.append(q)

                id_by_query = lookup_query_ids(cur, queries)

                matched_tuples: list[tuple[str, str, int]] = []
                for block, street, q in chunk_rows:
                    eid = id_by_query.get(q)
                    if eid is None:
                        unmatched.append(
                            {"block": block, "street_name": street, "expected_query_sent": q}
                        )
                        continue

                    matched += 1
                    matched_tuples.append((block, street, int(eid)))

                if not dry_run and matched_tuples:
                    ph = ",".join(["(%s,%s,%s)"] * len(matched_tuples))
                    flat: list[Any] = []
                    for b, s, e in matched_tuples:
                        flat.extend([b, s, e])
                    cur.execute(
                        f"""
                        UPDATE hdb_resale_transactions AS t
                        SET enriched_addr_id = v.eid::integer
                        FROM (VALUES {ph}) AS v(blk, st, eid)
                        WHERE t.block::text = v.blk
                          AND t.street_name::text = v.st
                          AND t.enriched_addr_id IS NULL
                        """,
                        flat,
                    )

                if not dry_run:
                    conn.commit()

        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": dry_run,
            "unique_addresses_with_null_enriched_id": total_pairs,
            "matched_unique_addresses": matched,
            "unmatched_count": len(unmatched),
            "unmatched_sample": unmatched[:200],
        }
        log_path.write_text(json.dumps(unmatched, indent=2), encoding="utf-8")

        print(json.dumps(out, indent=2))
        print(f"Full unmatched list written to {log_path} ({len(unmatched)} rows).")
        return out
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Lookup only; do not UPDATE hdb_resale_transactions",
    )
    args = p.parse_args()
    run_backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
