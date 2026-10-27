"""Load modelling MinIO layout from JSON (paths only; secrets stay in MINIO_* / DATABASE_* env vars)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_ENV_VAR = "HOMEYAI_MINIO_SOURCES_JSON"

_DEFAULT_REL = Path("modelling") / "config" / "minio_training_sources.sample.json"
_TRACKED_OVERRIDE_REL = Path("modelling") / "config" / "minio_training_sources.local.json"


def _repo_root_near(path: Path) -> Path | None:
    cur = path.resolve()
    for p in [cur, *cur.parents]:
        if (p / "modelling").is_dir():
            return p
    return None


def resolved_minio_sources_path(project_root: Path) -> Path:
    env = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    root = project_root.resolve()
    bases = [root]
    guessed = _repo_root_near(root)
    if guessed and guessed.resolve() != root.resolve():
        bases.append(guessed.resolve())

    for base in bases:
        local = base / _TRACKED_OVERRIDE_REL
        if local.is_file():
            return local.resolve()

    if (root / _DEFAULT_REL).is_file():
        return (root / _DEFAULT_REL).resolve()
    guessed = _repo_root_near(root)
    if guessed and (guessed / _DEFAULT_REL).is_file():
        return (guessed / _DEFAULT_REL).resolve()
    return (root / _DEFAULT_REL).resolve()


def load_minio_sources_dict(project_root: Path) -> dict[str, Any]:
    path = resolved_minio_sources_path(project_root)
    if not path.is_file():
        raise FileNotFoundError(
            f"MinIO sources manifest missing: {path}. Set {CONFIG_ENV_VAR}, commit "
            f"{_TRACKED_OVERRIDE_REL}, or add {_DEFAULT_REL}."
        )
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class BucketKey:
    bucket: str
    key: str


def resolve_object(cfg: dict[str, Any], logical_name: str) -> BucketKey:
    objs = cfg.get("objects") or {}
    raw = objs.get(logical_name)
    if raw is None:
        raise KeyError(f"manifest.objects missing key {logical_name!r}")
    default_bucket = (cfg.get("default_bucket") or "datasets").strip()
    if isinstance(raw, str):
        return BucketKey(bucket=default_bucket, key=str(raw))
    if isinstance(raw, dict):
        b = (raw.get("bucket") or default_bucket).strip()
        k = raw.get("key") or raw.get("object_key")
        if not k:
            raise ValueError(f"manifest.objects[{logical_name}] needs string or {{bucket,key}}")
        return BucketKey(bucket=b, key=str(k))
    raise TypeError(f"manifest.objects[{logical_name}] unexpected type")


def snapshots_prefix(cfg: dict[str, Any]) -> str:
    p = cfg.get("training_snapshots_prefix")
    return str(p).strip().strip("/") if p else "training_snapshots"

