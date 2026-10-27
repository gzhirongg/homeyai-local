#!/usr/bin/env python3
"""Download and prepare public HDB assets for the isolated homeyai_local database.

Run in the standalone backend container. All raw downloads are cached locally and
archived by SHA-256 in MinIO; no team VM or OneMap account is used.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

import requests
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(Path(__file__).resolve().parent)]

DATASETS = {
    "resale": ("d_8b84c4ee58e3cfc0ece0d773c8ca6abc", "HDBResale2017Onwards.csv"),
    "properties": ("d_17f5382f26140b1fdae0ba2ef6239d2f", "HDBPropertyInformation.csv"),
    "buildings": ("d_16b157c52ed637edd6ba1232e026258d", "HDBExistingBuilding.geojson"),
    "rpi": ("d_14f63e595975691e7c24a27ae4c07c79", "HDBResalePriceIndex.csv"),
}
ADDRESS_COMMIT = "7ff07ccb7699ea38979d1e865bf9ae7fbce62c32"
ADDRESS_URL = (
    "https://raw.githubusercontent.com/dhanyyudi/onemap-building-sg/"
    f"{ADDRESS_COMMIT}/data/onemap_15022026.csv"
)


def require_local_database() -> None:
    url = make_url(os.environ.get("DATABASE_URL", "sqlite://"))
    if url.host != "db" or url.database != "homeyai_local":
        raise RuntimeError("This bootstrap only writes to Docker host db / database homeyai_local")


def download_assets() -> dict[str, Path]:
    from minio import Minio
    from minio.error import S3Error

    directory = ROOT / "data"
    directory.mkdir(exist_ok=True)
    session = requests.Session()
    client = Minio(os.environ["MINIO_ENDPOINT"], access_key=os.environ["MINIO_ACCESS_KEY"],
                   secret_key=os.environ["MINIO_SECRET_KEY"], secure=False)
    provenance = {}
    paths = {}
    for name, (dataset, filename) in DATASETS.items():
        path = directory / filename
        source = f"https://data.gov.sg/datasets/{dataset}/view"
        if not path.is_file():
            api = f"https://api-open.data.gov.sg/v1/public/api/datasets/{dataset}"
            if name != "buildings":
                session.get(f"{api}/initiate-download", timeout=45)
                time.sleep(12)
            for attempt in range(12):
                response = session.get(f"{api}/poll-download", timeout=45)
                payload = response.json()
                url = (payload.get("data") or {}).get("url")
                if url:
                    response = session.get(url, timeout=180)
                    response.raise_for_status()
                    temp = path.with_suffix(path.suffix + ".part")
                    temp.write_bytes(response.content)
                    temp.replace(path)
                    break
                time.sleep(12)
            else:
                raise RuntimeError(f"Download not available for {dataset}: {payload.get('errorMsg')}")
            time.sleep(12)
        paths[name] = path
        provenance[name] = {"source": source, "dataset_id": dataset}
        print(f"Dataset ready: {filename} ({path.stat().st_size:,} bytes)", flush=True)

    path = directory / "OneMapAddresses20260215.csv"
    if not path.is_file():
        response = session.get(ADDRESS_URL, timeout=120)
        response.raise_for_status()
        path.write_bytes(response.content)
    paths["addresses"] = path
    provenance["addresses"] = {"source": ADDRESS_URL, "commit": ADDRESS_COMMIT,
                                "note": "Public archived OneMap export; corroborated against HDB footprints"}

    for name, path in paths.items():
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        key = f"raw/local_bootstrap/{name}/{digest}/{path.name}"
        try:
            client.stat_object("datasets", key)
        except S3Error as exc:
            if exc.code != "NoSuchKey":
                raise
            client.put_object("datasets", key, io.BytesIO(content), len(content))
        provenance[name].update(sha256=digest, object_key=key, bytes=len(content))
    (directory / "local_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return paths


def prepare_database(paths: dict[str, Path]) -> None:
    """Hydrate existing schema, with exact address matches corroborated by HDB footprints."""
    from collections import defaultdict
    from datetime import datetime, timezone

    import pandas as pd
    import psycopg2
    from psycopg2.extras import execute_values
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from minio import Minio
    from minio.error import S3Error

    from address_normalize import normalize_street
    from db_env import psycopg2_connect_dsn
    from models import SessionLocal, HdbAddressEnrichmentOnemap, HdbBuilding
    from ingestion import run_ingestion
    import ingest_hdb_property_information
    import ingest_hdb_rpi
    import ingest_hdb_buildings

    client = Minio(os.environ["MINIO_ENDPOINT"], access_key=os.environ["MINIO_ACCESS_KEY"],
                   secret_key=os.environ["MINIO_SECRET_KEY"], secure=False)
    for name, key in (
        ("resale", "raw/datagovsg/HDB_ResaleFlatPrices/HDBResale2017Onwards.csv"),
        ("buildings", "raw/datagovsg/HDB-data/HDBExistingBuilding.geojson"),
    ):
        try:
            client.stat_object("datasets", key)
        except S3Error as exc:
            if exc.code != "NoSuchKey":
                raise
            client.fput_object("datasets", key, str(paths[name]))

    catalogue = pd.read_csv(paths["properties"], dtype={"blk_no": str})
    property_keys = {
        f"{str(r.blk_no).strip().upper()} {normalize_street(str(r.street))}"
        for r in catalogue.itertuples()
    }
    cached = pd.read_csv(paths["addresses"], dtype=str).fillna("")
    cached.columns = [c.strip().lower() for c in cached.columns]
    aliases = {"postal": "postal_code", "road_name": "street", "latitude": "lat", "longitude": "lon"}
    cached = cached.rename(columns={k: v for k, v in aliases.items() if k in cached.columns})
    required = {"postal_code", "blk_no", "street"}
    if not required.issubset(cached.columns):
        raise ValueError(f"Address export missing {required - set(cached.columns)}; columns={list(cached.columns)}")
    postal_candidates = defaultdict(set)
    for row in cached.itertuples():
        postal = str(row.postal_code).strip().zfill(6)
        block = str(row.blk_no).strip().upper()
        street = normalize_street(str(row.street))
        if len(postal) == 6 and postal.isdigit() and f"{block} {street}" in property_keys:
            postal_candidates[postal].add((block, street))

    with paths["buildings"].open() as handle:
        features = json.load(handle)["features"]
    buildings = defaultdict(list)
    street_codes = defaultdict(set)
    for feature in features:
        props = feature["properties"]
        postal = str(props.get("POSTAL_COD", "")).strip().zfill(6)
        block = str(props.get("BLK_NO", "")).strip().upper()
        code = str(props.get("ST_COD", "")).strip()
        if len(postal) != 6 or not postal.isdigit() or postal == "000000":
            continue
        buildings[postal].append((block, code, feature["geometry"]))
        for cached_block, street in postal_candidates.get(postal, set()):
            if cached_block == block and code:
                street_codes[code].add(street)

    rows = []
    ambiguous = 0
    for postal, parts in sorted(buildings.items()):
        candidates = set()
        for block, code, _geometry in parts:
            for street in street_codes.get(code, set()):
                if len(street_codes[code]) == 1 and f"{block} {street}" in property_keys:
                    candidates.add((block, street))
            for cached_block, street in postal_candidates.get(postal, set()):
                if cached_block == block:
                    candidates.add((block, street))
        if len(candidates) != 1:
            ambiguous += 1
            continue
        block, street = next(iter(candidates))
        point = unary_union([shape(g) for b, _c, g in parts if b == block]).centroid
        if not (1.1 < point.y < 1.5 and 103.5 < point.x < 104.1):
            raise ValueError(f"Out-of-bounds building centroid for {postal}")
        rows.append({"query_sent": f"{block} {street}", "postal_code": postal,
                     "latitude": point.y, "longitude": point.x})
    # Never arbitrarily choose between postal codes for the same canonical address.
    key_counts = pd.Series([r["query_sent"] for r in rows]).value_counts()
    rows = [r for r in rows if key_counts[r["query_sent"]] == 1]
    if len(rows) < 8000:
        raise RuntimeError(f"Too few validated residential address matches: {len(rows)}")
    print(f"Validated {len(rows):,} addresses; {ambiguous:,} unmatched/non-residential postals omitted", flush=True)

    db = SessionLocal()
    try:
        existing = {r.query_sent: r for r in db.query(HdbAddressEnrichmentOnemap).all()}
        for row in rows:
            item = existing.get(row["query_sent"])
            if item is None:
                item = HdbAddressEnrichmentOnemap(query_sent=row["query_sent"])
                db.add(item)
            for key in ("postal_code", "latitude", "longitude"):
                setattr(item, key, row[key])
            item.results_count = 1
            item.attempt_count = 1
            item.last_attempt_at = datetime.now(timezone.utc)
            item.raw_response = json.dumps({"source": "data.gov.sg HDB footprint + archived OneMap street mapping",
                                            "address_export_commit": ADDRESS_COMMIT, "result": row})
        db.commit()
        run_ingestion(db)
        need_buildings = db.query(HdbBuilding).count() == 0
        address_ids = {r.query_sent: r.id for r in db.query(HdbAddressEnrichmentOnemap).all()}
    finally:
        db.close()
    if need_buildings:
        ingest_hdb_buildings.main()
    for module, name in ((ingest_hdb_property_information, "properties"), (ingest_hdb_rpi, "rpi")):
        if module.main(["--source", str(paths[name]), "--project-root", str(ROOT)]) != 0:
            raise RuntimeError(f"Failed to ingest {name}")

    frame = pd.read_csv(paths["resale"], dtype={"block": str})
    pairs = frame[["block", "street_name"]].drop_duplicates()
    values = []
    for block, street in pairs.itertuples(index=False, name=None):
        key = f"{block.strip().upper()} {normalize_street(street)}"
        values.append((block, street, key, address_ids.get(key)))
    with psycopg2.connect(psycopg2_connect_dsn(os.environ["DATABASE_URL"])) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE local_address_links (block text, street text, canonical text, address_id integer) ON COMMIT DROP")
            execute_values(cur, "INSERT INTO local_address_links VALUES %s", values)
            cur.execute("""UPDATE hdb_resale_transactions t
                SET block_street = a.canonical, enriched_addr_id = a.address_id
                FROM local_address_links a WHERE t.block = a.block AND t.street_name = a.street""")
            cur.execute("SELECT COUNT(*), COUNT(enriched_addr_id) FROM hdb_resale_transactions")
            total, linked = cur.fetchone()
    address_frame = pd.DataFrame(rows).rename(columns={"query_sent": "block_street", "latitude": "lat", "longitude": "lon"})
    address_frame.to_parquet(ROOT / "data" / "local_validated_addresses.parquet", index=False)
    report = {"property_catalogue_rows": len(catalogue), "validated_addresses": len(rows),
              "resale_transactions": total, "linked_transactions": linked,
              "linked_fraction": linked / total if total else 0,
              "footprints": len(features), "omitted_postals": ambiguous}
    (ROOT / "data" / "local_bootstrap_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Database ready: {total:,} resale rows, {linked:,} with validated addresses", flush=True)


def train_and_publish(paths: dict[str, Path]) -> None:
    """Train from local public files; reserve the last six months for temporal validation."""
    from datetime import datetime, timezone

    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, mean_squared_error, r2_score

    from address_normalize import normalize_street
    from modelling.config.feature_sets import get_feature_set
    from modelling.config.model_specs import get_model_spec
    from modelling.models.pipelines import build_full_pipeline
    from modelling.targets.rpi_normalization import (
        align_rpi_index_to_months, adjust_prices_to_baseline100,
        validate_rpi_alignment, TARGET_NORMALIZATION_RPI_BASELINE_100,
    )
    from models import SessionLocal, ModelVersion
    from services import model_store

    raw = pd.read_csv(paths["resale"], dtype={"block": str})
    raw["block_street"] = raw["block"].str.strip().str.upper() + " " + raw["street_name"].map(normalize_street)
    addresses = pd.read_parquet(ROOT / "data" / "local_validated_addresses.parquet")
    raw = raw.merge(addresses[["block_street", "lat", "lon"]], on="block_street", validate="many_to_one")
    latest = pd.Period(raw["month"].max(), freq="M")
    raw = raw[raw["month"] >= str(latest - 59)].sort_values("month").reset_index(drop=True)
    for column in ("floor_area_sqm", "resale_price"):
        raw[column] = pd.to_numeric(raw[column], errors="raise")
    raw = raw[(raw["resale_price"] > 0) & (raw["floor_area_sqm"] > 0)].reset_index(drop=True)
    rpi = pd.read_csv(paths["rpi"]).rename(columns=lambda c: c.lower().strip())
    indexes = align_rpi_index_to_months(raw["month"], rpi)
    validate_rpi_alignment(indexes, context="local training")
    adjusted = adjust_prices_to_baseline100(raw["resale_price"], indexes)
    cutoff = str(latest - 5)
    train_mask = (raw["month"] < cutoff).to_numpy()
    if train_mask.sum() < 10000 or (~train_mask).sum() < 1000:
        raise RuntimeError("Insufficient rows for chronological train/test split")

    fs = get_feature_set(ROOT, "baseline_v1")
    spec = get_model_spec(ROOT, "lightgbm")
    spec.estimator.set_params(n_estimators=400, learning_rate=0.05, num_leaves=63,
                              min_child_samples=30, reg_lambda=5.0, n_jobs=2)
    pipeline = build_full_pipeline(fs, spec, ROOT)
    print(f"Training LightGBM: {train_mask.sum():,} rows; temporal holdout: {(~train_mask).sum():,} rows ({cutoff} onward)", flush=True)
    pipeline.fit(raw.loc[train_mask], adjusted[train_mask])
    predictions = pipeline.predict(raw.loc[~train_mask]) * indexes[~train_mask] / 100.0
    truth = raw.loc[~train_mask, "resale_price"].to_numpy()
    scores = {"rmse": float(np.sqrt(mean_squared_error(truth, predictions))),
              "mae": float(mean_absolute_error(truth, predictions)),
              "r2": float(r2_score(truth, predictions)),
              "mape": float(mean_absolute_percentage_error(truth, predictions))}
    print(f"Temporal holdout metrics: {json.dumps(scores)}", flush=True)
    if scores["r2"] < 0.8 or scores["mape"] > 0.2 or not np.isfinite(predictions).all():
        raise RuntimeError("Model did not pass local validation; nothing published")
    print(f"Refitting validated configuration on {len(raw):,} available rows", flush=True)
    pipeline.fit(raw, adjusted)
    run = "local_lightgbm_baseline__" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "modelling" / "outputs" / "local_bootstrap" / run
    out.mkdir(parents=True)
    joblib.dump(pipeline, out / "model.pkl", compress=3)
    manifest = {"feature_set_id": "baseline_v1", "model_id": "lightgbm", "experiment_id": run,
                "target_normalization": TARGET_NORMALIZATION_RPI_BASELINE_100,
                "purpose": "Standalone local development baseline trained on public HDB transactions",
                "data_start": raw["month"].min(), "data_end": raw["month"].max(),
                "address_source": ADDRESS_URL, "local_development_model": True}
    metrics = {"feature_set": "baseline_v1", "model": "lightgbm", "experiment_id": run,
               "target_normalization": TARGET_NORMALIZATION_RPI_BASELINE_100,
               "test_metrics": scores, "n_train": int(train_mask.sum()), "n_test": int((~train_mask).sum()),
               "refit_rows": len(raw), "validation": "chronological final six months; refit after scoring",
               "training_context": {"target_normalization": TARGET_NORMALIZATION_RPI_BASELINE_100,
                                     "test_start": cutoff, "local_development_model": True}}
    config = {"experiment_id": run, "feature_set_id": "baseline_v1", "model_id": "lightgbm",
              "random_state": 42, "training_source": "public CSV + validated footprint centroids"}
    for filename, value in (("manifest.json", manifest), ("metrics.json", metrics), ("config.json", config)):
        (out / filename).write_text(json.dumps(value, indent=2) + "\n")
    prefix = f"dev/valuation/experiments/{run}"
    for filename in ("model.pkl", "manifest.json", "metrics.json", "config.json"):
        model_store.put_file_if_absent(f"{prefix}/{filename}", out / filename)
    key = f"{prefix}/model.pkl"
    # Use the existing registry pointer, which FastAPI reloads on startup.
    with SessionLocal() as db:
        db.query(ModelVersion).filter(ModelVersion.env == "dev").update({"is_production": False})
        db.add(ModelVersion(env="dev", object_key=key, experiment_id=run,
                            feature_set_id="baseline_v1", model_id="lightgbm", rmse=scores["rmse"],
                            is_production=True, promoted_at=datetime.now(timezone.utc)))
        db.commit()
    (ROOT / "data" / "local_model_report.json").write_text(json.dumps({"model_object_key": key, **metrics}, indent=2) + "\n")
    print(f"Published local model: models/{key}; restart the backend to load it", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    require_local_database()
    paths = download_assets()
    if args.download_only:
        return
    prepare_database(paths)
    train_and_publish(paths)


if __name__ == "__main__":
    main()
