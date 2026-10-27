"""
Admin MinIO browser: hierarchical listing and lightweight text/CSV/JSON previews.
"""
from __future__ import annotations

import csv
import io
import os
from typing import Any, Dict, List

from minio import Minio

ALLOWED_BUCKETS = frozenset({"datasets", "models"})
PREVIEW_MAX_BYTES = 256 * 1024
CSV_PREVIEW_READ_BYTES = min(512 * 1024, PREVIEW_MAX_BYTES * 2)
# Parquet needs the full file (footer); cap to avoid loading huge objects into memory.
MAX_PARQUET_PREVIEW_BYTES = 64 * 1024 * 1024


def _client() -> Minio:
    endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
    access = os.getenv("MINIO_ACCESS_KEY", "admin")
    secret = os.getenv("MINIO_SECRET_KEY", "password123")
    return Minio(endpoint, access_key=access, secret_key=secret, secure=False)


def _validate_bucket(bucket: str) -> None:
    if bucket not in ALLOWED_BUCKETS:
        raise ValueError(f"Bucket not allowed: {bucket}")


def _validate_path_fragment(s: str) -> None:
    if ".." in s or s.startswith("/"):
        raise ValueError("Invalid path")


def _normalize_list_prefix(prefix: str) -> str:
    prefix = (prefix or "").strip()
    _validate_path_fragment(prefix)
    if not prefix:
        return ""
    return prefix if prefix.endswith("/") else prefix + "/"


def parent_prefix(list_prefix: str) -> str:
    """Parent 'folder' prefix for breadcrumbs (empty string = bucket root)."""
    p = list_prefix.rstrip("/")
    if not p:
        return ""
    parts = p.split("/")
    if len(parts) <= 1:
        return ""
    return "/".join(parts[:-1]) + "/"


def browse(bucket: str, prefix: str = "") -> Dict[str, Any]:
    """
    List immediate children under prefix (filesystem-style).
    `prefix` is the logical path inside the bucket, e.g. "" or "raw/datagovsg/".
    """
    _validate_bucket(bucket)
    list_prefix = _normalize_list_prefix(prefix)
    client = _client()
    if not client.bucket_exists(bucket):
        return {
            "bucket": bucket,
            "prefix": list_prefix,
            "parent_prefix": parent_prefix(list_prefix),
            "folders": [],
            "objects": [],
            "error": "Bucket does not exist",
        }

    folders: Dict[str, str] = {}
    files: List[Dict[str, Any]] = []

    try:
        for obj in client.list_objects(bucket, prefix=list_prefix, recursive=False):
            name = obj.object_name
            if not name:
                continue
            rel = name[len(list_prefix) :] if list_prefix else name
            if not rel:
                continue

            is_dir = name.endswith("/") or getattr(obj, "is_dir", False)
            if is_dir:
                part = rel.rstrip("/").split("/")[0]
                if part:
                    sub = (list_prefix + part + "/") if list_prefix else (part + "/")
                    folders[part] = sub
            else:
                if "/" in rel:
                    part = rel.split("/")[0]
                    sub = (list_prefix + part + "/") if list_prefix else (part + "/")
                    folders.setdefault(part, sub)
                else:
                    files.append(
                        {
                            "name": rel,
                            "key": name,
                            "size_mb": round(obj.size / (1024 * 1024), 4),
                            "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                        }
                    )
    except Exception as e:
        return {
            "bucket": bucket,
            "prefix": list_prefix,
            "parent_prefix": parent_prefix(list_prefix),
            "folders": [],
            "objects": [],
            "error": str(e),
        }

    folder_list = [{"name": n, "prefix": p} for n, p in sorted(folders.items(), key=lambda x: x[0].lower())]
    files.sort(key=lambda x: x["name"].lower())

    return {
        "bucket": bucket,
        "prefix": list_prefix,
        "parent_prefix": parent_prefix(list_prefix),
        "folders": folder_list,
        "objects": files,
    }


def _read_object_all(client: Minio, bucket: str, object_key: str) -> bytes:
    response = client.get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _preview_parquet_from_bytes(data: bytes, object_key: str, stat_size: int) -> Dict[str, Any]:
    import pandas as pd

    try:
        df = pd.read_parquet(io.BytesIO(data))
    except Exception as e:
        return {
            "kind": "unsupported",
            "key": object_key,
            "size_bytes": stat_size,
            "message": f"Could not read Parquet: {e}",
        }

    total = len(df)
    head = df.head(5)

    def fmt(v: object) -> str:
        if pd.isna(v):
            return ""
        if hasattr(v, "isoformat") and callable(getattr(v, "isoformat")) and not isinstance(v, (str, bytes)):
            try:
                return v.isoformat()  # type: ignore[no-any-return]
            except Exception:
                return str(v)
        return str(v)

    header = [str(c) for c in head.columns]
    rows = [[fmt(v) for v in row] for _, row in head.iterrows()]

    return {
        "kind": "parquet",
        "key": object_key,
        "size_bytes": stat_size,
        "truncated": total > 5,
        "header": header,
        "rows": rows,
        "row_count_shown": len(rows),
        "total_row_count": total,
        "column_count": len(df.columns),
    }


def _preview_parquet_object(client: Minio, bucket: str, object_key: str, stat) -> Dict[str, Any]:
    stat_size = int(stat.size or 0)
    if stat_size > MAX_PARQUET_PREVIEW_BYTES:
        mb = stat_size / (1024 * 1024)
        cap_mb = MAX_PARQUET_PREVIEW_BYTES // (1024 * 1024)
        return {
            "kind": "unsupported",
            "key": object_key,
            "size_bytes": stat_size,
            "message": f"Parquet file is too large to preview ({mb:.1f} MiB; max {cap_mb} MiB).",
        }
    data = _read_object_all(client, bucket, object_key)
    return _preview_parquet_from_bytes(data, object_key, stat_size)


def preview(bucket: str, object_key: str) -> Dict[str, Any]:
    """Preview object contents: CSV, Parquet (first 5 rows), JSON/GeoJSON (first 20 lines)."""
    _validate_bucket(bucket)
    object_key = (object_key or "").strip().lstrip("/")
    _validate_path_fragment(object_key)
    if not object_key:
        raise ValueError("object key required")

    client = _client()
    stat = client.stat_object(bucket, object_key)
    lower = object_key.lower()

    if lower.endswith(".parquet"):
        return _preview_parquet_object(client, bucket, object_key, stat)

    read_limit = CSV_PREVIEW_READ_BYTES if lower.endswith(".csv") else PREVIEW_MAX_BYTES
    read_limit = min(read_limit, stat.size) if stat.size else read_limit

    response = client.get_object(bucket, object_key)
    try:
        chunk = response.read(read_limit if read_limit > 0 else PREVIEW_MAX_BYTES)
    finally:
        response.close()
        response.release_conn()

    truncated = stat.size > len(chunk) if stat.size else len(chunk) >= read_limit

    if len(chunk) >= 4 and chunk[:4] == b"PAR1":
        return _preview_parquet_object(client, bucket, object_key, stat)

    text = chunk.decode("utf-8", errors="replace")

    if lower.endswith(".csv"):
        rows: List[List[str]] = []
        try:
            reader = csv.reader(io.StringIO(text))
            for i, row in enumerate(reader):
                rows.append(row)
                if i >= 5:
                    break
        except Exception:
            rows = []
        header = rows[0] if rows else []
        data_rows = rows[1:6] if len(rows) > 1 else []
        return {
            "kind": "csv",
            "key": object_key,
            "size_bytes": stat.size,
            "truncated": truncated,
            "header": header,
            "rows": data_rows,
            "row_count_shown": len(data_rows),
        }

    if lower.endswith(".json") or lower.endswith(".geojson"):
        lines = text.splitlines()
        preview_lines = lines[:20]
        return {
            "kind": "json",
            "key": object_key,
            "size_bytes": stat.size,
            "truncated": truncated or len(lines) > 20,
            "lines": preview_lines,
            "line_count_shown": len(preview_lines),
        }

    return {
        "kind": "text",
        "key": object_key,
        "size_bytes": stat.size,
        "truncated": truncated,
        "content": text if len(text) <= 8000 else text[:8000],
    }
