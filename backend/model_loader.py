"""
Centralised model loading from MinIO object storage.

Models are stored in the 'models' bucket with environment-level separation:
    models/prod/xgboost_latest.pkl   ← production (default)
    models/dev/xgboost_test.pkl      ← development / experimental

The MODEL_ENV environment variable controls which folder is read (default: prod).
Models are cached in-memory after first load to avoid repeated downloads.
"""

import os
import pickle
import tempfile
from minio import Minio

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "password123")
MODEL_ENV = os.getenv("MODEL_ENV", "prod")
BUCKET_MODELS = "models"

_model_cache: dict = {}


def _get_minio_client() -> Minio:
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )


def load_model(model_name: str, env: str | None = None):
    """
    Download and deserialise a model from MinIO, with in-memory caching.

    Args:
        model_name: Filename of the model artifact, e.g. "xgboost_latest.pkl"
        env: Override the environment folder ("prod" or "dev").
             Defaults to MODEL_ENV.

    Returns:
        The deserialised Python object (model, scaler, explainer, etc.)

    Raises:
        FileNotFoundError: If the model does not exist in MinIO.
    """
    env = env or MODEL_ENV
    object_path = f"{env}/{model_name}"

    if object_path in _model_cache:
        return _model_cache[object_path]

    client = _get_minio_client()

    try:
        client.stat_object(BUCKET_MODELS, object_path)
    except Exception:
        raise FileNotFoundError(
            f"Model not found in MinIO: {BUCKET_MODELS}/{object_path}"
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pkl")
    try:
        client.fget_object(BUCKET_MODELS, object_path, tmp.name)
        with open(tmp.name, "rb") as f:
            model = pickle.load(f)
        _model_cache[object_path] = model
        return model
    finally:
        os.unlink(tmp.name)


def list_models(env: str | None = None) -> list[dict]:
    """List all model artifacts in the given environment folder."""
    env = env or MODEL_ENV
    client = _get_minio_client()

    if not client.bucket_exists(BUCKET_MODELS):
        return []

    objects = client.list_objects(BUCKET_MODELS, prefix=f"{env}/", recursive=True)
    return [
        {
            "name": obj.object_name,
            "size_mb": round(obj.size / (1024 * 1024), 2),
            "last_modified": str(obj.last_modified),
        }
        for obj in objects
    ]


def clear_cache():
    """Flush the in-memory model cache (e.g. after uploading a new model)."""
    _model_cache.clear()
    try:
        from services.model_store import clear_cache as clear_joblib_cache

        clear_joblib_cache()
    except ImportError:
        pass
