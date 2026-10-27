# Developer Manual

> The single source of truth for development rules and best practices.
> Any PR that changes architecture, infrastructure, or workflows must include a corresponding update to the relevant documentation.

---

## 1. Git Workflow

### Branching Strategy

```
main (protected)
  ├── feature/add-valuation-report    ← new features
  ├── fix/mrt-distance-calculation    ← bug fixes
  └── refactor/cleanup-auth-logic     ← refactoring
```

**Rules:**
- Always branch from `main`
- Use descriptive branch names: `feature/`, `fix/`, `refactor/`, `docs/`
- Never push directly to `main` — all changes go through Pull Requests
- Keep PRs focused: one feature or fix per PR
- Write descriptive PR titles — they become the changelog when a release is tagged

### Pull Request Requirements

Every PR to `main` must satisfy:
1. **CI pipeline passes** — all 5 jobs (backend-lint, backend-test, frontend-lint, frontend-build, migration-check)
2. **At least 1 approval** from another team member
3. **No merge conflicts** with main

### Commit Messages

Write clear, imperative commit messages:
- Good: `Add mortgage calculator endpoint`
- Good: `Fix incorrect MRT distance in PostGIS query`
- Bad: `updated stuff`
- Bad: `WIP`

---

## 2. Environment Modes

Your `.env` file controls which databases your local application connects to. See [Environment Variables](../reference/environment-variables.md) for full details.

| Mode | When to Use | Database | Port |
|------|------------|----------|------|
| **Mode A** | Running on the VM itself (production) | `real_estate_db` | 5432 |
| **Mode B** | Verifying production data locally (rare) | `real_estate_db` | 5432 |
| **Mode C** | Daily development (default) | `real_estate_dev_db` | 5433 |

**Default to Mode C for all development work.**

Only switch to Mode B when you specifically need to verify that something works against production data — and never write to it.

---

## 3. Database Rules

### Golden Rules
1. **Never connect to the production database for development work.** Use Mode C (dev DB) for all testing.
2. **Schema changes require an Alembic migration.** Never modify the database schema by hand (no raw `ALTER TABLE` in psql).
3. **Never delete or modify existing migration files.** Only create new ones. Migration history is append-only.
4. **Test migrations on the dev DB before submitting a PR.**

### Migration Workflow

```bash
# 1. Modify your model in backend/models.py
# 2. Generate a migration
cd backend
alembic revision --autogenerate -m "add listing_date to transactions"

# 3. Review the generated file in alembic/versions/
#    Verify the upgrade() and downgrade() functions look correct

# 4. Test on dev DB
DATABASE_URL=postgresql://admin:password123@<REMOTE_VM_IP>:5433/real_estate_dev_db \
  alembic upgrade head

# 5. Commit the migration file in your PR
git add alembic/versions/
git commit -m "Add migration: add listing_date to transactions"
```

The CI pipeline validates that all migrations apply cleanly from scratch.

On deploy, run `docker compose -f docker-compose.prod.yml exec backend alembic upgrade head` on the VM before rebuilding app containers (see [Deployment Guide](deployment.md)).

---

## 4. MinIO / Object Storage Rules

### Bucket Structure

| Bucket | Path | Content |
|--------|------|---------|
| `datasets` | `raw/hdb_resale/` | Raw CSV files from Data.gov.sg |
| `datasets` | `raw/ura/` | URA API response dumps |
| `datasets` | `raw/scraped/` | Web-scraped data (future) |
| `datasets` | `processed/` | Cleaned, feature-engineered parquet files |
| `models` | `prod/` | Production model artifacts (loaded by FastAPI) |
| `models` | `dev/` | Experimental model artifacts (for testing) |

### Rules
- **Do not upload experimental models to `models/prod/`.** Use `models/dev/` for testing.
- **Do not delete data from `datasets/raw/`.** Raw data is an immutable archive.
- Use the MinIO Console (port 9001) for manual uploads/downloads, or the `mc` CLI.
- Set `MODEL_ENV=dev` in your `.env` to load models from `models/dev/` during development.

### Using the mc CLI

```bash
# Set up alias (one-time)
mc alias set homeyai http://<REMOTE_VM_IP>:9000 admin password123

# Upload a trained model for testing
mc cp my_model.pkl homeyai/models/dev/

# Download production training data
mc cp homeyai/datasets/processed/hdb_resale_full.parquet ./local_data/

# List all objects
mc ls homeyai/datasets/ --recursive
mc ls homeyai/models/ --recursive
```

---

## 5. Prefect (Pipeline Orchestration)

### Architecture

Two centralised Prefect servers run on the VM:

| Server | Port | Purpose |
|--------|------|---------|
| `prefect-server` | 4200 | Production pipelines (scheduled ingestion, model retraining) |
| `prefect-server-dev` | 4201 | Development — test new flows and deployments here |

Both dashboards are accessible via Tailscale at `http://<REMOTE_VM_IP>:<port>` (use `REMOTE_VM_IP` from `.env`).

### Development Workflow

When building a new pipeline:

1. Write your flow in the backend codebase (e.g. `backend/flows/my_pipeline.py`).
2. Point your local Prefect client at the **dev** server:
   ```bash
   export PREFECT_API_URL=http://${REMOTE_VM_IP}:4201/api
   ```
3. Register / run your flow. It appears in the dev dashboard for the whole team to see.
4. Test against the **dev database** (Mode C) and `models/dev/` in MinIO.
5. Once validated, create a deployment targeting the **production** server (port 4200) as part of your PR.

### Rules

- **Never register experimental flows against the production server (4200).** Use the dev server (4201) for all testing.
- **Coordinate with the team** via the dev dashboard — check if someone else's flow is already running before launching heavy jobs.
- Production deployments should be reviewed as part of the normal PR process.

---

## 6. Code Quality Standards

### Backend (Python)
- **Linter:** `ruff check .` must pass (enforced by CI)
- **Tests:** `pytest tests/` must pass (enforced by CI)
- New API endpoints should have corresponding tests in `backend/tests/`
- Follow existing patterns in `main.py` for endpoint structure

### Frontend (TypeScript / React)
- **Linter:** `npx eslint .` must pass (enforced by CI)
- **Type check:** `npx tsc --noEmit` must pass (enforced by CI)
- **Build:** `npm run build` must succeed (enforced by CI)
- Use the existing component patterns (Navbar, RequireAuth, etc.)

### General
- No secrets in code (API keys, passwords). Use environment variables.
- No commented-out code in PRs. Delete unused code.
- Keep functions focused. If a function exceeds ~50 lines, consider splitting it.

---

## 7. Deployment

### Deploy Process

Deployment is manual — SSH into the VM, pull `main`, run migrations, and rebuild containers.

```bash
# SSH into the VM
ssh opc@<REMOTE_VM_IP>

cd /path/to/FYP-HomeyAI
git pull origin main
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
docker compose -f docker-compose.prod.yml up --build backend frontend caddy -d
```

See [Deployment Guide](deployment.md) for HTTPS setup, firewall, and rollback.

### Deployment Checklist

1. All intended PRs are merged to `main`
2. CI is green on `main`
3. SSH into the VM and pull latest `main`
4. Run migrations and rebuild (`docker compose -f docker-compose.prod.yml …` — see above)
5. Verify: `curl https://<PUBLIC_DOMAIN>/api/version`
6. Verify: open `https://<PUBLIC_DOMAIN>/admin/health` in the browser
7. (Optional) Tag the release: `git tag -a v1.x.0 -m "description"`

---

## 8. Rollback

If a deploy introduces a bug:

```bash
# 1. Identify the last known good version
git tag -l

# 2. Roll back
./scripts/rollback.sh v1.1.0

# 3. Verify
curl http://localhost:8000/api/version
```

See [Deployment Guide](deployment.md) for the complete rollback procedure.

---

## 9. Documentation Rule

**Any PR that changes the following must include a documentation update:**
- System architecture or service topology
- Database schema (new/modified tables or columns)
- API endpoints (new or changed routes)
- Environment variables or configuration
- Infrastructure (ports, networking, Docker services)
- Developer workflow or tooling
- **Data ingestion destinations or ML feature provenance** — update [`docs/knowledge/`](../knowledge/README.md) (KM) and/or [`docs/architecture/data-storage-strategy.md`](../architecture/data-storage-strategy.md); add or revise ADRs under `docs/adr/` when the decision is non-obvious.

PR reviewers are responsible for checking this. If a PR changes infrastructure but has no doc update, request one before approving.

Documentation lives in `docs/`. See the [README](../../README.md) for the full index. **Knowledge management (where data lands, why):** [`docs/knowledge/README.md`](../knowledge/README.md).
