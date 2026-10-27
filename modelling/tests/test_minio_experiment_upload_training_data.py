"""Manifest lists ``training_data_object`` when ``training_data.parquet`` is uploaded."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def capture_puts(monkeypatch):
    puts: list[tuple[str, str, bytes]] = []

    def fake_put(bucket: str, key: str, data: bytes, **_kwargs: object) -> None:
        puts.append((bucket, key, data))

    monkeypatch.setattr("modelling.storage.minio_io.put_object_bytes", fake_put)
    return puts


def test_upload_manifest_includes_training_data_object(tmp_path: Path, capture_puts) -> None:
    from modelling.runners.minio_experiment_upload import upload_experiment_directory_to_minio

    (tmp_path / "model.pkl").write_bytes(b"fake-model")
    pd.DataFrame({"resale_price": [100.0, 200.0]}).to_parquet(tmp_path / "training_data.parquet", index=False)

    out = upload_experiment_directory_to_minio(
        tmp_path,
        run_id="exp_test__20260101T000000Z",
        experiment_id="exp_test",
        feature_set_id="baseline_v1",
        dataset_version="snap_test",
        model_env="dev",
        source="pytest",
    )

    assert out["manifest"]["training_data_object"] == "training_data.parquet"

    manifest_puts = [p for p in capture_puts if p[1].endswith("/manifest.json")]
    assert len(manifest_puts) == 1
    doc = json.loads(manifest_puts[0][2].decode("utf-8"))
    assert doc["training_data_object"] == "training_data.parquet"
    assert doc["run_id"] == "exp_test__20260101T000000Z"
