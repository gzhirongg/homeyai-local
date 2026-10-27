"""Upload a local experiment directory to MinIO ``models/<env>/valuation/experiments/<run_id>/``."""

from __future__ import annotations

import json
from pathlib import Path

from modelling.storage import minio_io
from modelling.training_log import log_phase, training_logger

BUCKET_MODELS = "models"
_up_log = training_logger("upload")


def upload_experiment_directory_to_minio(
    local_run_dir: Path,
    *,
    run_id: str,
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    model_env: str,
    source: str = "prefect-worker",
) -> dict[str, object]:
    """Upload model artefacts, training frame parquet, plots; write ``manifest.json`` last."""

    env = model_env.strip().strip("/")
    base = f"{env}/valuation/experiments/{run_id.strip().strip('/')}/"
    root = local_run_dir.resolve()

    log_phase(
        _up_log,
        "minio_upload_start",
        run_id=run_id,
        prefix=f"{BUCKET_MODELS}/{base}",
        source=source,
    )

    manifest: dict[str, object] = {
        "experiment_id": experiment_id,
        "feature_set_id": feature_set_id,
        "dataset_version": dataset_version,
        "run_id": run_id,
        "source": source,
    }

    uploads = [
        ("model.pkl", "application/octet-stream"),
        ("training_data.parquet", "application/vnd.apache.parquet"),
        ("metrics.json", "application/json"),
        ("best_params.json", "application/json"),
        ("config.json", "application/json"),
        ("report.pdf", "application/pdf"),
        ("features_dropped.json", "application/json"),
        ("feature_variance.json", "application/json"),
        ("correlated_pairs.json", "application/json"),
        ("feature_mi_scores.json", "application/json"),
        ("feature_permutation_importance.json", "application/json"),
        ("feature_correlation_matrix.csv", "text/csv"),
    ]
    n_files = 0
    for name, ctype in uploads:
        p = root / name
        if p.is_file():
            minio_io.put_object_bytes(
                BUCKET_MODELS,
                f"{base}{name}",
                p.read_bytes(),
                content_type=ctype,
            )
            n_files += 1

    plots = root / "plots"
    if plots.is_dir():
        for p in plots.rglob("*"):
            if p.is_file():
                rel = p.relative_to(root).as_posix()
                minio_io.put_object_bytes(
                    BUCKET_MODELS,
                    f"{base}{rel}",
                    p.read_bytes(),
                    content_type="application/octet-stream",
                )
                n_files += 1

    if (root / "training_data.parquet").is_file():
        manifest["training_data_object"] = "training_data.parquet"

    metrics_path = root / "metrics.json"
    if metrics_path.is_file():
        try:
            mdoc = json.loads(metrics_path.read_text(encoding="utf-8"))
            tc = mdoc.get("training_context") if isinstance(mdoc.get("training_context"), dict) else {}
            tn = mdoc.get("target_normalization") or tc.get("target_normalization")
            if tn:
                manifest["target_normalization"] = tn
            rs = mdoc.get("rpi_source") or tc.get("rpi_source")
            if rs:
                manifest["rpi_source"] = rs
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    minio_io.put_object_bytes(
        BUCKET_MODELS,
        f"{base}manifest.json",
        json.dumps(manifest, indent=2).encode("utf-8"),
        content_type="application/json",
    )
    n_files += 1

    log_phase(_up_log, "minio_upload_done", run_id=run_id, n_objects=n_files)
    return {"experiment_prefix": base, "manifest": manifest}
