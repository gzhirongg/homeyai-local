#!/usr/bin/env python3
"""Populate Master Plan Land Use PIT scalars: MinIO GeoJSON × DB coords → Postgres (normalized).

One row per (enriched_addr_id, revision_year). Populate ``masterplan_revision_catalog``
from ``discover_revision_keys`` then compute scalars once per GeoJSON revision.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text as sql_text

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modelling.features.land_use_revision import DEFAULT_BUCKET, discover_revision_keys  # noqa: E402
from modelling.features.masterplan_landuse_geometry import combine_landuseScalars_for_unique_coords  # noqa: E402
from modelling.features.masterplan_loi_proximity import loi_proximity_for_unique_coords  # noqa: E402
from modelling.features.masterplan_landuse_pit import MASTERPLAN_PARQUET_VALUE_COLS, infer_dist_cbd_airport  # noqa: E402
from modelling.storage.minio_io import get_object_bytes  # noqa: E402


def _normalize_sqlalchemy_url(url: str) -> str:
    u = url.strip()
    if u.startswith("postgres://"):
        return "postgresql+psycopg2://" + u[len("postgres://") :]
    if u.startswith("postgresql://") and "+psycopg2" not in u.split("://", 1)[0]:
        return "postgresql+psycopg2://" + u[len("postgresql://") :]
    return u


def _resolve_admin_database_url() -> str:
    url = (os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL") or "").strip()
    if url:
        return _normalize_sqlalchemy_url(url)
    user = (os.environ.get("ADMIN_DB_USER") or "").strip()
    password = (os.environ.get("ADMIN_DB_PASSWORD") or "").strip()
    host = (os.environ.get("DB_HOST") or os.environ.get("REMOTE_VM_IP") or "").strip()
    port = (os.environ.get("DB_INNER_PORT") or os.environ.get("DB_PORT") or "5432").strip()
    db = (os.environ.get("DB_NAME") or "").strip()
    if not (user and password and host and db):
        return ""
    u, p = quote_plus(user), quote_plus(password)
    return f"postgresql+psycopg2://{u}:{p}@{host}:{port}/{db}"


def create_admin_engine():
    url = _resolve_admin_database_url()
    if not url:
        raise RuntimeError(
            "Admin DB URL not configured. Set DATABASE_URL_ADMIN or DATABASE_URL, or "
            "ADMIN_DB_USER, ADMIN_DB_PASSWORD, DB_HOST (or REMOTE_VM_IP), DB_PORT/DB_INNER_PORT, DB_NAME."
        )
    return create_engine(url)


def load_unique_geocoded_addrs_from_db(*, min_tx_month: str | None) -> pd.DataFrame:
    """Distinct geocoded addresses seen in resale rows with done MRT PIT jobs (rolling window)."""
    from modelling.training_db import create_training_engine, get_mrt_pit_min_years

    my = get_mrt_pit_min_years()
    engine = create_training_engine()
    try:
        with engine.connect() as conn:
            win = conn.execute(
                sql_text("SELECT to_char(CURRENT_DATE - (:my * INTERVAL '1 year'), 'YYYY-MM') AS m"),
                {"my": my},
            ).scalar_one()
        start_month = win
        if min_tx_month and str(min_tx_month).strip():
            mu = str(min_tx_month).strip()[:7]
            start_month = max(start_month, mu)

        return pd.read_sql(
            sql_text(
                """
                SELECT DISTINCT
                    t.enriched_addr_id,
                    oe.latitude AS lat,
                    oe.longitude AS lon
                FROM hdb_resale_transactions t
                INNER JOIN mrt_pit_build_jobs j
                    ON j.tx_year_month = t.month AND j.status = 'done'
                INNER JOIN hdb_address_enrichment_onemap oe
                    ON oe.id = t.enriched_addr_id
                   AND oe.latitude IS NOT NULL
                   AND oe.longitude IS NOT NULL
                WHERE t.month >= :start_month
                  AND t.enriched_addr_id IS NOT NULL
                """
            ),
            engine,
            params={"start_month": start_month},
        )
    finally:
        engine.dispose()


def _upsert_revision_catalog(conn, revision_year: int, minio_key: str) -> None:
    eff = f"{int(revision_year):04d}-01"
    conn.execute(
        sql_text(
            """
            INSERT INTO masterplan_revision_catalog (revision_year, effective_from, minio_key)
            VALUES (:yr, :eff, :mkey)
            ON CONFLICT (revision_year) DO UPDATE SET
                effective_from = EXCLUDED.effective_from,
                minio_key = EXCLUDED.minio_key
            """
        ),
        {"yr": revision_year, "eff": eff, "mkey": minio_key},
    )


def _scalar_column_list() -> str:
    return ", ".join(MASTERPLAN_PARQUET_VALUE_COLS)


def _upsert_scalars_batch(conn, rows: list[dict]) -> None:
    if not rows:
        return
    cols = ["enriched_addr_id", "revision_year"] + MASTERPLAN_PARQUET_VALUE_COLS
    col_sql = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in MASTERPLAN_PARQUET_VALUE_COLS)
    stmt = sql_text(
        f"""
        INSERT INTO masterplan_landuse_pit_scalars ({col_sql})
        VALUES ({placeholders})
        ON CONFLICT (enriched_addr_id, revision_year) DO UPDATE SET
            {updates},
            computed_at = NOW()
        """
    )
    for r in rows:
        conn.execute(stmt, r)


def _compute_scalars_for_revision(
    unique_addrs: pd.DataFrame,
    revision_year: int,
    minio_key: str,
    bucket: str,
) -> pd.DataFrame:
    geo_bytes = get_object_bytes(bucket, minio_key)
    u = unique_addrs[["lat", "lon"]].drop_duplicates().reset_index(drop=True)
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as tmp:
        tmp.write(geo_bytes)
        temp_path = tmp.name
    try:
        feats = combine_landuseScalars_for_unique_coords(u, temp_path)
        loi = loi_proximity_for_unique_coords(u, temp_path)
        for c in loi.columns:
            if c not in ("lat", "lon"):
                feats[c] = loi[c].to_numpy()
    finally:
        Path(temp_path).unlink(missing_ok=True)

    dists = infer_dist_cbd_airport(u[["lat", "lon"]])
    feats = pd.concat([feats.reset_index(drop=True), dists[["dist_cbd", "dist_airport"]]], axis=1)
    merged = unique_addrs.merge(feats, on=["lat", "lon"], how="left")
    merged["revision_year"] = int(revision_year)
    return merged


def _rows_to_upsert_dicts(df: pd.DataFrame) -> list[dict]:
    out: list[dict] = []
    for _, row in df.iterrows():
        d: dict = {
            "enriched_addr_id": int(row["enriched_addr_id"]),
            "revision_year": int(row["revision_year"]),
        }
        for c in MASTERPLAN_PARQUET_VALUE_COLS:
            v = row.get(c)
            d[c] = float(v) if pd.notna(v) else None
        out.append(d)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build normalized Master Plan land-use PIT scalars (Postgres + MinIO GeoJSON)."
    )
    parser.add_argument("--project-root", type=Path, default=_REPO_ROOT)
    parser.add_argument(
        "--coords-from",
        choices=("postgresql", "minio_resale_parquet"),
        default="postgresql",
        help="Distinct geocode source (Postgres rolling window vs MinIO training resale parquet from manifest).",
    )
    parser.add_argument(
        "--min-tx-month",
        type=str,
        default=None,
        help="Raise lower month bound (YYYY-MM) when --coords-from postgresql.",
    )
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Upsert masterplan_revision_catalog + masterplan_landuse_pit_scalars (admin DB URL).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional local parquet dump of all computed scalar rows (debug).",
    )
    parser.add_argument("--bucket", type=str, default=DEFAULT_BUCKET)
    args = parser.parse_args(argv)

    if not args.write_db and args.out is None:
        print("Specify --write-db and/or --out.", file=sys.stderr)
        return 1

    root = args.project_root.resolve()

    if args.coords_from == "postgresql":
        try:
            unique_addrs = load_unique_geocoded_addrs_from_db(min_tx_month=args.min_tx_month)
        except Exception as exc:
            print(f"Could not load addresses from DB: {exc}", file=sys.stderr)
            return 1
    else:
        from modelling.config.minio_sources import load_minio_sources_dict, resolve_object

        from modelling.storage.minio_io import load_parquet_dataframe

        try:
            mcfg = load_minio_sources_dict(root)
            rk = resolve_object(mcfg, "training_hdb_resale_parquet")
            raw = load_parquet_dataframe(rk.bucket, rk.key)
        except Exception as exc:
            print(
                "Could not load coordinates from MinIO resale parquet "
                "(set HOMEYAI_MINIO_SOURCES_JSON + upload manifest objects): "
                f"{exc}",
                file=sys.stderr,
            )
            return 1
        req = {"enriched_addr_id", "lat", "lon"}
        if not req.issubset(raw.columns):
            print(f"Resale parquet missing columns {sorted(req)} ; got {sorted(raw.columns)}", file=sys.stderr)
            return 1
        sub = raw.dropna(subset=["lat", "lon", "enriched_addr_id"])
        unique_addrs = sub[["enriched_addr_id", "lat", "lon"]].drop_duplicates().reset_index(drop=True)

    if unique_addrs.empty:
        print("No geocoded addresses to process.", file=sys.stderr)
        return 1

    revisions = discover_revision_keys(bucket=args.bucket)
    if not revisions:
        print("No Land Use GeoJSON revisions found in MinIO catalog.", file=sys.stderr)
        return 1

    all_chunks: list[pd.DataFrame] = []
    admin_eng = create_admin_engine() if args.write_db else None
    try:
        if args.write_db and admin_eng is not None:
            with admin_eng.begin() as conn:
                for yr, mkey in revisions:
                    _upsert_revision_catalog(conn, yr, mkey)

        for yr, mkey in revisions:
            print(f"revision {yr} key={mkey} addrs={len(unique_addrs)}", flush=True)
            keyed = _compute_scalars_for_revision(unique_addrs, yr, mkey, args.bucket)
            keep = ["enriched_addr_id", "revision_year"] + MASTERPLAN_PARQUET_VALUE_COLS
            keyed = keyed[keep]
            all_chunks.append(keyed)

            if args.write_db and admin_eng is not None:
                batch = _rows_to_upsert_dicts(keyed)
                step = 2000
                with admin_eng.begin() as conn:
                    for i in range(0, len(batch), step):
                        _upsert_scalars_batch(conn, batch[i : i + step])
    finally:
        if admin_eng is not None:
            admin_eng.dispose()

    combined = pd.concat(all_chunks, ignore_index=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(args.out, index=False)
        print(f"Wrote {args.out} shape={combined.shape}")

    if args.write_db:
        print(f"Upserted Postgres scalars total_rows={len(combined)} revisions={len(revisions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
