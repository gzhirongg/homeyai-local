#!/usr/bin/env python3
"""Aggregate monthly resale volume from Postgres, upload ``global_volume_monthly`` to MinIO; optional RPI/MAS fetch."""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modelling.config.minio_sources import load_minio_sources_dict, resolve_object  # noqa: E402
from modelling.features.macro_sentiment import fetch_interest_rates  # noqa: E402
from modelling.targets.rpi_normalization import load_rpi_levels_api, load_rpi_levels_minio  # noqa: E402
from modelling.storage.minio_io import minio_client, put_object_bytes  # noqa: E402
from modelling.training_db import create_training_engine  # noqa: E402


def aggregate_monthly_volume_from_db(engine) -> pd.DataFrame:
    sql = text(
        """
        SELECT CAST(month AS text) AS year_month, COUNT(*)::bigint AS monthly_volume
        FROM hdb_resale_transactions
        GROUP BY CAST(month AS text)
        ORDER BY 1
        """
    )
    df = pd.read_sql(sql, engine)
    df["volume_lagged_3m"] = df["monthly_volume"].shift(3)
    return df


def put_volume_series_minio(volume_df: pd.DataFrame, project_root: Path) -> tuple[str, str]:
    mc = load_minio_sources_dict(project_root)
    bk = resolve_object(mc, "global_volume_monthly")
    buf = io.BytesIO()
    volume_df.to_parquet(buf, index=False)
    data = buf.getvalue()
    put_object_bytes(bk.bucket, bk.key, data, client=minio_client())
    return bk.bucket, bk.key


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, default=_REPO_ROOT)
    p.add_argument(
        "--skip-volume-upload",
        action="store_true",
        help="Compute volume dataframe but do not upload to MinIO (debug).",
    )
    p.add_argument("--also-fetch-rpi", action="store_true", help="Fetch RPI from data.gov.sg (no disk cache).")
    p.add_argument("--also-fetch-mas", action="store_true", help="Fetch blended rates (requires MAS_API_KEY).")
    args = p.parse_args(argv)

    root = args.project_root.resolve()
    engine = create_training_engine()
    try:
        vol = aggregate_monthly_volume_from_db(engine)
    finally:
        engine.dispose()

    if vol.empty:
        print("No resale rows aggregated — check Postgres connectivity.", file=sys.stderr)
        return 1

    if not args.skip_volume_upload:
        b, k = put_volume_series_minio(vol, root)
        print(f"Uploaded volume series to s3://{b}/{k} ({vol.shape[0]} months)")
    else:
        print(f"Skipped upload; volume rows={vol.shape[0]}")

    if args.also_fetch_rpi:
        lev = load_rpi_levels_minio(root)
        if lev.empty:
            lev = load_rpi_levels_api(verbose=True)
        print(f"RPI quarters (levels, in-memory): {len(lev)}")
    if args.also_fetch_mas:
        ir = fetch_interest_rates(root, verbose=True)
        print(f"Interest months (in-memory for this process): {len(ir)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
