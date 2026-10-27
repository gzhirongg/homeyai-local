# Data Storage Strategy

Last updated: 2026-05-13

## Overview

HomeyAI uses a hybrid storage architecture: PostgreSQL (with PostGIS) for real-time application data, and MinIO for datasets and ML artifacts. PostgreSQL handles transactional and spatial queries; MinIO stores raw data, processed datasets, and model binaries.

## MinIO Bucket Structure

Two buckets are created by `minio-init` on first run:

### datasets

| Folder | Purpose |
|--------|---------|
| raw/hdb_resale/ | Raw HDB resale CSVs from Data.gov.sg |
| raw/ura/ | URA API response dumps (planned) |
| raw/scraped/ | Web-scraped datasets (future) |
| processed/ | Cleaned, standardized Parquet files for training |
| pois/ | Raw POI CSV/GeoJSON (mirrors `data/pois/`); uploaded by [`backend/scripts/ingest_poi_assets.py`](../../backend/scripts/ingest_poi_assets.py) for audit and re-ingest |

**KM:** Rationale and lineage for POI storage are in [`docs/knowledge/poi-data-km.md`](../knowledge/poi-data-km.md) and [ADR 001](../adr/001-poi-ingestion.md).

### models

Object keys are prefixed by **`MODEL_ENV`** (e.g. `prod`, `dev`), not by a separate top-level bucket folder name.

| Prefix (under bucket `models`) | Purpose |
|--------------------------------|---------|
| `<MODEL_ENV>/valuation/experiments/<run_id>/` | **Canonical training runs** — `model.pkl`, `metrics.json`, `config.json`, diagnostics, plots. Listed by the admin models dashboard; source for **Publish live** (copied to `artifacts/`). |
| `<MODEL_ENV>/valuation/artifacts/<run_id>/` | **Published / serving** copies after promote; `VALUATION_MODEL_OBJECT_KEY` points at `…/model.pkl` here. |
| Legacy flat keys | Older layouts may still appear under `…/artifacts/` only; APIs check experiments first, then artifacts. |

## PostgreSQL Tables

| Table | Purpose |
|-------|---------|
| users | User accounts, roles, valuation limits |
| saved_properties | User-saved properties with predicted prices |
| hdb_resale_transactions | HDB resale transaction history for analytics |
| hdb_buildings | PostGIS table with HDB building footprint geometries |
| poi_locations | Normalised POI points (schools, malls, parks, …) with optional validity dates; populated by POI ingest |
| hdb_poi_features | Pre-computed POI distance/count/gravity scalars per OneMap-enriched address (`hdb_address_enrichment_onemap.id`) |

## Data Flow

```
External sources (Data.gov.sg, URA API, scrapers)
    |
    v
raw/ (CSV, JSON)
    |
    v
Processing (cleaning, normalization)
    |
    v
processed/ (Parquet)
    |
    +--------------------------------------------------+
    |                                                  |
    v                                                  v
PostgreSQL (active subset for UI)              ML training pipeline
    |
    v
Web application (queries, map rendering)
```

## ML Workflow

1. **Training**: Reads narrow Parquet from `datasets/training_datasets/v2/` (or Postgres via workers). Fits models and uploads artefacts to `models/<MODEL_ENV>/valuation/experiments/<run_id>/` (see [`training-pipeline.md`](training-pipeline.md)).
2. **Promotion**: Admin **Publish live** server-side-copies `experiments/<run_id>/` → `artifacts/<run_id>/`, then sets `VALUATION_MODEL_OBJECT_KEY` to the artifact `model.pkl`.
3. **Inference**: FastAPI loads the pinned `model.pkl` from MinIO (`MODEL_ENV` + `VALUATION_MODEL_OBJECT_KEY`). Models are cached in memory after first load.
4. **Real-time features**: Geospatial features (e.g. distance to MRT) are computed via PostGIS at request time and combined with model inputs for prediction.

**Local `modelling/experiments/`** in the repo is gitignored and used only for `--keep-local` dev runs and `backfill_experiments_to_minio.py` — not for production API catalog reads.

## Why This Architecture

**MinIO benefits**: Centralised model management, versioned training data, and S3-compatible object storage that scales to large datasets. Training pipelines can stream Parquet directly from MinIO without database round-trips.

**Honest assessment**: At current scale (under 1 GB total data), PostgreSQL could serve all needs alone. MinIO is chosen for future scalability, clearer separation between training data and serving data, and better handling of large model artifacts and bulk reads during training. The architecture is designed for growth rather than minimal footprint.

## Accessing MinIO

### Web Console

- **URL**: `http://<REMOTE_VM_IP>:9001` (via Tailscale; use `REMOTE_VM_IP` from `.env`)
- **Local**: `http://localhost:9001` when running Docker Compose locally
- **Credentials**: Use `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` from environment

### mc CLI Examples

```bash
# Alias for local MinIO
mc alias set homeyai http://localhost:9000 admin password123

# List buckets
mc ls homeyai/

# Upload to datasets
mc cp my_data.parquet homeyai/datasets/processed/

# Upload model to dev
mc cp my_model.pkl homeyai/models/dev/

# Download from datasets
mc cp homeyai/datasets/processed/hdb_resale_full.parquet ./
```
