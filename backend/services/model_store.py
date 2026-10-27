"""MinIO access for immutable valuation model artifacts (pin-based load + upload helpers)."""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import zipfile
from datetime import timedelta
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

import joblib
import urllib3
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

BUCKET_MODELS = "models"

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "password123")


def _secure_minio() -> bool:
    return os.getenv("MINIO_SECURE", "false").lower() in ("1", "true", "yes")


_model_cache: dict[str, Any] = {}

# TTL cache for MinIO valuation artifact listing (dedup parallel dashboard requests).
_valuation_model_keys_cache: dict[str, tuple[float, list[str]]] = {}
_VALUATION_KEYS_CACHE_TTL_SEC = 60.0
_valuation_keys_lock = threading.Lock()


def _client() -> Minio:
    """MinIO SDK client with bounded connect/read timeouts (avoid urllib3 retry storms when endpoint is down)."""
    connect_s = float(os.getenv("MINIO_CONNECT_TIMEOUT_SEC", "8"))
    read_s = float(os.getenv("MINIO_READ_TIMEOUT_SEC", "180"))
    retry_total = max(0, int(os.getenv("MINIO_HTTP_RETRIES", "2")))
    timeout = urllib3.Timeout(connect=connect_s, read=read_s)
    retries = urllib3.Retry(
        total=retry_total,
        backoff_factor=0.2,
        status_forcelist=[500, 502, 503, 504],
    )
    http_client = urllib3.PoolManager(timeout=timeout, retries=retries)
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=_secure_minio(),
        http_client=http_client,
    )


def ensure_models_bucket() -> None:
    """Create ``models`` bucket if missing."""
    c = _client()
    if not c.bucket_exists(BUCKET_MODELS):
        c.make_bucket(BUCKET_MODELS)
        logger.info("Created MinIO bucket %s", BUCKET_MODELS)


def experiment_report_pdf_object_key(env_segment: str, run_id: str) -> str:
    rid = run_id.strip().strip("/")
    env_seg = env_segment.strip().strip("/") or "dev"
    return f"{env_seg}/valuation/experiments/{rid}/report.pdf"


def put_experiment_report_pdf_bytes(env_segment: str, run_id: str, data: bytes) -> str:
    """Create or overwrite ``report.pdf`` for an experiment run under MinIO valuation experiments."""
    ensure_models_bucket()
    key = experiment_report_pdf_object_key(env_segment, run_id)
    c = _client()
    c.put_object(BUCKET_MODELS, key, io.BytesIO(data), length=len(data), content_type="application/pdf")
    return key


def presigned_experiment_report_pdf_url(
    env_segment: str,
    run_id: str,
    *,
    ttl_seconds: int = 900,
) -> str | None:
    """Return GET URL for ``report.pdf`` or None when missing."""

    rid = run_id.strip().strip("/")
    env_seg = env_segment.strip().strip("/") or "dev"
    key = experiment_report_pdf_object_key(env_seg, rid)
    if not object_exists(key):
        return None
    c = _client()
    return c.presigned_get_object(BUCKET_MODELS, key, expires=timedelta(seconds=ttl_seconds))


def object_exists(object_key: str) -> bool:
    """Return True if object exists in ``models`` bucket."""
    c = _client()
    try:
        c.stat_object(BUCKET_MODELS, object_key)
        return True
    except S3Error as e:
        if getattr(e, "code", "") == "NoSuchKey":
            return False
        raise


def put_bytes_if_absent(object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Upload object only if it does not exist. Raises FileExistsError if present."""
    ensure_models_bucket()
    if object_exists(object_key):
        raise FileExistsError(f"Refusing overwrite: s3://{BUCKET_MODELS}/{object_key}")
    c = _client()
    c.put_object(BUCKET_MODELS, object_key, io.BytesIO(data), length=len(data), content_type=content_type)
    _maybe_invalidate_listing_cache_after_upload(object_key)


def put_file_if_absent(object_key: str, local_path: Path, content_type: str = "application/octet-stream") -> None:
    data = Path(local_path).read_bytes()
    put_bytes_if_absent(object_key, data, content_type=content_type)


def get_object_bytes(object_key: str) -> bytes:
    c = _client()
    resp = c.get_object(BUCKET_MODELS, object_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def stream_object_into_zip(zf: zipfile.ZipFile, object_key: str, arcname: str) -> None:
    """Stream a bucket object into an open ``ZipFile`` member (avoids loading large blobs in RAM)."""
    c = _client()
    resp = c.get_object(BUCKET_MODELS, object_key)
    try:
        with zf.open(arcname, "w") as dest:
            shutil.copyfileobj(resp, dest, length=1024 * 1024)
    finally:
        resp.close()
        resp.release_conn()


def load_joblib_from_object(object_key: str, *, use_cache: bool = True) -> Any:
    """Download ``model.pkl`` (joblib) from MinIO and deserialize."""
    if use_cache and object_key in _model_cache:
        return _model_cache[object_key]

    data = get_object_bytes(object_key)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pkl")
    try:
        tmp.write(data)
        tmp.flush()
        tmp.close()
        obj = joblib.load(tmp.name)
        if use_cache:
            _model_cache[object_key] = obj
        return obj
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def load_json_sidecar_from_object_key(model_object_key: str, suffix: str) -> dict[str, Any] | None:
    """Derive sibling key by replacing ``model.pkl`` with ``suffix`` (e.g. metrics.json)."""
    if not model_object_key.endswith("model.pkl"):
        base = model_object_key.rsplit("/", 1)[0]
        key = f"{base}/{suffix}"
    else:
        key = model_object_key.replace("model.pkl", suffix)
    try:
        raw = get_object_bytes(key)
        return json.loads(raw.decode("utf-8"))
    except S3Error:
        return None
    except json.JSONDecodeError:
        logger.warning("Invalid JSON for sidecar %s", key)
        return None


def clear_cache() -> None:
    _model_cache.clear()


def invalidate_valuation_model_keys_cache(env: str | None = None) -> None:
    """Drop cached ``model.pkl`` key listings for one env (or all envs when ``env`` is None)."""
    with _valuation_keys_lock:
        if env is None:
            _valuation_model_keys_cache.clear()
            return
        key = (env or os.getenv("MODEL_ENV", "prod")).strip().strip("/")
        _valuation_model_keys_cache.pop(key, None)


# Alias for callers / docs
invalidate_listing_cache = invalidate_valuation_model_keys_cache


def _maybe_invalidate_listing_cache_after_upload(object_key: str) -> None:
    """New objects under valuation artifacts change folder listings — bust cache for that env segment."""
    parts = object_key.split("/")
    if len(parts) < 2:
        return
    env_segment = parts[0].strip()
    if not env_segment:
        return
    prefix = valuation_artifacts_prefix(env_segment)
    if object_key.startswith(prefix):
        invalidate_valuation_model_keys_cache(env_segment)


def derive_metrics_object_key(model_object_key: str) -> str:
    return (
        model_object_key.replace("model.pkl", "metrics.json")
        if model_object_key.endswith("model.pkl")
        else f"{model_object_key.rsplit('/', 1)[0]}/metrics.json"
    )


def derive_manifest_object_key(model_object_key: str) -> str:
    return (
        model_object_key.replace("model.pkl", "manifest.json")
        if model_object_key.endswith("model.pkl")
        else f"{model_object_key.rsplit('/', 1)[0]}/manifest.json"
    )


def list_objects_with_prefix(prefix: str) -> list[dict[str, Any]]:
    """List objects under ``prefix`` in the ``models`` bucket."""
    c = _client()
    if not c.bucket_exists(BUCKET_MODELS):
        return []
    out: list[dict[str, Any]] = []
    for obj in c.list_objects(BUCKET_MODELS, prefix=prefix, recursive=True):
        out.append(
            {
                "object_name": obj.object_name,
                "size": int(obj.size or 0),
                "last_modified": str(obj.last_modified) if obj.last_modified else "",
            }
        )
    return out


def valuation_artifacts_prefix(env: str | None = None) -> str:
    env = (env or os.getenv("MODEL_ENV", "prod")).strip().strip("/")
    return f"{env}/valuation/artifacts/"


def valuation_experiments_prefix(env: str | None = None) -> str:
    env = (env or os.getenv("MODEL_ENV", "prod")).strip().strip("/")
    return f"{env}/valuation/experiments/"


def experiment_folder_from_model_object_key(object_key: str) -> str | None:
    """Folder segment under ``.../valuation/experiments/<folder>/model.pkl``."""
    parts = object_key.split("/")
    try:
        idx = parts.index("experiments")
        if idx + 1 < len(parts) and parts[-1] == "model.pkl":
            return parts[idx + 1]
    except ValueError:
        pass
    return None


def list_valuation_experiment_model_keys(env: str | None = None) -> list[str]:
    prefix = valuation_experiments_prefix(env)
    keys: list[str] = []
    for row in list_objects_with_prefix(prefix):
        name = row["object_name"]
        if name.endswith("model.pkl"):
            keys.append(name)
    return sorted(keys)


def load_json_object_key(object_key: str) -> dict[str, Any] | None:
    try:
        raw = get_object_bytes(object_key)
        return json.loads(raw.decode("utf-8"))
    except (S3Error, json.JSONDecodeError, OSError):
        return None


def catalog_row_from_minio_experiment_model_key(model_key: str) -> dict[str, Any] | None:
    """Build a disk-shaped catalog row from MinIO experiment artefacts."""
    folder = experiment_folder_from_model_object_key(model_key)
    if not folder:
        return None
    base = model_key.rsplit("/", 1)[0]
    metrics = load_json_object_key(f"{base}/metrics.json") or {}
    config = load_json_object_key(f"{base}/config.json")
    best_params = load_json_object_key(f"{base}/best_params.json")
    return {
        "id": folder,
        "config": config,
        "metrics": metrics,
        "best_params": best_params,
        "has_metrics": bool(metrics),
    }


def copy_valuation_experiment_folder_to_artifacts(env_seg: str, experiment_folder: str) -> str:
    """
    Server-side copy ``{env}/valuation/experiments/<folder>/*`` → ``artifacts/<folder>/*``.
    Returns the destination ``model.pkl`` object key.
    """
    from minio.commonconfig import CopySource

    ensure_models_bucket()
    env_seg = env_seg.strip().strip("/")
    folder = experiment_folder.strip().strip("/")
    src_prefix = f"{env_seg}/valuation/experiments/{folder}/"
    c = _client()
    keys = [row["object_name"] for row in list_objects_with_prefix(src_prefix)]
    if not keys:
        raise FileNotFoundError(f"No experiment objects under prefix {src_prefix!r}")
    dest_model_key = ""
    for src_key in keys:
        suffix = src_key[len(src_prefix) :] if src_key.startswith(src_prefix) else src_key.split("/")[-1]
        dest_key = f"{env_seg}/valuation/artifacts/{folder}/{suffix}"
        c.copy_object(BUCKET_MODELS, dest_key, CopySource(BUCKET_MODELS, src_key))
        if dest_key.endswith("model.pkl"):
            dest_model_key = dest_key
    if not dest_model_key:
        raise ValueError("Experiment folder did not contain model.pkl")
    _maybe_invalidate_listing_cache_after_upload(dest_model_key)
    return dest_model_key


def folder_names_from_model_keys(keys: list[str]) -> set[str]:
    """Derive artifact folder names from ``model.pkl`` object keys (no MinIO I/O)."""
    names: set[str] = set()
    for k in keys:
        fn = folder_name_from_model_object_key(k)
        if fn:
            names.add(fn)
    return names


def folder_name_from_model_object_key(object_key: str) -> str | None:
    """Return folder segment under ``.../valuation/artifacts/<folder>/model.pkl``."""
    parts = object_key.split("/")
    try:
        idx = parts.index("artifacts")
        if idx + 1 < len(parts) and parts[-1] == "model.pkl":
            return parts[idx + 1]
    except ValueError:
        pass
    return None


def _list_valuation_model_object_keys_uncached(env: str | None = None) -> list[str]:
    """Full MinIO keys for ``model.pkl`` under valuation artifacts (no TTL cache)."""
    prefix = valuation_artifacts_prefix(env)
    keys: list[str] = []
    for row in list_objects_with_prefix(prefix):
        name = row["object_name"]
        if name.endswith("model.pkl"):
            keys.append(name)
    return sorted(keys)


def list_valuation_model_object_keys(env: str | None = None) -> list[str]:
    """Full MinIO keys for ``model.pkl`` under valuation artifacts (short TTL cache per env)."""
    cache_key = (env or os.getenv("MODEL_ENV", "prod")).strip().strip("/")
    now = time.monotonic()
    with _valuation_keys_lock:
        entry = _valuation_model_keys_cache.get(cache_key)
        if entry is not None:
            ts, cached = entry
            if now - ts < _VALUATION_KEYS_CACHE_TTL_SEC:
                return list(cached)
        keys = _list_valuation_model_object_keys_uncached(env)
        _valuation_model_keys_cache[cache_key] = (now, list(keys))
        return keys


def valuation_artifact_folder_names(env: str | None = None) -> set[str]:
    """Artifact folder names (publish prefixes) that contain a ``model.pkl``."""
    names: set[str] = set()
    for k in list_valuation_model_object_keys(env):
        fn = folder_name_from_model_object_key(k)
        if fn:
            names.add(fn)
    return names


def _valuation_artifact_row_dict(
    key: str,
    *,
    active_object_key: str | None,
) -> dict[str, Any]:
    manifest = load_json_sidecar_from_object_key(key, "manifest.json") or {}
    metrics = load_json_sidecar_from_object_key(key, "metrics.json") or {}
    tm = (
        metrics.get("test_metrics")
        or (manifest.get("metrics_summary") or {}).get("test_metrics")
        or {}
    )
    return {
        "object_key": key,
        "artifact_folder": folder_name_from_model_object_key(key),
        "uploaded_at": manifest.get("uploaded_at"),
        "experiment_id": manifest.get("experiment_id") or metrics.get("experiment_id"),
        "feature_set_id": manifest.get("feature_set_id") or metrics.get("feature_set"),
        "model_id": manifest.get("model_id") or metrics.get("model"),
        "metrics_summary": {
            "rmse": tm.get("rmse"),
            "mae": tm.get("mae"),
            "r2": tm.get("r2"),
        },
        "is_active": bool(active_object_key and key == active_object_key.strip()),
    }


def local_run_has_minio_counterpart(run_id: str, folder_names: set[str]) -> bool:
    """Whether a disk experiment ``run_id`` was uploaded under the same or extended prefix."""
    if run_id in folder_names:
        return True
    prefix = f"{run_id}__"
    return any(fn.startswith(prefix) for fn in folder_names)


def describe_valuation_artifacts(
    env: str | None = None,
    *,
    active_object_key: str | None = None,
    prefetched_model_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Rows for admin UI: one entry per ``model.pkl`` with manifest/metrics summary."""
    if prefetched_model_keys is not None:
        keys = sorted(prefetched_model_keys, reverse=True)
    else:
        keys = sorted(list_valuation_model_object_keys(env), reverse=True)
    if not keys:
        return []
    max_workers = min(len(keys), 8)
    worker = partial(_valuation_artifact_row_dict, active_object_key=active_object_key)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        rows = list(pool.map(worker, keys))
    return rows
