#!/usr/bin/env python3
"""Summarize MinIO valuation experiment runs for advisory vs apply feature-selection A/B.

Requires MinIO env vars (same as modelling runners): ``MINIO_ENDPOINT``, ``MINIO_ACCESS_KEY``,
``MINIO_SECRET_KEY``, ``MODEL_ENV``.

Examples::

    PYTHONPATH=. python modelling/runners/compare_feature_selection_ab.py --list-runs
    PYTHONPATH=. python modelling/runners/compare_feature_selection_ab.py --pair-latest \\
        --experiment-id xgboost_tuned__mrt --experiment-id xgboost_tuned__full_stack

Fair comparison: pin the same ``dataset_version`` when enqueueing both Prefect batches and keep
``TRAINING_FORCE_DATASET_REBUILD=0`` on the worker (see docs/reference/environment-variables.md).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modelling.feature_selection_ab_compare import (  # noqa: E402
    metrics_row_for_compare,
    pair_latest_advisory_vs_apply,
    split_run_folder,
)
from modelling.storage import minio_io  # noqa: E402

_BUCKET = "models"


def _list_run_folders(env: str) -> list[str]:
    prefix = f"{env.strip().strip('/')}/valuation/experiments/"
    keys = minio_io.list_object_keys_with_prefix(_BUCKET, prefix)
    folders: set[str] = set()
    for k in keys:
        if not k.endswith("/model.pkl"):
            continue
        parts = k.split("/")
        if len(parts) >= 2:
            folders.add(parts[-2])
    return sorted(folders)


def _load_metrics(env: str, run_folder: str) -> dict | None:
    key = f"{env.strip().strip('/')}/valuation/experiments/{run_folder.strip().strip('/')}/metrics.json"
    try:
        raw = minio_io.get_object_bytes(_BUCKET, key)
        doc = json.loads(raw.decode("utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--model-env",
        default=None,
        help="MinIO prefix segment (default: MODEL_ENV env or prod)",
    )
    p.add_argument(
        "--experiment-id",
        action="append",
        dest="experiment_ids",
        default=None,
        help="Filter logical experiment id (repeatable). Matches run folder prefix before __timestamp.",
    )
    p.add_argument(
        "--dataset-version-substring",
        default=None,
        help="Keep rows whose training_context.dataset_version contains this string.",
    )
    p.add_argument("--list-runs", action="store_true", help="Print discovered run folder names and exit.")
    p.add_argument(
        "--pair-latest",
        action="store_true",
        help="Emit paired latest advisory vs apply run per logical experiment id (CSV).",
    )
    args = p.parse_args(argv)

    import os

    env = (args.model_env or os.getenv("MODEL_ENV") or "prod").strip().strip("/")

    folders = _list_run_folders(env)
    if args.list_runs:
        for f in folders:
            print(f)
        return 0

    want_ids = None
    if args.experiment_ids:
        want_ids = frozenset(str(x).strip() for x in args.experiment_ids if str(x).strip())

    rows: list[dict[str, object]] = []
    for folder in folders:
        logical_id, _ts = split_run_folder(folder)
        if want_ids is not None and logical_id not in want_ids:
            continue
        met = _load_metrics(env, folder)
        if not met:
            continue
        row = metrics_row_for_compare(met, run_folder=folder)
        if args.dataset_version_substring:
            sub = args.dataset_version_substring.strip()
            if sub and sub not in str(row.get("dataset_version") or ""):
                continue
        rows.append(row)

    if args.pair_latest:
        pairs = pair_latest_advisory_vs_apply(rows)
        if not pairs:
            print("(no advisory+apply pairs for filter)", file=sys.stderr)
            return 1
        w = csv.DictWriter(sys.stdout, fieldnames=list(pairs[0].keys()))
        w.writeheader()
        for r in pairs:
            w.writerow(r)
        return 0

    if not rows:
        print("(no rows)", file=sys.stderr)
        return 1

    w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
    w.writeheader()
    for r in sorted(rows, key=lambda x: (str(x["logical_experiment_id"]), str(x["run_timestamp"]))):
        w.writerow(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
