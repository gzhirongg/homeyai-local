#!/bin/bash
# =============================================================================
# Seed / reset the development database (real_estate_dev_db)
#
# Canonical workflow:
#   MinIO (source of truth) → dev DB → test → prod DB
#
# Run this script on the VM after:
#   - First-time VM setup
#   - After a dev DB wipe
#   - After new Alembic migrations are added
#
# Usage:
#   ssh opc@<vm-ip>
#   cd ~/CSIT321-FYP-PredictingHomePrices
#   bash scripts/seed_dev_db.sh
# =============================================================================

set -e

DEV_DB_URL="postgresql://admin:password123@db-dev:5432/real_estate_dev_db"

echo "=== Seed Development Database ==="
echo "Target: real_estate_dev_db (port 5433)"
echo ""

# 1. Run Alembic migrations against the dev DB
echo "[1/4] Running Alembic migrations …"
docker compose exec -e DATABASE_URL="$DEV_DB_URL" backend \
  bash -c "cd /app && PYTHONPATH=/app alembic upgrade head"

# 2. Ingest HDB building footprints from MinIO
echo ""
echo "[2/4] Ingesting HDB building footprints from MinIO …"
docker compose exec -e DATABASE_URL="$DEV_DB_URL" backend \
  bash -c "cd /app && PYTHONPATH=/app python scripts/ingest_hdb_buildings.py"

# 3. Ingest MRT station exits from MinIO
echo ""
echo "[3/4] Ingesting MRT station exits from MinIO …"
docker compose exec -e DATABASE_URL="$DEV_DB_URL" backend \
  bash -c "cd /app && PYTHONPATH=/app python scripts/ingest_mrt_stations.py"

# 4. Ingest HDB resale transactions from MinIO
echo ""
echo "[4/4] Ingesting HDB resale transactions from MinIO …"
docker compose exec -e DATABASE_URL="$DEV_DB_URL" backend \
  bash -c "cd /app && PYTHONPATH=/app python -c \"
import os, sys
sys.path.insert(0, '/app')
os.environ['DATABASE_URL'] = '$DEV_DB_URL'
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ingestion import run_ingestion
engine = create_engine('$DEV_DB_URL')
db = sessionmaker(bind=engine)()
run_ingestion(db)
db.close()
\""

echo ""
echo "=== Dev database seeded successfully ==="
echo ""
echo "Row counts:"
docker compose exec db-dev psql -U admin -d real_estate_dev_db -c "
  SELECT
    (SELECT COUNT(*) FROM hdb_resale_transactions) AS resale_txns,
    (SELECT COUNT(*) FROM hdb_buildings)           AS hdb_buildings,
    (SELECT COUNT(*) FROM mrt_station_exits)       AS mrt_exits,
    (SELECT COUNT(*) FROM users)                   AS users;
"
