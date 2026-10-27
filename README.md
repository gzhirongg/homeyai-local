# HomeyAI — Standalone Local HDB Valuation

A Singapore HDB valuation application with historical resale analytics, SHAP
explanations, recorded comparable sales, PDF reports and geospatial maps.
This repository packages the supplied HomeyAI project with a reproducible local
Docker setup and the verified fixes documented in the feature audit.

**Start here:** [Fresh-clone setup guide](docs/guides/public-repository-setup.md).
The verified local scope is HDB. Condo/landed valuation and several integrations
remain incomplete; see [current capabilities and gaps](docs/guides/local-feature-completion.md).

## Quick Start

Prerequisites: Git and a running Docker installation with Compose v2. Use Bash
(WSL2 on Windows). Run:

```bash
git clone https://github.com/gzhirongg/homeyai-local.git
cd homeyai-local
cp .env.local.example .env.local
./scripts/local.sh up -d --build --wait
```

This starts the app, API, PostGIS database, MinIO storage and a local Prefect
server. No Tailscale, team VM, host Node.js or host virtual environment is required.
For the first installation, download public data and train/register the model:

```bash
./scripts/local.sh exec -T backend python -u scripts/bootstrap_local_valuation.py
./scripts/local.sh exec -T backend python -u scripts/bootstrap_local_map.py
./scripts/local.sh exec -T backend python -u scripts/calibrate_local_valuation.py
./scripts/local.sh restart backend
python3 scripts/check_local.py --valuation --map
```

The last check requires optional host Python 3. Downloads are rate limited and
cached; first startup/import takes longer. Data and trained weights are recreated
locally rather than committed to Git. Sources and provenance: [data/README.md](data/README.md).

Open [http://localhost:3001](http://localhost:3001). Demo accounts:

| Role | Email | Password |
| --- | --- | --- |
| Premium | `premium@homeyai.com` | `premium123` |
| Free | `free@homeyai.com` | `free123` |
| Admin | `admin@homeyai.com` | `admin123` |

These are public **local-demo** credentials. The provided stack binds to localhost
and is not an internet-facing production deployment.

Try postal code **600021**, select **21 TEBAN GARDENS ROAD**, choose **4 ROOM**,
enter **89 sqm** and **floor 8**, then calculate. On Analytics, enable URA boundaries
and MRT stations. Premium users can open `/valuation-report` after a valuation.

## Verify and manage the installation

```bash
./scripts/local.sh exec -T backend python -u scripts/verify_local_features.py
./scripts/local.sh exec -T backend python -m pytest -q
./scripts/local.sh exec -T backend python -m pytest -q -rs /workspace/modelling/tests
./scripts/local.sh exec -T frontend npx tsc --noEmit --incremental false

# Stop while preserving database and storage volumes.
./scripts/local.sh down

# Start again and inspect logs.
./scripts/local.sh up -d --wait
./scripts/local.sh logs --tail 100 backend frontend
```

Verified on 27 October 2026: **146 backend tests passed**, **121 modelling tests
passed / 1 missing-POI test skipped**, successful TypeScript and production build,
plus live valuation, SHAP, report, assistant, market-data and map checks. Optional
credentials should remain blank for the default live verifier. Known lint warnings
and unfinished workflows are documented in the audit.

## Scope and limitations

- HDB search/valuation and historical charts use public resale/catalogue data.
- Nearby comparables use actual recorded transactions, with explicit selection criteria.
- SHAP explains the active local model; reports use actual comparable-sale records.
- Prediction ranges use separate calibration/test periods. The documented run had
  a **90% target and 86.6% later test coverage**, which is disclosed rather than guaranteed.
- URA polygons and MRT locations work. Opening/planned status, POIs and routed
  travel times need additional data/credentials; grey stations mean status unknown.
- Local assistant mode queries HDB statistics. Full conversational AI, MAS rates
  and other external integrations need their respective credentials.
- Google login, password reset, payments, quota enforcement and automatic pipeline
  scheduling are unfinished. The marketing-video asset was not supplied.
- Prefect was part of the original project. The local server does not imply that
  workers, deployments or schedules have been configured.

## Repository layout

| Path | Purpose |
| --- | --- |
| `frontend/` | Next.js/React UI |
| `backend/` | FastAPI, database models/migrations, services, scripts and tests |
| `modelling/` | Feature engineering, training, inference and modelling tests |
| `data/README.md` | Dataset recreation and provenance; downloads stay local |
| `docker-compose.local.yml`, `docker/` | Self-contained service stack |
| `scripts/` | Startup and smoke-check helpers |
| `docs/` | Setup, architecture, audits, limitations and API reference |

The older VM-based compose files and guides are retained for reference. This source
copy references the original [HomeyAI project](https://github.com/weixiantay/CSIT321-FYP-PredictingHomePrices);
use the standalone guide above for this repository's local installation.

## Documentation

| Document | Description |
|----------|-------------|
| **Architecture** | |
| [System Design](docs/architecture/system-design.md) | Full system architecture, tech stack, data flow |
| [Data Storage Strategy](docs/architecture/data-storage-strategy.md) | MinIO bucket structure, datasets, models |
| [Infrastructure](docs/architecture/infrastructure.md) | Oracle VM, Tailscale, Docker topology, ports |
| **Guides** | |
| [Fresh-clone standalone setup](docs/guides/public-repository-setup.md) | Complete setup, data/model recreation, demo accounts and troubleshooting |
| [Feature completion audit](docs/guides/local-feature-completion.md) | Changes, validation evidence and remaining gaps |
| [Developer Manual](docs/guides/developer-manual.md) | Git workflow, DB rules, code quality, deployment |
| [Local Dev Setup](docs/guides/local-dev-setup.md) | Environment setup for new team members |
| [Deployment](docs/guides/deployment.md) | Deploy, rollback, versioning procedures |
| **Knowledge management (KM)** | |
| [KM index](docs/knowledge/README.md) | Where important data lands, justification, links to ADRs |
| [POI data: storage & modelling](docs/knowledge/poi-data-km.md) | MinIO `datasets/pois/`, Postgres `poi_locations` / `hdb_poi_features`, modelling integration |
| **Reference** | |
| [API Endpoints](docs/reference/api-endpoints.md) | Full API route reference |
| [Glossary: HDB vs URA spatial terms](docs/reference/glossary-hdb-ura-spatial.md) | Town, planning area, region, joins |
| [Environment Variables](docs/reference/environment-variables.md) | All env vars, modes A/B/C |
| [Project Requirements](docs/reference/project-requirements.md) | User stories, non-functional requirements |
| **Features** | |
| [System Health Monitor](docs/features/system-health-monitor.md) | /admin/health page specification |

## Tech Stack

- **Frontend:** Next.js 16, React 19, Tailwind CSS, Leaflet, Recharts
- **Backend:** Python 3.11, FastAPI, SQLAlchemy, Uvicorn
- **Database:** PostgreSQL 15 + PostGIS 3.3
- **Object Storage:** MinIO (datasets + ML model artifacts)
- **Orchestration:** Prefect 3 (pipeline scheduling and monitoring)
- **Local infrastructure:** Docker Compose; no team VM/Tailscale required
- **Verification:** Backend/modelling pytest suites, frontend TypeScript/build, live smoke checks
