"""
Prefect flow: export wide HDB training Parquet (legacy ``datasets/training_snapshots/``).

Deprecated for scheduled training: ``model_train_flow`` now builds narrow datasets under
``datasets/training_datasets/v2`` per ``feature_set_id``. Keep this flow for manual wide exports
or tooling that still expects ``hdb_resale.parquet`` + sidecars.

Deploy manually when needed:
  cd backend && prefect deploy --prefect-file prefect.yaml --entrypoint prefect/flows/snapshot_flow.py:training_snapshot_flow

Previously registered as ``training-snapshot-default`` in older prefect.yaml revisions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from prefect import flow, task

_FLOW_FILE = Path(__file__).resolve()
_BACKEND_DIR = _FLOW_FILE.parents[2]
_REPO_ROOT = _BACKEND_DIR.parent

for _p in (_BACKEND_DIR, _REPO_ROOT):
    sp = str(_p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# Load .env (repo root and backend)
for _env_candidate in (_BACKEND_DIR / ".env", _REPO_ROOT / ".env"):
    if _env_candidate.exists():
        for _line in _env_candidate.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                k, _, v = _line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        break


@task
def export_snapshot_task(version: str | None = None) -> dict:
    from modelling.training_log import configure_training_logging
    from modelling.runners.export_training_snapshot import export_training_snapshot_to_minio

    configure_training_logging(force=True, source="PREFECT")
    return export_training_snapshot_to_minio(_REPO_ROOT, version=version)


@flow(name="homeyai-training-snapshot")
def training_snapshot_flow(version: str | None = None) -> dict:
    """Write a new Parquet snapshot and refresh ``_latest.json`` pointer."""
    from modelling.training_log import prefect_training_logger

    logger = prefect_training_logger()
    info = export_snapshot_task(version)
    logger.info("Snapshot %s rows=%s", info.get("version"), info.get("row_count"))
    return info
