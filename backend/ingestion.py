import os
import tempfile
import json
import numpy as np
import pandas as pd
from minio import Minio
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from models import HdbResaleTransaction, UraRegion, UraPlanningArea
from hdb_lease import parse_remaining_lease_to_years

MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",   "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY",  "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY",  "password123")

BUCKET_DATASETS  = "datasets"
MINIO_RAW_PREFIX = "raw/datagovsg/HDB_ResaleFlatPrices"
PROCESSED_PREFIX = "processed"
# Legacy path written by the original ingestion run — used as fallback
LEGACY_RAW_PREFIX = "raw/hdb_resale"


def _make_minio_client() -> Minio:
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )


def _download_csvs_from_minio(client: Minio, dest_dir: str) -> list[str]:
    """Download HDB resale CSVs from MinIO to dest_dir. Returns local paths."""
    os.makedirs(dest_dir, exist_ok=True)
    local_paths = []
    objects = list(client.list_objects(BUCKET_DATASETS, prefix=MINIO_RAW_PREFIX + "/", recursive=True))
    if not objects:
        # Fall back to legacy prefix uploaded by the original ingestion run
        objects = list(client.list_objects(BUCKET_DATASETS, prefix=LEGACY_RAW_PREFIX + "/", recursive=True))
    for obj in objects:
        if not obj.object_name.endswith(".csv"):
            continue
        filename = os.path.basename(obj.object_name)
        local_path = os.path.join(dest_dir, filename)
        print(f"  Downloading {obj.object_name} …")
        client.fget_object(BUCKET_DATASETS, obj.object_name, local_path)
        local_paths.append(local_path)
    return local_paths


def run_ingestion(db: Session, force: bool = False):
    if force:
        print("Force re-ingest: truncating hdb_resale_transactions …")
        db.execute(text("TRUNCATE TABLE hdb_resale_transactions RESTART IDENTITY CASCADE"))
        db.commit()
    elif db.query(HdbResaleTransaction).first():
        print("HDB resale data already ingested. Skipping.")
        return

    print("Starting HDB resale ingestion pipeline …")

    client = _make_minio_client()

    if not client.bucket_exists(BUCKET_DATASETS):
        client.make_bucket(BUCKET_DATASETS)

    print("Downloading HDB resale CSVs from MinIO …")
    _tmp_dir = tempfile.mkdtemp(prefix="hdb_resale_")
    csv_files = _download_csvs_from_minio(client, _tmp_dir)

    if not csv_files:
        print("ERROR: No CSV files found in MinIO. Aborting ingestion.")
        return

    all_dfs = []

    for csv_file in csv_files:
        filename = os.path.basename(csv_file)
        # Mirror to canonical MinIO path if not already there
        minio_path = f"{MINIO_RAW_PREFIX}/{filename}"
        try:
            client.stat_object(BUCKET_DATASETS, minio_path)
        except Exception:
            try:
                client.fput_object(BUCKET_DATASETS, minio_path, csv_file)
                print(f"Uploaded {minio_path} to MinIO.")
            except Exception as e:
                print(f"Warning: could not upload {minio_path}: {e}")

        df = pd.read_csv(csv_file)
        all_dfs.append(df)

    combined_df = pd.concat(all_dfs, ignore_index=True)
    combined_df.columns = [c.lower().replace(' ', '_') for c in combined_df.columns]

    raw_lease = combined_df["remaining_lease"] if "remaining_lease" in combined_df.columns else None
    if raw_lease is not None:
        parsed = raw_lease.map(parse_remaining_lease_to_years)
    else:
        parsed = pd.Series([None] * len(combined_df), index=combined_df.index, dtype=object)

    sale_year = pd.to_datetime(combined_df["month"], format="%Y-%m", errors="coerce").dt.year
    if "lease_commence_date" in combined_df.columns:
        lcd = pd.to_numeric(combined_df["lease_commence_date"], errors="coerce")
    else:
        lcd = pd.Series(np.nan, index=combined_df.index, dtype=float)
    formula = (99 - (sale_year - lcd)).clip(lower=0, upper=99)
    years = parsed.where(parsed.notna(), formula)
    combined_df["remaining_lease_years"] = years.round().astype("Int64")
    if "remaining_lease" in combined_df.columns:
        combined_df = combined_df.drop(columns=["remaining_lease"])

    # Upload processed Parquet snapshot
    parquet_filename = "hdb_resale_full.parquet"
    tmp_parquet_path = f"/tmp/{parquet_filename}"
    combined_df.to_parquet(tmp_parquet_path, engine='pyarrow', compression='snappy')
    parquet_minio_path = f"{PROCESSED_PREFIX}/{parquet_filename}"
    try:
        client.stat_object(BUCKET_DATASETS, parquet_minio_path)
        print(f"{parquet_minio_path} already exists in MinIO.")
    except Exception:
        try:
            client.fput_object(BUCKET_DATASETS, parquet_minio_path, tmp_parquet_path)
            print(f"Uploaded {parquet_minio_path} to MinIO.")
        except Exception as e:
            print(f"Warning: could not upload parquet: {e}")

    from sqlalchemy import create_engine
    from models import DATABASE_URL
    eng = create_engine(DATABASE_URL)

    cols_to_keep = ['month', 'town', 'flat_type', 'block', 'street_name', 'storey_range',
                    'floor_area_sqm', 'flat_model', 'lease_commence_date', 'remaining_lease_years', 'resale_price']

    combined_df = combined_df[cols_to_keep]
    print(f"Inserting {len(combined_df):,} rows into hdb_resale_transactions …")
    combined_df.to_sql('hdb_resale_transactions', con=eng, if_exists='append', index=False, chunksize=10000)
    print("HDB resale ingestion completed successfully.")

def ingest_master_plan_data(db: Session, client: Minio, force: bool = False):
    if force:
        print("Force re-ingest: truncating URA Master Plan tables …")
        db.execute(text("TRUNCATE TABLE ura_mp19_regions_no_sea RESTART IDENTITY CASCADE"))
        db.execute(text("TRUNCATE TABLE ura_mp19_planning_areas_no_sea RESTART IDENTITY CASCADE"))
        db.commit()
    elif db.query(UraRegion).first():
        print("Master Plan 2019 data already ingested. Skipping.")
        return

    print("Downloading Master Plan GeoJSONs from MinIO …")
    regions_path = "raw/datagovsg/MasterPlan2019RegionBoundaryNoSea/Master Plan 2019 Region Boundary (No Sea) (GEOJSON).geojson"
    pa_path = "raw/datagovsg/MasterPlan2019PlanningAreaBoundaryNoSea.geojson"

    try:
        r_resp = client.get_object(BUCKET_DATASETS, regions_path)
        regions_data = json.loads(r_resp.read().decode('utf-8'))
        r_resp.close()
        r_resp.release_conn()

        for feature in regions_data.get('features', []):
            props = feature['properties']
            geom_str = json.dumps(feature['geometry'])
            region = UraRegion(
                region_n=props.get('REGION_N'),
                region_c=props.get('REGION_C'),
                geom=func.ST_SetSRID(func.ST_GeomFromGeoJSON(geom_str), 4326)
            )
            db.add(region)
            
        p_resp = client.get_object(BUCKET_DATASETS, pa_path)
        pa_data = json.loads(p_resp.read().decode('utf-8'))
        p_resp.close()
        p_resp.release_conn()

        for feature in pa_data.get('features', []):
            props = feature['properties']
            geom_str = json.dumps(feature['geometry'])
            pa = UraPlanningArea(
                pln_area_n=props.get('PLN_AREA_N'),
                pln_area_c=props.get('PLN_AREA_C'),
                region_c=props.get('REGION_C'),
                geom=func.ST_SetSRID(func.ST_GeomFromGeoJSON(geom_str), 4326)
            )
            db.add(pa)
            
        db.commit()
        print("Master Plan 2019 Regions & Planning Areas ingested successfully.")
    except Exception as e:
        print(f"Failed to ingest Master Plan data: {e}")
        db.rollback()
