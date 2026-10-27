#!/usr/bin/env python3
"""Train a registered experiment; artefacts go to MinIO (temp disk only during training)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import pandas as pd  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modelling.config.experiments import Experiment, effective_mrt_pit_min_years, get_experiment  # noqa: E402
from modelling.data.loaders import LoaderConfig, describe_training_source, load_training_frame  # noqa: E402
from modelling.data.quality import assert_training_frame_ready, engineer_preview_frame  # noqa: E402
from modelling.runners.training_data_quality import sql_coverage_for_dq_summary  # noqa: E402
from modelling.runners.train_core import train_from_frame  # noqa: E402


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_single(
    exp: Experiment,
    raw_df: pd.DataFrame,
    project_root: Path,
    out_dir: Path,
    *,
    loader_meta: dict[str, Any] | None = None,
    data_quality_summary: dict[str, Any] | None = None,
    dataset_version: str | None = None,
    engineered_preview_df: pd.DataFrame | None = None,
    feature_selection_policy: str | None = None,
) -> dict[str, Any]:
    return train_from_frame(
        exp,
        raw_df,
        project_root,
        out_dir,
        loader_meta=loader_meta,
        data_quality_summary=data_quality_summary,
        dataset_version=dataset_version,
        engineered_preview_df=engineered_preview_df,
        feature_selection_policy=feature_selection_policy,
    )


def run_mrt_pit_baselines(
    raw_df: pd.DataFrame,
    project_root: Path,
    out_parent: Path,
    exp_template: Experiment,
) -> tuple[Path, list[dict[str, Any]]]:
    stamp = _utc_stamp()
    parent = out_parent / f"mrt_pit_baselines__{stamp}"
    parent.mkdir(parents=True, exist_ok=False)
    results = []
    for mid in ("linear", "random_forest", "mlp"):
        sub = Experiment(
            id=f"{mid}__mrt_pit_run",
            feature_set_id="mrt_pit",
            model_id=mid,
            description=f"Companion run for mrt_pit_baselines ({mid})",
            test_fraction=exp_template.test_fraction,
            cv_splits=exp_template.cv_splits,
            max_train_rows=exp_template.max_train_rows,
            rf_search_iter=exp_template.rf_search_iter,
            nn_search_iter=exp_template.nn_search_iter,
            random_state=exp_template.random_state,
            flat_type_scope=exp_template.flat_type_scope,
        )
        out = parent / mid
        results.append(_run_single(sub, raw_df, project_root, out, loader_meta=None))
    return parent, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a modelling experiment.")
    parser.add_argument("--name", required=True, help="Experiment id from config.experiments")
    parser.add_argument("--project-root", type=Path, default=_REPO_ROOT)
    parser.add_argument(
        "--from-parquet-minio",
        action="store_true",
        help="Load resale + optional sidecars from MinIO manifest; default reads Postgres.",
    )
    parser.add_argument("--test-fraction", type=float, default=None)
    parser.add_argument("--cv-splits", type=int, default=None)
    parser.add_argument(
        "--max-train-rows",
        type=int,
        default=None,
        help="Override experiment default; use 0 for no cap.",
    )
    parser.add_argument("--rf-search-iter", type=int, default=None)
    parser.add_argument("--nn-search-iter", type=int, default=None)
    parser.add_argument("--random-state", type=int, default=None)
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip MinIO upload; move run directory to modelling/experiments/ (survives process exit).",
    )
    parser.add_argument(
        "--dataset-version",
        type=str,
        default="local",
        help="Label stored in MinIO manifest (default: local).",
    )
    parser.add_argument(
        "--min-tx-month",
        type=str,
        default=None,
        help="Drop training rows with month < this YYYY-MM (reference 2015 slice).",
    )
    parser.add_argument(
        "--feature-selection-policy",
        type=str,
        default=None,
        metavar="POLICY",
        help="Override HOMEYAI_FEATURE_SELECTION_POLICY: advisory_only | apply (apply_recommended_drops).",
    )
    parser.add_argument(
        "--flat-type-scope",
        choices=("all", "core_35"),
        default=None,
        help=(
            "Override experiment flat-type row filter applied before temporal split: "
            "core_35 keeps resale rows with canonical 3/4/5 ROOM labels only."
        ),
    )
    args = parser.parse_args(argv)

    root = args.project_root.resolve()
    parquet_minio = bool(args.from_parquet_minio)

    exp = get_experiment(root, args.name)
    overrides: dict = {}
    if args.test_fraction is not None:
        overrides["test_fraction"] = args.test_fraction
    if args.cv_splits is not None:
        overrides["cv_splits"] = args.cv_splits
    if args.max_train_rows is not None:
        overrides["max_train_rows"] = None if args.max_train_rows == 0 else args.max_train_rows
    if args.rf_search_iter is not None:
        overrides["rf_search_iter"] = args.rf_search_iter
    if args.nn_search_iter is not None:
        overrides["nn_search_iter"] = args.nn_search_iter
    if args.random_state is not None:
        overrides["random_state"] = args.random_state
    if args.flat_type_scope is not None:
        overrides["flat_type_scope"] = args.flat_type_scope
    if overrides:
        exp = replace(exp, **overrides)

    prev_mrt_years_env = os.environ.get("MRT_PIT_MIN_YEARS")
    try:
        if exp.mrt_pit_min_years is not None:
            os.environ["MRT_PIT_MIN_YEARS"] = str(exp.mrt_pit_min_years)

        loader = LoaderConfig(
            project_root=root,
            parquet_minio=parquet_minio,
            use_database=not parquet_minio,
            min_tx_month=(args.min_tx_month.strip() if args.min_tx_month else None),
        )
        raw_df = load_training_frame(loader)

        eng_preview = engineer_preview_frame(exp, raw_df, root)
        dq = assert_training_frame_ready(
            raw_df,
            engineered_df=eng_preview,
            experiment_id=exp.id,
            feature_set_id=exp.feature_set_id,
            project_root=root,
        )
        dq_dict = dq.as_dict()
        try:
            dq_dict["sql_coverage"] = sql_coverage_for_dq_summary(int(effective_mrt_pit_min_years(exp)))
        except Exception as exc:
            dq_dict["sql_coverage"] = {"error": str(exc)}

        model_env = os.getenv("MODEL_ENV", "dev").strip().strip("/") or "dev"
        dver = (args.dataset_version or "local").strip()

        ts_label, ts_uri = describe_training_source(loader)
        loader_meta = {
            "from_db": bool(not parquet_minio and loader.use_database),
            "training_source": ts_label,
            "dataset_path": ts_uri,
            "mrt_features_path": "",
            "masterplan_landuse_path": "",
            "masterplan_source": (
                "postgresql_normalized" if not parquet_minio else "parquet_minio_sidecars"
            ),
            "merge_masterplan": bool(parquet_minio and loader.merge_masterplan_landuse_parquet is not False),
            "min_tx_month": loader.min_tx_month or "",
        }

        with tempfile.TemporaryDirectory(prefix="hm_train_") as temp_base:
            base = Path(temp_base)
            if exp.id == "mrt_pit_baselines":
                parent, _results = run_mrt_pit_baselines(raw_df, root, base, exp)
                if not args.no_upload:
                    from modelling.runners.minio_experiment_upload import upload_experiment_directory_to_minio

                    for mid in ("linear", "random_forest", "mlp"):
                        p = parent / mid
                        if not p.is_dir():
                            continue
                        rid = f"{parent.name}__{mid}"
                        exp_id = f"{mid}__mrt_pit_run"
                        upload_experiment_directory_to_minio(
                            p,
                            run_id=rid,
                            experiment_id=exp_id,
                            feature_set_id="mrt_pit",
                            dataset_version=dver,
                            model_env=model_env,
                            source="cli-mrt-baselines",
                        )
                        print(
                            f"Uploaded {rid} to MinIO prefix {model_env}/valuation/experiments/{rid}/",
                            file=sys.stderr,
                        )
                else:
                    dest_root = root / "modelling" / "experiments"
                    dest_root.mkdir(parents=True, exist_ok=True)
                    final_parent = dest_root / parent.name
                    if final_parent.exists():
                        print(f"Refusing to overwrite existing {final_parent}", file=sys.stderr)
                        return 1
                    shutil.move(str(parent), str(final_parent))
                    print(f"MRT baselines artefacts (no upload): {final_parent}", file=sys.stderr)
                return 0

            out = base / f"{exp.id}__{_utc_stamp()}"
            out.mkdir(parents=True, exist_ok=False)
            _run_single(
                exp,
                raw_df,
                root,
                out,
                loader_meta=loader_meta,
                data_quality_summary=dq_dict,
                dataset_version=dver,
                engineered_preview_df=eng_preview,
                feature_selection_policy=args.feature_selection_policy,
            )

            if not args.no_upload:
                from modelling.runners.minio_experiment_upload import upload_experiment_directory_to_minio

                upload_experiment_directory_to_minio(
                    out,
                    run_id=out.name,
                    experiment_id=exp.id,
                    feature_set_id=exp.feature_set_id,
                    dataset_version=dver,
                    model_env=model_env,
                    source="cli",
                )
                print(
                    f"Uploaded to MinIO: {model_env}/valuation/experiments/{out.name}/model.pkl",
                    file=sys.stderr,
                )
            else:
                dest_root = root / "modelling" / "experiments"
                dest_root.mkdir(parents=True, exist_ok=True)
                final_out = dest_root / out.name
                if final_out.exists():
                    print(f"Refusing to overwrite existing {final_out}", file=sys.stderr)
                    return 1
                shutil.move(str(out), str(final_out))
                print(f"Train complete (no upload). Artefacts: {final_out}", file=sys.stderr)

        return 0
    finally:
        if exp.mrt_pit_min_years is not None:
            if prev_mrt_years_env is None:
                os.environ.pop("MRT_PIT_MIN_YEARS", None)
            else:
                os.environ["MRT_PIT_MIN_YEARS"] = prev_mrt_years_env


if __name__ == "__main__":
    raise SystemExit(main())
