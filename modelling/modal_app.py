"""
Modal app: train valuation experiments from MinIO Parquet snapshots.

Deploy (from repo root, with Modal CLI authenticated):

  modal deploy modelling/modal_app.py

After dependency changes (e.g. LightGBM), redeploy so workers rebuild the image.

Secrets (example):

  modal secret create homeyai-training-secrets \\
    MINIO_ENDPOINT=<PUBLIC_HOST>:9000 MINIO_ACCESS_KEY=... MINIO_SECRET_KEY=... \\
    MINIO_SECURE=false MODEL_ENV=prod

Prefect workers may pass ``parquet_bytes`` so Modal loads the training frame over gRPC instead of
reading the ``datasets`` bucket (still requires MinIO reachability for **model artefact uploads**).

For Prefect log streaming, workers call ``train_one_experiment_*_gen`` and iterate ``remote_gen()``;
those functions yield structured phase dicts plus a final ``{"type": "result", ...}`` payload.
``train_one_experiment_l40s_gen`` uses an L40S GPU for CUDA XGBoost (see ``xgboost_tuned_gpu`` /
``Experiment.modal_profile``).

``DATABASE_URL_READ_ONLY`` must be present in ``homeyai-training-secrets`` for POI-heavy feature
sets: there is no ``data/pois/`` on the container image, so engineering reads ``poi_locations`` from
Postgres via SQLAlchemy + ``psycopg2``. Postgres must be **reachable from Modal cloud egress**
(public host, VPN tunnel, or similar)—Tailscale-only DB URLs will fail at runtime.

Optional Postgres TCP probe: set ``HOMEYAI_MODAL_PROBE_POSTGRES=1``.

Live macro pulls (only when MinIO manifest lacks CSV sidecars): HTTPS to ``data.gov.sg`` (RPI)
and optional ``MAS_API_KEY`` to ``eservices.mas.gov.sg``.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import modal
import pandas as pd

# Local repo paths (deploy machine): requirements + ``add_local_dir`` source.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODELLING_DIR = _REPO_ROOT / "modelling"

# Remote layout: ``add_local_dir`` places package at ``/root/repo/modelling``.
# Modal loads this module as ``/root/modal_app.py`` — ``Path(__file__).parent.parent`` is wrong there.
_MODAL_REPO_ROOT = "/root/repo"


def _ensure_modelling_importable() -> None:
    if _MODAL_REPO_ROOT not in sys.path:
        sys.path.insert(0, _MODAL_REPO_ROOT)


# ``add_local_dir`` must be last on the image (no pip/env after it — Modal 1.4+).
# ``PYTHONPATH`` helps subprocesses; ``_ensure_modelling_importable`` handles in-process imports.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("build-essential", "procps")
    .pip_install_from_requirements(str(_MODELLING_DIR / "requirements.txt"))
    .pip_install(
        "xgboost>=2.0",
        "lightgbm>=4.0",
        "minio>=7.2",
        "psutil>=5.9",
        "psycopg2-binary>=2.9",
    )
    .env({"PYTHONPATH": "/root/repo"})
    .add_local_dir(
        local_path=str(_MODELLING_DIR),
        remote_path="/root/repo/modelling",
    )
)

app = modal.App("homeyai-training")

_training_secret = modal.Secret.from_name("homeyai-training-secrets")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _train_impl_gen(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    run_id: str | None,
    model_env: str,
    parquet_bytes: bytes | None,
    feature_selection_policy: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Training steps as a generator: yields phase dicts then a final ``type=result`` payload."""
    _ensure_modelling_importable()

    from modelling.training_log import configure_training_logging, phase_dict, training_logger

    configure_training_logging(force=True, source="MODAL")
    os.environ.setdefault("HOMEYAI_LOG_SOURCE", "MODAL")
    repo = Path(_MODAL_REPO_ROOT)
    modal_run_log = training_logger("modal")

    from modelling.network_diagnostics import run_modal_preflight_checks, training_macro_sources_summary

    run_modal_preflight_checks(skip_minio_tcp_probe=bool(parquet_bytes))

    from modelling.config.experiments import get_experiment
    from modelling.data.snapshot_loader import load_training_frame_from_dataset_version
    from modelling.runners.minio_experiment_upload import upload_experiment_directory_to_minio
    from modelling.runners.train_core import train_from_frame

    p = phase_dict(
        "modal_train_impl_start",
        experiment_id=experiment_id,
        feature_set_id=feature_set_id,
        dataset_version=dataset_version,
        parquet_passthrough=bool(parquet_bytes),
        run_id=(run_id or "").strip() or None,
    )
    modal_run_log.info(p["msg"])
    yield p

    exp = get_experiment(repo, experiment_id)
    if exp.feature_set_id != feature_set_id:
        raise ValueError(
            f"feature_set_id mismatch: got {feature_set_id!r}, experiment expects {exp.feature_set_id!r}"
        )

    macro_src = training_macro_sources_summary(repo)
    p = phase_dict(
        "macro_sidecar_availability",
        volume_cached_minio=macro_src.get("volume_cached_minio"),
        rpi_cached_minio=macro_src.get("rpi_cached_minio"),
        ir_cached_minio=macro_src.get("ir_cached_minio"),
        mas_api_key_set=bool((os.getenv("MAS_API_KEY") or "").strip()),
    )
    modal_run_log.info(p["msg"])
    yield p

    p = phase_dict("modal_snapshot_load_start", dataset_version=dataset_version)
    modal_run_log.info(p["msg"])
    yield p
    if parquet_bytes:
        raw_df = pd.read_parquet(io.BytesIO(parquet_bytes))
        month_min = month_max = ""
        if "month" in raw_df.columns and len(raw_df):
            months = raw_df["month"].astype(str)
            month_min, month_max = str(months.min()), str(months.max())
        loader_meta: dict[str, object] = {
            "from_db": False,
            "training_source": f"modal_parquet_passthrough:{dataset_version}",
            "dataset_path": "grpc:parquet_bytes",
            "mrt_features_path": "",
            "masterplan_landuse_path": "",
            "masterplan_source": "postgresql_normalized",
            "merge_masterplan": False,
            "min_tx_month": month_min,
            "dataset_version": dataset_version,
            "snapshot_manifest": {},
        }
        if month_max:
            loader_meta["dataset_month_max"] = month_max
    else:
        raw_df, loader_meta = load_training_frame_from_dataset_version(dataset_version, repo)
    p = phase_dict("modal_snapshot_load_done", rows=len(raw_df))
    modal_run_log.info(p["msg"])
    yield p

    stamp = _utc_stamp()
    rid = (run_id or "").strip() or f"{experiment_id}__{stamp}"
    p = phase_dict("modal_run_id_resolved", run_id=rid)
    modal_run_log.info(p["msg"])
    yield p

    with tempfile.TemporaryDirectory(prefix="hm_modal_train_") as td:
        out_dir = Path(td) / rid
        p = phase_dict("modal_train_from_frame_start", out_dir=str(out_dir))
        modal_run_log.info(p["msg"])
        yield p
        train_from_frame(
            exp,
            raw_df,
            repo,
            out_dir,
            loader_meta=loader_meta,
            dataset_version=dataset_version,
            feature_selection_policy=feature_selection_policy,
        )
        p = phase_dict("modal_train_from_frame_done", run_id=rid)
        modal_run_log.info(p["msg"])
        yield p
        me = os.getenv("MODEL_ENV", model_env).strip().strip("/") or model_env
        p = phase_dict("modal_minio_upload_start", model_env=me)
        modal_run_log.info(p["msg"])
        yield p
        upload_experiment_directory_to_minio(
            out_dir,
            run_id=rid,
            experiment_id=experiment_id,
            feature_set_id=feature_set_id,
            dataset_version=dataset_version,
            model_env=me,
            source="modal",
        )
        p = phase_dict("modal_train_impl_done", run_id=rid)
        modal_run_log.info(p["msg"])
        yield p
        yield {"type": "result", "run_id": rid, "dataset_version": dataset_version, "model_env": me}


def _train_impl(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    run_id: str | None,
    model_env: str,
    parquet_bytes: bytes | None,
    feature_selection_policy: str | None = None,
) -> dict[str, object]:
    """Non-streaming entry: same steps as :func:`_train_impl_gen`, returns result dict only."""
    result: dict[str, object] | None = None
    for item in _train_impl_gen(
        experiment_id,
        feature_set_id,
        dataset_version,
        run_id,
        model_env,
        parquet_bytes,
        feature_selection_policy,
    ):
        if isinstance(item, dict) and item.get("type") == "result":
            result = {k: v for k, v in item.items() if k != "type"}
    if result is None:
        raise RuntimeError("Modal training finished without a result payload")
    return result


@app.function(
    image=image,
    secrets=[_training_secret],
    cpu=2.0,
    memory=8192,
    timeout=3600,
    retries=0,
)
def train_one_experiment_cpu(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    run_id: str | None = None,
    model_env: str = "prod",
    parquet_bytes: bytes | None = None,
    feature_selection_policy: str | None = None,
) -> dict[str, object]:
    return _train_impl(
        experiment_id,
        feature_set_id,
        dataset_version,
        run_id,
        model_env,
        parquet_bytes,
        feature_selection_policy=feature_selection_policy,
    )


@app.function(
    image=image,
    secrets=[_training_secret],
    gpu="T4",
    memory=16384,
    timeout=3600,
    retries=0,
)
def train_one_experiment_gpu(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    run_id: str | None = None,
    model_env: str = "prod",
    parquet_bytes: bytes | None = None,
    feature_selection_policy: str | None = None,
) -> dict[str, object]:
    return _train_impl(
        experiment_id,
        feature_set_id,
        dataset_version,
        run_id,
        model_env,
        parquet_bytes,
        feature_selection_policy=feature_selection_policy,
    )


@app.function(
    image=image,
    secrets=[_training_secret],
    cpu=2.0,
    # Larger heaps for ~190k-row frames + pre-fit MI/corr diagnostics (8GiB can OOM → Modal "Input aborted").
    memory=16384,
    timeout=5400,
)
def train_one_experiment_cpu_gen(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    run_id: str | None = None,
    model_env: str = "prod",
    parquet_bytes: bytes | None = None,
    feature_selection_policy: str | None = None,
):
    yield from _train_impl_gen(
        experiment_id,
        feature_set_id,
        dataset_version,
        run_id,
        model_env,
        parquet_bytes,
        feature_selection_policy=feature_selection_policy,
    )


@app.function(
    image=image,
    secrets=[_training_secret],
    gpu="T4",
    memory=16384,
    timeout=3600,
)
def train_one_experiment_gpu_gen(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    run_id: str | None = None,
    model_env: str = "prod",
    parquet_bytes: bytes | None = None,
    feature_selection_policy: str | None = None,
):
    yield from _train_impl_gen(
        experiment_id,
        feature_set_id,
        dataset_version,
        run_id,
        model_env,
        parquet_bytes,
        feature_selection_policy=feature_selection_policy,
    )


@app.function(
    image=image,
    secrets=[_training_secret],
    gpu="L40S",
    cpu=4.0,
    memory=32768,
    timeout=5400,
    retries=0,
)
def train_one_experiment_l40s(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    run_id: str | None = None,
    model_env: str = "prod",
    parquet_bytes: bytes | None = None,
    feature_selection_policy: str | None = None,
) -> dict[str, object]:
    return _train_impl(
        experiment_id,
        feature_set_id,
        dataset_version,
        run_id,
        model_env,
        parquet_bytes,
        feature_selection_policy=feature_selection_policy,
    )


@app.function(
    image=image,
    secrets=[_training_secret],
    gpu="L40S",
    cpu=4.0,
    memory=32768,
    timeout=5400,
    # Generator functions cannot use ``retries`` (Modal InvalidError); match cpu_gen / gpu_gen.
)
def train_one_experiment_l40s_gen(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    run_id: str | None = None,
    model_env: str = "prod",
    parquet_bytes: bytes | None = None,
    feature_selection_policy: str | None = None,
):
    yield from _train_impl_gen(
        experiment_id,
        feature_set_id,
        dataset_version,
        run_id,
        model_env,
        parquet_bytes,
        feature_selection_policy=feature_selection_policy,
    )
