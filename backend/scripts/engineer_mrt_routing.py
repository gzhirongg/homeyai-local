"""
engineer_mrt_routing.py
========================
Prefect flow: pass-1 materialisation of up to four line-diverse MRT station legs
per HDB enrichment address (2 km, all non-UNKNOWN pit buckets), via OneMap
walk + public-transit only. Pass-2 PIT feature selection remains in
``hdb_mrt_features_at`` / snapshot SQL.

Usage (run locally, targeting the dev Prefect server):
    export PREFECT_API_URL=http://${REMOTE_VM_IP}:4201/api
    python backend/scripts/engineer_mrt_routing.py
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path
from collections import defaultdict

# Add backend directory to path to allow importing models
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
sys.path.append(str(_BACKEND_DIR))

# Load .env
for _env_candidate in [_BACKEND_DIR / ".env", _BACKEND_DIR.parent / ".env"]:
    if _env_candidate.exists():
        for _line in _env_candidate.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                k, _, v = _line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        break

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
import json
import logging

from prefect import flow, task, get_run_logger
from prefect.task_runners import ThreadPoolTaskRunner
from prefect.cache_policies import NO_CACHE

from models import SessionLocal, HdbMrtRoute, DATABASE_URL as _MODELS_DATABASE_URL
from services.onemap_service import OneMapService
from services.geospatial_service import select_line_diverse_mrt_candidates

if "sqlite" in (_MODELS_DATABASE_URL or "").lower():
    sys.exit(
        "ERROR: PostgreSQL is required. Set DATABASE_URL_ADMIN or DATABASE_URL "
        "(or ADMIN_DB_* + DB_HOST + DB_NAME; see backend/scripts/db_env.py)."
    )

MODES = ["walk", "pt"]


def parse_route_result(resp: dict, route_type: str):
    """
    Returns (distance_m, time_mins) or (None, None) if the response is
    empty or un-parseable.
    """
    try:
        if route_type in ("walk", "drive", "cycle"):
            summary = resp.get("route_summary", {})
            dist = summary.get("total_distance")
            t = summary.get("total_time")
            if dist is None or t is None:
                return None, None
            return int(dist), int(t) // 60
        elif route_type == "pt":
            plan = resp.get("plan", {})
            itineraries = plan.get("itineraries", [])
            if not itineraries:
                return None, None
            best = itineraries[0]
            return int(best.get("walkDistance", 0)), int(best.get("duration", 0)) // 60
    except Exception as e:
        pass
    return None, None


def _purge_stale_routes_for_addresses(db: Session, route_dicts: list) -> None:
    """Remove hdb_mrt_routes rows not in the new canonical physical_station_id set per address."""
    by_addr: dict[int, set[int]] = defaultdict(set)
    for r in route_dicts:
        by_addr[int(r["hdb_addr_id"])].add(int(r["physical_station_id"]))
    for aid, keep in by_addr.items():
        if not keep:
            continue
        (
            db.query(HdbMrtRoute)
            .filter(
                HdbMrtRoute.hdb_addr_id == aid,
                HdbMrtRoute.physical_station_id.notin_(list(keep)),
            )
            .delete(synchronize_session=False)
        )


def refresh_routes_global(
    *,
    limit: int,
    only_hdb_addr_id: int | None = None,
) -> int:
    """
    Global refresh to align legacy station-set choices to the new selector, while minimizing OneMap calls:

    - For each enrichment address with coords, compute S_new (up to 4 physical_station_id).
    - Read S_old from hdb_mrt_routes.
    - Purge rows in (S_old - S_new).
    - Compute routes ONLY for (S_new - S_old).
    - If (addr, physical_station_id) already exists, skip OneMap even if metrics are NULL (per refresh reuse rule).
    """
    logger = logging.getLogger(__name__)
    service = OneMapService(logger=logger)

    db = SessionLocal()
    try:
        if only_hdb_addr_id is not None:
            addr_rows = db.execute(
                text(
                    """
                    SELECT id AS hdb_addr_id, latitude, longitude
                    FROM hdb_address_enrichment_onemap
                    WHERE id = :id
                      AND latitude IS NOT NULL
                      AND longitude IS NOT NULL
                    """
                ),
                {"id": only_hdb_addr_id},
            ).fetchall()
        else:
            addr_rows = db.execute(
                text(
                    """
                    SELECT id AS hdb_addr_id, latitude, longitude
                    FROM hdb_address_enrichment_onemap
                    WHERE latitude IS NOT NULL
                      AND longitude IS NOT NULL
                    ORDER BY id ASC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).fetchall()

        inserted = 0
        for row in addr_rows:
            hdb_addr_id = int(row.hdb_addr_id)
            lat, lng = float(row.latitude), float(row.longitude)

            top_mrts = select_line_diverse_mrt_candidates(lat, lng, db, radius_km=2.0, max_stations=4)
            s_new = {int(m["physical_station_id"]) for m in top_mrts if m.get("physical_station_id")}
            haversine_by_physical_id = {
                int(m["physical_station_id"]): int(float(m.get("distance", 0.0)) * 1000)
                for m in top_mrts
                if m.get("physical_station_id")
            }

            s_old = set(
                r[0]
                for r in db.execute(
                    text(
                        "SELECT physical_station_id FROM hdb_mrt_routes WHERE hdb_addr_id = :aid"
                    ),
                    {"aid": hdb_addr_id},
                ).fetchall()
            )

            if not s_new:
                if s_old:
                    db.query(HdbMrtRoute).filter(HdbMrtRoute.hdb_addr_id == hdb_addr_id).delete(
                        synchronize_session=False
                    )
                    db.commit()
                continue

            stale = list(s_old - s_new)
            if stale:
                (
                    db.query(HdbMrtRoute)
                    .filter(
                        HdbMrtRoute.hdb_addr_id == hdb_addr_id,
                        HdbMrtRoute.physical_station_id.in_(stale),
                    )
                    .delete(synchronize_session=False)
                )

            s_add = sorted(s_new - s_old)
            for physical_station_id in s_add:
                mrt_coords = db.execute(
                    text(
                        """
                        SELECT lat, long
                        FROM mrt_physical_stations
                        WHERE id = :id
                        """
                    ),
                    {"id": physical_station_id},
                ).fetchone()
                if not mrt_coords or mrt_coords.lat is None or mrt_coords.long is None:
                    continue

                end_lat, end_lng = mrt_coords.lat, mrt_coords.long

                routes_data = {mode: {"dist": None, "time": None, "raw": None} for mode in MODES}
                for mode in MODES:
                    try:
                        resp = service.get_route(lat, lng, end_lat, end_lng, route_type=mode)
                        if resp is not None:
                            dist, time_mins = parse_route_result(resp, mode)
                            if dist is not None:
                                routes_data[mode] = {
                                    "dist": dist,
                                    "time": time_mins,
                                    "raw": json.dumps(resp),
                                }
                    except Exception as e:
                        logger.warning(
                            f"{mode} routing FAILED for hdb_addr_id={hdb_addr_id} "
                            f"-> physical_station_id={physical_station_id}: {e}"
                        )

                db.add(
                    HdbMrtRoute(
                        hdb_addr_id=hdb_addr_id,
                        physical_station_id=physical_station_id,
                        haversine_distance_m=haversine_by_physical_id.get(physical_station_id),
                        walk_distance_m=routes_data["walk"]["dist"],
                        walk_time_mins=routes_data["walk"]["time"],
                        raw_walk_response=routes_data["walk"]["raw"],
                        drive_distance_m=None,
                        drive_time_mins=None,
                        raw_drive_response=None,
                        pt_distance_m=routes_data["pt"]["dist"],
                        pt_time_mins=routes_data["pt"]["time"],
                        raw_pt_response=routes_data["pt"]["raw"],
                        updated_at=datetime.now(tz=timezone.utc),
                    )
                )
                inserted += 1

            db.commit()

        return inserted
    finally:
        db.close()


@task(name="fetch-unrouted-addresses", retries=2, retry_delay_seconds=5)
def fetch_unrouted_addresses(rerun_partial: bool, limit: int = 5000) -> list:
    """Return a list of addresses that need routing."""
    logger = get_run_logger()
    logger.info(f"Fetching addresses (rerun_partial={rerun_partial}) ...")

    db = SessionLocal()
    try:
        if rerun_partial:
            sql = text("""
                SELECT DISTINCT e.id AS hdb_addr_id, t.block, t.street_name, e.latitude, e.longitude
                FROM hdb_address_enrichment_onemap e
                JOIN hdb_resale_transactions t ON t.enriched_addr_id = e.id
                JOIN hdb_mrt_routes r ON r.hdb_addr_id = e.id
                WHERE e.latitude IS NOT NULL
                  AND (
                       r.walk_distance_m IS NULL OR r.walk_time_mins IS NULL
                       OR r.pt_distance_m IS NULL OR r.pt_time_mins IS NULL
                  )
                LIMIT :limit
            """)
        else:
            sql = text("""
                SELECT DISTINCT e.id AS hdb_addr_id, t.block, t.street_name, e.latitude, e.longitude
                FROM hdb_address_enrichment_onemap e
                JOIN hdb_resale_transactions t ON t.enriched_addr_id = e.id
                LEFT JOIN hdb_mrt_routes r ON r.hdb_addr_id = e.id
                WHERE r.hdb_addr_id IS NULL AND e.latitude IS NOT NULL
                LIMIT :limit
            """)
        rows = db.execute(sql, {"limit": limit}).fetchall()
    finally:
        db.close()

    logger.info(f"Found {len(rows):,} addresses to process.")
    return rows


@task(name="route-hdb-to-mrts", retries=1, retry_delay_seconds=3, cache_policy=NO_CACHE)
def route_block_to_mrts(
    row: dict,
    service: OneMapService
) -> list:
    """Line-diverse MRT candidates + OneMap walk/PT only."""
    logger = get_run_logger()
    block, street = row["block"], row["street_name"]
    hdb_addr_id = row["hdb_addr_id"]
    lat, lng = row["latitude"], row["longitude"]

    db = SessionLocal()
    try:
        top_mrts = select_line_diverse_mrt_candidates(lat, lng, db, radius_km=2.0, max_stations=4)

        if not top_mrts:
            db.query(HdbMrtRoute).filter(HdbMrtRoute.hdb_addr_id == hdb_addr_id).delete(
                synchronize_session=False
            )
            db.commit()
            return []

        all_routes = []
        for mrt in top_mrts:
            physical_station_id = mrt.get("physical_station_id")
            if not physical_station_id:
                continue
            physical_station_id = int(physical_station_id)

            existing = (
                db.query(HdbMrtRoute)
                .filter(
                    HdbMrtRoute.hdb_addr_id == hdb_addr_id,
                    HdbMrtRoute.physical_station_id == physical_station_id,
                )
                .one_or_none()
            )
            if (
                existing is not None
                and existing.walk_distance_m is not None
                and existing.walk_time_mins is not None
                and existing.pt_distance_m is not None
                and existing.pt_time_mins is not None
            ):
                all_routes.append(
                    {
                        "hdb_addr_id": hdb_addr_id,
                        "physical_station_id": physical_station_id,
                        "haversine_distance_m": int(mrt.get("distance", 0) * 1000),
                        "walk_distance_m": existing.walk_distance_m,
                        "walk_time_mins": existing.walk_time_mins,
                        "raw_walk_response": existing.raw_walk_response,
                        "drive_distance_m": existing.drive_distance_m,
                        "drive_time_mins": existing.drive_time_mins,
                        "raw_drive_response": existing.raw_drive_response,
                        "pt_distance_m": existing.pt_distance_m,
                        "pt_time_mins": existing.pt_time_mins,
                        "raw_pt_response": existing.raw_pt_response,
                        "updated_at": datetime.now(tz=timezone.utc),
                    }
                )
                continue

            mrt_coords = db.execute(
                text(
                    """
                    SELECT lat, long
                    FROM mrt_physical_stations
                    WHERE id = :id
                    """
                ),
                {"id": physical_station_id},
            ).fetchone()
            if not mrt_coords or mrt_coords.lat is None or mrt_coords.long is None:
                continue

            end_lat, end_lng = mrt_coords.lat, mrt_coords.long
            haversine_m = int(mrt.get("distance", 0) * 1000)

            routes_data = {mode: {"dist": None, "time": None, "raw": None} for mode in MODES}

            for mode in MODES:
                try:
                    resp = service.get_route(lat, lng, end_lat, end_lng, route_type=mode)
                    if resp is not None:
                        dist, time_mins = parse_route_result(resp, mode)
                        if dist is not None:
                            routes_data[mode] = {
                                "dist": dist,
                                "time": time_mins,
                                "raw": json.dumps(resp)
                            }
                except Exception as e:
                    logger.warning(
                        f"{mode} routing FAILED for {block} {street} "
                        f"-> physical_station_id={physical_station_id}: {e}"
                    )

            all_routes.append(
                {
                    "hdb_addr_id": hdb_addr_id,
                    "physical_station_id": physical_station_id,
                    "haversine_distance_m": haversine_m,
                    "walk_distance_m": routes_data["walk"]["dist"],
                    "walk_time_mins": routes_data["walk"]["time"],
                    "raw_walk_response": routes_data["walk"]["raw"],
                    "drive_distance_m": None,
                    "drive_time_mins": None,
                    "raw_drive_response": None,
                    "pt_distance_m": routes_data["pt"]["dist"],
                    "pt_time_mins": routes_data["pt"]["time"],
                    "raw_pt_response": routes_data["pt"]["raw"],
                    "updated_at": datetime.now(tz=timezone.utc),
                }
            )
    finally:
        db.close()

    return all_routes


@task(name="batch-update-mrt-routes", retries=2, retry_delay_seconds=10)
def batch_update_mrt_routes(all_routes: list) -> int:
    """Upsert routing data and drop stale physical_station_id legs per address."""
    if not all_routes:
        return 0

    logger = get_run_logger()
    db = SessionLocal()
    try:
        for rdict in all_routes:
            existing = (
                db.query(HdbMrtRoute)
                .filter(
                    HdbMrtRoute.hdb_addr_id == rdict["hdb_addr_id"],
                    HdbMrtRoute.physical_station_id == rdict["physical_station_id"],
                )
                .one_or_none()
            )
            if existing:
                for k, v in rdict.items():
                    setattr(existing, k, v)
            else:
                db.add(HdbMrtRoute(**rdict))
        _purge_stale_routes_for_addresses(db, all_routes)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to upsert routes: {e}")
        raise
    finally:
        db.close()

    return len(all_routes)


@flow(
    name="hdb-mrt-routing",
    description="Multi-threaded routing from HDB blocks to adjacent top MRTs.",
    task_runner=ThreadPoolTaskRunner(max_workers=5),
)
def mrt_routing_flow(rerun_partial: bool = False, limit: int = 5000) -> int:
    logger = get_run_logger()
    service = OneMapService(logger=logger)

    unprocessed = fetch_unrouted_addresses(rerun_partial=rerun_partial, limit=limit)
    if not unprocessed:
        logger.info("No addresses to process.")
        return 0

    chunk_size = 100
    total_upserted = 0

    for i in range(0, len(unprocessed), chunk_size):
        chunk = unprocessed[i:i + chunk_size]

        futures = []
        for row in chunk:
            r_dict = {
                "hdb_addr_id": row.hdb_addr_id,
                "block": row.block,
                "street_name": row.street_name,
                "latitude": row.latitude,
                "longitude": row.longitude,
            }
            future = route_block_to_mrts.submit(r_dict, service)
            futures.append(future)

        chunk_routes = []
        for future in futures:
            res = future.result()
            if res:
                chunk_routes.extend(res)

        upserted = batch_update_mrt_routes(chunk_routes)
        total_upserted += upserted
        logger.info(f"Progress: {min(i + chunk_size, len(unprocessed)):,} / {len(unprocessed):,} (Upserted {upserted} routes)")

    return total_upserted


@flow(
    name="hdb-mrt-routing-global-refresh",
    description="Global set-diff refresh for hdb_mrt_routes with minimal recompute.",
)
def mrt_routing_global_refresh_flow(limit: int = 5000, only_hdb_addr_id: int | None = None) -> int:
    logger = get_run_logger()
    logger.info(
        "Starting global refresh (limit=%s, only_hdb_addr_id=%s)",
        limit,
        only_hdb_addr_id,
    )
    inserted = refresh_routes_global(limit=limit, only_hdb_addr_id=only_hdb_addr_id)
    logger.info("Global refresh inserted %s new route rows", inserted)
    return inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HDB → nearby MRT OneMap routing")
    parser.add_argument("--limit", type=int, default=2000, help="Rows per fetch batch")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Global refresh: purge stale legs and insert missing legs for coords addresses (minimal recompute).",
    )
    parser.add_argument(
        "--refresh-only-hdb-addr-id",
        type=int,
        default=None,
        help="Refresh a single enrichment address id (smoke/debug).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--once-unrouted",
        action="store_true",
        help="Single unrouted-address batch then exit (safe to repeat).",
    )
    group.add_argument(
        "--once-partial",
        action="store_true",
        help="Single partial-rerun batch then exit.",
    )
    args = parser.parse_args()

    def _resolve_prefect_api_url() -> str:
        u = (os.environ.get("PREFECT_API_URL") or "").strip()
        if u:
            return u
        host = (os.environ.get("REMOTE_VM_IP") or "").strip()
        if not host:
            print(
                "ERROR: Set PREFECT_API_URL or REMOTE_VM_IP (e.g. in project root .env) "
                "for the Prefect API URL.",
                file=sys.stderr,
            )
            sys.exit(1)
        return f"http://{host}:4201/api"

    PREFECT_API_URL = _resolve_prefect_api_url()
    os.environ.setdefault("PREFECT_API_URL", PREFECT_API_URL)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if args.refresh:
        n = refresh_routes_global(limit=args.limit, only_hdb_addr_id=args.refresh_only_hdb_addr_id)
        print(f"Done: inserted {n} new route rows")
        sys.exit(0 if n >= 0 else 1)

    if args.once_unrouted:
        print(f"▶ One batch: unrouted (limit={args.limit})")
        n = mrt_routing_flow(rerun_partial=False, limit=args.limit)
        print(f"Done: upserted {n} route rows")
        sys.exit(0 if n >= 0 else 1)

    if args.once_partial:
        print(f"▶ One batch: partial reroute (limit={args.limit})")
        n = mrt_routing_flow(rerun_partial=True, limit=args.limit)
        print(f"Done: upserted {n} route rows")
        sys.exit(0 if n >= 0 else 1)

    # Phase 1: Fully unrouted blocks
    print("▶ Phase 1: Routing addresses with no mrt routes...")
    while True:
        upserted = mrt_routing_flow(rerun_partial=False, limit=args.limit)
        if upserted == 0:
            break

    # Phase 2: Rerun partials
    print("▶ Phase 2: Re-running partially failed routes...")
    while True:
        upserted = mrt_routing_flow(rerun_partial=True, limit=args.limit)
        if upserted == 0:
            break

    print("✅ Full MRT routing enrichment complete!")
