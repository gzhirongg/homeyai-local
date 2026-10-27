# HDB ↔ MRT enrichment runbook (temporal features)

Operational guide backing the Temporal MRT plan: validate Postgres, refresh station registry, enqueue OneMap routing in Prefect, then materialise the PIT snapshot for modelling.

---

## Prerequisites

- Postgres + PostGIS reachable from wherever you run commands.
- `DATABASE_URL` for **admin/schema** workloads (Alembic, ingest, Prefect routing script, snapshot build).
- OneMap credential env vars consumed by [`onemap_service.py`](../../backend/services/onemap_service.py) (`ONEMAP_EMAIL*` / `ONEMAP_PASSWORD*`).
- Prefect server URL in `PREFECT_API_URL` (must include `/api` suffix, same as `/api/health` probe).

**Alembic URL resolution**: [`backend/alembic/env.py`](../../backend/alembic/env.py) reads `DATABASE_URL` only — it does **not** auto-assemble from `ADMIN_DB_*` / `DB_HOST`. Export an explicit SQLAlchemy URL before `alembic upgrade`:

```bash
cd backend
export DATABASE_URL='postgresql://admin:PASSWORD@HOST:5433/real_estate_dev_db'
alembic current
alembic upgrade head
```

Target revisions:
- Split MRT + PIT function: **`f1a2b3c4d5e6`** (requires history through `e8f1a2b3c4d5`).
- **Batch PIT job tracker** (`mrt_pit_build_jobs`): **`a1b2c3d4e5f6`** (depends on `f1a2b3c4d5e6`).

---

## Ordering constraint (do not reorder)

```mermaid
flowchart LR
    A[Alembic upgrade head]
    B[ingest_mrt_temporal.py]
    C[Prefect mrt_routing_flow]
    A --> B
    B --> C
```

1. **`alembic upgrade head`** applies temporal/PIT migrations through `e8f1a2b3c4d5`, then splits MRT into **`mrt_physical_stations`** + **`mrt_station_lines`** (`f1a2b3c4d5e6`).
2. **`scripts/ingest_mrt_temporal.py`** wipes and reloads **`mrt_physical_stations`** + **`mrt_station_lines`**: without this, [`geospatial_service.py::get_nearby_mrts`](../../backend/services/geospatial_service.py) sees no `COMMITTED_*` / `ANNOUNCED_*` planned bucket → **planned candidates never route**.
3. **Prefect flow** fills [`hdb_mrt_routes`](../../backend/scripts/engineer_mrt_routing.py) (**pass 1**): up to **four** line-diverse physical MRT clusters within **2 km** (candidate pool includes operational + announced/planned pit buckets; `UNKNOWN` excluded), **OneMap walk + PT only** (cycle columns removed from the table). `enriched_addr_id` backfill/postal enrichment is assumed done separately.

4. **PIT snapshot** ([`hdb_mrt_features_at`](../../backend/alembic/versions/f1a2b3c4d5e6_split_mrt_physical_station.py) + [`build_mrt_pit_snapshot.py`](../../backend/scripts/build_mrt_pit_snapshot.py)) is **pass 2**: operational features use routed legs only when `opening_date <= tx_date`; speculative/nuisance signals use registry geometry. Pass 1 widens the pre-materialised leg set; pass 2 selects what becomes model features.

Running routing before MRT registry ingest still yields incomplete planned coverage for pass 1; running snapshot before routes exist yields NULL operational walk metrics until pass 1 completes.

---

## Phase 1 — Validate + ingest + deploy + trigger

### 1A — Read-only checklist

From `backend/`:

```bash
export DATABASE_URL=...
python scripts/validate_mrt_enrichment.py              # iterative dev OK with warnings
python scripts/validate_mrt_enrichment.py --strict-warnings   # CI / gate before snapshot
```

The script verifies: Alembic head, PostGIS, temporal columns, `hdb_mrt_features_at`, snapshot table existence, ingest fill-rates, route gaps, partial NULL distance rows, smoke `hdb_mrt_features_at(...)`.

### 1B — Reingest MRT CSV (after migrations)

```bash
cd backend
python scripts/ingest_mrt_temporal.py
```

Check `backend/logs/mrt_data_quality.json` for contradictions flagged by ingest.

### 1D — Prefect deployment

Create/select work pool **`default-agent-pool`** if missing (Prefect UI or CLI).

```bash
cd backend   # prefect.yaml resolves entrypoint scripts/... relative here
prefect deploy --all --prefect-file prefect.yaml
```

### 1E — Async enqueue via FastAPI admin

```bash
curl -sS -X POST "$API/api/admin/trigger-mrt-routing" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"rerun_partial": false, "limit": 5000}'
```

Repeat with `{ "rerun_partial": true, "limit": 5000 }` after the backlog drains to mop up NULL walk/PT/time fields.

Overrides:

| Env var | Purpose |
| --- | --- |
| `PREFECT_MRT_ROUTING_DEPLOYMENT_ID` | Skip name lookup — pass deployment UUID directly |
| `PREFECT_MRT_FLOW_NAME` | Default `hdb-mrt-routing` |
| `PREFECT_MRT_DEPLOYMENT_NAME` | Default `mrt-routing-default` |
| `PREFECT_API_KEY` / `PREFECT_API_VERSION` | Cloud / hardened servers |

Workers must poll `default-agent-pool`. The backend only queues runs; execution happens on agents.

---

## Phase 2 — After routing completes

### 2A — Re-validate coverage

```bash
cd backend
python scripts/validate_mrt_enrichment.py --strict-warnings
```

Interpret **partial NULL distance** WARN as “rerun_partial pass still needed”. Use **planned-station heuristic** WARN if ingest/order was wrong.

### 2B — Materialise snapshot + parquet

From repo root (script loads `.env`, normalises psycopg2 driver):

```bash
export DATABASE_URL=...
python backend/scripts/build_mrt_pit_snapshot.py
```

**Batch / concurrent fill (default):** the script seeds `mrt_pit_build_jobs` from `hdb_resale_transactions`, then workers claim **one month at a time** with `FOR UPDATE SKIP LOCKED` (recent months first). Start with **`--workers 4`** on a small VM; if Postgres CPU and `pg_stat_activity` stay healthy, increase slowly. For a cautious first run, try **`--workers 2`**.

| Flag | Use |
| --- | --- |
| `--workers N` | Parallel workers (default `4`) |
| `--from-month` / `--to-month` | Optional `YYYY-MM` bounds |
| `--max-months K` | Cap months this invocation (incremental runs) |
| `--retry-errors` | Re-claim months left in `status='error'` |
| `--reset-month YYYY-MM` | Admin: remove that month’s snapshot rows + reset the job row |
| `--no-export-parquet` | Skip parquet export after DB work |

**Monitoring** (any role with `SELECT` on `mrt_pit_build_jobs`):

```sql
SELECT status, COUNT(*) AS months, SUM(pairs_inserted) AS rows_done
FROM mrt_pit_build_jobs
GROUP BY status
ORDER BY 1;
```

**Recovery:** rerun with `--retry-errors` for transient failures; use `--reset-month` if a month needs a full rebuild (validator flags bad rows, or partial flush left bad data — `ON CONFLICT DO NOTHING` will not overwrite existing snapshot cells).

**Training sanity:** modelling uses `MRT_PIT_MIN_YEARS` (default `5`) and joins only months with `mrt_pit_build_jobs.status = 'done'`. Ensure the batch build finishes enough recent months or temporarily set `ML_TRAINING_SKIP_MRT_WINDOW_CHECK=1` for exploratory loads only.

**Pre-build validation (read-only):**

```bash
cd backend
python scripts/validate_mrt_pit_features.py
```

Produces `data/hdb_mrt_features.parquet`, `modelling/_mrt_lines.json`, `.meta.json` (or `*.partial.parquet` when `--max-months` caps a run — see script help).

**Troubleshooting — 0% training join coverage:** If [`report_training_completeness.py`](../../modelling/runners/report_training_completeness.py) shows **0 rows** in `hdb_mrt_features_pit_snapshot`, the join in [`training_db.py`](../../modelling/training_db.py) cannot return PIT features until you run this step successfully. Read-only DB users cannot `TRUNCATE`/`INSERT` the snapshot; use an admin URL.

### 2C — Training join readiness SQL

Before modelling / `--from-db` comparison:

```sql
SELECT
    COUNT(*)::bigint                                  AS total_txns,
    COUNT(f.hdb_addr_id)::bigint                       AS snapshot_join_hits,
    ROUND(100.0 * COUNT(f.hdb_addr_id) / NULLIF(COUNT(*), 0), 2) AS pct_covered
FROM hdb_resale_transactions t
LEFT JOIN hdb_mrt_features_pit_snapshot f
  ON f.hdb_addr_id = t.enriched_addr_id
 AND f.tx_year_month = t.month;
```

Compare `pct_covered` loosely to admin **MRT routing legs** % after accounting for nullable PIT scalars vs “any route exists” completeness semantics ([`analytics_service.py`](../../backend/services/analytics_service.py)).
