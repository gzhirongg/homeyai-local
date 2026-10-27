#!/usr/bin/env python3
"""
Read-only checklist for Temporal MRT feature prerequisites (Postgres / PostGIS).

Usage (from repo root or backend):

    cd backend && export DATABASE_URL_ADMIN=postgresql://...
    python scripts/validate_mrt_enrichment.py

Exit codes:
    0 - all checks pass (warnings only are OK unless --strict-warnings)
    1 - one or more [FAIL]
    2 - connectivity / dialect issues

Loads ``DATABASE_URL_ADMIN`` or ``DATABASE_URL`` from the environment or from backend/.env and repo /.env via setdefault-style parsing.

See docs/guides/mrt-enrichment-pipeline.md for the full runbook.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent

for _candidate in (_BACKEND / ".env", _REPO / ".env"):
    if _candidate.exists():
        for _line in _candidate.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                k, _, v = _line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break


def _load_dotenv_candidates() -> None:
    """No-op helper — env already loaded above; kept for tests / imports."""
    return


EXPECTED_ALEMBIC_REV = os.environ.get(
    "EXPECTED_ALEMBIC_REV", "f1a2b3c4d5e6"
).strip()


def _resolve_database_url() -> str:
    url = (
        (os.environ.get("DATABASE_URL_ADMIN") or "").strip()
        or (os.environ.get("DATABASE_URL") or "").strip()
    )
    if url:
        return url
    # Optional assembly from ADMIN_DB_* and host vars (compose / .env)
    user = os.environ.get("ADMIN_DB_USER", "").strip()
    password = os.environ.get("ADMIN_DB_PASSWORD", "").strip()
    host = os.environ.get("DB_HOST") or os.environ.get("REMOTE_VM_IP") or ""
    host = host.strip()
    port = os.environ.get("DB_INNER_PORT", os.environ.get("DB_PORT", "5432")).strip()
    db = os.environ.get("DB_NAME", "real_estate_dev_db").strip()
    if user and password and host and db:
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
    return ""


def _ensure_engine_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


def _status(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Treat [WARN] as failure exit code.",
    )
    args = parser.parse_args()

    _load_dotenv_candidates()
    raw_url = _resolve_database_url()
    if not raw_url:
        print(
            "ERROR: No admin database URL (set DATABASE_URL_ADMIN or DATABASE_URL, "
            "or complete ADMIN_DB_* / host assemble vars)."
        )
        print(
            "Example: export DATABASE_URL_ADMIN=postgresql://... or set ADMIN_DB_USER, "
            "ADMIN_DB_PASSWORD, DB_HOST, DB_INNER_PORT, DB_NAME"
        )
        return 2

    failed = False
    warned = False

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("ERROR: sqlalchemy is required.")
        return 2

    try:
        engine = create_engine(_ensure_engine_url(raw_url), pool_pre_ping=True)
    except Exception as exc:
        print(f"ERROR: could not create engine: {exc}")
        return 2

    dialect = getattr(engine.dialect, "name", "")
    if dialect != "postgresql":
        _status("FAIL", f"PostgreSQL required for temporal pipeline; dialect={dialect!r}")
        engine.dispose()
        return 2

    with engine.connect() as conn:
        # --- dialect smoke ---
        try:
            rv = conn.execute(text("SHOW server_version")).scalar()
            _status("PASS", f"Postgres reachable (server_version hint: {str(rv)[:60]})")
        except Exception as exc:
            _status("FAIL", f"PostgreSQL probe failed: {exc}")
            engine.dispose()
            return 2

        # --- Alembic head ---
        try:
            row = conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1")).fetchone()
            head = row[0] if row else None
            if head != EXPECTED_ALEMBIC_REV:
                warned = True
                _status(
                    "WARN",
                    f"Alembic head is {head!r}; expected {EXPECTED_ALEMBIC_REV!r} "
                    "(run alembic upgrade head from backend/ if pending).",
                )
            else:
                _status("PASS", f"Alembic head matches ({head})")
        except Exception as exc:
            failed = True
            _status("FAIL", f"Could not read alembic_version: {exc}")

        # --- PostGIS ---
        try:
            ext = conn.execute(
                text("SELECT COUNT(*) FROM pg_extension WHERE extname = 'postgis'")
            ).scalar_one()
            if int(ext or 0) < 1:
                failed = True
                _status("FAIL", "PostGIS extension is not enabled on this cluster.")
            else:
                _status("PASS", "PostGIS extension is present")
        except Exception as exc:
            failed = True
            _status("FAIL", f"Could not probe PostGIS: {exc}")

        # --- MRT split schema (physical + line rows) ---
        line_cols = {"derived_state", "opening_date_confidence", "physical_station_id"}
        phys_cols = {"canonical_name", "geom", "is_interchange", "lat", "long"}
        try:
            pr = conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'mrt_station_lines'
                    """
                )
            ).fetchall()
            existing_l = {r[0] for r in pr}
            missing_l = sorted(line_cols - existing_l)
            if missing_l:
                failed = True
                _status(
                    "FAIL",
                    "mrt_station_lines missing columns: " + ", ".join(missing_l),
                )
            else:
                _status(
                    "PASS",
                    "mrt_station_lines has line/temporal columns ("
                    + ", ".join(sorted(line_cols))
                    + ")",
                )
        except Exception as exc:
            failed = True
            _status("FAIL", f"Schema probe failed for mrt_station_lines: {exc}")

        try:
            pr2 = conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'mrt_physical_stations'
                    """
                )
            ).fetchall()
            existing_p = {r[0] for r in pr2}
            missing_p = sorted(phys_cols - existing_p)
            if missing_p:
                failed = True
                _status(
                    "FAIL",
                    "mrt_physical_stations missing columns: " + ", ".join(missing_p),
                )
            else:
                _status(
                    "PASS",
                    "mrt_physical_stations has footprint columns ("
                    + ", ".join(sorted(phys_cols))
                    + ")",
                )
        except Exception as exc:
            failed = True
            _status("FAIL", f"Schema probe failed for mrt_physical_stations: {exc}")

        # --- Snapshot & function ---
        try:
            fn_ok = conn.execute(
                text("SELECT COUNT(*) FROM pg_proc WHERE proname = 'hdb_mrt_features_at'")
            ).scalar_one()
            if int(fn_ok or 0) >= 1:
                _status("PASS", "Function hdb_mrt_features_at exists")
            else:
                failed = True
                _status("FAIL", "Function hdb_mrt_features_at is missing.")
        except Exception as exc:
            failed = True
            _status("FAIL", f"Could not probe hdb_mrt_features_at: {exc}")

        try:
            snap = conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema='public'
                          AND table_name='hdb_mrt_features_pit_snapshot'
                    )
                    """
                )
            ).scalar_one()
            if snap:
                _status("PASS", "Table hdb_mrt_features_pit_snapshot exists")
            else:
                failed = True
                _status("FAIL", "Table hdb_mrt_features_pit_snapshot missing")
        except Exception as exc:
            failed = True
            _status("FAIL", f"Could not probe snapshot table: {exc}")

        # --- MRT station ingest quality ---
        try:
            line_total = conn.execute(
                text("SELECT COUNT(*) FROM mrt_station_lines")
            ).scalar_one()
            phys_total = conn.execute(
                text("SELECT COUNT(*) FROM mrt_physical_stations")
            ).scalar_one()
            geom = conn.execute(
                text("SELECT COUNT(*) FROM mrt_physical_stations WHERE geom IS NOT NULL")
            ).scalar_one()
            dstate = conn.execute(
                text("SELECT COUNT(*) FROM mrt_station_lines WHERE derived_state IS NOT NULL")
            ).scalar_one()
            phys_fk = conn.execute(
                text(
                    "SELECT COUNT(*) FROM mrt_station_lines WHERE physical_station_id IS NOT NULL"
                )
            ).scalar_one()
            _status(
                "PASS",
                f"mrt line rows={int(line_total)}, physical={int(phys_total)}, "
                f"physical_with_geom={int(geom)}, derived_state_fill={int(dstate)}, "
                f"physical_fk_fill={int(phys_fk)}",
            )
            if int(line_total) > 0 and int(dstate) < int(line_total):
                warned = True
                _status(
                    "WARN",
                    "derived_state partially NULL — rerun scripts/ingest_mrt_temporal.py after migrations.",
                )
            if int(phys_total) > 0 and int(geom) < int(phys_total):
                warned = True
                _status("WARN", "Some physical MRT rows lack geom.")
        except Exception as exc:
            failed = True
            _status("FAIL", f"MRT row counts failed: {exc}")

        # --- Derived_state distribution ---
        try:
            dist = conn.execute(
                text(
                    """
                    SELECT COALESCE(derived_state, '<NULL>') AS st, COUNT(*)::bigint
                    FROM mrt_station_lines
                    GROUP BY 1 ORDER BY 2 DESC
                    """
                )
            ).fetchall()
            txt = "; ".join(f"{st}:{ct}" for st, ct in dist[:10])
            _status("INFO", f"derived_state distribution (top buckets): {txt or 'EMPTY TABLE'}")
        except Exception:
            pass

        # --- Enrichment completeness ---
        try:
            onemap_good = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM hdb_address_enrichment_onemap
                    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                    """
                )
            ).scalar_one()
            enr_fill = conn.execute(
                text("SELECT COUNT(*) FROM hdb_resale_transactions WHERE enriched_addr_id IS NOT NULL")
            ).scalar_one()
            tx_total = conn.execute(text("SELECT COUNT(*) FROM hdb_resale_transactions")).scalar_one()
            pct = round(100.0 * float(enr_fill or 0) / max(float(tx_total or 1), 1.0), 2)
            _status(
                "PASS",
                f"OneMap coords rows={int(onemap_good)}; resale with enriched_addr_id={int(enr_fill)}/{int(tx_total)} ({pct}%)",
            )
            if pct < 90.0 and tx_total:
                warned = True
                _status("WARN", "Low enriched_addr_id coverage — rerun backfill/engineer postal pipeline.")
        except Exception as exc:
            failed = True
            _status("FAIL", f"Enrichment coverage query failed: {exc}")

        # --- Routing completeness ---
        with_routes_cnt: int | None = None
        try:
            need_routes = conn.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT t.enriched_addr_id)::bigint
                    FROM hdb_resale_transactions t
                    WHERE t.enriched_addr_id IS NOT NULL
                    """
                )
            ).scalar_one()
            with_routes_cnt = conn.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT r.hdb_addr_id)::bigint
                    FROM hdb_mrt_routes r
                    """
                )
            ).scalar_one()
            unrouted = int((need_routes or 0) - (with_routes_cnt or 0))
            _status(
                "PASS",
                f"HDB enrichment addresses resale-linked={int(need_routes)}, "
                f"distinct with hdb_mrt_routes={int(with_routes_cnt)} (gap_est={max(unrouted,0)})",
            )
            if unrouted > 0:
                warned = True
                _status("WARN", f"Estimated {unrouted} enriched addresses still lacking any route legs.")
        except Exception as exc:
            failed = True
            with_routes_cnt = None
            _status("FAIL", f"Routing completeness query failed: {exc}")

        # --- Partial rerun candidates ---
        try:
            partial = conn.execute(
                text(
                    """
                    SELECT COUNT(*)::bigint
                    FROM hdb_mrt_routes
                    WHERE walk_distance_m IS NULL
                       OR walk_time_mins IS NULL
                       OR pt_distance_m IS NULL
                       OR pt_time_mins IS NULL
                    """
                )
            ).scalar_one()
            _status(
                "INFO",
                f"hdb_mrt_routes rows with NULL walk/pt metrics: {int(partial or 0)}",
            )
            if int(partial or 0) > 0:
                warned = True
                _status(
                    "WARN",
                    "Partial routing gaps remain — rerun Prefect with rerun_partial=true after Phase1.",
                )
        except Exception as exc:
            failed = True
            _status("FAIL", f"Partial route probe failed: {exc}")

        # --- Planned-leg coverage heuristic ---
        try:
            planned_routes = conn.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT r.hdb_addr_id)::bigint
                    FROM hdb_mrt_routes r
                    JOIN mrt_station_lines m ON m.physical_station_id = r.physical_station_id
                    WHERE m.derived_state IN (
                        'COMMITTED_DATED',
                        'COMMITTED_ESTIMATED',
                        'ANNOUNCED_UNDATED'
                    )
                    """
                )
            ).scalar_one()
            _status(
                "INFO",
                f"Distinct hdb_addr_id with routed legs touching planned-derived_state stations: "
                f"{int(planned_routes or 0)}",
            )
            if int(planned_routes or 0) == 0 and with_routes_cnt is not None and int(with_routes_cnt) > 0:
                warned = True
                _status(
                    "WARN",
                    "No planned-station joins detected yet — ingest may omit derived_state "
                    "or routing may not reach planned buckets.",
                )
        except Exception as exc:
            warned = True
            _status("WARN", f"Planned route heuristic skipped ({exc}).")

        # --- Sample smoke for PIT function (avoid ORDER BY random() on huge txn tables) ---
        sample_id = conn.execute(
            text(
                """
                SELECT enriched_addr_id
                FROM hdb_resale_transactions
                WHERE enriched_addr_id IS NOT NULL
                ORDER BY enriched_addr_id
                LIMIT 1
                """
            )
        ).scalar_one_or_none()

        sample_month = conn.execute(
            text(
                """
                SELECT month FROM hdb_resale_transactions
                WHERE enriched_addr_id IS NOT NULL AND month IS NOT NULL
                ORDER BY month
                LIMIT 1
                """
            )
        ).scalar_one_or_none()

        if sample_id is None:
            warned = True
            _status("WARN", "No enriched_addr_id to sample hdb_mrt_features_at(...).")
        else:
            try:
                ym = sample_month or "2020-01"
                fx = conn.execute(
                    text("SELECT * FROM hdb_mrt_features_at(:aid, CAST(:tx || '-01' AS DATE))"),
                    {"aid": int(sample_id), "tx": str(ym)[:7]},
                ).mappings().fetchone()
                if fx:
                    nz = sum(1 for _v in fx.values() if _v is not None)
                    _status(
                        "PASS",
                        f"Smoke hdb_mrt_features_at(addr={int(sample_id)}, month={ym}): rows returned "
                        f"(non-null field count ~= {nz})",
                    )
                else:
                    warned = True
                    _status("WARN", "hdb_mrt_features_at returned no row for sampled address/month.")
            except Exception as exc:
                warned = True
                _status("WARN", f"hdb_mrt_features_at smoke failed: {exc}")

    engine.dispose()

    print("----- summary -----")
    if failed:
        _status("FAIL", "Hard failures detected — resolve before enrichment/snapshot rebuild.")
        return 1
    if args.strict_warnings and warned:
        _status("FAIL", "Warnings treated as failures (--strict-warnings).")
        return 1
    if warned:
        _status("WARN", "Validation completed with warnings (OK for iterative dev runs).")
    else:
        _status("PASS", "Validation completed without warnings.")

    print(
        "\nNext steps:"
        "\n - Phase 1D: prefect deploy --all --prefect-file prefect.yaml"
        "\n - Phase 1E: POST /api/admin/trigger-mrt-routing (admin JWT)"
        "\n - Phase 2 docs: docs/guides/mrt-enrichment-pipeline.md"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
