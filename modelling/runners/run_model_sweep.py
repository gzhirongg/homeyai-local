#!/usr/bin/env python3
"""Sequential sweep: (linear, random_forest, xgboost) × four feature sets × MRT_PIT_MIN_YEARS in {5,10,15,20}.

MLP is omitted by policy. XGBoost must be importable (install ``xgboost`` / OpenMP) or this script exits
with an error. POI-dependent feature sets are skipped when ``data/pois/hdb_block_coords.csv`` is missing.

Examples::

    PYTHONPATH=. python modelling/runners/run_model_sweep.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

MODEL_IDS = ("linear", "random_forest", "xgboost")
FEATURE_SET_IDS = ("baseline_v1", "mrt_pit", "poi_distancing", "mrt_pit__poi_distancing")
YEARS_GRID = (5, 10, 15, 20)


def _require_xgboost() -> None:
    from modelling.config.model_specs import build_default_specs

    specs = build_default_specs()
    if "xgboost" not in specs:
        print(
            "ERROR: The model sweep requires XGBoost, but it is not available.\n"
            "Install the Python package and system libraries, for example:\n"
            "  pip install xgboost\n"
            "On macOS you may need: brew install libomp\n"
            "Then verify: python -c \"from xgboost import XGBRegressor\"",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _assert_pit_window(years: int, *, skip_check: bool) -> None:
    if skip_check:
        return
    from modelling.training_db import create_training_engine, get_training_window_summary

    engine = create_training_engine()
    try:
        summary = get_training_window_summary(engine, min_years=years)
    finally:
        engine.dispose()
    need = int(summary["expected_min_months"])
    got = int(summary["n_done_months_in_window"])
    if got < need:
        print(
            f"ERROR: MRT PIT window incomplete for MRT_PIT_MIN_YEARS={years}: "
            f"only {got} done job-months vs required {need}.\n"
            "Backfill snapshot jobs or lower the window. To override for dev/CI, set:\n"
            "  ML_TRAINING_SKIP_MRT_WINDOW_CHECK=1",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run full model sweep (MLP excluded).")
    parser.add_argument("--project-root", type=Path, default=_REPO_ROOT)
    parser.add_argument(
        "--from-parquet-minio",
        action="store_true",
        help="Load resale + optional parquet sidecars purely from MinIO manifest (default: Postgres).",
    )
    args = parser.parse_args(argv)

    _require_xgboost()

    root = args.project_root.resolve()
    parquet_minio = bool(args.from_parquet_minio)
    from modelling.data.loaders import LoaderConfig, describe_training_source, load_training_frame
    from modelling.config.experiments import Experiment
    from modelling.runners.run_experiment import _run_single, _utc_stamp
    from modelling.runners.training_data_quality import (
        append_window_to_report,
        data_quality_summary_for_metrics,
        run_window_quality,
        write_markdown_report,
    )

    loader = LoaderConfig(
        project_root=root,
        parquet_minio=parquet_minio,
        use_database=not parquet_minio,
    )
    ts_label, ts_uri = describe_training_source(loader)
    loader_meta = {
        "from_db": bool(not parquet_minio and loader.use_database),
        "training_source": ts_label,
        "dataset_path": ts_uri,
        "mrt_features_path": "",
        "masterplan_landuse_path": "",
        "masterplan_source": "postgresql_normalized"
        if not parquet_minio
        else "parquet_minio_sidecars",
        "merge_masterplan": bool(parquet_minio and loader.merge_masterplan_landuse_parquet is not False),
    }

    poi_coords = root / "data" / "pois" / "hdb_block_coords.csv"
    skip_window = os.getenv("ML_TRAINING_SKIP_MRT_WINDOW_CHECK", "").strip() in ("1", "true", "yes")

    poi_db_ok = False
    training_db_url: str | None = None
    try:
        from modelling.training_db import get_training_database_url
        from modelling.features.poi_distancing import poi_locations_populated

        training_db_url = get_training_database_url()
        poi_db_ok = poi_locations_populated(training_db_url)
    except Exception as exc:  # noqa: BLE001
        print(f"[sweep] POI DB check skipped: {exc}", file=sys.stderr)

    for years in YEARS_GRID:
        os.environ["MRT_PIT_MIN_YEARS"] = str(years)
        _assert_pit_window(years, skip_check=skip_window)

        raw_df = load_training_frame(loader)
        loader_desc = f"training_source={ts_label} uri={ts_uri}"
        window_payload = run_window_quality(
            root, min_years=years, raw_df=raw_df, loader_desc=loader_desc
        )
        append_window_to_report(root, window_payload)
        write_markdown_report(root)
        dq_summary = data_quality_summary_for_metrics(root, years)

        for model_id in MODEL_IDS:
            for fs_id in FEATURE_SET_IDS:
                if fs_id in ("poi_distancing", "mrt_pit__poi_distancing"):
                    if not poi_coords.is_file() and not poi_db_ok:
                        print(
                            f"[sweep] skip {model_id} {fs_id} y{years}: "
                            f"missing {poi_coords} and poi_locations is empty or DB unreachable",
                            file=sys.stderr,
                        )
                        continue
                extra: dict[str, object] = {}
                if fs_id in ("poi_distancing", "mrt_pit__poi_distancing"):
                    if poi_db_ok and training_db_url:
                        extra["use_db"] = True
                        extra["database_url"] = training_db_url
                    elif poi_coords.is_file():
                        extra["merge_coords_csv"] = str(poi_coords)
                exp = Experiment(
                    id=f"{model_id}__{fs_id}__y{years}",
                    feature_set_id=fs_id,
                    model_id=model_id,
                    description="Automated model sweep (MLP omitted).",
                    extra_engineer_kwargs=extra,
                )
                out = root / "modelling" / "experiments" / f"{exp.id}__{_utc_stamp()}"
                print(f"[sweep] training {out.name}", flush=True)
                _run_single(
                    exp,
                    raw_df,
                    root,
                    out,
                    loader_meta=loader_meta,
                    data_quality_summary=dq_summary,
                )

    print("Sweep finished.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
