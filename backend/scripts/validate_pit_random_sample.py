#!/usr/bin/env python3
"""
Random-sample validation: compare ``hdb_mrt_features_pit_snapshot`` rows to live
``hdb_mrt_features_at`` for the same (hdb_addr_id, month) after routing / PIT rebuilds.

Usage (backend container, admin DB URL set — ``DATABASE_URL_ADMIN`` or ``DATABASE_URL``)::

    cd /app && python scripts/validate_pit_random_sample.py --seed 42 --n 25
    cd /app && python scripts/validate_pit_random_sample.py \\
        --seed 1 --n 15 --month 2024-07 --include-ids 6451

Always includes postal ``050034`` (34 Upper Cross Street, ``hdb_addr_id=6451``) unless
disabled with ``--no-canonical``.

Exit code: 0 if all sampled snapshot rows match the function; 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

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


def _db_url() -> str:
    u = (
        (os.environ.get("DATABASE_URL_ADMIN") or "").strip()
        or (os.environ.get("DATABASE_URL") or "").strip()
    )
    if not u:
        print("DATABASE_URL_ADMIN or DATABASE_URL required", file=sys.stderr)
        sys.exit(2)
    if u.startswith("postgresql://") and "+" not in u.split("://", 1)[0]:
        return "postgresql+psycopg2://" + u[len("postgresql://") :]
    return u


def _float_eq(a, b, tol: float = 1e-3) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def _row_match(snap: dict, fn: dict, tol: float) -> bool:
    keys = [
        "dist_to_nearest_op_mrt",
        "travel_time_to_active_mrt",
        "pt_time_savings_vs_walk",
        "line_connectivity_index",
        "num_unique_lines_within_1km",
        "days_since_mrt_announcement",
        "days_to_mrt_opening",
        "speculative_upside_score",
        "has_future_upside",
        "nearest_planned_mrt_dist",
        "is_proximity_nuisance",
    ]
    for k in keys:
        if not _float_eq(snap.get(k), fn.get(k), tol):
            return False
    # arrays: compare as tuple string for simplicity
    if (snap.get("nearest_op_lines") or []) != (fn.get("nearest_op_lines") or []):
        return False
    if (snap.get("nearest_planned_lines") or []) != (fn.get("nearest_planned_lines") or []):
        return False
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=str, default="42", help="Salt for deterministic pseudo-random order")
    p.add_argument("--n", type=int, default=20, help="Number of random addresses (excluding canonical)")
    p.add_argument(
        "--month",
        type=str,
        default=None,
        help="Force YYYY-MM for all ids (must exist in snapshot for each id, else skipped)",
    )
    p.add_argument(
        "--include-ids",
        type=str,
        default="",
        help="Comma-separated hdb_addr_id values to always include",
    )
    p.add_argument("--no-canonical", action="store_true", help="Do not include 050034 / 6451")
    p.add_argument("--tol", type=float, default=1e-2, help="Float tolerance for comparisons")
    args = p.parse_args()

    eng = create_engine(_db_url())
    salt = str(args.seed)

    canonical_id = 6451  # postal 050034 — 34 Upper Cross Street
    extra = [int(x.strip()) for x in args.include_ids.split(",") if x.strip().isdigit()]
    must = set(extra)
    if not args.no_canonical:
        must.add(canonical_id)

    with eng.connect() as conn:
        # Distinct ids with deterministic shuffle
        pool = conn.execute(
            text(
                """
                SELECT hdb_addr_id FROM (
                    SELECT DISTINCT hdb_addr_id FROM hdb_mrt_features_pit_snapshot
                ) t
                ORDER BY md5(t.hdb_addr_id::text || :salt)
                LIMIT 50000
                """
            ),
            {"salt": salt},
        ).scalars().all()

    chosen: list[int] = []
    seen = set()
    for hid in pool:
        if hid in must:
            continue
        if hid in seen:
            continue
        seen.add(hid)
        chosen.append(int(hid))
        if len(chosen) >= args.n:
            break

    ids = list(must) + [x for x in chosen if x not in must]

    if not ids:
        print("No ids to sample", file=sys.stderr)
        return 2
    in_list = ",".join(str(int(i)) for i in ids)
    with eng.connect() as conn:
        postals = {
            int(r[0]): r[1]
            for r in conn.execute(
                text(
                    f"SELECT id, postal_code FROM hdb_address_enrichment_onemap "
                    f"WHERE id IN ({in_list})"
                )
            ).fetchall()
        }

    mismatches = 0
    print(f"sample_size={len(ids)} seed_salt={salt!r} forced_month={args.month!r}")
    print(
        "hdb_addr_id\tpostal\tmonth\tdist_m\tt_walk\tmatch_fn"
        "\tpt_save\tconn_idx\thas_future\tnuis"
    )

    with eng.connect() as conn:
        for hid in ids:
            if args.month:
                ym = args.month
            else:
                ym = conn.execute(
                    text(
                        "SELECT MAX(tx_year_month) FROM hdb_mrt_features_pit_snapshot "
                        "WHERE hdb_addr_id = :hid"
                    ),
                    {"hid": hid},
                ).scalar_one()
            if ym is None:
                print(f"{hid}\t{postals.get(hid)}\t(no snapshot rows)\t\t\tSKIP")
                continue

            snap = conn.execute(
                text(
                    "SELECT * FROM hdb_mrt_features_pit_snapshot "
                    "WHERE hdb_addr_id = :hid AND tx_year_month = :ym"
                ),
                {"hid": hid, "ym": ym},
            ).mappings().first()
            if not snap:
                print(f"{hid}\t{postals.get(hid)}\t{ym}\t(no row)\t\tSKIP")
                continue

            d = f"{ym}-01"
            fn = conn.execute(
                text("SELECT * FROM hdb_mrt_features_at(:hid, CAST(:d AS date))"),
                {"hid": hid, "d": d},
            ).mappings().first()
            if not fn:
                print(f"{hid}\t{postals.get(hid)}\t{ym}\t(function empty)\t\tFAIL")
                mismatches += 1
                continue

            snap_d = dict(snap)
            fn_d = dict(fn)
            ok = _row_match(snap_d, fn_d, args.tol)
            if not ok:
                mismatches += 1

            pc = postals.get(hid, "")
            flag = "OK" if ok else "MISMATCH"
            print(
                f"{hid}\t{pc}\t{ym}\t{snap_d.get('dist_to_nearest_op_mrt')}\t"
                f"{snap_d.get('travel_time_to_active_mrt')}\t{flag}\t"
                f"{snap_d.get('pt_time_savings_vs_walk')}\t{snap_d.get('line_connectivity_index')}\t"
                f"{snap_d.get('has_future_upside')}\t{snap_d.get('is_proximity_nuisance')}"
            )

    if canonical_id in ids and not args.no_canonical:
        print(
            "\nNote: postal 050034 (hdb_addr_id=6451) should show short operational access "
            "after routing correction (e.g. ~353 m walk / ~4 min to Chinatown corridor in recent months), "
            "not distant CBD interchange legs from the pre-refresh bug."
        )

    if mismatches:
        print(f"\nFAIL: {mismatches} snapshot vs function mismatches (tol={args.tol})", file=sys.stderr)
        return 1
    print("\nPASS: all sampled rows match hdb_mrt_features_at for the chosen month.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
