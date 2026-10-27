"""Load LTA MRT Station Exit GeoJSON from MinIO into the PostGIS mrt_station_exits table.

Run this once (or after a DB wipe) to populate the table.

Usage — inside the backend container:
    python scripts/ingest_mrt_stations.py

The GeoJSON is downloaded from MinIO bucket:
    datasets/raw/datagovsg/LTAMRTStationExitGEOJSON.geojson
"""

import json
import os
import sys
import time
import tempfile
from pathlib import Path

import psycopg2
import psycopg2.extras
from minio import Minio

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MINIO_ENDPOINT  = os.getenv("MINIO_ENDPOINT",  "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "password123")

MINIO_BUCKET = "datasets"
MINIO_OBJECT = "raw/datagovsg/LTAMRTStationExitGEOJSON.geojson"

BATCH_SIZE = 200

# Load .env from repo root / backend root; resolve admin URL (DATABASE_URL_ADMIN preferred).
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

from scripts.db_env import load_repo_env, psycopg2_connect_dsn, resolve_admin_database_url

load_repo_env(_here.parent.parent)

try:
    DATABASE_URL = psycopg2_connect_dsn(resolve_admin_database_url())
except RuntimeError as e:
    sys.exit(f"ERROR: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def download_from_minio(dest_path: str) -> None:
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )
    print(f"Downloading s3://{MINIO_BUCKET}/{MINIO_OBJECT} …")
    client.fget_object(MINIO_BUCKET, MINIO_OBJECT, dest_path)
    print(f"Saved to {dest_path}")


def props_to_row(props: dict, geom_json: str) -> tuple:
    return (
        props.get("OBJECTID"),
        props.get("STATION_NA"),
        props.get("EXIT_CODE"),
        props.get("INC_CRC"),
        props.get("FMEL_UPD_D"),
        geom_json,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        download_from_minio(tmp_path)

        print("Parsing GeoJSON …")
        with open(tmp_path, encoding="utf-8") as f:
            collection = json.load(f)

        features = collection.get("features", [])
        total = len(features)
        print(f"Found {total:,} features.")

        print("Connecting to database …")
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cur = conn.cursor()

        try:
            print("Truncating mrt_station_exits …")
            cur.execute("TRUNCATE TABLE mrt_station_exits RESTART IDENTITY")

            insert_sql = """
                INSERT INTO mrt_station_exits
                    (objectid, station_name, exit_code, inc_crc, fmel_upd_d, geom)
                VALUES
                    (%s, %s, %s, %s, %s,
                     ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
            """

            inserted = 0
            start = time.time()
            batch: list[tuple] = []

            for feature in features:
                geom_json = json.dumps(feature["geometry"])
                row = props_to_row(feature.get("properties", {}), geom_json)
                batch.append(row)

                if len(batch) >= BATCH_SIZE:
                    psycopg2.extras.execute_batch(cur, insert_sql, batch)
                    inserted += len(batch)
                    batch = []

            if batch:
                psycopg2.extras.execute_batch(cur, insert_sql, batch)
                inserted += len(batch)

            conn.commit()
            elapsed = time.time() - start
            print(f"Done. Inserted {inserted:,} rows in {elapsed:.1f}s.")

        except Exception as exc:
            conn.rollback()
            print(f"\nERROR: {exc}")
            raise
        finally:
            cur.close()
            conn.close()

    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    main()
