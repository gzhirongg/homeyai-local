#!/usr/bin/env python3
"""Upload a training run directory to MinIO under an immutable versioned prefix.

Usage (from repo root or backend container):
  PYTHONPATH=backend python backend/scripts/publish_model_to_minio.py \\
    --run-dir modelling/experiments/xgboost__mrt__20260101T000000Z \\
    --env dev

Never overwrites existing ``model.pkl`` at the target prefix.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _SCRIPT_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from services import model_store  # noqa: E402


def _sanitize_segment(name: str) -> str:
    """Safe single path segment for object keys."""
    s = re.sub(r"[^\w.\-+]", "_", name.strip())
    return s[:200] if len(s) > 200 else s


def resolve_run_dir(run_dir: str) -> Path:
    """Resolve ``--run-dir``: cwd-relative, then ``HOMEYAI_MODELLING_DIR``."""
    raw = Path(run_dir)
    if raw.is_absolute():
        p = raw.resolve()
        if p.is_dir():
            return p
        raise FileNotFoundError(f"Run directory not found: {p}")

    cand = (Path.cwd() / raw).resolve()
    if cand.is_dir():
        return cand

    mdir = (os.environ.get("HOMEYAI_MODELLING_DIR") or "").strip()
    if mdir:
        alt = (Path(mdir) / raw).resolve()
        if alt.is_dir():
            return alt

    raise FileNotFoundError(
        f"Run directory not found: tried {cand}"
        + (f" and {Path(mdir) / raw}" if mdir else "")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Path to experiment folder containing model.pkl and metrics.json",
    )
    parser.add_argument(
        "--env",
        default=os.environ.get("MODEL_ENV", "dev"),
        help="MODEL_ENV folder prefix (default: MODEL_ENV env or dev)",
    )
    parser.add_argument(
        "--stamp",
        default=None,
        help="UTC stamp suffix (default: current UTC YYYYMMDDTHHMMSSZ)",
    )
    args = parser.parse_args(argv)

    run_dir = resolve_run_dir(args.run_dir)
    model_pkl = run_dir / "model.pkl"
    metrics_json = run_dir / "metrics.json"
    config_json = run_dir / "config.json"

    if not model_pkl.is_file():
        print(f"ERROR: missing {model_pkl}", file=sys.stderr)
        return 2
    if not metrics_json.is_file():
        print(f"ERROR: missing {metrics_json}", file=sys.stderr)
        return 2

    metrics = json.loads(metrics_json.read_text(encoding="utf-8"))
    experiment_id = metrics.get("experiment_id") or run_dir.name
    experiment_id = _sanitize_segment(str(experiment_id))

    stamp = args.stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamp = _sanitize_segment(stamp)

    env_seg = _sanitize_segment(args.env.strip() or "dev")
    prefix = f"{env_seg}/valuation/artifacts/{experiment_id}__{stamp}"

    keys = {
        "model.pkl": model_pkl,
        "metrics.json": metrics_json,
    }
    optional_upload = []
    if config_json.is_file():
        optional_upload.append(("config.json", config_json))

    uploaded_meta = {
        "experiment_id": metrics.get("experiment_id"),
        "feature_set_id": metrics.get("feature_set"),
        "model_id": metrics.get("model"),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "source_run_dir": str(run_dir),
        "git_commit": os.getenv("GIT_COMMIT", ""),
        "app_version": os.getenv("APP_VERSION", ""),
        "metrics_summary": {
            "test_metrics": metrics.get("test_metrics"),
            "best_cv_rmse": metrics.get("best_cv_rmse"),
            "n_train": metrics.get("n_train"),
            "n_test": metrics.get("n_test"),
        },
    }
    manifest_bytes = json.dumps(uploaded_meta, indent=2).encode("utf-8")

    print(f"Uploading to s3://{model_store.BUCKET_MODELS}/{prefix}/ ...")
    try:
        model_store.put_file_if_absent(f"{prefix}/model.pkl", model_pkl)
        model_store.put_file_if_absent(
            f"{prefix}/metrics.json", metrics_json, content_type="application/json"
        )
        for name, path in optional_upload:
            model_store.put_file_if_absent(f"{prefix}/{name}", path)
        model_store.put_bytes_if_absent(
            f"{prefix}/manifest.json",
            manifest_bytes,
            content_type="application/json",
        )
    except FileExistsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    model_key = f"{prefix}/model.pkl"
    print("\nOK — immutable artifacts uploaded.")
    print("\nSet this in your deployment environment:")
    print(f"  VALUATION_MODEL_OBJECT_KEY={model_key}")
    print(f"\n(Optional) METRICS/MANIFEST sibling keys:")
    print(f"  {prefix}/metrics.json")
    print(f"  {prefix}/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
