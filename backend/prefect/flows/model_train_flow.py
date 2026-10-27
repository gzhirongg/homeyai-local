"""
Prefect flow: orchestrate dataset snapshot freshness + Modal (or inline) training.

Deploy from ``backend/`` with the worker attached to ``default-agent-pool``:

  cd backend && prefect deploy --all --prefect-file prefect.yaml
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from prefect import flow, task

_FLOW_FILE = Path(__file__).resolve()
_BACKEND_DIR = _FLOW_FILE.parents[2]
_REPO_ROOT = _BACKEND_DIR.parent

# Prefer repo-root ``modelling/`` when ``modelling/data`` exists (canonical package).
_repo = str(_REPO_ROOT)
_backend = str(_BACKEND_DIR)
_tail = [p for p in sys.path if p not in (_repo, _backend)]
_has_repo_data = (_REPO_ROOT / "modelling" / "data" / "snapshot_loader.py").is_file()
_has_backend_data = (_BACKEND_DIR / "modelling" / "data" / "snapshot_loader.py").is_file()
if _has_repo_data:
    sys.path[:] = [_repo, _backend] + _tail
elif _has_backend_data:
    sys.path[:] = [_backend, _repo] + _tail
else:
    sys.path[:] = [_repo, _backend] + _tail

for _env_candidate in (_BACKEND_DIR / ".env", _REPO_ROOT / ".env"):
    if _env_candidate.exists():
        for _line in _env_candidate.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                k, _, v = _line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        break


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _training_snapshot_min_rows_threshold() -> int | None:
    """Minimum ``manifest.json`` ``row_count`` for training; ``None`` disables the check."""
    raw = (os.environ.get("TRAINING_SNAPSHOT_MIN_ROWS") or "10000").strip().lower()
    if raw in ("", "0", "false", "no", "off"):
        return None
    try:
        n = int(raw)
    except ValueError:
        return 10_000
    return None if n <= 0 else n


def _manifest_row_count_for_dataset_version(version: str) -> int | None:
    from modelling.data.dataset_builder import TRAINING_DATASET_PREFIX
    from modelling.data.snapshot_loader import is_legacy_snapshot_dataset_version
    from modelling.runners.export_training_snapshot import BUCKET_DATASETS, SNAPSHOT_PREFIX
    from modelling.storage import minio_io

    ver = version.strip().strip("/")
    if is_legacy_snapshot_dataset_version(ver):
        key = f"{SNAPSHOT_PREFIX}/{ver}/manifest.json"
    else:
        key = f"{TRAINING_DATASET_PREFIX}/{ver}/manifest.json"
    if not minio_io.object_exists(BUCKET_DATASETS, key):
        return None
    try:
        doc = json.loads(minio_io.get_object_bytes(BUCKET_DATASETS, key).decode("utf-8"))
        rc = doc.get("row_count")
        return int(rc) if rc is not None else None
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return None


def _manifest_row_count_from_minio(version: str) -> int | None:
    """Backward-compatible name — resolves legacy snapshot or v2 dynamic manifest."""
    return _manifest_row_count_for_dataset_version(version)


def _enforce_training_snapshot_min_rows(
    version: str,
    *,
    logger,
    row_count: int | None = None,
) -> None:
    threshold = _training_snapshot_min_rows_threshold()
    if threshold is None:
        return
    n = row_count if row_count is not None else _manifest_row_count_from_minio(version)
    if n is None:
        logger.warning(
            "Skipping TRAINING_SNAPSHOT_MIN_ROWS=%s check: no manifest row_count for snapshot %s",
            threshold,
            version,
        )
        return
    if n >= threshold:
        return
    raise RuntimeError(
        f"Training dataset {version!r} has only {n} rows (manifest row_count); "
        f"minimum required TRAINING_SNAPSHOT_MIN_ROWS={threshold}. "
        "Small snapshots often come from scripts/bootstrap_modal_dev_snapshot.py (--limit 2000). "
        "For full history use Prefect training (dynamic dataset build) or legacy snapshot export. "
        "Multi-year grids use modelling/runners/run_model_sweep.py (MRT_PIT_MIN_YEARS). "
        "Set TRAINING_SNAPSHOT_MIN_ROWS=0 to disable this check."
    )


@task
def resolve_training_dataset_version_task(
    requested: str | None,
    max_age_hours: float,
    feature_set_id: str,
    mrt_pit_min_years: int | None = None,
) -> str:
    from modelling.config.feature_modules import expected_training_dataset_column_set
    from modelling.data.dataset_builder import (
        TRAINING_DATASET_PREFIX,
        build_upload_resolve_dataset_key,
        dataset_cache_key,
        dynamic_dataset_manifest_age_hours,
        fetch_dynamic_dataset_manifest,
        query_db_max_resale_tx_month,
    )
    from modelling.data.snapshot_loader import (
        BUCKET_DATASETS,
        SNAPSHOT_PREFIX,
        is_legacy_snapshot_dataset_version,
    )
    from modelling.storage import minio_io
    from modelling.training_db import create_training_engine, get_mrt_pit_min_years
    from modelling.training_log import configure_training_logging, prefect_training_logger

    configure_training_logging(force=True, source="PREFECT")
    logger = prefect_training_logger()

    if requested:
        v = requested.strip().strip("/")
        if is_legacy_snapshot_dataset_version(v):
            resale_key = f"{SNAPSHOT_PREFIX}/{v}/hdb_resale.parquet"
            if not minio_io.object_exists(BUCKET_DATASETS, resale_key):
                raise FileNotFoundError(f"No legacy dataset snapshot {v!r} ({resale_key})")
            _enforce_training_snapshot_min_rows(v, logger=logger)
            logger.info("Using legacy snapshot dataset_version=%s", v)
            return v
        ds_parquet = f"{TRAINING_DATASET_PREFIX}/{v}/dataset.parquet"
        if minio_io.object_exists(BUCKET_DATASETS, ds_parquet):
            _enforce_training_snapshot_min_rows(v, logger=logger)
            logger.info("Using pinned dynamic dataset_version=%s", v)
            return v
        raise FileNotFoundError(
            f"No training dataset for version {v!r}: expected legacy …/training_snapshots/{{ts}}/hdb_resale.parquet "
            f"or dynamic …/{TRAINING_DATASET_PREFIX}/{{key}}/dataset.parquet"
        )

    force_rebuild = os.getenv("TRAINING_FORCE_DATASET_REBUILD", "").lower() in ("1", "true", "yes")
    my = int(mrt_pit_min_years) if mrt_pit_min_years is not None else get_mrt_pit_min_years()
    cache_key = dataset_cache_key(feature_set_id, my)
    parquet_key = f"{TRAINING_DATASET_PREFIX}/{cache_key}/dataset.parquet"

    if not force_rebuild:
        age_h = dynamic_dataset_manifest_age_hours(cache_key)
        manifest_doc = fetch_dynamic_dataset_manifest(cache_key)
        if (
            age_h is not None
            and age_h <= max_age_hours
            and minio_io.object_exists(BUCKET_DATASETS, parquet_key)
            and manifest_doc is not None
        ):
            invalidate_reasons: list[str] = []
            cols = manifest_doc.get("columns")
            if isinstance(cols, list) and cols:
                expected = expected_training_dataset_column_set(feature_set_id)
                if set(str(c) for c in cols) != set(expected):
                    invalidate_reasons.append("column_schema_mismatch")
            m_max = str(manifest_doc.get("max_tx_month") or "").strip()
            if m_max:
                eng = create_training_engine()
                try:
                    db_max = query_db_max_resale_tx_month(eng)
                    if db_max and db_max > m_max:
                        invalidate_reasons.append(
                            f"db_max_month={db_max}_newer_than_manifest_max_month={m_max}"
                        )
                finally:
                    eng.dispose()
            if not invalidate_reasons:
                logger.info(
                    "Using cached dynamic dataset key=%s (age_h=%.2f, feature_set_id=%s)",
                    cache_key,
                    age_h,
                    feature_set_id,
                )
                _enforce_training_snapshot_min_rows(cache_key, logger=logger)
                return cache_key
            logger.info(
                "Invalidating v2 cache key=%s feature_set_id=%s reasons=%s",
                cache_key,
                feature_set_id,
                invalidate_reasons,
            )
    else:
        logger.info("TRAINING_FORCE_DATASET_REBUILD=1 — rebuilding dynamic dataset for feature_set_id=%s", feature_set_id)

    logger.info("Building dynamic training dataset (feature_set_id=%s mrt_pit_min_years=%s)", feature_set_id, my)
    key, manifest = build_upload_resolve_dataset_key(_REPO_ROOT, feature_set_id, force_rebuild=True, min_years=my)
    rc = manifest.get("row_count")
    row_count = int(rc) if rc is not None else None
    _enforce_training_snapshot_min_rows(key, logger=logger, row_count=row_count)
    return key


def load_training_parquet_bytes_for_modal(dataset_version: str):
    """Return Parquet bytes for Modal gRPC passthrough when under size limit; else ``None`` (Modal reads MinIO)."""
    from modelling.data.dataset_builder import training_dataset_parquet_object_key
    from modelling.runners.export_training_snapshot import BUCKET_DATASETS
    from modelling.storage import minio_io
    from modelling.training_log import prefect_training_logger

    logger = prefect_training_logger()
    raw_limit = (os.getenv("MODAL_PARQUET_PASSTHROUGH_MAX_BYTES") or "95000000").strip()
    try:
        max_bytes = int(raw_limit)
    except ValueError:
        max_bytes = 95_000_000
    if max_bytes <= 0:
        logger.info("MODAL_PARQUET_PASSTHROUGH_MAX_BYTES<=0 — Modal will load training data from MinIO")
        return None
    object_key = training_dataset_parquet_object_key(dataset_version)
    try:
        raw = minio_io.get_object_bytes(BUCKET_DATASETS, object_key)
    except Exception as exc:
        logger.warning(
            "Could not read training parquet for Modal passthrough (%s): %s — Modal will load from MinIO",
            object_key,
            exc,
        )
        return None
    if len(raw) > max_bytes:
        logger.warning(
            "Training parquet %s is %s bytes (limit %s); Modal will load dataset from MinIO instead of passthrough",
            object_key,
            len(raw),
            max_bytes,
        )
        return None
    logger.info(
        "Modal dataset passthrough: %s bytes from MinIO key datasets/%s",
        len(raw),
        object_key,
    )
    return raw


@task(log_prints=True)
def train_via_modal_task(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    *,
    modal_fn_name: str,
    parquet_bytes: bytes | None = None,
    feature_selection_policy: str | None = None,
) -> dict:
    import modal

    from modelling.training_log import prefect_training_logger

    logger = prefect_training_logger()
    fn = modal.Function.from_name("homeyai-training", modal_fn_name)
    logger.info(
        "Dispatching Modal app=homeyai-training fn=%s experiment_id=%s feature_set_id=%s dataset_version=%s parquet_passthrough=%s",
        modal_fn_name,
        experiment_id,
        feature_set_id,
        dataset_version,
        parquet_bytes is not None,
    )

    model_env_val = os.getenv("MODEL_ENV", "prod")
    kwargs: dict = dict(
        experiment_id=experiment_id,
        feature_set_id=feature_set_id,
        dataset_version=dataset_version,
        run_id=None,
        model_env=model_env_val,
        feature_selection_policy=feature_selection_policy,
    )
    if parquet_bytes is not None:
        kwargs["parquet_bytes"] = parquet_bytes

    remote_gen = getattr(fn, "remote_gen", None)
    if not callable(remote_gen):
        raise RuntimeError(
            "modal.Function.remote_gen is missing — upgrade modal>=0.64 on the Prefect worker "
            "or redeploy Modal train_one_experiment_*_gen functions."
        )

    result_payload: dict | None = None
    for entry in remote_gen(**kwargs):
        if isinstance(entry, dict) and entry.get("type") == "result":
            result_payload = {k: v for k, v in entry.items() if k != "type"}
            continue
        if isinstance(entry, dict):
            lvl = str(entry.get("level", "INFO")).upper()
            msg = entry.get("msg", entry)
            if lvl == "WARNING":
                logger.warning("[MODAL] %s", msg)
            elif lvl == "ERROR":
                logger.error("[MODAL] %s", msg)
            elif lvl == "DEBUG":
                logger.debug("[MODAL] %s", msg)
            else:
                logger.info("[MODAL] %s", msg)
        else:
            logger.info("[MODAL] %s", entry)

    if result_payload is None:
        raise RuntimeError("Modal generator completed without yielding a result entry")

    rid = result_payload.get("run_id")
    logger.info("Modal returned for experiment_id=%s run_id=%s", experiment_id, rid)
    return result_payload


@task
def train_inline_on_worker_task(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str,
    feature_selection_policy: str | None = None,
) -> dict:
    import tempfile

    from modelling.training_log import configure_training_logging

    configure_training_logging(force=True, source="PREFECT")
    from modelling.config.experiments import get_experiment
    from modelling.data.snapshot_loader import load_training_frame_from_dataset_version
    from modelling.runners.minio_experiment_upload import upload_experiment_directory_to_minio
    from modelling.runners.train_core import train_from_frame

    exp = get_experiment(_REPO_ROOT, experiment_id)
    if exp.feature_set_id != feature_set_id:
        raise ValueError(
            f"feature_set_id mismatch: got {feature_set_id!r}, experiment expects {exp.feature_set_id!r}"
        )
    raw_df, loader_meta = load_training_frame_from_dataset_version(dataset_version, _REPO_ROOT)
    rid = f"{experiment_id}__{_utc_stamp()}"
    with tempfile.TemporaryDirectory(prefix="hm_prefect_train_") as td:
        out_dir = Path(td) / rid
        train_from_frame(
            exp,
            raw_df,
            _REPO_ROOT,
            out_dir,
            loader_meta=loader_meta,
            dataset_version=dataset_version,
            feature_selection_policy=feature_selection_policy,
        )
        upload_experiment_directory_to_minio(
            out_dir,
            run_id=rid,
            experiment_id=experiment_id,
            feature_set_id=feature_set_id,
            dataset_version=dataset_version,
            model_env=os.getenv("MODEL_ENV", "prod"),
            source="prefect-worker-inline",
        )
    return {"run_id": rid, "dataset_version": dataset_version}


@flow(name="homeyai-model-train", log_prints=True)
def model_train_flow(
    experiment_id: str,
    feature_set_id: str,
    dataset_version: str | None = None,
    use_gpu: bool | None = None,
    feature_selection_policy: str | None = None,
) -> dict:
    """Train one registered experiment; Modal remote when ``MODAL_ENABLED`` is true."""
    from modelling.config.experiments import get_experiment, resolve_modal_train_fn
    from modelling.training_log import prefect_training_logger

    logger = prefect_training_logger()
    exp = get_experiment(_REPO_ROOT, experiment_id)
    if exp.feature_set_id != feature_set_id:
        raise ValueError(
            f"feature_set_id mismatch: got {feature_set_id!r}, experiment expects {exp.feature_set_id!r}"
        )
    max_age = float(os.getenv("SNAPSHOT_MAX_AGE_HOURS", "24"))
    ver = resolve_training_dataset_version_task(
        dataset_version,
        max_age,
        feature_set_id,
        mrt_pit_min_years=exp.mrt_pit_min_years,
    )
    logger.info("Using dataset_version=%s", ver)

    gpu = use_gpu
    if gpu is None:
        gpu = os.getenv("PREFECT_TRAINING_USE_GPU_DEFAULT", "").lower() in ("1", "true", "yes")

    modal_on = os.getenv("MODAL_ENABLED", "true").lower() in ("1", "true", "yes")
    if modal_on:
        pq_bytes = load_training_parquet_bytes_for_modal(ver)
        modal_fn_name = resolve_modal_train_fn(exp, use_gpu=gpu)
        result = train_via_modal_task(
            experiment_id,
            feature_set_id,
            ver,
            modal_fn_name=modal_fn_name,
            parquet_bytes=pq_bytes,
            feature_selection_policy=feature_selection_policy,
        )
        logger.info("Modal training finished: %s", result)
        return result

    result = train_inline_on_worker_task(experiment_id, feature_set_id, ver, feature_selection_policy)
    logger.info("Inline worker training finished: %s", result)
    return result
