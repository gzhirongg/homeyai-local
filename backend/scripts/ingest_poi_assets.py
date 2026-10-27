#!/usr/bin/env python3
"""Upload raw POI files to MinIO and populate ``poi_locations`` in Postgres.

Requires:
  - ``data/pois/`` with the seven assets (see ``modelling.features.poi_distancing.POI_FILENAMES``).
  - Primary-school CSVs may omit ``lat``/``lon``; if ``postal_code`` is present, rows are geocoded via OneMap (needs ``ONEMAP_EMAIL_*`` / ``ONEMAP_PASSWORD_*``).
  - Admin DB: ``DATABASE_URL_ADMIN`` **or** ``DATABASE_URL`` **or** ``ADMIN_DB_*`` + ``DB_HOST``/``REMOTE_VM_IP`` + ``DB_NAME``
    **or** libpq ``PGUSER``, ``PGPASSWORD``, ``PGHOST``, ``PGDATABASE`` (optional ``PGPORT``).
  - MinIO env vars (``MINIO_*``) matching other ingest scripts. If ``MINIO_ENDPOINT`` is unset, ``MINIO_HOST`` + ``MINIO_INNER_PORT`` are used when MinIO upload is enabled.

Usage (repo root on host)::

    PYTHONPATH=. python backend/scripts/ingest_poi_assets.py
    PYTHONPATH=. python backend/scripts/ingest_poi_assets.py --smoke

Docker (remote DB + MinIO from ``.env`` — **docker-compose.dev.yml** backend)::

    ./scripts/docker_dev_backend.sh python /app/scripts/ingest_poi_assets.py --smoke

    # equivalent:
    docker compose -f docker-compose.dev.yml exec backend env PYTHONPATH=/:/app bash -lc \\
        'cd / && python /app/scripts/ingest_poi_assets.py --smoke'

When MinIO is unreachable (e.g. VPN down), Postgres ingest can still run::

    PYTHONPATH=. python backend/scripts/ingest_poi_assets.py --skip-minio-upload
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
from minio import Minio

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from db_env import load_repo_env, psycopg2_connect_dsn, resolve_admin_database_url  # noqa: E402

from modelling.features.poi_distancing import (  # noqa: E402
    POI_FILENAMES,
    pois_dir,
    process_linestring_geojson_centroids,
    process_polygon_geojson,
)

MINIO_BUCKET = "datasets"
MINIO_PREFIX = "pois"

# Keys in POI_FILENAMES → poi_locations.poi_type
ASSET_KEY_TO_DB_TYPE: dict[str, str] = {
    "top_20_schools": "school_top20",
    "all_schools": "school_any",
    "malls": "mall",
    "supermarkets": "supermarket",
    "parks": "park",
    "markets": "market",
    "pcn": "pcn",
}

_NAME_CANDIDATES = (
    "SCHOOLNAME",
    "SchoolName",
    "school_name",
    "NAME",
    "Name",
    "name",
    "DESCRIPTION",
    "Description",
    "description",
    "BUILDING",
    "Building",
)


def _pick_name_row(row: pd.Series) -> str:
    for col in _NAME_CANDIDATES:
        if col in row.index:
            v = row[col]
            if pd.notna(v) and str(v).strip():
                return str(v).strip()[:2000]
    return ""


def _first_lat_lon_from_onemap(resp: dict) -> tuple[float, float] | None:
    for r in resp.get("results") or []:
        try:
            la = float(r.get("LATITUDE"))
            lo = float(r.get("LONGITUDE"))
            if not (math.isnan(la) or math.isnan(lo)):
                return la, lo
        except (TypeError, ValueError):
            continue
    return None


def _load_onemap_service_class() -> Any:
    """Load OneMap without ``import services`` (package ``__init__`` pulls optional deps e.g. WeasyPrint)."""
    path = _REPO / "backend" / "services" / "onemap_service.py"
    spec = importlib.util.spec_from_file_location("_homeyai_onemap_service", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load OneMap module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.OneMapService


def _ensure_school_csv_lat_lon(asset_key: str, df: pd.DataFrame, path: Path) -> pd.DataFrame:
    """MOE-style exports often have ``postal_code`` but no coordinates; geocode via OneMap."""
    if asset_key not in ("top_20_schools", "all_schools"):
        return df
    df = df.copy()
    if (
        "lat" in df.columns
        and "lon" in df.columns
        and df["lat"].notna().any()
        and df["lon"].notna().any()
    ):
        return df
    if "postal_code" not in df.columns:
        raise ValueError(
            f"{path}: school CSV needs lat/lon columns or postal_code for OneMap geocoding"
        )
    OneMapService = _load_onemap_service_class()

    svc = OneMapService()
    lats: list[float] = []
    lons: list[float] = []
    n = len(df)
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        postal_raw = str(row.get("postal_code", "")).strip()
        postal = postal_raw.replace(" ", "")
        name = str(row.get("school_name", "") or row.get("SCHOOLNAME", "") or "").strip()
        query = postal if len(postal) >= 6 else name
        if not query:
            raise ValueError(f"{path}: row {i}/{n} has no postal_code or school_name for geocoding")
        resp = svc.search_address(query)
        ll = _first_lat_lon_from_onemap(resp)
        if ll is None and query != name and name:
            resp = svc.search_address(name)
            ll = _first_lat_lon_from_onemap(resp)
        if ll is None:
            raise RuntimeError(
                f"{path}: OneMap returned no coordinates for postal={postal_raw!r} name={name!r}"
            )
        lats.append(ll[0])
        lons.append(ll[1])
        if i % 25 == 0 or i == n:
            print(f"  Geocoded schools {i}/{n} …", flush=True)
    df["lat"] = lats
    df["lon"] = lons
    return df


def _parse_asset_rows(asset_key: str, path: Path, *, smoke_limit: int | None) -> list[tuple[Any, ...]]:
    poi_type = ASSET_KEY_TO_DB_TYPE[asset_key]
    source_file = path.name
    rows: list[tuple[Any, ...]] = []

    if asset_key in ("parks", "markets"):
        df = process_polygon_geojson(path)
        for _, r in df.iterrows():
            v = r["name"] if "name" in r.index else ""
            nm = str(v).strip()[:2000] if pd.notna(v) and str(v).strip() else ""
            rows.append((poi_type, nm, float(r["lat"]), float(r["lon"]), source_file))
    elif asset_key == "pcn":
        df = process_linestring_geojson_centroids(path)
        for _, r in df.iterrows():
            v = r["name"] if "name" in r.index else ""
            nm = str(v).strip()[:2000] if pd.notna(v) and str(v).strip() else ""
            rows.append((poi_type, nm, float(r["lat"]), float(r["lon"]), source_file))
    else:
        df = pd.read_csv(path)
        df = _ensure_school_csv_lat_lon(asset_key, df, path)
        if "lat" not in df.columns or "lon" not in df.columns:
            raise ValueError(f"{path} must contain lat, lon columns (or postal_code for schools)")
        df = df.dropna(subset=["lat", "lon"], how="any")
        for _, r in df.iterrows():
            nm = _pick_name_row(r)
            rows.append((poi_type, nm, float(r["lat"]), float(r["lon"]), source_file))

    if smoke_limit is not None and len(rows) > smoke_limit:
        rows = rows[:smoke_limit]
    return rows


def _upload_minio(client: Minio | None, local_path: Path) -> None:
    if client is None:
        print(f"SKIP MinIO upload (--skip-minio-upload): {local_path.name}")
        return
    key = f"{MINIO_PREFIX}/{local_path.name}"
    client.fput_object(MINIO_BUCKET, key, str(local_path))
    print(f"Uploaded s3://{MINIO_BUCKET}/{key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest POI CSV/GeoJSON into MinIO + Postgres.")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Only upload + insert first 10 rows per asset (still deletes prior rows per source_file).",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_REPO,
        help="Repo root (contains data/pois).",
    )
    parser.add_argument(
        "--skip-minio-upload",
        action="store_true",
        help="Only load into Postgres (skip MinIO fput); re-run without this when MinIO is reachable.",
    )
    args = parser.parse_args(argv)
    smoke_limit = 10 if args.smoke else None

    load_repo_env(_REPO)
    try:
        db_url = resolve_admin_database_url()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    root = args.project_root.resolve()
    base = pois_dir(root)

    client: Minio | None
    if args.skip_minio_upload:
        client = None
    else:
        if not (os.getenv("MINIO_ENDPOINT") or "").strip():
            host = (os.getenv("MINIO_HOST") or "").strip()
            port = (os.getenv("MINIO_INNER_PORT") or "9000").strip()
            if host:
                os.environ["MINIO_ENDPOINT"] = f"{host}:{port}"
        endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
        client = Minio(
            endpoint,
            access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "password123"),
            secure=False,
        )

    conn = psycopg2.connect(psycopg2_connect_dsn(db_url))
    try:
        cur = conn.cursor()
        for asset_key, filename in POI_FILENAMES.items():
            path = base / filename
            if not path.is_file():
                print(f"SKIP missing file: {path}", file=sys.stderr)
                continue
            _upload_minio(client, path)
            rows = _parse_asset_rows(asset_key, path, smoke_limit=smoke_limit)
            cur.execute("DELETE FROM poi_locations WHERE source_file = %s", (filename,))
            if rows:
                cur.executemany(
                    """
                    INSERT INTO poi_locations (poi_type, name, lat, lon, source_file)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    rows,
                )
            print(f"Ingested {len(rows):,} rows for {filename} ({ASSET_KEY_TO_DB_TYPE[asset_key]})")
        conn.commit()
    finally:
        conn.close()

    print("POI ingest finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


try:
    from prefect import flow
except ImportError:  # pragma: no cover
    flow = None  # type: ignore[misc, assignment]

if flow is not None:  # pragma: no cover

    @flow(name="ingest-poi-assets", log_prints=True, retries=0)
    def ingest_poi_assets_flow(*, smoke: bool = False, skip_minio_upload: bool = False) -> int:
        """Prefect entry point: run full ingest (or ``smoke=True`` for capped rows)."""
        argv: list[str] = []
        if smoke:
            argv.append("--smoke")
        if skip_minio_upload:
            argv.append("--skip-minio-upload")
        return main(argv)
