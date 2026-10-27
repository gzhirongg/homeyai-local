"""Validate v2 dynamic dataset loads fail fast when Parquet rows disagree with manifest."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd
import pytest


def test_v2_manifest_row_count_mismatch_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.BytesIO()
    pd.DataFrame({"a": [1, 2]}).to_parquet(buf, index=False)
    pq_bytes = buf.getvalue()

    manifest_doc = {"schema": "training_dataset_v2", "row_count": 99}

    def fake_object_exists(bucket: str, key: str, client=None) -> bool:
        _ = bucket, client
        assert key.endswith("dataset.parquet") or key.endswith("manifest.json")
        return True

    def fake_get_object_bytes(bucket: str, key: str, client=None) -> bytes:
        _ = bucket, client
        if key.endswith("manifest.json"):
            return json.dumps(manifest_doc).encode("utf-8")
        raise AssertionError(f"unexpected key {key}")

    def fake_load_parquet_dataframe(bucket: str, key: str, client=None):
        _ = bucket, client
        assert key.endswith("dataset.parquet")
        return pd.read_parquet(io.BytesIO(pq_bytes))

    monkeypatch.setattr("modelling.data.snapshot_loader.minio_io.object_exists", fake_object_exists)
    monkeypatch.setattr("modelling.data.snapshot_loader.minio_io.get_object_bytes", fake_get_object_bytes)
    monkeypatch.setattr(
        "modelling.data.snapshot_loader.minio_io.load_parquet_dataframe",
        fake_load_parquet_dataframe,
    )

    from modelling.data.snapshot_loader import load_training_frame_from_dataset_version

    with pytest.raises(RuntimeError, match="row_count"):
        load_training_frame_from_dataset_version("abcachekey00000000000001", tmp_path)


def test_v2_manifest_row_count_match_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.BytesIO()
    pd.DataFrame({"a": [1, 2]}).to_parquet(buf, index=False)
    pq_bytes = buf.getvalue()

    manifest_doc = {"schema": "training_dataset_v2", "row_count": 2}

    def fake_object_exists(bucket: str, key: str, client=None) -> bool:
        _ = bucket, client
        return True

    def fake_get_object_bytes(bucket: str, key: str, client=None) -> bytes:
        _ = bucket, client
        if key.endswith("manifest.json"):
            return json.dumps(manifest_doc).encode("utf-8")
        raise AssertionError(key)

    def fake_load_parquet_dataframe(bucket: str, key: str, client=None):
        _ = bucket, client
        return pd.read_parquet(io.BytesIO(pq_bytes))

    monkeypatch.setattr("modelling.data.snapshot_loader.minio_io.object_exists", fake_object_exists)
    monkeypatch.setattr("modelling.data.snapshot_loader.minio_io.get_object_bytes", fake_get_object_bytes)
    monkeypatch.setattr(
        "modelling.data.snapshot_loader.minio_io.load_parquet_dataframe",
        fake_load_parquet_dataframe,
    )

    from modelling.data.snapshot_loader import load_training_frame_from_dataset_version

    df, meta = load_training_frame_from_dataset_version("abcachekey00000000000001", tmp_path)
    assert len(df) == 2
    assert meta.get("snapshot_manifest", {}).get("row_count") == 2
