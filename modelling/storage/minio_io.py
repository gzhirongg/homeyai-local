"""Lightweight MinIO (S3-compatible) client for modelling code — no backend imports."""

from __future__ import annotations

import io
import os
from datetime import timedelta

from minio import Minio
from minio.error import S3Error


def _secure() -> bool:
    return os.getenv("MINIO_SECURE", "false").lower() in ("1", "true", "yes")


def normalize_minio_endpoint(raw: str) -> str:
    """Return ``host:port`` suitable for the MinIO SDK (no URL scheme, no path).

    Accepts common mistakes such as ``http://minio:9000`` so Docker ``.env`` can stay URL-shaped.
    TLS remains controlled by ``MINIO_SECURE``, not by whether the string used ``https://``.
    """
    s = raw.strip()
    lower = s.lower()
    if lower.startswith("https://"):
        s = s[8:]
    elif lower.startswith("http://"):
        s = s[7:]
    s = s.split("/", 1)[0].strip()
    return s


def minio_client() -> Minio:
    endpoint = normalize_minio_endpoint(os.getenv("MINIO_ENDPOINT", "localhost:9000"))
    access = os.getenv("MINIO_ACCESS_KEY", os.getenv("MINIO_ROOT_USER", "admin")).strip()
    secret = os.getenv("MINIO_SECRET_KEY", os.getenv("MINIO_ROOT_PASSWORD", "password123")).strip()
    return Minio(endpoint, access_key=access, secret_key=secret, secure=_secure())


def ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def put_object_bytes(
    bucket: str,
    object_key: str,
    data: bytes,
    *,
    content_type: str = "application/octet-stream",
    client: Minio | None = None,
) -> None:
    c = client or minio_client()
    ensure_bucket(c, bucket)
    c.put_object(bucket, object_key, io.BytesIO(data), length=len(data), content_type=content_type)


def get_object_bytes(bucket: str, object_key: str, *, client: Minio | None = None) -> bytes:
    c = client or minio_client()
    resp = c.get_object(bucket, object_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def presigned_get_object_url(
    bucket: str,
    object_key: str,
    *,
    expires_seconds: int = 900,
    client: Minio | None = None,
) -> str:
    c = client or minio_client()
    return c.presigned_get_object(bucket, object_key, expires=timedelta(seconds=expires_seconds))


def object_exists(bucket: str, object_key: str, *, client: Minio | None = None) -> bool:
    c = client or minio_client()
    try:
        c.stat_object(bucket, object_key)
        return True
    except S3Error as e:
        if getattr(e, "code", "") == "NoSuchKey":
            return False
        raise


def copy_object_same_bucket(
    bucket: str,
    src_key: str,
    dest_key: str,
    *,
    client: Minio | None = None,
) -> None:
    """Server-side copy within one bucket."""
    from minio.commonconfig import CopySource

    c = client or minio_client()
    ensure_bucket(c, bucket)
    c.copy_object(bucket, dest_key, CopySource(bucket, src_key))


def load_parquet_dataframe(bucket: str, object_key: str, *, client: Minio | None = None):
    """Load a Parquet dataset from MinIO without touching local disk."""
    import pandas as pd

    blob = get_object_bytes(bucket, object_key, client=client)
    return pd.read_parquet(io.BytesIO(blob))


def load_csv_dataframe(bucket: str, object_key: str, *, client: Minio | None = None):
    """Load a CSV blob from MinIO into a DataFrame."""
    import pandas as pd

    blob = get_object_bytes(bucket, object_key, client=client)
    return pd.read_csv(io.BytesIO(blob))


def list_object_keys_with_prefix(bucket: str, prefix: str, *, client: Minio | None = None) -> list[str]:
    c = client or minio_client()
    if not c.bucket_exists(bucket):
        return []
    keys: list[str] = []
    for obj in c.list_objects(bucket, prefix=prefix, recursive=True):
        keys.append(obj.object_name)
    return sorted(keys)
