"""
engineer_postal_codes.py
========================
Prefect flow that resolves postal codes for all unique HDB block+street
combinations and back-fills the `hdb_resale_transactions.postal_code` column.

Usage (run locally, targeting the dev Prefect server):
    export PREFECT_API_URL=http://${REMOTE_VM_IP}:4201/api
    # or rely on REMOTE_VM_IP in project-root .env (same URL derived automatically)
    python backend/scripts/engineer_postal_codes.py

The flow runs in TWO PHASES:

  Phase 1 – Validation sample (50 diverse records).
             Writes a human-readable validation_sample.md and pauses for
             operator approval before proceeding.

  Phase 2  – Full batch resolution and database back-fill.
             Runs only after the operator re-runs with --approved flag or
             when called programmatically with approved=True.

Flags
-----
    --sample-only   Run Phase 1 and exit (default first run).
    --approved      Skip Phase 1 and run the full batch (Phase 2).
    --sample-size N Number of rows in the validation sample (default 50).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from difflib import SequenceMatcher
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Bootstrap: ensure repo root is on the path so local modules resolve
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_BACKEND_DIR))

from scripts.db_env import load_repo_env, psycopg2_connect_dsn, resolve_admin_database_url

load_repo_env(_BACKEND_DIR.parent)

from address_normalize import _normalize_street  # noqa: E402

import psycopg2
from prefect import flow, task, get_run_logger
from prefect.task_runners import ThreadPoolTaskRunner
from prefect.cache_policies import NO_CACHE

from services.onemap_service import OneMapService

try:
    DATABASE_URL = psycopg2_connect_dsn(resolve_admin_database_url())
except RuntimeError as e:
    sys.exit(f"ERROR: {e}")


def _resolve_prefect_api_url() -> str:
    u = (os.environ.get("PREFECT_API_URL") or "").strip()
    if u:
        return u
    host = (os.environ.get("REMOTE_VM_IP") or "").strip()
    if not host:
        sys.exit(
            "ERROR: Set PREFECT_API_URL or REMOTE_VM_IP (e.g. in project root .env) "
            "for the Prefect API URL."
        )
    return f"http://{host}:4201/api"


# Dev Prefect server (or compose-injected URL)
PREFECT_API_URL = _resolve_prefect_api_url()

# Brain / artifact output directory — walk upward from script looking for .gemini
def _find_artifact_dir() -> Path:
    candidate = _SCRIPT_DIR
    for _ in range(6):        # max 6 levels up
        brain = candidate / ".gemini" / "antigravity" / "brain"
        if brain.exists():
            subdirs = [d for d in brain.iterdir() if d.is_dir()]
            if subdirs:
                return max(subdirs, key=lambda p: p.stat().st_mtime)
        candidate = candidate.parent
    return Path("/tmp")

_ARTIFACT_DIR = _find_artifact_dir()
VALIDATION_SAMPLE_PATH = _ARTIFACT_DIR / "validation_sample.json"
UNMATCHED_DUMP_PATH = _BACKEND_DIR / "logs" / "unmatched_addresses.json"

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@task(name="fetch-unique-addresses", retries=2, retry_delay_seconds=5)
def fetch_unique_addresses() -> list[tuple[str, str]]:
    """Return a deduplicated list of (block, street_name) from the DB."""
    logger = get_run_logger()
    logger.info("Fetching unique (block, street_name) pairs …")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT t.block, t.street_name
                FROM hdb_resale_transactions t
                LEFT JOIN hdb_address_enrichment_onemap e ON t.enriched_addr_id = e.id
                WHERE t.enriched_addr_id IS NULL
                   OR (
                        e.postal_code IS NULL
                        AND (e.last_attempt_at IS NULL OR e.last_attempt_at < NOW() - INTERVAL '90 days')
                   )
                ORDER BY t.block, t.street_name
            """)
            rows = cur.fetchall()
    finally:
        conn.close()
    logger.info(f"Found {len(rows):,} unique addresses.")
    return rows


def _extract_number(s: str) -> str:
    match = re.search(r'\d+', s)
    return match.group(0) if match else ""

def pick_best_onemap_result(block: str, norm_street: str, results: list[dict], threshold: float = 0.9) -> tuple[Optional[str], Optional[float], Optional[float]]:
    """
    Selects the best postal code and coords from OneMap results based on strict matching rules.
    - Exact block match OR numeric block match.
    - Street name similarity > 0.9 after standardization.
    """
    if not results:
        return None, None, None
        
    target_street = norm_street
    target_block = str(block).upper().strip()
    target_block_num = _extract_number(target_block)
    
    best_score = 0.0
    best_match = (None, None, None)
    
    for r in results:
        api_block = str(r.get("BLK_NO", "")).upper().strip()
        api_street = str(r.get("ROAD_NAME", "")).upper().strip()
        
        # Condition 1: Block Match
        block_matches = False
        if api_block == target_block:
            block_matches = True
        elif target_block_num and _extract_number(api_block) == target_block_num:
            # If the letters differ but number matches (e.g. 122B vs 122 B or 122).
            # We accept it into the similarity evaluation phase.
            block_matches = True
            
        if not block_matches:
            continue
            
        # Condition 2: Street Similarity
        score = SequenceMatcher(None, target_street, api_street).ratio()
        if score >= threshold and score > best_score:
            postal = r.get("POSTAL", "").strip()
            if postal and postal != "NIL":
                try:
                    lat = float(r.get("LATITUDE"))
                    lon = float(r.get("LONGITUDE"))
                except (ValueError, TypeError):
                    lat, lon = None, None
                best_score = score
                best_match = (postal, lat, lon)
                
    return best_match

@task(name="resolve-postal-code", retries=1, retry_delay_seconds=3, cache_policy=NO_CACHE)
def resolve_postal_code(
    block: str,
    street: str,
    service: OneMapService,
) -> dict:
    """Query OneMap and return the postal code, all result records, and result count."""
    logger = get_run_logger()
    norm_street = _normalize_street(street)
    query = f"{block} {norm_street}"
    try:
        response = service.search_address(query)
        results = response.get("results", [])
        found = response.get("found", 0)

        postal, lat, lon = pick_best_onemap_result(block, norm_street, results)

        return {
            "postal": postal,
            "latitude": lat,
            "longitude": lon,
            "query_sent": query,
            "full_response": results,
            "results_count": found
        }
    except Exception as exc:
        logger.error(f"Error resolving {query!r}: {exc}")
        return {"postal": None, "latitude": None, "longitude": None, "query_sent": query, "full_response": [], "results_count": 0}


@task(name="write-validation-sample", retries=0)
def write_validation_sample(
    sample_results: list[dict],
) -> Path:
    """Write a formatted JSON validation artifact, sorted by result count, and return its path."""
    logger = get_run_logger()
    VALIDATION_SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Sort results by results_count descending (most ambiguous addresses first)
    sample_results.sort(key=lambda x: x.get("results_count", 0), reverse=True)

    # Calculate match distribution (how many addresses had 0, 1, 2, ... results)
    from collections import Counter
    counts = Counter(r.get("results_count", 0) for r in sample_results)
    distribution = {str(k): v for k, v in sorted(counts.items())}

    ok = sum(1 for r in sample_results if r.get("postal"))
    match_rate = 100 * ok / len(sample_results) if sample_results else 0

    output = {
        "metadata": {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "unique_addresses_processed": len(sample_results),
            "successful_resolutions": ok,
            "match_rate_pct": round(match_rate, 2),
            "match_distribution": distribution,
            "instruction": "Approve this sample by re-running the flow with --approved to proceed to full back-fill."
        },
        "results": sample_results
    }

    VALIDATION_SAMPLE_PATH.write_text(json.dumps(output, indent=2))
    logger.info(f"Validation results (JSON) written to {VALIDATION_SAMPLE_PATH}")
    return VALIDATION_SAMPLE_PATH


@task(name="batch-update-postal-codes", retries=2, retry_delay_seconds=10)
def batch_update_postal_codes(resolved: list[dict]) -> dict:
    """Write resolved postal codes back to the database."""
    logger = get_run_logger()
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    updated = 0

    try:
        with conn.cursor() as cur:
            for row in resolved:
                block, street = row["block"], row["street"]
                postal = row["postal"]
                lat, lon = row.get("latitude"), row.get("longitude")
                results_count = row.get("results_count", 0)
                query_sent = row.get("query_sent", f"{block} {street}")
                raw = json.dumps(row.get("full_response", []))
                now = datetime.now(tz=timezone.utc)

                cur.execute(
                    """
                    SELECT id FROM hdb_address_enrichment_onemap
                    WHERE query_sent = %s
                    LIMIT 1
                    """,
                    (query_sent,),
                )
                existing_enr = cur.fetchone()
                addr_id = existing_enr[0] if existing_enr and existing_enr[0] is not None else None

                if addr_id is None:
                    cur.execute(
                        """
                        SELECT enriched_addr_id FROM hdb_resale_transactions
                        WHERE block = %s AND street_name = %s AND enriched_addr_id IS NOT NULL
                        LIMIT 1
                        """,
                        (block, street),
                    )
                    existing_tx = cur.fetchone()
                    addr_id = (
                        existing_tx[0]
                        if existing_tx and existing_tx[0] is not None
                        else None
                    )

                if addr_id is not None:
                    cur.execute(
                        """
                        UPDATE hdb_address_enrichment_onemap SET
                            postal_code = %s,
                            latitude = %s,
                            longitude = %s,
                            results_count = %s,
                            query_sent = %s,
                            raw_response = %s,
                            last_attempt_at = %s,
                            attempt_count = COALESCE(attempt_count, 0) + 1
                        WHERE id = %s
                        """,
                        (postal, lat, lon, results_count, query_sent, raw, now, addr_id),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO hdb_address_enrichment_onemap
                            (postal_code, latitude, longitude, results_count, query_sent, raw_response, last_attempt_at, attempt_count)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (postal, lat, lon, results_count, query_sent, raw, now, 1),
                    )
                    addr_id = cur.fetchone()[0]

                cur.execute(
                    """
                    UPDATE hdb_resale_transactions
                    SET enriched_addr_id = %s
                    WHERE block = %s AND street_name = %s
                    """,
                    (addr_id, block, street),
                )
                updated += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        f"Done. Upserted {updated:,} addresses to cache repository."
    )
    return {"updated_dictionary": updated}


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------

@flow(
    name="postal-code-validation-full",
    description="Phase 1: Query ALL unique addresses missing from repo and produce validation artifact.",
    task_runner=ThreadPoolTaskRunner(max_workers=5),   # Map across threads
)
def validation_sample_flow(sample_size: int = 50) -> Path:
    """Note: sample_size ignored as we are now processing ALL unique addresses."""
    logger = get_run_logger()
    service = OneMapService(logger=logger)

    addresses = fetch_unique_addresses()
    logger.info(f"Resolving ALL {len(addresses):,} unique addresses …")

    # Process in chunks of 500 to incrementally save to DB and keep memory low
    chunk_size = 500
    total_updated = 0
    for i in range(0, len(addresses), chunk_size):
        chunk = addresses[i:i+chunk_size]
        
        # Dispatch concurrently
        futures = []
        for (block, street) in chunk:
            future = resolve_postal_code.submit(block, street, service)
            futures.append((block, street, future))
            
        # Gather and format
        resolved = []
        for (block, street, future) in futures:
            res = future.result()
            resolved.append({
                "block": block,
                "street": street,
                "postal": res["postal"],
                "latitude": res.get("latitude"),
                "longitude": res.get("longitude"),
                "query_sent": res.get("query_sent"),
                "results_count": res["results_count"],
                "full_response": res["full_response"]
            })
            
        logger.info(f"Progress: {min(i+chunk_size, len(addresses)):,} / {len(addresses):,}")

    return write_validation_sample(resolved)


@flow(
    name="postal-code-full-backfill",
    description="Phase 2: Resolve missing addresses and back-fill the database.",
    task_runner=ThreadPoolTaskRunner(max_workers=5),   # Map across threads
)
def full_backfill_flow() -> dict:
    logger = get_run_logger()
    service = OneMapService(logger=logger)

    addresses = fetch_unique_addresses()
    logger.info(f"Starting full resolution of {len(addresses):,} addresses …")

    chunk_size = 500
    total_updated = 0
    
    for i in range(0, len(addresses), chunk_size):
        chunk = addresses[i:i+chunk_size]
        
        # Dispatch concurrently
        futures = []
        for (block, street) in chunk:
            future = resolve_postal_code.submit(block, street, service)
            futures.append((block, street, future))
            
        # Gather and format
        resolved = []
        for (block, street, future) in futures:
            res = future.result()
            resolved.append({
                "block": block,
                "street": street,
                "postal": res["postal"],
                "latitude": res.get("latitude"),
                "longitude": res.get("longitude"),
                "query_sent": res.get("query_sent"),
                "results_count": res["results_count"],
                "full_response": res["full_response"]
            })
            
        # DB Push
        res_dict = batch_update_postal_codes(resolved)
        total_updated += res_dict.get("updated_dictionary", 0)
        logger.info(f"Progress: {min(i+chunk_size, len(addresses)):,} / {len(addresses):,}")

    return {"updated_dictionary": total_updated}


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import prefect
    # Point at the dev server
    os.environ.setdefault("PREFECT_API_URL", PREFECT_API_URL)

    parser = argparse.ArgumentParser(description="Engineer postal codes for HDB resale transactions.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sample-only", action="store_true", default=False,
                       help="Run Phase 1 (validation sample) only and exit.")
    group.add_argument("--approved", action="store_true", default=False,
                       help="Skip Phase 1 and run Phase 2 (full back-fill).")
    parser.add_argument("--sample-size", type=int, default=50,
                        help="Number of records in the validation sample (default 50).")
    args = parser.parse_args()

    if args.approved:
        print("▶  Phase 2: Full back-fill …")
        result = full_backfill_flow()
        print(f"✅ Back-fill complete: {result}")
    else:
        print("▶  Phase 1: Generating validation sample …")
        out_path = validation_sample_flow(sample_size=args.sample_size)
        print(f"\n✅ Validation sample written to: {out_path}")
        print("   Review the file, then re-run with --approved to proceed to full back-fill.")
