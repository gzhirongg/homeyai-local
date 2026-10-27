# Environment Variables Reference

Last updated: 2026-05-20

## Shared Config

| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE_URL_ADMIN | (unset) | **Preferred** full admin Postgres URL for FastAPI, Alembic, and admin scripts. When set, code prefers this over `DATABASE_URL`. Supports `${VAR}` expansion in `.env` (see `backend/scripts/db_env.py`). |
| DATABASE_URL | (unset) | Legacy full admin URL (e.g. assembled by Docker Compose from `ADMIN_DB_*` + `DB_HOST`) used when `DATABASE_URL_ADMIN` is unset. |
| ADMIN_DB_USER | admin | PostgreSQL admin username (Postgres containers; compose `DATABASE_URL` when explicit URLs are unset) |
| ADMIN_DB_PASSWORD | password123 | PostgreSQL admin password |
| DB_NAME | real_estate_db | Database name (change to real_estate_dev_db for Mode C) |
| URA_API_KEY | (required) | Urban Redevelopment Authority API key |
| MINIO_ROOT_USER | admin | MinIO root credentials |
| MINIO_ROOT_PASSWORD | password123 | MinIO root credentials |

## Mode-Specific Config

| Variable | Mode A | Mode B | Mode C |
|----------|--------|--------|--------|
| DB_HOST | db | `${REMOTE_VM_IP}` | `${REMOTE_VM_IP}` |
| DB_INNER_PORT | 5432 | 5432 | 5433 |
| DB_NAME | real_estate_db | real_estate_db | real_estate_dev_db |
| MINIO_HOST | minio | `${REMOTE_VM_IP}` | `${REMOTE_VM_IP}` |
| MINIO_INNER_PORT | 9000 | 9000 | 9000 |
| PREFECT_API_URL | http://prefect-server:4200/api | As needed | Dev compose defaults from `REMOTE_VM_IP` on port 4201 when unset (see `docker-compose.dev.yml`) |
| NEXT_PUBLIC_API_URL | (empty) | http://localhost:8000 | http://localhost:8000 |
| NEXT_PUBLIC_REMOTE_VM_IP | `${REMOTE_VM_IP}` | `${REMOTE_VM_IP}` | `${REMOTE_VM_IP}` |

## Optional

| Variable | Default | Description |
|----------|---------|-------------|
| REMOTE_VM_IP | (unset) | **Single VM address** (Tailscale IP, public IP, or hostname) everyone uses — drives DB/MinIO host in dev modes, admin health (`NEXT_PUBLIC_REMOTE_VM_IP`), CORS `http://<REMOTE_VM_IP>:3000` and `:8000`, and Prefect URL defaults in dev compose/scripts. |
| PUBLIC_DOMAIN | (unset) | **Production HTTPS hostname** for Caddy (e.g. `homeyai.duckdns.org`). DNS A record must point to the VM public IP. Required when running the `caddy` service in `docker-compose.prod.yml`. |
| CORS_EXTRA_ORIGINS | (unset) | Comma-separated full browser Origin URLs merged into the FastAPI CORS allowlist (e.g. `https://homeyai.duckdns.org`). |
| BACKEND_INTERNAL_ORIGIN | http://backend:8000 | Next.js server-side `/api` proxy target inside Docker Compose. Do not change unless the backend service name or port changes. |
| NEXT_PUBLIC_REMOTE_VM_IP | (unset) | Same value as `REMOTE_VM_IP`, exposed to the Next.js client for the admin health page. Docker Compose sets this from `REMOTE_VM_IP`; for local Next dev, export or use `.env.local`. |
| MODEL_ENV | prod | **Object key prefix** for the MinIO `models` bucket: training uploads, experiment catalog (`/valuation/experiments/…`), admin **Publish live**, and DB registry all use `models/<MODEL_ENV>/…`. Use the **same** value everywhere the API, workers, and upload CLIs run, or listings and promote will look empty or reject keys. Must match Tailscale/firewall reachability to **`MINIO_ENDPOINT`** from that process. |
| VALUATION_MODEL_OBJECT_KEY | (unset) | **Required for `/api/valuation`:** full object key in the MinIO `models` bucket for `model.pkl`, e.g. `dev/valuation/artifacts/xgboost__mrt__20260101T000000Z__20260115T120000Z/model.pkl`. After upload, the CLI prints the exact value to set. |
| VALUATION_METRICS_OBJECT_KEY | (unset) | Optional override for `metrics.json` when it is not stored next to the model object (defaults to sibling `metrics.json` derived from the model key). |
| MINIO_ENDPOINT | minio:9000 | MinIO S3 endpoint (host:port); dev compose sets from `MINIO_HOST` + `MINIO_INNER_PORT` |
| MINIO_ACCESS_KEY | admin | MinIO access key |
| MINIO_SECRET_KEY | password123 | MinIO secret key |
| APP_VERSION | dev | Git tag or describe output for build metadata |
| GIT_COMMIT | unknown | Short git SHA for build metadata |
| HOMEYAI_MODELLING_DIR | (unset) | Absolute path to the repo `modelling/` directory inside the API process. **Docker:** compose sets `/modelling` with a bind mount for optional files under `modelling/outputs/` (training QA reports, SHAP PNG). **Local uvicorn:** unset — resolved from `<repo>/modelling` next to `backend/`. Experiment catalog, metrics comparison, and serving use **MinIO** (`MODEL_ENV` / `VALUATION_MODEL_OBJECT_KEY`). |
| DATABASE_URL_READ_ONLY | (unset) | Optional full read-only Postgres URL for modelling. If unset, `modelling/training_db.py` builds `postgresql://…` from `READ_ONLY_DB_USER`, `READ_ONLY_DB_PASSWORD`, `DB_HOST` or `REMOTE_VM_IP`, `DB_PORT` or `DB_INNER_PORT`, and `DB_NAME`. See `backend/scripts/sql/create_ml_readonly_role.sql`. |
| READ_ONLY_DB_USER | (unset) | Read-only role login (e.g. `ml_training_readonly`); POSIX name (safe for `export` / `source .env`) |
| READ_ONLY_DB_PASSWORD | (unset) | Password for the read-only role |
| PREFECT_MRT_ROUTING_DEPLOYMENT_ID | (unset) | Optional UUID shortcut for `/api/admin/trigger-mrt-routing` if deployment name lookup is unavailable |
| PREFECT_MRT_FLOW_NAME | hdb-mrt-routing | Flow name slug for Prefect REST `GET …/deployments/name/{flow}/{deployment}` |
| PREFECT_MRT_DEPLOYMENT_NAME | mrt-routing-default | Deployment name slug (matches `backend/prefect.yaml`) |
| PREFECT_API_KEY | (unset) | Bearer token when Prefect server requires auth (Cloud / locked-down installs) |
| PREFECT_API_VERSION | (unset) | Optional `X-PREFECT-API-VERSION` header value |
| PREFECT_TRAINING_FLOW_NAME | homeyai-model-train | Flow name slug for Prefect REST `GET …/deployments/name/{flow}/{deployment}` when triggering `/api/admin/model/train` |
| PREFECT_TRAINING_DEPLOYMENT_NAME | model-train-default | Deployment name slug for the training flow |
| PREFECT_MODEL_TRAINING_DEPLOYMENT_ID | (unset) | Optional UUID shortcut for training if deployment name lookup is unavailable (same pattern as `PREFECT_MRT_ROUTING_DEPLOYMENT_ID`) |
| PREFECT_TRAINING_BATCH_FLOW_NAME | homeyai-model-train-batch | Flow name for `/api/admin/model/train/batch` |
| PREFECT_TRAINING_BATCH_DEPLOYMENT_NAME | model-train-batch-default | Deployment name for the batch training flow |
| PREFECT_MODEL_TRAINING_BATCH_DEPLOYMENT_ID | (unset) | Optional UUID shortcut for batch training deployment lookup |
| MODAL_ENABLED | true | When `false`, Prefect `homeyai-model-train` runs training on the worker (snapshot → fit → upload to MinIO experiments) instead of invoking Modal. |
| MODAL_TOKEN_ID | (unset) | Modal API token id for workers calling `modal.Function.from_name` (set on Prefect worker container / VM env). |
| MODAL_TOKEN_SECRET | (unset) | Modal API token secret (pair with `MODAL_TOKEN_ID`). Prefer secrets manager over plain `.env` in production. |
| SNAPSHOT_MAX_AGE_HOURS | 24 | When `dataset_version` is unset, reuse an existing v2 dataset under `datasets/training_datasets/v2/<key>/` if manifest age ≤ this (hours), **and** content checks pass (`max_tx_month`, column schema). |
| TRAINING_FORCE_DATASET_REBUILD | false | When `1`/`true`/`yes`, skip v2 cache hits and rebuild + overwrite the dynamic dataset for that `feature_set_id`. **After fixes to estate-maturity or masterplan land-use merges**, set this once and re-run affected experiments so MinIO drops inflated `row_count` Parquets (Modal train logs should show ~150k–200k eligible resale rows for a 5y window, not tens of millions). Cancel in-flight training that used corrupt caches. |
| TRAINING_SKIP_ELIGIBLE_ROW_CHECK | false | When `1`/`true`/`yes`, **skip** the check that baseline Parquet row count equals `get_training_window_summary` `n_eligible_tx` during [`build_training_dataframe`](../../modelling/data/dataset_builder.py). Default **off** — only for rare debugging. Row-count preservation after pillar merges is still enforced. |
| MODAL_PARQUET_PASSTHROUGH_MAX_BYTES | 95000000 | Max Parquet size (bytes) the Prefect worker sends to Modal via gRPC; larger datasets force Modal to read input from MinIO. Stay below Modal ~100MB gRPC payload limit. Set `0` or negative to **disable** passthrough (always MinIO read on Modal). |
| HOMEYAI_MODAL_PROBE_POSTGRES | false | When `1`/`true`/`yes`, Modal training runs a TCP probe to Postgres before fitting (optional fail-fast for DB-heavy experiments). Default off so secrets with `DATABASE_URL_READ_ONLY` do not block Modal when DB is Tailscale-only. |
| TRAINING_CV_N_JOBS | (unset) | Overrides joblib parallelism for hyperparameter search (`GridSearchCV` / `RandomizedSearchCV`) and `permutation_importance` in [`modelling/runners/train_core.py`](../../modelling/runners/train_core.py). When unset: **`-1`** on Prefect workers / CLI; **`1`** on Modal when `HOMEYAI_LOG_SOURCE=MODAL` (the Modal app sets this automatically). POI-heavy stacks on Modal still need **`DATABASE_URL_READ_ONLY`** in `homeyai-training-secrets` and a DB URL reachable from **Modal cloud egress** (not Tailscale-only); the training image includes **`psycopg2-binary`** for `poi_locations` reads. |
| HOMEYAI_FEATURE_SELECTION_POLICY | advisory_only | Pre-fit variance / correlation / MI diagnostics: **`advisory_only`** (default) writes JSON/plots only; **`apply_recommended_drops`** (alias **`apply`**) removes failing **numeric** registry columns from the in-memory `FeatureSet` before pipeline build when safe (minimum numeric floor). CLI: `run_experiment.py --feature-selection-policy apply`. Standalone `run_feature_selection.py --apply-drops` emits `features_dropped.json` without fitting. **Prefect/API:** `POST /api/admin/model/train` and `/train/batch` accept optional JSON **`feature_selection_policy`** (`advisory_only` \| `apply`) so Modal secrets need not flip between A/B batches (requires redeployed Modal app + Prefect flows). POI feature sets use coord-valid rows **only for diagnostics**. For fair A/B vs historical runs, pin **`dataset_version`** on the batch body and keep **`TRAINING_FORCE_DATASET_REBUILD=0`** on the worker so both batches hit the same cached Parquet. |
| TRAINING_SNAPSHOT_MIN_ROWS | 10000 | Hard fail when a resolved dataset manifest `row_count` is below this. Set `0` to disable. |
| PREFECT_TRAINING_USE_GPU_DEFAULT | false | When a train/batch run omits `use_gpu`, this env selects T4 vs CPU **only for experiments with `modal_profile=cpu`**. **`modal_profile=l40s`** or **`t4`** on the experiment overrides this for that job (`resolve_modal_train_fn`). |
| MINIO_SECURE | false | When `true`, modelling MinIO clients use HTTPS/TLS to `MINIO_ENDPOINT`. Set for TLS-terminated endpoints. |

### Modelling MinIO object layout (`HOMEYAI_MINIO_SOURCES_JSON`)

Secrets stay in **`MINIO_*`**, **`DATABASE_URL_READ_ONLY`**, and related DB passwords. Bucket names and object keys for optional parquet sidecars (MRT snapshot export, macros, resale training mirror) live in **JSON**:

| Variable | Default | Description |
|----------|---------|-------------|
| HOMEYAI_MINIO_SOURCES_JSON | (unset: use `minio_training_sources.local.json` **if present**, else `minio_training_sources.sample.json`) | Absolute path overrides the default resolution order. Manifest contains `default_bucket`, `objects`, optional `training_snapshots_prefix`. **`modelling/config/minio_training_sources.local.json`** can be committed so dev and prod share the same canonical object keys (e.g. populated via `ingest_training_parquets_to_minio.py --update-manifest`). |

Training quality gate thresholds (`modelling/config/training_quality_gates.yml`): override the file path with **`HOMEYAI_DQ_CONFIG`**, or a single YAML leaf with **`HOMEYAI_DQ_<section>__<key>`** using a **double underscore** between section and key (e.g. `HOMEYAI_DQ_mrt__snapshot_hit_rate_min=0.80`; section/key lowercased).

One-shot disk→MinIO upload for **eligible legacy files only** (MRT parquet, macro artefacts, `data/pois/**`; not resale ingestion): `PYTHONPATH=. python modelling/runners/ingest_training_parquets_to_minio.py`. Postgres remains the canonical training path; `--from-parquet-minio` on modelling CLIs selects the manifest layout instead.

### OneMap token file (not an env var)

The backend caches the OneMap API access token in **`backend/.onemap_token_v2.json`** after the first successful auth. This file is **gitignored** and must exist only on your machine (or in your deployment secrets), never committed.

### ML training (read-only connection)

| Variable | Description |
| --- | --- |
| `ML_TRAINING_FALLBACK_LATERAL_LIMIT` | If the read-only role cannot `SELECT` `hdb_mrt_features_pit_snapshot`, set to a positive integer (e.g. `80000`) to load only the **newest N** resale rows and compute PIT MRT via `hdb_mrt_features_at()` per row. Prefer granting snapshot access ([`backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql`](../../backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql)) for full history + fast loads. |
| `ML_TRAINING_USE_MRT_FUNCTION` | If `1` / `true`, always uses `hdb_mrt_features_at()` for **all** rows (very slow on full history). Use only for small experiments. |

### POI ingest and pre-compute (admin connection)

Scripts: [`backend/scripts/ingest_poi_assets.py`](../../backend/scripts/ingest_poi_assets.py), [`build_poi_features.py`](../../backend/scripts/build_poi_features.py). Resolution is implemented in [`backend/scripts/db_env.py`](../../backend/scripts/db_env.py) (same idea as `build_mrt_pit_snapshot.py`). **Do not use the read-only training role** for these writes.

| Variable | Description |
| --- | --- |
| `DATABASE_URL_ADMIN` | **Preferred** full admin URL. If set, used before `DATABASE_URL` (see `backend/scripts/db_env.py`, `backend/models.py`, Alembic `env.py`). `${VAR}` placeholders in `.env` are expanded after load. |
| `DATABASE_URL` | Legacy full admin URL when `DATABASE_URL_ADMIN` is unset. |
| `ADMIN_DB_USER`, `ADMIN_DB_PASSWORD` | With `DB_HOST` or `REMOTE_VM_IP`, `DB_INNER_PORT` or `DB_PORT`, and `DB_NAME`, builds the connection URL if neither explicit admin URL is set. |
| `PGUSER`, `PGPASSWORD`, `PGHOST`, `PGDATABASE` | libpq-style alternative when explicit URLs and `ADMIN_DB_*` are not used; optional `PGPORT` (default `5432`). |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | Same as other ingest jobs; objects land under `datasets/pois/`. |

**Read path for modelling:** `DATABASE_URL_READ_ONLY` / `READ_ONLY_DB_*` (see above) is used to detect and load `poi_locations` during sweeps when the table is populated. See [`docs/knowledge/poi-data-km.md`](../knowledge/poi-data-km.md).

### Valuation API inference (process-local TTL caches)

Used by `/api/valuation` helpers in `modelling/` (RPI lookups, Master Plan land-use GeoJSON from MinIO). Safe defaults refresh every few minutes unless overridden.

| Variable | Default | Description |
| --- | --- | --- |
| `HOMEYAI_RPI_DB_CACHE_TTL_SEC` | `300` | TTL (seconds) for cached `hdb_resale_price_index` levels per Postgres URL (`load_rpi_levels_database`). |
| `HOMEYAI_RPI_SERIES_FALLBACK_CACHE_TTL_SEC` | `300` | TTL for the MinIO / read-only Postgres / API fallback chain in `load_rpi_index_series` when no explicit DB URL resolves. |
| `HOMEYAI_MASTERPLAN_LANDUSE_CACHE_TTL_SEC` | `3600` | TTL for parsed GeoDataFrame per `(bucket, object_key)` in `compute_land_use_row_from_minio`. Also applies to per-coordinate masterplan scalar row cache. |
| `HOMEYAI_MACRO_CACHE_TTL_SEC` | `300` | TTL for macro MinIO parquet/CSV blobs (`macro_sentiment._cached_minio_dataframe`). |

Diagnostics: [`backend/scripts/sql/valuation_latency_checks.sql`](../../backend/scripts/sql/valuation_latency_checks.sql). Latency benchmark: `python backend/scripts/benchmark_valuation_latency.py --base-url http://localhost:8000`. Snapshot coverage: `python backend/scripts/report_mrt_snapshot_completeness.py`.

## Modes Explained

The project supports three operational modes:

**Mode A (Production on VM):** Services run on the Oracle Cloud VM via `docker-compose.prod.yml`. PostgreSQL and MinIO run on the same host. DB_HOST resolves to the internal service name `db`, and MINIO_HOST resolves to `minio`. Set `PUBLIC_DOMAIN` for Caddy HTTPS; leave `NEXT_PUBLIC_API_URL` empty so the browser uses same-origin `/api` proxied by Next.js to `BACKEND_INTERNAL_ORIGIN`. Set `CORS_EXTRA_ORIGINS=https://<PUBLIC_DOMAIN>`. Docker Compose **project name** (usually the directory name) prefixes named volumes (e.g. `*_postgres_data`). Recreating containers does **not** remove those volumes; use the same compose working directory or set `COMPOSE_PROJECT_NAME` so you always attach the same volume. If tables look empty, list volumes (`docker volume ls | grep postgres`) and run [`scripts/diagnose_postgres_volumes.sh`](../../scripts/diagnose_postgres_volumes.sh) on the VM (`COMPOSE_DIR=/path/to/repo ./scripts/diagnose_postgres_volumes.sh`).

**Mode B (Local pointing at prod DB):** For verification only. You run the frontend and backend locally (e.g., on your laptop), but they connect to the production PostgreSQL and MinIO on the VM (`REMOTE_VM_IP` / Tailscale) via Tailscale VPN. Use this to sanity-check production data or debug connectivity. Exercise caution to avoid modifying production data.

**Mode C (Local pointing at dev DB):** Recommended for daily development. Similar to Mode B, but uses a separate development database (real_estate_dev_db) on port 5433. Keeps development work isolated from production data. Uses the centralised Prefect dev server (port 4201) for pipeline testing. Start with `docker compose -f docker-compose.dev.yml up --build`.
