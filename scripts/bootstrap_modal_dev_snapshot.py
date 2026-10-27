#!/usr/bin/env python3
"""Create a small training snapshot in MinIO for Modal / integration smoke tests.

Loads at most ``--limit`` rows via ``get_hdb_resale_bootstrap_query`` (pit snapshot join,
limited to newest window transactions first — fast for smoke tests), then uploads via
``export_training_snapshot_to_minio``.

Requires ``DATABASE_URL_READ_ONLY`` (or READ_ONLY_DB_* + DB_*) and MinIO credentials.

Does not print secret values.

Examples:

  PYTHONPATH=. python scripts/bootstrap_modal_dev_snapshot.py --limit 2000 --env-file .env

  PYTHONPATH=. python scripts/bootstrap_modal_dev_snapshot.py --limit 2000 \\
    --minio-endpoint HOST:9000 --minio-access-key AK --minio-secret-key SK
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from minio import Minio

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from modelling.runners.export_training_snapshot import export_training_snapshot_to_minio
from modelling.training_db import create_training_engine, get_hdb_resale_bootstrap_query


def _resolve_minio_client(
    *,
    env_file: Path,
    endpoint: str | None,
    access_key: str | None,
    secret_key: str | None,
    secure: bool | None,
) -> Minio:
    """Build MinIO client without merging ``os.environ`` into naive ``${VAR}`` expansion (too slow)."""
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise SystemExit("FAIL install python-dotenv (pip install python-dotenv)") from exc

    raw = dotenv_values(env_file, interpolate=True) if env_file.is_file() else {}

    def pick(key: str) -> str:
        v = raw.get(key)
        if v not in (None, ""):
            return str(v).strip()
        return os.environ.get(key, "").strip()

    ep = (endpoint or "").strip()
    ak = (access_key or "").strip()
    sk = (secret_key or "").strip()
    sec = secure

    if ep and ak and sk:
        pass
    else:
        raw_ep = pick("MINIO_ENDPOINT")
        if raw_ep:
            ep = _endpoint_host_port(raw_ep)
        else:
            host = pick("MINIO_HOST")
            port = pick("MINIO_INNER_PORT") or "9000"
            if host:
                ep = f"{host}:{port}"
        ak = ak or pick("MINIO_ACCESS_KEY")
        sk = sk or pick("MINIO_SECRET_KEY")
        if sec is None:
            sec = pick("MINIO_SECURE").lower() in ("1", "true", "yes")

    if sec is None:
        sec = False

    if not ep or not ak or not sk:
        raise SystemExit(
            "FAIL missing MinIO endpoint or credentials "
            "(use --env-file with MINIO_HOST/MINIO_INNER_PORT or MINIO_ENDPOINT + keys, "
            "or pass --minio-endpoint / --minio-access-key / --minio-secret-key). "
            "Ensure python-dotenv interpolation can resolve REMOTE_VM_IP in ``.env``."
        )

    if "${" in ep:
        raise SystemExit(
            "FAIL MINIO endpoint still contains unresolved ${…}; fix ``.env`` or pass --minio-endpoint host:9000"
        )

    return Minio(_endpoint_host_port(ep), access_key=ak, secret_key=sk, secure=sec)


def _endpoint_host_port(raw: str) -> str:
    """Normalize ``host:port`` or ``http(s)://host:port`` for Minio client."""
    e = raw.strip().rstrip("/")
    if "://" in e:
        e = e.split("://", 1)[1]
    return e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--limit",
        type=int,
        default=2500,
        help="Max rows in snapshot Parquet (min 500, matches training_db lateral limit SQL)",
    )
    ap.add_argument(
        "--skip-mrt-window",
        action="store_true",
        help="Set ML_TRAINING_SKIP_MRT_WINDOW_CHECK=1 for this process (avoids long window gate)",
    )
    ap.add_argument("--env-file", type=Path, default=REPO / ".env")
    ap.add_argument("--minio-endpoint", default="", help="host:port (not Docker-only `minio`)")
    ap.add_argument("--minio-access-key", default="")
    ap.add_argument("--minio-secret-key", default="")
    ap.add_argument("--minio-secure", action="store_true")
    args = ap.parse_args()
    lim = max(500, min(2_000_000, int(args.limit)))
    if args.skip_mrt_window:
        os.environ["ML_TRAINING_SKIP_MRT_WINDOW_CHECK"] = "1"

    print("Connecting MinIO client …", flush=True)
    mc = _resolve_minio_client(
        env_file=args.env_file,
        endpoint=args.minio_endpoint or None,
        access_key=args.minio_access_key or None,
        secret_key=args.minio_secret_key or None,
        secure=True if args.minio_secure else None,
    )

    print("Loading up to", lim, "rows from read-only DB …", flush=True)
    engine = create_training_engine()
    try:
        import pandas as pd

        df = pd.read_sql(get_hdb_resale_bootstrap_query(lim), engine)
        print("Loaded", len(df), "rows", flush=True)
    finally:
        engine.dispose()

    if df.empty:
        print("FAIL read_sql returned 0 rows — check DATABASE_URL_READ_ONLY and grants")
        return 1

    print("Uploading Parquet to datasets/training_snapshots/ …", flush=True)
    manifest = export_training_snapshot_to_minio(
        REPO,
        include_local_mrt_parquet=False,
        dataframe=df,
        skip_mrt_line_validate=True,
        minio_client=mc,
    )
    print("OK snapshot version", manifest.get("version"), "rows", manifest.get("row_count"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
