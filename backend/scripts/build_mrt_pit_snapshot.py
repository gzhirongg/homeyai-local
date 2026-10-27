#!/usr/bin/env python3
"""
Materialise ``hdb_mrt_features_pit_snapshot`` using ``hdb_mrt_features_at`` (Alembic
``e8f1a2b3c4d5`` + ``f1a2b3c4d5e6``). Requires migration ``a1b2c3d4e5f6`` (jobs table).

**Batch mode (default):** no table TRUNCATE; workers claim one ``YYYY-MM`` at a time
(recent-first), ``INSERT … ON CONFLICT DO NOTHING``, update ``mrt_pit_build_jobs``.

**Smoke:** ``--smoke-limit N`` still TRUNCATEs the snapshot and inserts ``N`` random
distinct pairs (writes ``*.smoke.parquet`` only).

Usage (repo root)::

    python backend/scripts/build_mrt_pit_snapshot.py --workers 4
    python backend/scripts/build_mrt_pit_snapshot.py --max-months 24 --workers 4
    python backend/scripts/build_mrt_pit_snapshot.py --retry-errors
    python backend/scripts/build_mrt_pit_snapshot.py --reset-month 2024-06
    python backend/scripts/build_mrt_pit_snapshot.py --smoke-limit 50

Docker (backend service has deps: SQLAlchemy, prefect, etc.). From repo root with
``docker-compose.dev.yml`` (working directory in container is ``/app``)::

    docker compose -f docker-compose.dev.yml exec backend \\
      python scripts/build_mrt_pit_snapshot.py --smoke-limit 100

The backend service inherits ``PREFECT_API_URL`` from compose; deploy Prefect workflows from ``/app``::

    docker compose -f docker-compose.dev.yml exec backend sh -c 'cd /app && prefect deploy --all --prefect-file prefect.yaml'

Full VM stack (``docker-compose.yml``)::

    docker compose exec backend python scripts/build_mrt_pit_snapshot.py --workers 4
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from multiprocessing import Lock, Process, Value
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from prefect import flow, get_run_logger


def _repo_root() -> Path:
    """Host monorepo: …/project (has ``backend/main.py``). Docker backend container: …/parents[2] is ``/`` — use mounts at ``/data`` and ``/modelling``."""
    raw = (os.environ.get("HOMEYAI_REPO_ROOT") or "").strip()
    if raw:
        return Path(raw).resolve()
    script = Path(__file__).resolve()
    candidate = script.parents[2]
    if (candidate / "backend" / "main.py").is_file():
        return candidate
    return Path("/")


_REPO = _repo_root()


def _load_env() -> None:
    _backend_app = Path(__file__).resolve().parents[1]  # /app in Docker; …/backend on host
    for p in [_REPO / ".env", _REPO / "backend" / ".env", _backend_app / ".env"]:
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
    _expand_env_placeholders()


def _expand_env_placeholders(max_passes: int = 8) -> None:
    def sub(s: str) -> str:
        return re.sub(
            r"\$\{([^}]+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            s,
        )

    for _ in range(max_passes):
        changed = False
        for k, val in list(os.environ.items()):
            if "${" not in str(val):
                continue
            new_val = sub(str(val))
            if new_val != val:
                os.environ[k] = new_val
                changed = True
        if not changed:
            break


def _resolve_database_url() -> str:
    url = (os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL") or "").strip()
    if url:
        return url
    user = (os.environ.get("ADMIN_DB_USER") or "").strip()
    password = (os.environ.get("ADMIN_DB_PASSWORD") or "").strip()
    host = (os.environ.get("DB_HOST") or os.environ.get("REMOTE_VM_IP") or "").strip()
    port = (
        os.environ.get("DB_INNER_PORT") or os.environ.get("DB_PORT") or "5432"
    ).strip()
    db = (os.environ.get("DB_NAME") or "").strip()
    if not (user and password and host and db):
        return ""
    u, p = quote_plus(user), quote_plus(password)
    return f"postgresql+psycopg2://{u}:{p}@{host}:{port}/{db}"


def _normalize_sqlalchemy_url(url: str) -> str:
    u = url.strip()
    if u.startswith("postgres://"):
        return "postgresql+psycopg2://" + u[len("postgres://") :]
    if u.startswith("postgresql://") and "+psycopg2" not in u.split("://", 1)[0]:
        return "postgresql+psycopg2://" + u[len("postgresql://") :]
    return u


def _populate_smoke_sql(*, pair_limit: int) -> str:
    if pair_limit < 1:
        raise ValueError("pair_limit must be >= 1")
    lim = int(pair_limit)
    return f"""
        INSERT INTO hdb_mrt_features_pit_snapshot (
            hdb_addr_id, tx_year_month,
            dist_to_nearest_op_mrt, travel_time_to_active_mrt, pt_time_savings_vs_walk,
            line_connectivity_index, nearest_op_lines,
            days_since_mrt_announcement, days_to_mrt_opening, speculative_upside_score,
            has_future_upside, nearest_planned_lines, is_proximity_nuisance,
            num_unique_lines_within_1km, nearest_planned_mrt_dist,
            computed_at
        )
        SELECT
            pairs.hdb_addr_id,
            pairs.tx_year_month,
            f.dist_to_nearest_op_mrt,
            f.travel_time_to_active_mrt,
            f.pt_time_savings_vs_walk,
            f.line_connectivity_index,
            f.nearest_op_lines,
            f.days_since_mrt_announcement,
            f.days_to_mrt_opening,
            f.speculative_upside_score,
            f.has_future_upside,
            f.nearest_planned_lines,
            f.is_proximity_nuisance,
            f.num_unique_lines_within_1km,
            f.nearest_planned_mrt_dist,
            NOW()
        FROM (
            SELECT DISTINCT enriched_addr_id AS hdb_addr_id, month AS tx_year_month
            FROM hdb_resale_transactions
            WHERE enriched_addr_id IS NOT NULL AND month IS NOT NULL
            LIMIT {lim}
        ) pairs
        CROSS JOIN LATERAL (
            SELECT * FROM hdb_mrt_features_at(
                pairs.hdb_addr_id,
                (pairs.tx_year_month || '-01')::date
            )
        ) f;
        """


def _insert_one_month_sql() -> str:
    return """
        INSERT INTO hdb_mrt_features_pit_snapshot (
            hdb_addr_id, tx_year_month,
            dist_to_nearest_op_mrt, travel_time_to_active_mrt, pt_time_savings_vs_walk,
            line_connectivity_index, nearest_op_lines,
            days_since_mrt_announcement, days_to_mrt_opening, speculative_upside_score,
            has_future_upside, nearest_planned_lines, is_proximity_nuisance,
            num_unique_lines_within_1km, nearest_planned_mrt_dist,
            computed_at
        )
        SELECT
            pairs.hdb_addr_id,
            pairs.tx_year_month,
            f.dist_to_nearest_op_mrt,
            f.travel_time_to_active_mrt,
            f.pt_time_savings_vs_walk,
            f.line_connectivity_index,
            f.nearest_op_lines,
            f.days_since_mrt_announcement,
            f.days_to_mrt_opening,
            f.speculative_upside_score,
            f.has_future_upside,
            f.nearest_planned_lines,
            f.is_proximity_nuisance,
            f.num_unique_lines_within_1km,
            f.nearest_planned_mrt_dist,
            NOW()
        FROM (
            SELECT DISTINCT enriched_addr_id AS hdb_addr_id, month AS tx_year_month
            FROM hdb_resale_transactions
            WHERE enriched_addr_id IS NOT NULL AND month = :ym
        ) pairs
        CROSS JOIN LATERAL (
            SELECT * FROM hdb_mrt_features_at(
                pairs.hdb_addr_id,
                (pairs.tx_year_month || '-01')::date
            )
        ) f
        ON CONFLICT (hdb_addr_id, tx_year_month) DO NOTHING;
        """


def _seed_jobs_ddl() -> str:
    return """
        INSERT INTO mrt_pit_build_jobs (tx_year_month, pairs_total)
        SELECT month, COUNT(DISTINCT enriched_addr_id)::int
        FROM hdb_resale_transactions
        WHERE enriched_addr_id IS NOT NULL AND month IS NOT NULL
        GROUP BY month
        ON CONFLICT (tx_year_month) DO UPDATE
        SET pairs_total = EXCLUDED.pairs_total
        WHERE mrt_pit_build_jobs.status IN ('pending', 'error');
        """


def _claim_sql(*, retry_errors: bool, from_m: str | None, to_m: str | None) -> str:
    statuses = "('pending', 'error')" if retry_errors else "('pending')"
    bounds: list[str] = []
    if from_m:
        bounds.append("j.tx_year_month >= :from_m")
    if to_m:
        bounds.append("j.tx_year_month <= :to_m")
    filt = (" AND " + " AND ".join(bounds)) if bounds else ""
    return f"""
        WITH cand AS (
            SELECT j.tx_year_month
            FROM mrt_pit_build_jobs j
            WHERE j.status IN {statuses}
            {filt}
            ORDER BY j.tx_year_month DESC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE mrt_pit_build_jobs j
        SET status = 'running',
            worker_id = :wid,
            started_at = NOW(),
            error_msg = NULL
        FROM cand c
        WHERE j.tx_year_month = c.tx_year_month
        RETURNING j.tx_year_month, j.pairs_total;
        """


def _mp_worker(cfg: dict[str, Any]) -> None:
    """Child process: claim months until none left or shared budget exhausted."""
    from sqlalchemy import create_engine, text

    url = cfg["url"]
    wid = cfg["wid"]
    retry_errors = cfg["retry_errors"]
    from_m = cfg.get("from_m")
    to_m = cfg.get("to_m")
    max_months: int = cfg["max_months"]
    shared_done: Any = cfg["shared_done"]
    done_lock: Any = cfg["done_lock"]

    eng = create_engine(url)
    ins = text(_insert_one_month_sql())

    try:
        while True:
            with done_lock:
                if max_months > 0 and shared_done.value >= max_months:
                    break
            params: dict[str, Any] = {"wid": wid}
            if from_m:
                params["from_m"] = from_m
            if to_m:
                params["to_m"] = to_m
            claim_sql = text(_claim_sql(retry_errors=retry_errors, from_m=from_m, to_m=to_m))
            with eng.begin() as conn:
                row = conn.execute(claim_sql, params).mappings().first()
            if not row:
                break
            ym = str(row["tx_year_month"])
            expected = int(row["pairs_total"])
            t0 = time.perf_counter()
            try:
                with eng.begin() as conn:
                    conn.execute(ins, {"ym": ym})
                    got = int(
                        conn.execute(
                            text(
                                "SELECT COUNT(*)::int FROM hdb_mrt_features_pit_snapshot "
                                "WHERE tx_year_month = :ym"
                            ),
                            {"ym": ym},
                        ).scalar_one()
                    )
                    if got != expected:
                        raise RuntimeError(
                            f"month {ym}: snapshot rows {got} != pairs_total {expected}"
                        )
                    conn.execute(
                        text(
                            """
                            UPDATE mrt_pit_build_jobs
                            SET pairs_inserted = :got,
                                status = 'done',
                                completed_at = NOW()
                            WHERE tx_year_month = :ym
                            """
                        ),
                        {"got": got, "ym": ym},
                    )
                dt = time.perf_counter() - t0
                print(f"[worker {wid}] done {ym} ({expected} pairs) in {dt:.1f}s", flush=True)
            except Exception as exc:
                err = (str(exc) + "\n" + traceback.format_exc())[:4000]
                with eng.begin() as conn:
                    conn.execute(
                        text(
                            """
                            UPDATE mrt_pit_build_jobs
                            SET status = 'error',
                                error_msg = :err,
                                completed_at = NOW()
                            WHERE tx_year_month = :ym
                            """
                        ),
                        {"err": err, "ym": ym},
                    )
                print(f"[worker {wid}] ERROR {ym}: {exc}", flush=True)
            with done_lock:
                shared_done.value += 1
                if max_months > 0 and shared_done.value >= max_months:
                    break
    finally:
        eng.dispose()


def _run_smoke(args: argparse.Namespace, url: str) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    try:
        import pandas as pd
    except ImportError as e:
        sys.exit(str(e))

    engine = create_engine(url)
    pair_limit = args.smoke_limit
    count_sql = text(
        """
        SELECT COUNT(*)::bigint AS n
        FROM (
            SELECT DISTINCT enriched_addr_id, month
            FROM hdb_resale_transactions
            WHERE enriched_addr_id IS NOT NULL AND month IS NOT NULL
        ) t
        """
    )
    with engine.connect() as conn:
        total_pairs = int(conn.execute(count_sql).scalar_one())
    print(
        f"[smoke] distinct pairs in resale: {total_pairs:,}; TRUNCATE + insert up to {pair_limit}",
        flush=True,
    )
    populate = text(_populate_smoke_sql(pair_limit=pair_limit))
    lines_sql = text(
        """
        SELECT DISTINCT TRIM(network_line) AS nl
        FROM mrt_station_lines
        WHERE network_line IS NOT NULL AND TRIM(network_line) <> ''
        ORDER BY 1
        """
    )
    line_rows: list = []
    insert_s = 0.0
    with engine.begin() as conn:
        try:
            conn.execute(
                text(
                    "LOCK TABLE hdb_mrt_features_pit_snapshot IN ACCESS EXCLUSIVE MODE NOWAIT"
                )
            )
        except OperationalError as exc:
            sys.exit(
                "[smoke] could not lock snapshot table — another session is active.\n" + str(exc)
            )
        conn.execute(text("TRUNCATE TABLE hdb_mrt_features_pit_snapshot"))
        print("[smoke] running bounded INSERT …", flush=True)
        t0 = time.perf_counter()
        conn.execute(populate)
        insert_s = time.perf_counter() - t0
        line_rows = conn.execute(lines_sql).fetchall()
    inserted = 0
    with engine.connect() as conn:
        inserted = int(
            conn.execute(text("SELECT COUNT(*)::bigint FROM hdb_mrt_features_pit_snapshot")).scalar_one()
        )
    rate = inserted / insert_s if insert_s > 0 else 0.0
    eta_s = (total_pairs / rate) if rate > 0 else float("nan")
    print(
        f"[smoke] INSERT wall time: {insert_s:.2f}s ({inserted} rows); "
        f"~{rate:.2f} rows/s",
        flush=True,
    )
    if eta_s == eta_s:
        print(
            f"[smoke] extrapolated full INSERT: {eta_s / 3600:.2f} h (linear, approximate)",
            flush=True,
        )
    data_dir = _REPO / "data"
    modelling_dir = _REPO / "modelling"
    data_dir.mkdir(parents=True, exist_ok=True)
    modelling_dir.mkdir(parents=True, exist_ok=True)
    lines = [str(r.nl).strip() for r in line_rows if r.nl and str(r.nl).strip()]
    (modelling_dir / "_mrt_lines.smoke.json").write_text(
        json.dumps(lines, indent=2), encoding="utf-8"
    )
    pdf = pd.read_sql(
        """
        SELECT hdb_addr_id AS enriched_addr_id, tx_year_month AS month,
               dist_to_nearest_op_mrt, travel_time_to_active_mrt, pt_time_savings_vs_walk,
               line_connectivity_index, nearest_op_lines, days_since_mrt_announcement,
               days_to_mrt_opening, speculative_upside_score, has_future_upside,
               nearest_planned_lines, is_proximity_nuisance,
               num_unique_lines_within_1km, nearest_planned_mrt_dist
        FROM hdb_mrt_features_pit_snapshot ORDER BY 1, 2
        """,
        engine,
    )
    pq = data_dir / "hdb_mrt_features.smoke.parquet"
    pdf.to_parquet(pq, index=False)
    meta_path = data_dir / "hdb_mrt_features.smoke.parquet.meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "smoke_limit": pair_limit,
                "insert_lateral_wall_seconds": insert_s,
            },
            indent=2,
        )
    )
    print(f"[smoke] wrote {pq}", flush=True)
    engine.dispose()


def _export_full_parquet(url: str, *, partial: bool) -> None:
    from sqlalchemy import create_engine, text

    try:
        import pandas as pd
    except ImportError as e:
        sys.exit(str(e))

    eng = create_engine(url)
    lines_sql = text(
        """
        SELECT DISTINCT TRIM(network_line) AS nl
        FROM mrt_station_lines
        WHERE network_line IS NOT NULL AND TRIM(network_line) <> ''
        ORDER BY 1
        """
    )
    with eng.connect() as conn:
        line_rows = conn.execute(lines_sql).fetchall()
    lines = [str(r.nl).strip() for r in line_rows if r.nl and str(r.nl).strip()]
    suffix = ".partial" if partial else ""
    md_dir = _REPO / "modelling"
    md_dir.mkdir(parents=True, exist_ok=True)
    (md_dir / f"_mrt_lines{suffix}.json").write_text(json.dumps(lines, indent=2), encoding="utf-8")

    pdf = pd.read_sql(
        """
        SELECT hdb_addr_id AS enriched_addr_id, tx_year_month AS month,
               dist_to_nearest_op_mrt, travel_time_to_active_mrt, pt_time_savings_vs_walk,
               line_connectivity_index, nearest_op_lines, days_since_mrt_announcement,
               days_to_mrt_opening, speculative_upside_score, has_future_upside,
               nearest_planned_lines, is_proximity_nuisance,
               num_unique_lines_within_1km, nearest_planned_mrt_dist
        FROM hdb_mrt_features_pit_snapshot ORDER BY 1, 2
        """,
        eng,
    )
    data_dir = _REPO / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    base = "hdb_mrt_features"
    pq = data_dir / f"{base}{suffix}.parquet" if suffix else data_dir / f"{base}.parquet"
    pdf.to_parquet(pq, index=False)
    meta = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(pdf),
        "partial": partial,
        "network_line_vocab": lines,
    }
    (data_dir / f"{base}{suffix}.parquet.meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Exported {pq} ({len(pdf)} rows)", flush=True)
    eng.dispose()


def _run_batch(args: argparse.Namespace, url: str) -> dict[str, Any]:
    """Seed jobs, run multiprocessing workers, optional parquet export. Used by CLI and Prefect."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    eng = create_engine(url)
    try:
        if args.reset_month:
            ym = args.reset_month.strip()
            with eng.begin() as conn:
                conn.execute(
                    text("DELETE FROM hdb_mrt_features_pit_snapshot WHERE tx_year_month = :ym"),
                    {"ym": ym},
                )
                conn.execute(
                    text(
                        """
                        UPDATE mrt_pit_build_jobs
                        SET status = 'pending', pairs_inserted = 0,
                            worker_id = NULL, started_at = NULL, completed_at = NULL, error_msg = NULL
                        WHERE tx_year_month = :ym
                        """
                    ),
                    {"ym": ym},
                )
            print(f"[reset] month {ym} cleared; job reset to pending", flush=True)

        with eng.begin() as conn:
            conn.execute(text(_seed_jobs_ddl()))
    except SQLAlchemyError as exc:
        if "mrt_pit_build_jobs" in str(exc).lower():
            sys.exit(
                "mrt_pit_build_jobs missing — run: cd backend && alembic upgrade head "
                f"(need revision a1b2c3d4e5f6). DB error: {exc}"
            )
        raise
    finally:
        eng.dispose()

    max_m = max(0, int(args.max_months))
    shared_done = Value("i", 0)
    done_lock = Lock()
    procs: list[Process] = []
    for i in range(max(1, int(args.workers))):
        cfg = {
            "url": url,
            "wid": f"w{i}-{os.getpid()}",
            "retry_errors": bool(args.retry_errors),
            "from_m": args.from_month,
            "to_m": args.to_month,
            "max_months": max_m,
            "shared_done": shared_done,
            "done_lock": done_lock,
        }
        p = Process(target=_mp_worker, args=(cfg,))
        p.start()
        procs.append(p)
    for p in procs:
        p.join()

    eng = create_engine(url)
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pnd,
                        SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS run,
                        SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS err,
                        SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done
                    FROM mrt_pit_build_jobs
                    """
                )
            ).mappings().one()
        print(
            f"jobs: pending={row['pnd']} running={row['run']} error={row['err']} done={row['done']}",
            flush=True,
        )
        pending = row["pnd"] or 0
        running = row["run"] or 0
        err_count = row["err"] or 0
        done_count = row["done"] or 0
        partial = max_m > 0 or pending > 0 or err_count > 0 or running > 0
        summary = {
            "jobs_pending": int(pending),
            "jobs_running": int(running),
            "jobs_error": int(err_count),
            "jobs_done": int(done_count),
            "partial": bool(partial),
        }
    finally:
        eng.dispose()

    if not args.no_export_parquet:
        _export_full_parquet(url, partial=bool(partial))
    return summary


@flow(name="build-pit-snapshot", log_prints=True, retries=0)
def build_pit_snapshot_flow(
    workers: int = 6,
    from_month: str | None = None,
    to_month: str | None = None,
    max_months: int = 0,
    retry_errors: bool = False,
    reset_month: str | None = None,
    export_parquet: bool = False,
) -> dict[str, Any]:
    """Prefect 3 flow: month-grain snapshot backfill (runs on VM worker; use spawn for child processes)."""
    import multiprocessing as mp

    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    log = get_run_logger()
    _load_env()
    raw = _resolve_database_url().strip()
    if not raw:
        raise RuntimeError(
            "DATABASE_URL_ADMIN, DATABASE_URL, or ADMIN_DB_* + DB_HOST + DB_NAME required on the Prefect worker host."
        )
    url = _normalize_sqlalchemy_url(raw)
    log.info(
        "PIT snapshot batch: workers=%s from_month=%s to_month=%s max_months=%s retry_errors=%s export_parquet=%s",
        workers,
        from_month,
        to_month,
        max_months,
        retry_errors,
        export_parquet,
    )
    ns = argparse.Namespace(
        smoke_limit=0,
        workers=workers,
        from_month=from_month,
        to_month=to_month,
        max_months=max_months,
        retry_errors=retry_errors,
        reset_month=reset_month,
        no_export_parquet=not export_parquet,
    )
    return _run_batch(ns, url)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-limit", type=int, default=0, metavar="N")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--from-month", type=str, default=None, help="YYYY-MM inclusive lower bound")
    parser.add_argument("--to-month", type=str, default=None, help="YYYY-MM inclusive upper bound")
    parser.add_argument(
        "--max-months",
        type=int,
        default=0,
        help="Stop after this many month-completions across the pool (0 = unlimited)",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Allow claiming jobs in status error",
    )
    parser.add_argument(
        "--reset-month",
        type=str,
        default=None,
        help="Delete snapshot rows for YYYY-MM and reset that job row to pending",
    )
    parser.add_argument(
        "--no-export-parquet",
        action="store_true",
        help="Skip parquet / _mrt_lines export after batch run",
    )
    args = parser.parse_args(argv)

    _load_env()
    raw = _resolve_database_url().strip()
    if not raw:
        sys.exit(
            "DATABASE_URL_ADMIN, DATABASE_URL, or ADMIN_DB_* + DB_HOST + DB_NAME required (see script docstring)."
        )
    url = _normalize_sqlalchemy_url(raw)

    if args.smoke_limit > 0:
        _run_smoke(args, url)
        return

    _run_batch(args, url)


if __name__ == "__main__":
    main()

