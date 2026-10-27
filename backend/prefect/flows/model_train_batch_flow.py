"""
Prefect flow: run multiple registered valuation experiments on one snapshot.

Uses the same Modal / inline training tasks as ``model_train_flow.py``.
Deploy from ``backend/`` via ``prefect.yaml`` (``model-train-batch-default``).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from prefect import flow
from prefect.task_runners import ThreadPoolTaskRunner

# Upper bound for concurrent experiment tasks; wave size is capped by ``max_concurrent`` parameter.
_BATCH_FLOW_MAX_WORKERS = 32

_FLOW_FILE = Path(__file__).resolve()
_BACKEND_DIR = _FLOW_FILE.parents[2]
_REPO_ROOT = _BACKEND_DIR.parent

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


def _load_model_train_flow():
    path = Path(__file__).resolve().parent / "model_train_flow.py"
    spec = importlib.util.spec_from_file_location("_hm_prefect_model_train_flow", path)
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load model_train_flow.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mtf_mod():
    global _MTF_MOD
    if _MTF_MOD is None:
        _MTF_MOD = _load_model_train_flow()
    return _MTF_MOD


_MTF_MOD = None

from modelling.config.experiment_batches import PERFORMANCE_PLAN_V1
from modelling.config.experiments import effective_mrt_pit_min_years, get_experiment, resolve_modal_train_fn


def _resolution_label(feature_set_id: str, min_years: int) -> str:
    return f"{feature_set_id}|mrt_years={min_years}"


@flow(
    name="homeyai-model-train-batch",
    log_prints=True,
    task_runner=ThreadPoolTaskRunner(max_workers=_BATCH_FLOW_MAX_WORKERS),
)
def model_train_batch_flow(
    experiment_ids: list[str] | None = None,
    dataset_version: str | None = None,
    use_gpu: bool | None = None,
    max_concurrent: int = 5,
    feature_selection_policy: str | None = None,
) -> dict:
    """Train many experiments concurrently (wave-limited); partial failures are captured per experiment.

    Resolves one narrow Parquet per distinct ``(feature_set_id, effective MRT window years)`` when
    ``dataset_version`` is unset (dynamic mode). Experiments with ``Experiment.mrt_pit_min_years`` set
    get a separate cache key from env-default window runs on the same feature set.
    When ``dataset_version`` is pinned (legacy snapshot or explicit v2 key), all experiments share that version.

    Experiments run in waves of at most ``max_concurrent`` concurrent Prefect tasks (each task maps to one
    Modal or inline training run). Failures do not abort the batch; check ``failed_experiment_ids`` and
    re-run with ``experiment_ids`` set to that subset.
    """
    from modelling.data.snapshot_loader import is_legacy_snapshot_dataset_version
    from modelling.training_log import prefect_training_logger

    logger = prefect_training_logger()
    mtf = _mtf_mod()
    ids = list(experiment_ids) if experiment_ids is not None else list(PERFORMANCE_PLAN_V1)
    max_age = float(os.getenv("SNAPSHOT_MAX_AGE_HOURS", "24"))

    ds_raw = (dataset_version or "").strip()
    legacy_pin = bool(ds_raw and is_legacy_snapshot_dataset_version(ds_raw))
    explicit_other = bool(ds_raw and not legacy_pin)

    if legacy_pin or explicit_other:
        ver_shared = mtf.resolve_training_dataset_version_task(
            dataset_version,
            max_age,
            "baseline_v1",
            mrt_pit_min_years=None,
        )
        ver_by_resolution = None
        logger.info("Batch shared dataset_version=%s for %d experiments", ver_shared, len(ids))
    else:
        unique_pairs: list[tuple[str, int]] = []
        seen_pairs: set[tuple[str, int]] = set()
        for eid in ids:
            exp = get_experiment(_REPO_ROOT, str(eid).strip())
            fs = exp.feature_set_id
            my = effective_mrt_pit_min_years(exp)
            pair = (fs, my)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                unique_pairs.append(pair)
        ver_by_resolution = {
            _resolution_label(fs, my): mtf.resolve_training_dataset_version_task(None, max_age, fs, mrt_pit_min_years=my)
            for fs, my in unique_pairs
        }
        ver_shared = None
        logger.info(
            "Batch dynamic datasets for resolution_keys=%s (%d experiments)",
            sorted(ver_by_resolution.keys()),
            len(ids),
        )

    gpu = use_gpu
    if gpu is None:
        gpu = os.getenv("PREFECT_TRAINING_USE_GPU_DEFAULT", "").lower() in ("1", "true", "yes")

    modal_on = os.getenv("MODAL_ENABLED", "true").lower() in ("1", "true", "yes")

    mc_raw = int(max_concurrent) if max_concurrent is not None else 5
    wave_size = max(1, min(mc_raw, _BATCH_FLOW_MAX_WORKERS))
    if mc_raw != wave_size:
        logger.warning(
            "max_concurrent=%s clamped to wave_size=%s (cap=%s)",
            mc_raw,
            wave_size,
            _BATCH_FLOW_MAX_WORKERS,
        )

    pq_shared: bytes | None = None
    pq_by_resolution: dict[str, bytes | None] | None = None
    if modal_on:
        if ver_shared is not None:
            pq_shared = mtf.load_training_parquet_bytes_for_modal(ver_shared)
            logger.info(
                "Batch parquet prefetch (shared dataset_version=%s) bytes=%s",
                ver_shared,
                None if pq_shared is None else len(pq_shared),
            )
        else:
            assert ver_by_resolution is not None
            pq_by_resolution = {}
            for label, ver in ver_by_resolution.items():
                pq_by_resolution[label] = mtf.load_training_parquet_bytes_for_modal(ver)
                logger.info(
                    "Batch parquet prefetch resolution=%s dataset_version=%s bytes=%s",
                    label,
                    ver,
                    None if pq_by_resolution[label] is None else len(pq_by_resolution[label]),
                )

    experiment_configs: list[tuple[str, str, str, bytes | None, str]] = []
    for eid in ids:
        eid_stripped = str(eid).strip()
        exp = get_experiment(_REPO_ROOT, eid_stripped)
        fs_id = exp.feature_set_id
        my = effective_mrt_pit_min_years(exp)
        label = _resolution_label(fs_id, my)
        if ver_shared is not None:
            ver = ver_shared
            pq_bytes = pq_shared if modal_on else None
        else:
            assert ver_by_resolution is not None
            ver = ver_by_resolution[label]
            if modal_on:
                assert pq_by_resolution is not None
                pq_bytes = pq_by_resolution.get(label)
            else:
                pq_bytes = None
        modal_fn_name = resolve_modal_train_fn(exp, use_gpu=gpu)
        experiment_configs.append((eid_stripped, fs_id, ver, pq_bytes, modal_fn_name))

    results: list[dict] = []
    failed_ids: list[str] = []
    n_total = len(experiment_configs)

    for wave_start in range(0, n_total, wave_size):
        wave = experiment_configs[wave_start : wave_start + wave_size]
        wave_no = wave_start // wave_size + 1
        n_waves = (n_total + wave_size - 1) // wave_size
        logger.info(
            "Starting wave %d/%d (%d experiments, max_concurrent=%d)",
            wave_no,
            n_waves,
            len(wave),
            wave_size,
        )
        futures: list[tuple[str, str, str, object]] = []
        for eid_stripped, fs_id, ver, pq_bytes, modal_fn_name in wave:
            logger.info(
                "Submit experiment_id=%s feature_set_id=%s fn=%s dataset_version=%s",
                eid_stripped,
                fs_id,
                modal_fn_name,
                ver,
            )
            if modal_on:
                fut = mtf.train_via_modal_task.submit(
                    eid_stripped,
                    fs_id,
                    ver,
                    modal_fn_name=modal_fn_name,
                    parquet_bytes=pq_bytes,
                    feature_selection_policy=feature_selection_policy,
                )
            else:
                fut = mtf.train_inline_on_worker_task.submit(
                    eid_stripped,
                    fs_id,
                    ver,
                    feature_selection_policy=feature_selection_policy,
                )
            futures.append((eid_stripped, fs_id, ver, fut))

        for eid_stripped, fs_id, ver, fut in futures:
            try:
                out = fut.result()
                row = dict(out) if isinstance(out, dict) else {"result": out}
            except Exception as exc:
                logger.error(
                    "FAILED experiment_id=%s feature_set_id=%s dataset_version=%s error=%s",
                    eid_stripped,
                    fs_id,
                    ver,
                    exc,
                    exc_info=True,
                )
                row = {"error": str(exc)}
                failed_ids.append(eid_stripped)
            row["experiment_id"] = eid_stripped
            row["feature_set_id"] = fs_id
            row["dataset_version"] = ver
            results.append(row)
            logger.info("Finished %s (success=%s)", eid_stripped, "error" not in row)

    return {
        "dataset_version": ver_shared if ver_shared is not None else "dynamic_per_resolution_key",
        "dataset_versions_by_resolution": ver_by_resolution or {},
        "feature_selection_policy": feature_selection_policy,
        "n_experiments": len(results),
        "n_failed": len(failed_ids),
        "failed_experiment_ids": failed_ids,
        "max_concurrent": wave_size,
        "results": results,
    }
