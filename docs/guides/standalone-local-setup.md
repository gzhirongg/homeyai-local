# Standalone local setup

Initial setup verified on 25 October 2026 on this Apple Silicon Mac.

**27 October update:** the active development model now has independent interval
calibration. SHAP, report generation/customization, calculators, local assistant
statistics and market signals were checked and repaired where necessary. See the
[feature completion audit](local-feature-completion.md) for current model metrics,
observed interval undercoverage, verification evidence and remaining prerequisites.
The original refitted baseline metrics below describe the preceding model.

## Property valuation is enabled

The local stack has now been populated and a new local baseline model trained and
activated. Postal-code search, building lookup, transaction analytics, and price
prediction work without the team VM or a OneMap account. For example, search
`600021`, select **21 TEBAN GARDENS ROAD**, choose a flat type and enter the unit
details, then calculate the valuation.

Current imported data:

- 243,500 official HDB resale transactions (January 2017–October 2026).
- 13,392 HDB Property Information catalogue rows and 13,436 building footprints.
- 13,267 unambiguous addresses, corroborated against the HDB footprints; 243,475
  of the resale transactions link to one of these addresses.
- 146 quarterly HDB RPI records; latest available in this downloaded snapshot is
  2026-Q2. The existing serving code carries the last published index forward.

The LightGBM model uses the registered `baseline_v1` feature set and the existing
pipeline, including RPI-adjusted training targets and nominal-SGD serving. Its
validation model trained on 118,340 transactions and held out the final six months
(13,458 transactions from May 2026). Holdout results: RMSE **S$43,330**, MAE
**S$29,507**, MAPE **4.35%**, and R² **0.962**. The validated configuration was then
refitted on all 131,798 matched transactions in the latest five-year window.
This is a local development baseline; it does not reproduce the team's advanced
MRT/POI models.

Reproduce the import and training after a fresh local installation:

```bash
./scripts/local.sh up -d --build --wait
./scripts/local.sh exec -T backend python -u scripts/bootstrap_local_valuation.py
./scripts/local.sh restart backend
python3 scripts/check_local.py --valuation
```

The bootstrap refuses to write anywhere except Docker host `db`, database
`homeyai_local`. It caches the downloads in `data/`, archives raw copies under
content-hashed `datasets/raw/local_bootstrap/` keys, reuses the existing ingestion
scripts, and publishes immutable model/metadata files under
`models/dev/valuation/experiments/`. It sets the existing database model-registry
pointer, so the model is restored automatically when the backend restarts.
It never reads a training dataset through the admin database connection: training
uses the downloaded public files and the validated local address parquet.

Provenance and reports are saved in `data/local_provenance.json`,
`data/local_bootstrap_report.json`, `data/local_model_report.json`, and
`modelling/outputs/local_bootstrap/`. The public source datasets are
[HDB resale transactions](https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view),
[HDB Property Information](https://data.gov.sg/datasets/d_17f5382f26140b1fdae0ba2ef6239d2f/view),
[HDB Existing Building](https://data.gov.sg/datasets/d_16b157c52ed637edd6ba1232e026258d/view),
and [HDB RPI](https://data.gov.sg/datasets/d_14f63e595975691e7c24a27ae4c07c79/view).
Street-name mapping uses a pinned
[public archived OneMap export](https://github.com/dhanyyudi/onemap-building-sg/blob/7ff07ccb7699ea38979d1e865bf9ae7fbce62c32/data/onemap_15022026.csv).
Only unambiguous block/street matches in the official HDB catalogue are accepted;
postal codes and centroid coordinates come from the official building footprints.

## Analytics map overlays

The original switches returned empty layers because the local URA and MRT tables
were empty. Populate the map independently of training:

```bash
./scripts/local.sh exec -T backend python -u scripts/bootstrap_local_map.py
```

The local map now contains **5 regions**, **55 planning areas**, and **147 physical
MRT stations** (175 line entries). Region selection switches to planning areas;
town selection highlights the matching areas. The MRT overlay combines interchange
line entries into a single marker and lists the codes/lines in its popup.

Sources: [URA regions](https://data.gov.sg/datasets/d_bf4d24df9129d5a8ff8cf82e20959ee0/view),
[URA planning areas](https://data.gov.sg/datasets/d_4765db0e87b9c86336792efe8a1f7a66/view),
and [LTA station exits](https://data.gov.sg/datasets/d_b39d3a0871985372d7e1637193335da5/view).
Station codes and approximate station coordinates come from the pinned archived
OneMap export cited above, with exact-name and nearby-exit corroboration. LRT
stations are excluded. All published MRT names matched; future station names in
the archive without corroborating exits are omitted. The snapshot is not a live
rail-network feed and may lag new openings.

**Status limitation:** these public location datasets do not provide reliable
opening/announcement history. No dates or operational statuses are invented:
local markers appear grey under **All** / **? (Unknown)**. **Open** and **Planned**
show an explicit no-match message until the temporal registry is independently
enriched. This import does not enable historical MRT modelling or OneMap routing.

Raw sources are archived by content hash in MinIO. Provenance and counts are in
`data/local_map_provenance.json`. The script only writes to `homeyai_local`, uses
upserts, and preserves existing MRT IDs, dates, and routes on reruns. Map requests
now validate responses, show errors and empty states, allow retries, and cancel
outdated requests when the layer or selected area changes.
The area summary also keeps unknown MRT states separate from operational states.
Verified in the browser: both overlays, 12 West Region planning areas, Jurong East
highlighting, interchange popup codes, and empty Open/Planned filters. Small-screen
layout no longer overlaps the section below the map; duplicate zoom controls were
removed. Screenshot: [verified local map](local-analytics-map-verified.png).

```bash
python3 scripts/check_local.py --valuation --map
```

## Start and stop

Docker Desktop must be running. Host Node.js, host Python packages, and Tailscale are
not required to run this stack. The first build requires internet access and several
GB of Docker disk space; later starts use cached images.

Run from the project root:

```bash
./scripts/local.sh up -d --build --wait
./scripts/local.sh ps
```

The wrapper creates `.env.local` from `.env.local.example` when absent. The local
Compose project has separate container names, networks, and persistent volumes.
Ports 3001 and 8001 avoid the older project copies already using 3000 and 8000.

| Service | Address | Login |
| --- | --- | --- |
| Application | http://localhost:3001 | `admin@homeyai.com` / `admin123` |
| API documentation | http://localhost:8001/docs | Public API documentation |
| MinIO storage UI | http://localhost:9001 | `admin` / `LOCAL_MINIO_PASSWORD` from `.env.local` |
| MinIO S3 API | http://localhost:9000 | Same local storage credentials |
| Prefect | http://localhost:4201 | Local server |
| PostGIS | Internal Docker host `db:5432` | Local credentials from Compose; no host port exposed |

Other seeded app users: `free@homeyai.com` / `free123` and
`premium@homeyai.com` / `premium123`.

```bash
# Stop this copy; preserve its database, storage, and installed modules.
./scripts/local.sh down

# Restart without rebuilding.
./scripts/local.sh up -d --wait

# Inspect startup errors.
./scripts/local.sh logs --tail 100 backend frontend

# Verify pages, proxy, authentication, and all four service health checks.
python3 scripts/check_local.py

# Run backend tests in the container.
./scripts/local.sh exec -T backend python -m pytest -q

# Type-check the frontend after the dev server has generated route types.
./scripts/local.sh exec -T frontend npx tsc --noEmit --incremental false
```

Edit port settings in `.env.local` if a listed port is occupied, then recreate
the stack with the start command. API requests use the frontend's same-origin
proxy, so no browser API URL needs to be changed.

## What was fixed

- Docker Desktop was stopped; starting it restored access to the Docker runtime.
- There was no active environment configuration. All modes in `.env.example`
  were commented out, and the original dev stack depended on a team VM.
- The copied `backend/.venv` points to a missing Homebrew Python 3.13 binary.
  Node.js is absent from the normal shell path. Docker supplies both runtimes.
- Added a separate local stack with PostGIS, MinIO, Prefect, readiness checks,
  automatic bucket initialization, and migrations before API startup.
- The fresh Alembic chain assumed manually created address tables/columns and
  intermediate route keys. Repaired revision `77cb299260ef` so an empty database
  can reach head `a9b8c7d6e5f4` without a VM schema snapshot.
- An unbounded SQLAlchemy install selected 2.1, whose default PostgreSQL driver
  is not the installed psycopg2 driver. Added a `<2.1` compatibility bound and an
  explicit `postgresql+psycopg2` local connection URL.
- Official MinIO Docker Hub and Quay pulls failed. The local image builds the
  [official source](https://github.com/minio/minio) at commit
  `7aac2a2c5b7c882e68c1ce017d8256be2feea27f` using Go in Docker.
- The archive includes stale `.next` route types referencing a deleted debug
  page. The local frontend gets a clean, separate `.next` volume and Linux
  `node_modules`, rather than reusing copied machine-specific generated files.
- Excluded the copied virtual environment, caches, and OneMap token files from
  the backend Docker build context; added local secret/cache ignore rules.
- Repaired backend test imports and stale mocks/expectations. Dataset coverage
  tests explicitly skip when their external source CSV is absent.
- Removed a ref assignment during render in the admin alert component.
- Updated the health dashboard to display the configured service addresses and
  avoid claiming a Tailscale connection is active in the standalone setup.

## Initial verification results (25 October 2026)

The latest 27 October checks are **146 backend tests passed**, **121 modelling
tests passed / 1 POI test skipped**, plus successful production build and live
feature checks. See the [completion audit](local-feature-completion.md).
The checks below record the earlier setup stage and preceding model.

- Fresh database: complete Alembic upgrade to head passed; rerunning is a no-op.
- Python dependency consistency (`pip check`): passed.
- Backend tests at this stage: **131 passed**. Initial checks were 104 passed / 2 skipped
  before importing the public CSV; the imported CSV enables those checks, and two
  new regression cases verify the corrected address-filtered aggregates. Fifteen
  additional cases cover recorded nearby sales, exclusion criteria, and no-data
  handling; the valuation smoke check exercises the premium comparable-sales API.
  Eight map checks cover exact names, interchange codes, unmatched/future stations,
  LRT exclusion, invalid or disagreeing coordinates, and unknown-status separation.
- Frontend TypeScript: passed with regenerated Next.js route types.
- Clean frontend production build with `NODE_ENV=production`: passed.
- Smoke checks: home, login, valuation, analytics, admin health; authentication
  enforcement; admin login; user profile; analytics filters; model status;
  experiment catalog; API/PostgreSQL/MinIO/Prefect health all passed.
- Browser: admin sign-in and analytics page rendered successfully.
- Browser valuation: selected `600021`, 4-room / 89 sqm / floor 8; the form
  returned **S$582,183.90** using the trained local model. Price and band labels
  also fit the narrow embedded-browser viewport. API checks still pass after
  recreating the backend container, confirming the model pointer persists.
- Lint still reports **3 existing `react-hooks/set-state-in-effect` errors in
  `frontend/src/components/Map.tsx`**, plus warnings. These do not prevent the
  dev server or production build from running. They have not been disabled.
- Backend deprecation warnings remain. The address-filtered analytics aggregate
  queries now preserve the address join; regression tests ensure an unrelated
  property's transactions cannot leak into time-series, town, or flat-type totals.

## Features still requiring assets or credentials

The local bootstrap enables the baseline valuation flow. The following describes
what is populated and what still needs additional assets or credentials.

| Feature | Missing prerequisite |
| --- | --- |
| Resale charts | Populated by the local bootstrap |
| Address/property lookup | Populated by the local bootstrap; ambiguous/unmatched addresses are omitted |
| Building overlays | HDB footprints populated by the local bootstrap |
| URA boundaries / MRT station locations | Populated by `bootstrap_local_map.py`; MRT temporal statuses and future stations remain unavailable |
| Land-use/POI overlays | Corresponding spatial datasets and ingestion/enrichment jobs still needed |
| Price predictions | Local LightGBM baseline active, with model and metadata in local MinIO |
| MAS interest signal | Valid `MAS_API_KEY` |
| Authenticated OneMap enrichment/routing | Valid `ONEMAP_EMAIL_1` and `ONEMAP_PASSWORD_1` |
| URA integration | Valid `URA_API_KEY` |
| Training/scheduled jobs | Required datasets, registered Prefect deployments, and a worker; the local stack starts the Prefect server only |

To replace the local baseline with a team model, upload its model and sidecars
to local MinIO and promote it through the existing registry. The small legacy
`modelling/models/homeyai_v1_model.pkl` is not used: the bootstrap trains a new
compatible pipeline on real public transactions.

No sample prices or fake trained model were substituted for missing assets.
The UI's Google login button has no authentication implementation in this copy;
use the local email/password login.
