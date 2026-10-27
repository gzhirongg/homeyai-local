#!/usr/bin/env bash
# Diagnose Postgres "missing data" after compose recreate (run on Docker host, e.g. Oracle VM).
# Does not print secrets. See plan: postgres volume / project mismatch vs actual data loss.
set -euo pipefail

echo "=== A) Running DB containers: volume mounts ==="
for c in sg_real_estate_db sg_real_estate_db_dev; do
  if docker inspect "$c" >/dev/null 2>&1; then
    echo "--- $c ---"
    docker inspect "$c" --format '{{range .Mounts}}{{println .Type .Name .Source "->" .Destination}}{{end}}'
    docker inspect "$c" --format 'project={{index .Config.Labels "com.docker.compose.project"}} workdir={{index .Config.Labels "com.docker.compose.project.working_dir"}}'
  else
    echo "--- $c (not running) ---"
  fi
done

echo ""
echo "=== B) All local volumes (name + size under Docker root) ==="
ROOT=$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo "/var/lib/docker")
echo "DockerRootDir=$ROOT"
docker volume ls
echo ""
echo "Postgres-related volume sizes (MB):"
docker volume ls -q | grep -iE 'postgres|real_estate' || true
for v in $(docker volume ls -q | grep -iE 'postgres|real_estate' || true); do
  sz=$(sudo du -sm "${ROOT}/volumes/${v}/_data" 2>/dev/null | awk '{print $1}' || echo "?")
  echo "  $v  ${sz}MB"
done

echo ""
echo "=== C) Orphan risk: multiple *postgres_data* projects ==="
docker volume ls | grep -i postgres || true

echo ""
echo "=== D) Public table counts (compose exec; needs project dir on host) ==="
COMPOSE_DIR="${COMPOSE_DIR:-}"
if [[ -n "$COMPOSE_DIR" && -f "$COMPOSE_DIR/docker-compose.yml" ]]; then
  (cd "$COMPOSE_DIR" && docker compose exec -T -u postgres db psql -d postgres -c '\l' 2>/dev/null) || echo "  db: compose exec failed"
  for svc in db db-dev; do
    echo "-- $svc / real_estate_dev_db (if exists) --"
    (cd "$COMPOSE_DIR" && docker compose exec -T -u postgres "$svc" psql -d real_estate_dev_db -tAc \
      "SELECT count(*)||' public tables' FROM pg_tables WHERE schemaname='public';" 2>/dev/null) || echo "  (skipped)"
  done
else
  echo "  Set COMPOSE_DIR=/path/to/repo (with docker-compose.yml) to run psql checks."
fi

echo ""
echo "=== Recommendations (read-only summary) ==="
echo "1. force-recreate does NOT remove named volumes; data loss implies down -v, volume rm, or NEW volume name."
echo "2. If an OLD volume (different compose project name) has du >> 0 but is unused, reattach with external volume or same COMPOSE_PROJECT_NAME as before."
echo "3. If public tables ~0 but du is large: cluster may be empty/wiped; restore backup or re-ingest (MinIO + backend ingestion)."
echo "4. ml_training_readonly auth errors: re-run SQL then align .env —"
echo "     backend/scripts/sql/create_ml_readonly_role.sql"
echo "     backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql"
