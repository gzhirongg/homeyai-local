#!/bin/bash
set -e

TAG=${1:?"Usage: ./rollback.sh <version-tag>  e.g. ./rollback.sh v1.1.0"}

echo "=== HomeyAI Rollback to $TAG ==="

git fetch origin --tags
git checkout "$TAG"

echo "Rolling back database migration..."
docker compose exec backend alembic downgrade -1 || echo "Migration rollback skipped"

export APP_VERSION=$(git describe --tags --always)
export GIT_COMMIT=$(git rev-parse --short HEAD)

echo "Rebuilding containers at $TAG..."
docker compose up --build backend frontend -d

echo ""
echo "=== Rollback complete: $APP_VERSION ($GIT_COMMIT) ==="
echo "Verify: curl http://localhost:8000/api/version"
