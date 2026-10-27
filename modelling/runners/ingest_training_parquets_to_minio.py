#!/usr/bin/env python3
"""One-shot ingest: eligible local artefacts under data/ → MinIO (narrow list; resale / MP GeoJSON excluded)."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from modelling.config.minio_sources import load_minio_sources_dict
from modelling.storage.minio_io import minio_client, put_object_bytes


def _project_root_argv(arg: Path | None) -> Path:
    if arg:
        return arg.resolve()
    here = Path(__file__).resolve()
    return here.parents[2]


def _upload_file(bucket: str, abs_path: Path, object_key: str, *, dry_run: bool) -> bool:
    if not abs_path.is_file():
        return False
    data = abs_path.read_bytes()
    if dry_run:
        print(f"[dry-run] PUT s3://{bucket}/{object_key} ({len(data)} bytes) ← {abs_path}")
        return True
    put_object_bytes(bucket, object_key, data, client=minio_client())
    print(f"PUT s3://{bucket}/{object_key} ({len(data)} bytes) ← {abs_path}")
    return True


def _resolve_logical_key(bucket_default: str, objs: dict, logical: str) -> tuple[str, str] | None:
    raw = objs.get(logical)
    if raw is None:
        return None
    b = bucket_default
    k = ""
    if isinstance(raw, str):
        k = raw
    elif isinstance(raw, dict):
        b = raw.get("bucket") or bucket_default
        k = raw.get("key") or raw.get("object_key") or ""
    if not k:
        return None
    return str(b).strip(), str(k)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Override manifest path for this invocation (does not mutate env).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="Copy the resolved manifest to modelling/config/minio_training_sources.local.json (commit shared dev/prod object layout here).",
    )
    args = parser.parse_args()
    root = _project_root_argv(args.project_root)

    manifest_path: Path | None = None
    if args.manifest:
        manifest_path = args.manifest.expanduser().resolve()
        cfg = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        cfg = load_minio_sources_dict(root)
        manifest_path = None

    bucket_default = (cfg.get("default_bucket") or "datasets").strip()
    objs = cfg.get("objects") or {}

    candidates = [
        ("mrt_features_parquet", root / Path("data/hdb_mrt_features.parquet")),
        ("global_volume_monthly", root / Path("data/macro/global_volume_monthly.parquet")),
        ("macro_rpi_csv", root / Path("data/macro/hdb_rpi.csv")),
        ("macro_interest_csv", root / Path("data/macro/interest_rates_monthly.csv")),
    ]

    any_ok = False
    for logical, abs_path in candidates:
        bk = _resolve_logical_key(bucket_default, objs, logical)
        if not bk:
            print(f"[skip {logical}] not defined under manifest.objects")
            continue
        b0, key0 = bk
        if _upload_file(b0, abs_path, key0, dry_run=bool(args.dry_run)):
            any_ok = True

    po_prefix = objs.get("pois_prefix") or objs.get("poi_prefix") or ""
    if isinstance(po_prefix, dict):
        po_prefix = po_prefix.get("key") or ""
    po_prefix = str(po_prefix).rstrip("/") + "/" if str(po_prefix).strip() else ""

    po_base = root / Path("data/pois")
    if po_prefix.strip("/") and po_base.is_dir():
        for fp in sorted(po_base.rglob("*")):
            if fp.is_file():
                suffix = fp.relative_to(po_base).as_posix()
                nk = (po_prefix + suffix).replace("//", "/")
                if _upload_file(bucket_default, fp, nk, dry_run=bool(args.dry_run)):
                    any_ok = True

    if args.update_manifest and not args.dry_run:
        dest = root / Path("modelling/config/minio_training_sources.local.json")
        src = manifest_path or (root / Path("modelling/config/minio_training_sources.sample.json"))
        if manifest_path:
            shutil.copy2(manifest_path, dest)
        else:
            shutil.copy2(src, dest)
        print(f"copied manifest → {dest}")

    if not any_ok:
        print(
            "Nothing uploaded — expected files include data/hdb_mrt_features.parquet, "
            "data/macro/*.parquet|*.csv (per manifest.objects), optionally data/pois/**.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
