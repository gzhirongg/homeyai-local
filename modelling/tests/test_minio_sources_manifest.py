from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def test_sample_manifest_required_object_keys_exist() -> None:
    from modelling.config.minio_sources import load_minio_sources_dict, resolve_object

    cfg = load_minio_sources_dict(_REPO)
    for logical in (
        "training_hdb_resale_parquet",
        "mrt_features_parquet",
        "masterplan_landuse_pit_parquet",
        "global_volume_monthly",
        "macro_rpi_csv",
        "macro_interest_csv",
    ):
        bk = resolve_object(cfg, logical)
        assert bk.bucket
        assert bk.key

    assert "training_snapshots" in (cfg.get("training_snapshots_prefix") or "training_snapshots")


def test_resolve_object_accepts_dict_form() -> None:
    cfg = {
        "default_bucket": "b1",
        "objects": {
            "training_hdb_resale_parquet": {"bucket": "b2", "key": "k/x.parquet"},
        },
    }
    from modelling.config.minio_sources import resolve_object

    bk = resolve_object(cfg, "training_hdb_resale_parquet")
    assert bk.bucket == "b2"
    assert bk.key == "k/x.parquet"


def test_resolve_object_missing_raises() -> None:
    cfg = {"default_bucket": "datasets", "objects": {}}
    from modelling.config.minio_sources import resolve_object

    with pytest.raises(KeyError):
        resolve_object(cfg, "nonexistent")

