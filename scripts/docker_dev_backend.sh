#!/usr/bin/env bash
# Run a command in the **docker-compose.dev.yml** backend service (uses `.env`:
# remote Postgres on the VM, MinIO endpoint, MODEL_ENV, etc.).
#
# Repo ``modelling`` is mounted at ``/modelling``. ``/app/modelling`` is an empty
# import stub only. We ``cd /`` and set ``PYTHONPATH=/:/app`` so ``import modelling``
# resolves to the full tree under ``/modelling``.
#
# Prereq: `docker compose -f docker-compose.dev.yml up -d backend`
#
# Examples:
#   ./scripts/docker_dev_backend.sh python /app/scripts/ingest_poi_assets.py --smoke
#   ./scripts/docker_dev_backend.sh python -m modelling.runners.backfill_experiments_to_minio --dry-run
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec docker compose -f docker-compose.dev.yml exec -T backend env PYTHONPATH=/:/app bash -lc 'cd / && exec "$@"' _ "$@"
