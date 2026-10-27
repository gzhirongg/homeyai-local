#!/usr/bin/env python3
"""Backfill local training run folders to MinIO ``models/<MODEL_ENV>/valuation/experiments/<run_id>/``.

Uses the same layout as live training uploads (``modelling.runners.minio_experiment_upload``).

Scans ``--scan-experiments-dir`` (default ``modelling/experiments``): direct children with
``model.pkl``, plus nested ``mrt_pit_baselines__*`` / ``linear|random_forest|mlp`` folders.

Examples::

  python -m modelling.runners.backfill_experiments_to_minio --dry-run
  python -m modelling.runners.backfill_experiments_to_minio \\
      --scan-experiments-dir modelling/experiments --model-env prod --overwrite

  ./scripts/docker_dev_backend.sh python -m modelling.runners.backfill_experiments_to_minio --dry-run

Environment: ``MINIO_*``, ``MODEL_ENV`` (via ``--model-env`` or compose env).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modelling.runners.minio_experiment_upload import (  # noqa: E402
    BUCKET_MODELS,
    upload_experiment_directory_to_minio,
)
from modelling.storage import minio_io  # noqa: E402

_MRT_PIT_BASELINE_SUBMODELS = frozenset({"linear", "random_forest", "mlp"})


def _canonical_experiment_run_id(local_dir: Path, fallback_run_id: str) -> str:
    """Resolve MinIO ``run_id`` for a local artefact directory."""
    try:
        parent = local_dir.parent
        if parent.name.startswith("mrt_pit_baselines__") and local_dir.name in _MRT_PIT_BASELINE_SUBMODELS:
            return f"{parent.name}__{local_dir.name}"
    except (OSError, ValueError):
        pass
    return fallback_run_id.strip()


def _dataset_version(metrics: dict[str, Any], fallback: str) -> str:
    tc = metrics.get("training_context") or {}
    v = tc.get("dataset_version")
    if v not in (None, ""):
        return str(v)
    return fallback


def _scan_experiments_dir(repo_root: Path, rel: str) -> list[Path]:
    base = (repo_root / rel).resolve()
    if not base.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if (child / "model.pkl").is_file():
            out.append(child)
            continue
        if child.name.startswith("mrt_pit_baselines__"):
            for sub in sorted(child.iterdir()):
                if (
                    sub.is_dir()
                    and sub.name in _MRT_PIT_BASELINE_SUBMODELS
                    and (sub / "model.pkl").is_file()
                ):
                    out.append(sub)
    return out


def _minio_model_key(model_env: str, run_id: str) -> str:
    env = model_env.strip().strip("/")
    rid = run_id.strip().strip("/")
    return f"{env}/valuation/experiments/{rid}/model.pkl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument(
        "--scan-experiments-dir",
        type=str,
        default="modelling/experiments",
        help="Directory under repo root to scan (default: modelling/experiments).",
    )
    parser.add_argument(
        "--model-env",
        default=os.environ.get("MODEL_ENV", "dev"),
        help="MinIO prefix segment MODEL_ENV.",
    )
    parser.add_argument("--source", default="backfill-cli")
    parser.add_argument(
        "--default-dataset-version",
        default="backfill-unknown",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    jobs = _scan_experiments_dir(repo_root, args.scan_experiments_dir.strip())
    if args.limit is not None:
        jobs = jobs[: args.limit]

    if not jobs:
        print(f"No runs under {args.scan_experiments_dir!r}", file=sys.stderr)
        return 0

    model_env = args.model_env.strip() or "dev"
    uploaded = skipped = failed = 0

    for local_dir in jobs:
        if not (local_dir / "model.pkl").is_file():
            print(f"SKIP (no model.pkl): {local_dir}", file=sys.stderr)
            skipped += 1
            continue
        metrics_path = local_dir / "metrics.json"
        if not metrics_path.is_file():
            print(f"SKIP (no metrics.json): {local_dir}", file=sys.stderr)
            skipped += 1
            continue

        effective_run_id = _canonical_experiment_run_id(local_dir, local_dir.name)
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"FAIL (bad metrics.json): {local_dir} ({exc})", file=sys.stderr)
            failed += 1
            continue

        experiment_id = str(metrics.get("experiment_id") or effective_run_id).strip()
        feature_set_id = str(metrics.get("feature_set") or "unknown").strip()
        dver = _dataset_version(metrics, args.default_dataset_version)

        key = _minio_model_key(model_env, effective_run_id)
        exists = False if args.dry_run else minio_io.object_exists(BUCKET_MODELS, key)
        if exists and not args.overwrite:
            print(f"SKIP (exists): s3://{BUCKET_MODELS}/{key}", file=sys.stderr)
            skipped += 1
            continue

        print(
            f"{'WOULD UPLOAD' if args.dry_run else 'UPLOAD'} "
            f"run_id={effective_run_id} from {local_dir}"
        )
        if args.dry_run:
            uploaded += 1
            continue

        try:
            upload_experiment_directory_to_minio(
                local_dir,
                run_id=effective_run_id,
                experiment_id=experiment_id,
                feature_set_id=feature_set_id,
                dataset_version=dver,
                model_env=model_env,
                source=args.source,
            )
            uploaded += 1
        except Exception as exc:
            print(f"FAIL: {local_dir} ({exc})", file=sys.stderr)
            failed += 1

    print(
        f"\nDone. uploaded={uploaded} skipped={skipped} failed={failed} "
        f"(jobs={len(jobs)} model_env={model_env})",
        file=sys.stderr,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
