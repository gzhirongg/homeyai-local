# KM: POI data — where it is ingested and why

**Audience:** developers and ML operators maintaining HDB resale features that use schools, malls, parks, markets, supermarkets, and park connectors.

**Related:** [ADR 001: POI ingestion](../adr/001-poi-ingestion.md) · [`modelling/features/poi_distancing.py`](../../modelling/features/poi_distancing.py) · [`backend/scripts/ingest_poi_assets.py`](../../backend/scripts/ingest_poi_assets.py) · [`backend/scripts/build_poi_features.py`](../../backend/scripts/build_poi_features.py)

---

## 1. Summary table (where data lands)

| Layer | Location | What is stored | Who writes | Who reads |
|-------|-----------|----------------|------------|-----------|
| **Source of truth (human)** | Repo `data/pois/` (seven files; see [`data/pois/README.md`](../../data/pois/README.md)) | Original CSV / GeoJSON from NParks, NEA, internal lists | Data owner / analyst | `ingest_poi_assets.py` |
| **Object storage (audit + DR)** | MinIO bucket `datasets`, prefix `pois/<filename>` | Byte-identical copies of each source file | `ingest_poi_assets.py` (admin credentials) | Operators re-ingesting; optional download for offline audit |
| **Structured points (query + ML input)** | Postgres `public.poi_locations` | One row per POI point: `poi_type`, `name`, `lat`, `lon`, optional `valid_from` / `valid_to`, `source_file`, `ingested_at` | `ingest_poi_assets.py` | `load_poi_tables_from_db()` in modelling; ad-hoc SQL / GIS |
| **Pre-computed address scalars** | Postgres `public.hdb_poi_features` | One row per `hdb_address_enrichment_onemap.id`: distance/count/gravity columns | `build_poi_features.py` | Future loaders / analytics; optional join for serving |
| **Training-time frame (ephemeral)** | In-memory `pandas` during `engineer_poi_frame` | Full POI numeric pack from [`POI_NUMERIC_FEATURES`](../../modelling/features/poi_distancing.py) | `run_experiment` / sweep | sklearn pipelines |

**Slim pack (`poi_amenity_v2`):** [`features/poi_amenity_v2.py`](../../modelling/features/poi_amenity_v2.py) exposes seven school/hawker/mall numerics. Training runs that use `use_db=True` may **reuse** `hdb_poi_features.dist_nearest_any_school`, `within_1km_any_pri_school`, `within_1km_2km_pri_school`, and `dist_nearest_mall` per `enriched_addr_id` instead of recomputing those scalars; see [`poi-amenity-v2-roadmap.md`](poi-amenity-v2-roadmap.md).

---

## 2. Justification by destination

### MinIO (`datasets/pois/`)

- **Durability:** Postgres rows can be rebuilt from MinIO objects if the DB is restored without POI tables.
- **Provenance:** Object key includes original filename; matches `poi_locations.source_file` for traceability.
- **Separation:** Keeps large GeoJSON out of migration files and keeps the application DB focused on queryable rows.

### Postgres `poi_locations`

- **Query performance:** GiST index on `ST_SetSRID(ST_MakePoint(lon, lat), 4326)` supports spatial filters without shipping GeoJSON to every training machine.
- **Single normalised schema:** All POI kinds share one table with `poi_type` discriminator (`school_top20`, `school_any`, `mall`, `supermarket`, `park`, `market`, `pcn`).
- **Temporal readiness:** `valid_from` / `valid_to` exist for future point-in-time POI filtering (not yet populated from external change feeds).

### Postgres `hdb_poi_features`

- **Cost:** BallTree over tens of thousands of PCN vertices per training run is avoided when features are pre-materialised per address.
- **Consistency:** Same formulas as [`append_poi_features`](../../modelling/features/poi_distancing.py) (single implementation path in code).
- **Serving / analytics:** Read-only role can `SELECT` for dashboards without `geopandas` on the API host.

### Local `data/pois/` (still supported)

- **Offline / CI:** File-based `load_poi_tables()` needs no DB.
- **Parquet training:** `hdb_block_coords.csv` remains the merge key when coordinates are not on the resale frame.

---

## 3. Modelling integration

| Concern | Detail |
|---------|--------|
| **Feature module** | [`modelling/features/poi_distancing.py`](../../modelling/features/poi_distancing.py) — `POI_NUMERIC_FEATURES`, `load_poi_tables`, `load_poi_tables_from_db`, `engineer_poi_frame`, `append_poi_features`. |
| **Feature sets** | [`modelling/config/feature_sets.py`](../../modelling/config/feature_sets.py) — `poi_distancing`, `mrt_pit__poi_distancing`. |
| **Sweep / quality** | [`modelling/runners/run_model_sweep.py`](../../modelling/runners/run_model_sweep.py), [`training_data_quality.py`](../../modelling/runners/training_data_quality.py) — if `poi_locations` is non-empty (read-only DB URL), POI loads from DB; else requires `data/pois/hdb_block_coords.csv` for file-backed POI when coords must be merged. |
| **Dependencies** | GeoJSON path: install [`modelling/requirements-poi.txt`](../../modelling/requirements-poi.txt) (`geopandas`). |
| **Docker** | `docker-compose.yml` mounts `./data:/app/data:ro` so `data/pois/` is visible in the backend container at `/app/data/pois`. |

---

## 4. Operational sequence (happy path)

1. Place assets under `data/pois/` (see README there).
2. `cd backend && alembic upgrade head` (creates `poi_locations`, `hdb_poi_features`).
3. With **admin** DB credentials (``DATABASE_URL`` **or** ``ADMIN_DB_*`` + ``DB_HOST``/``REMOTE_VM_IP`` + ``DB_NAME``, **or** ``PGUSER``/``PGPASSWORD``/``PGHOST``/``PGDATABASE`` — see [`backend/scripts/db_env.py`](../../backend/scripts/db_env.py)) and MinIO env: `PYTHONPATH=.. python scripts/ingest_poi_assets.py` (use `--smoke` for 10 rows per file).
4. Same admin URL: `PYTHONPATH=.. python scripts/build_poi_features.py` (fills `hdb_poi_features`).
5. Train with read-only URL; sweep will prefer DB POIs when step 3 populated `poi_locations`.

---

## 5. Known limitations (KM)

- **Temporal leakage:** Unless `valid_from` / `valid_to` are backfilled from authoritative sources, historical transactions see today’s POI geometry.
- **`hdb_poi_features` vs training frame:** Pre-computed per-address table matches training BallTree helpers for shared columns; training still assembles the full stack in Python when using `engineer_poi_frame`.

---

## 6. Revision history

| Date | Change |
|------|--------|
| 2026-05-13 | Initial KM doc; aligned with ADR 001 and ingestion scripts. |
