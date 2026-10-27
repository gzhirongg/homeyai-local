#!/usr/bin/env python3
"""
Read-only validation: snapshot / parquet rows must match hdb_mrt_features_at() (canonical).

Usage (repo root or backend):
    PYTHONPATH=. python backend/scripts/validate_mrt_pit_features.py
    PYTHONPATH=. python backend/scripts/validate_mrt_pit_features.py \\
        --parquet data/hdb_mrt_features.smoke.parquet

Exits 0 on [OK], 1 on [FAIL].
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_BACKEND = Path(__file__).resolve().parents[1]


def _ensure_repo_on_path() -> None:
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))


def _normalize_lines(val: Any) -> list[str | None]:
    if val is None:
        return []
    if hasattr(val, "tolist"):
        val = val.tolist()
    if isinstance(val, (list, tuple)):
        out = []
        for x in val:
            if x is None or (isinstance(x, float) and math.isnan(x)):
                out.append(None)
            else:
                out.append(str(x).strip())
        return sorted((x for x in out if x), key=lambda s: s)
    return sorted([str(val).strip()], key=lambda s: s) if str(val).strip() else []


def _nullish_scalar(x: Any) -> bool:
    if x is None:
        return True
    if isinstance(x, float) and math.isnan(x):
        return True
    try:
        import numpy as np

        if isinstance(x, np.floating) and np.isnan(x):
            return True
    except (ImportError, TypeError, ValueError):
        pass
    return False


def _scalar_eq(a: Any, b: Any) -> bool:
    if _nullish_scalar(a) and _nullish_scalar(b):
        return True
    if _nullish_scalar(a) or _nullish_scalar(b):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def _row_matches_fn(
    snap: dict[str, Any],
    fn_row: dict[str, Any],
) -> tuple[bool, str]:
    pairs = [
        ("dist_to_nearest_op_mrt", "dist_to_nearest_op_mrt"),
        ("travel_time_to_active_mrt", "travel_time_to_active_mrt"),
        ("pt_time_savings_vs_walk", "pt_time_savings_vs_walk"),
        ("line_connectivity_index", "line_connectivity_index"),
        ("days_since_mrt_announcement", "days_since_mrt_announcement"),
        ("days_to_mrt_opening", "days_to_mrt_opening"),
        ("speculative_upside_score", "speculative_upside_score"),
        ("has_future_upside", "has_future_upside"),
        ("is_proximity_nuisance", "is_proximity_nuisance"),
        ("num_unique_lines_within_1km", "num_unique_lines_within_1km"),
        ("nearest_planned_mrt_dist", "nearest_planned_mrt_dist"),
    ]
    for sk, fk in pairs:
        if not _scalar_eq(snap.get(sk), fn_row.get(fk)):
            return False, f"{sk}: snapshot={snap.get(sk)!r} fn={fn_row.get(fk)!r}"
    s_lines = _normalize_lines(snap.get("nearest_op_lines"))
    f_lines = _normalize_lines(fn_row.get("nearest_op_lines"))
    if s_lines != f_lines:
        return False, f"nearest_op_lines: snapshot={s_lines!r} fn={f_lines!r}"
    s_pl = _normalize_lines(snap.get("nearest_planned_lines"))
    f_pl = _normalize_lines(fn_row.get("nearest_planned_lines"))
    if s_pl != f_pl:
        return False, f"nearest_planned_lines: snapshot={s_pl!r} fn={f_pl!r}"
    return True, ""


def _admin_engine_url() -> str:
    import importlib.util

    path = _BACKEND / "scripts" / "build_mrt_pit_snapshot.py"
    spec = importlib.util.spec_from_file_location("_bsp_snapshot", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load build_mrt_pit_snapshot")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._load_env()
    raw = mod._resolve_database_url().strip()
    if not raw:
        raise RuntimeError("admin database URL not configured (DATABASE_URL_ADMIN / DATABASE_URL / ADMIN_DB_*)")
    return mod._normalize_sqlalchemy_url(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parquet",
        type=Path,
        default=_REPO / "data" / "hdb_mrt_features.smoke.parquet",
        help="Parquet with enriched_addr_id + month + snapshot columns",
    )
    parser.add_argument(
        "--use-admin-url",
        action="store_true",
        help="Use DATABASE_URL_ADMIN / DATABASE_URL / ADMIN_DB_* instead of read-only training URL",
    )
    args = parser.parse_args(argv)

    pq = args.parquet.resolve()
    if not pq.is_file():
        print(f"[FAIL] missing parquet: {pq}", file=sys.stderr)
        return 1

    try:
        import pandas as pd
        from sqlalchemy import create_engine, text
    except ImportError as e:
        print(f"[FAIL] need pandas, sqlalchemy: {e}", file=sys.stderr)
        return 1

    _ensure_repo_on_path()
    if args.use_admin_url:
        url = _admin_engine_url()
    else:
        from modelling.training_db import (  # noqa: PLC0415
            create_training_engine,
            get_training_database_url,
        )

        url = get_training_database_url()

    if not url:
        print("[FAIL] could not resolve database URL", file=sys.stderr)
        return 1
    if "postgresql://" in url and "+psycopg2" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg2://" + url.split("postgresql://", 1)[1]

    engine = create_engine(url)
    pdf = pd.read_parquet(pq)
    checks = 0
    failures: list[str] = []

    fn_sql = text(
        """
        SELECT
            dist_to_nearest_op_mrt,
            travel_time_to_active_mrt,
            pt_time_savings_vs_walk,
            line_connectivity_index,
            nearest_op_lines,
            days_since_mrt_announcement,
            days_to_mrt_opening,
            speculative_upside_score,
            has_future_upside,
            nearest_planned_lines,
            is_proximity_nuisance,
            num_unique_lines_within_1km,
            nearest_planned_mrt_dist
        FROM hdb_mrt_features_at(:aid, (:ym || '-01')::date)
        """
    )

    # 1) Round-trip vs parquet rows
    for _, row in pdf.iterrows():
        aid = int(row["enriched_addr_id"])
        ym = str(row["month"]).strip()
        snap = row.to_dict()
        with engine.connect() as conn:
            fn_row = dict(conn.execute(fn_sql, {"aid": aid, "ym": ym}).mappings().one())
        ok, msg = _row_matches_fn(snap, fn_row)
        checks += 1
        if not ok:
            failures.append(f"pair ({aid}, {ym}): {msg}")
            break

    if not failures:
        # 2) Determinism — 5 random pairs from parquet, 3 calls each
        sample = pdf.head(5)
        for _, row in sample.iterrows():
            aid = int(row["enriched_addr_id"])
            ym = str(row["month"]).strip()
            blobs: list[dict[str, Any]] = []
            with engine.connect() as conn:
                for _ in range(3):
                    blobs.append(dict(conn.execute(fn_sql, {"aid": aid, "ym": ym}).mappings().one()))
            checks += 3
            ok12, m12 = _row_matches_fn(blobs[0], blobs[1])
            ok23, m23 = _row_matches_fn(blobs[1], blobs[2])
            if not ok12 or not ok23:
                failures.append(f"non-deterministic ({aid}, {ym}): {m12 or m23}")
                break

    if not failures:
        # 3) No-coords branch
        no_coord_sql = text(
            """
            SELECT oe.id
            FROM hdb_address_enrichment_onemap oe
            WHERE oe.latitude IS NULL OR oe.longitude IS NULL
            LIMIT 1
            """
        )
        with engine.connect() as conn:
            rid = conn.execute(no_coord_sql).scalar()
        if rid is not None:
            with engine.connect() as conn:
                fn_row = dict(
                    conn.execute(fn_sql, {"aid": int(rid), "ym": "2020-06"}).mappings().one()
                )
            checks += 1
            exp = {
                "dist_to_nearest_op_mrt": None,
                "travel_time_to_active_mrt": None,
                "pt_time_savings_vs_walk": None,
                "line_connectivity_index": 1,
                "nearest_op_lines": [],
                "days_since_mrt_announcement": None,
                "days_to_mrt_opening": None,
                "speculative_upside_score": None,
                "has_future_upside": 0,
                "nearest_planned_lines": None,
                "is_proximity_nuisance": 0,
                "num_unique_lines_within_1km": None,
                "nearest_planned_mrt_dist": None,
            }
            for k, v in exp.items():
                if k == "nearest_op_lines":
                    got = _normalize_lines(fn_row.get(k))
                    if got != []:
                        failures.append(f"no-coords nearest_op_lines: expected [], got {got!r}")
                        break
                elif not _scalar_eq(fn_row.get(k), v):
                    failures.append(f"no-coords {k}: expected {v!r} got {fn_row.get(k)!r}")
                    break

    if not failures:
        # 4) Sanity — Tampines / Bishan near MRT (post-1990)
        town_sql = text(
            """
            SELECT DISTINCT ON (t.town, t.enriched_addr_id)
                t.enriched_addr_id, t.month, t.town
            FROM hdb_resale_transactions t
            WHERE t.enriched_addr_id IS NOT NULL
              AND t.month IS NOT NULL
              AND t.month >= '1990-01'
              AND (
                  t.town ILIKE '%TAMPINES%'
                  OR t.town ILIKE '%BISHAN%'
              )
            ORDER BY t.town, t.enriched_addr_id, t.month DESC
            LIMIT 5
            """
        )
        with engine.connect() as conn:
            towns = conn.execute(town_sql).mappings().all()
        for tr in towns:
            aid = int(tr["enriched_addr_id"])
            ym = str(tr["month"]).strip()
            with engine.connect() as conn:
                fn_row = dict(conn.execute(fn_sql, {"aid": aid, "ym": ym}).mappings().one())
            checks += 1
            d = fn_row.get("dist_to_nearest_op_mrt")
            lines = _normalize_lines(fn_row.get("nearest_op_lines"))
            if d is None or d >= 2000:
                failures.append(f"sanity distance ({aid}, {ym}, {tr['town']}): dist={d!r}")
                break
            if not lines:
                failures.append(f"sanity lines empty ({aid}, {ym}, {tr['town']})")
                break

    engine.dispose()

    if failures:
        print("[FAIL]", failures[0], file=sys.stderr)
        return 1
    print(f"[OK] {checks} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
