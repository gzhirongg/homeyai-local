# ADR 001: POI ingestion, storage, and feature engineering

**KM companion (where data lands, justification, modelling links):** [`docs/knowledge/poi-data-km.md`](../knowledge/poi-data-km.md)

## Status

Accepted — implemented 2026-05-13.

## Context

Places-of-interest (POI) features for HDB resale modelling were read only from static files under `data/pois/` via [`modelling/features/poi_distancing.py`](../modelling/features/poi_distancing.py). Those files were not mounted in the default `docker-compose.yml` backend service, and there was no long-lived store in Postgres or MinIO. A reference Colab export ([`modelling/references/homeyai_distancing_to_areasv2_+_poi.py`](../modelling/references/homeyai_distancing_to_areasv2_+_poi.py)) contained plaintext database credentials (removed; use env vars only).

## Decision

1. **MinIO (`datasets/pois/<filename>`)** — Raw CSV/GeoJSON assets are uploaded for durability, audit, and re-ingest without relying on the host `data/` tree alone.

2. **Postgres `poi_locations`** — Normalised point rows with `poi_type`, optional `name`, `lat`, `lon`, optional `valid_from` / `valid_to`, `source_file`, and a GiST index on `ST_SetSRID(ST_MakePoint(lon, lat), 4326)` for spatial queries.

3. **Postgres `hdb_poi_features`** — Pre-computed POI scalars per `hdb_address_enrichment_onemap.id`, populated by [`backend/scripts/build_poi_features.py`](../backend/scripts/build_poi_features.py) using the same BallTree logic as training.

4. **Ingest script** — [`backend/scripts/ingest_poi_assets.py`](../backend/scripts/ingest_poi_assets.py) parses the seven configured assets, uploads to MinIO, replaces rows per `source_file` in `poi_locations`, optional `--smoke` cap, optional Prefect flow `ingest_poi_assets_flow`.

5. **Training paths** — File-based `load_poi_tables()` unchanged. Added `load_poi_tables_from_db(database_url)` and `engineer_poi_frame(..., use_db=True, database_url=...)`. Model sweep and training-data quality prefer DB POIs when `poi_locations` is populated (read-only training URL), else `hdb_block_coords.csv`.

6. **Docker** — `./data:/app/data:ro` on backend (plus dev compose) so `repo_root()/data/pois` resolves inside the container when code runs from `/app`.

7. **Feature changes** (breaking column set vs old `is_park_adjacent`-only stack):

   - Added continuous `dist_nearest_top20_school`, `dist_nearest_any_school`, `dist_nearest_park`.
   - Replaced sparse `is_park_adjacent` (50 m) with `is_park_200m` and `dist_nearest_park`.
   - PCN: sample line vertices every **100 m** in EPSG:3414 to cap BallTree size.
   - Gravity weights default: malls 1.2, schools 1.0, parks 1.0, markets 0.9 (override via `gravity_weights` kwarg).

8. **Dependencies** — `geopandas` remains in [`modelling/requirements-poi.txt`](../modelling/requirements-poi.txt); ingest/build scripts document installing it for GeoJSON paths.

## ML utility (expected)

- Strong: CBD / mall distance and density, school proximity (policy-sensitive in SG).
- Moderate: gravity scores, markets, park PCN distance.
- Weaker / noisy: airport distance, PCN as price driver.

## Drawbacks and risks

- **Temporal leakage**: POI snapshots are “as of ingest”; without `valid_from`/`valid_to` population from authoritative change logs, models trained on long history still see modern POIs for old transactions. Mitigation: backfill validity dates and filter POIs by transaction month (future PIT-style POI layer).

- **Collinearity**: `dist_cbd` correlates with mall density; use regularised / tree models.

- **Coverage**: Rows without geocoding are dropped before POI engineering; monitor the warning when &gt;5% of rows lack lat/lon.

- **Credential hygiene**: Never commit DB passwords; rotate any keys that were ever in the reference notebook.

## Migration

Apply Alembic revision `c2d3e4f5a6b7` (`poi_locations`, `hdb_poi_features`).

## Operational runbook

```bash
# 1. Place assets under data/pois/ (see POI_FILENAMES in poi_distancing.py)
# 2. Migrate
cd backend && alembic upgrade head

# 3. Ingest (admin DATABASE_URL)
PYTHONPATH=.. python scripts/ingest_poi_assets.py
# optional smoke:
PYTHONPATH=.. python scripts/ingest_poi_assets.py --smoke

# 4. Pre-compute address features
PYTHONPATH=.. python scripts/build_poi_features.py
```

## Alternatives considered

- **Parquet snapshot only** — Rejected for POI; DB upserts are simpler to query and diff than large parquet for static address keys.
- **Single combined `pois` table without MinIO** — Rejected; MinIO retains raw provenance for audits and disaster recovery.
