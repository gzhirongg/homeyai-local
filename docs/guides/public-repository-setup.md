# Run HomeyAI from a fresh clone

This repository packages the supplied HomeyAI project with a standalone local
installation and the fixes described in the [feature audit](local-feature-completion.md).
It runs an HDB valuation demo without access to the original team's VM/Tailscale.
Prefect was already part of the project; the standalone stack adds a local server.

## 1. Prerequisites

- Git, Docker Desktop (macOS/Windows) or Docker Engine with Compose v2 (Linux).
- Start Docker before running the commands below. `docker compose version` and
  `docker info` must succeed.
- Internet access for container images/build dependencies and public datasets.
- Several GB of free disk space for images, volumes and dependencies.
- A Bash-compatible terminal; on Windows use WSL2 with Docker integration.
- Host Python 3 is optional, needed only for `scripts/check_local.py`.

Host Node.js, a host Python virtual environment, Tailscale, API accounts and a
pretrained model are not required for the default local demo. The container build
provides the runtime dependencies. First startup takes longer because MinIO is
built from pinned official source, followed by application dependency installation.

## 2. Start the services

Clone this repository and start the services:

```bash
git clone https://github.com/gzhirongg/homeyai-local.git
cd homeyai-local
cp .env.local.example .env.local
./scripts/local.sh up -d --build --wait
./scripts/local.sh ps
```

The helper also creates `.env.local` if it is missing. Leave optional API keys
blank initially. Local services bind to the loopback interface.

| Service | Local address |
| --- | --- |
| App | http://localhost:3001 |
| API docs | http://localhost:8001/docs |
| MinIO console | http://localhost:9001 |
| Prefect dashboard | http://localhost:4201 |
| Database | Docker-internal `db:5432` (not exposed on the host) |

If a port is occupied, change its `LOCAL_*_PORT` value in `.env.local`, then rerun
the startup command. Older team-VM compose files are retained as reference; use
`scripts/local.sh` for the self-contained installation.

## 3. Import public data and train the local model

The first server start creates the schema and demo users. Search/map/model assets
are populated separately:

```bash
./scripts/local.sh exec -T backend python -u scripts/bootstrap_local_valuation.py
./scripts/local.sh exec -T backend python -u scripts/bootstrap_local_map.py
./scripts/local.sh exec -T backend python -u scripts/calibrate_local_valuation.py
./scripts/local.sh restart backend
```

These commands:

1. Download and cache public HDB data plus the pinned address archive.
2. Validate address matches and populate the existing PostGIS schema.
3. Archive raw source copies and content hashes in local MinIO.
4. Train/register the initial baseline using the existing modelling pipeline.
5. Populate URA polygons and corroborated MRT station locations.
6. Fit a baseline with separate chronological training/calibration/test periods
   and publish immutable development model artifacts. The old model is retained.

The download API is rate limited; the scripts deliberately wait between requests.
If interrupted, rerun the command: completed downloads are reused. If a source
download fails, inspect the logged dataset ID, confirm internet access and retry
later. Do not replace missing inputs with guessed data.

The bootstrap scripts refuse to write outside the isolated `homeyai_local`
database on Docker host `db`. Data, model weights, databases and Docker volumes
are generated locally and are not included in the Git repository.

## 4. Sign in and try a valuation

| Demo account | Password | Purpose |
| --- | --- | --- |
| `premium@homeyai.com` | `premium123` | Reports, SHAP and comparable sales |
| `free@homeyai.com` | `free123` | Free experience |
| `admin@homeyai.com` | `admin123` | Admin/model/service dashboards |

These are intentionally public local-demo accounts. This stack is not a hardened
internet-facing deployment. Do not expose it publicly using these credentials.
For MinIO, use username `admin` and `LOCAL_MINIO_PASSWORD` from `.env.local`.

Open the app, search for postal code `600021`, select **21 TEBAN GARDENS ROAD**,
choose **4 ROOM**, enter **89 sqm** and **floor 8**, then calculate. The estimate,
SHAP explanation, actual recorded nearby sales and range should appear.

For a premium account, the report page at `/valuation-report` uses the last
valuation, supports section customization and downloads a PDF. In Analytics,
enable **URA Boundaries** and **MRT Stations**. Grey MRT markers mean that reliable
opening/status dates are absent; they do not indicate closure.

## 5. Verify the installation

With default blank optional credentials:

```bash
python3 scripts/check_local.py --valuation --map
./scripts/local.sh exec -T backend python -u scripts/verify_local_features.py
./scripts/local.sh exec -T backend python -m pytest -q
./scripts/local.sh exec -T backend python -m pytest -q -rs /workspace/modelling/tests
./scripts/local.sh exec -T frontend npx tsc --noEmit --incremental false
```

The live verifier uses seeded demo accounts and expects the locally calibrated
model, no MAS rate data and local-data assistant mode. It saves a sample PDF and
verification JSON under `data/`. Configure optional integrations after this check.

The 27 October verification run passed **146 backend tests**, **121 modelling
tests** (one missing-POI test skipped), TypeScript and a production build. Counts
can differ before public datasets are imported; dataset-dependent tests may skip.
The feature audit records warnings and checks not yet completed. A successful
build is not a claim that every listed product feature is finished.

A separate clean source export passed **144 backend tests / 2 skipped** and
**121 modelling tests / 1 skipped**, plus a frontend production build. Those
three skips reflect datasets intentionally excluded from the repository.

## 6. Stop, restart and troubleshoot

```bash
# Stop containers while preserving database/storage volumes.
./scripts/local.sh down

# Restart the saved installation.
./scripts/local.sh up -d --wait

# Read recent application logs.
./scripts/local.sh logs --tail 100 backend frontend
```

| Symptom | Check |
| --- | --- |
| Docker cannot connect | Start Docker Desktop and wait for `docker info` to work |
| Permission denied running helper | Run `bash scripts/local.sh ...`, or restore its executable bit |
| Empty property search/model unavailable | Complete the valuation bootstrap, calibration and backend restart |
| Empty boundary/station layer | Run `bootstrap_local_map.py`, then reload the page |
| Open/Planned MRT filters show no matches | Location snapshots have no opening history; use All/Unknown |
| No schools, parks or routed MRT times | POI/routing assets are absent; see remaining gaps below |
| Git clone did not include a pretrained model | Expected: training/publishing recreates it locally |

## 7. Included scope and remaining gaps

Working local scope includes HDB search/valuation, historical analytics, SHAP,
recorded comparables, calibrated development ranges, PDF reports, calculators,
URA/MRT location overlays and rule-based HDB statistics. A 90% interval target is
not guaranteed coverage: the documented later test coverage was **86.6%**. The
UI/report disclose that result, and source updates can change future coverage.

Optional integrations use `.env.local`: OpenAI, MAS, URA and OneMap credentials.
After changing them, recreate the backend with
`./scripts/local.sh up -d --force-recreate backend`.
Adding a key does not create missing product flows or training datasets.

Still incomplete: Google login, password recovery, payments, quota reset/enforcement,
full news/social sentiment, private-property valuation, POI datasets, MRT opening
history/routing and automatic worker/deployment scheduling. The Prefect server
alone does not run jobs automatically. The landing-page marketing-video path is
present in the original UI, but the video asset was not supplied.

Do not commit `.env.local`, tokens, downloaded data, generated model weights or
database dumps. Templates and source code are sufficient to reproduce this local
setup. Source URLs and provenance are documented in `data/README.md` and the
bootstrap scripts; follow each external data provider's terms when reusing data.
