#!/usr/bin/env python3
"""CLI checks before full-feature XGBoost training (5-year window, DB + MinIO hints).

Fails with exit code **1** if ``mrt_pit_build_jobs`` has fewer completed months than required.

Examples::

    PYTHONPATH=. python modelling/runners/check_training_prerequisites.py
    PYTHONPATH=. python modelling/runners/check_training_prerequisites.py --skip-db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-db", action="store_true", help="Skip Postgres checks.")
    parser.add_argument("--project-root", type=Path, default=_REPO_ROOT)
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    notes: list[str] = []

    if not args.skip_db:
        from sqlalchemy import text

        from modelling.training_db import create_training_engine, get_mrt_pit_min_years, get_training_window_summary

        my = get_mrt_pit_min_years()
        engine = create_training_engine()
        try:
            summary = get_training_window_summary(engine, min_years=my)
            need = int(summary["expected_min_months"])
            got = int(summary["n_done_months_in_window"])
            notes.append(f"MRT pit window ({my}y): done months={got} (need>={need})")
            ok = got >= need
            with engine.connect() as conn:
                n_mp = conn.execute(
                    text("SELECT COUNT(*)::bigint FROM masterplan_landuse_pit_scalars"),
                ).scalar()
                notes.append(f"masterplan_landuse_pit_scalars rows: {int(n_mp or 0):,}")

                pois = conn.execute(text("SELECT COUNT(*)::bigint FROM poi_locations")).scalar()
                notes.append(f"poi_locations rows: {int(pois or 0):,}")
        finally:
            engine.dispose()
        print("\n".join(notes))
        if not ok:
            print("BLOCKER: Incomplete MRT PIT window — run snapshots or reduce MRT_PIT_MIN_YEARS.", file=sys.stderr)
            return 1
        print("\nPostgreSQL prerequisites: OK.")
    else:
        print("PostgreSQL prerequisite checks skipped.")

    hint = ""
    manifest = root / "modelling" / "config" / "training_quality_gates.yml"
    if manifest.is_file():
        hint = f"\n DQ thresholds editable in {manifest.relative_to(root)}."

    mc = ""
    mp = root / "modelling" / "config" / "minio_training_sources.sample.json"
    loc = root / "modelling" / "config" / "minio_training_sources.local.json"
    if loc.is_file():
        mc = str(loc.relative_to(root))
    elif mp.is_file():
        mc = str(mp.relative_to(root))
    if mc:
        print(f"MinIO manifest: {mc}. Ensure macro parquet/CSVs PUT (build_macro_sidecar).")
    print("Next: PYTHONPATH=. python modelling/runners/build_macro_sidecar.py (if not done)" + hint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
