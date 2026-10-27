#!/usr/bin/env bash
# =============================================================================
# Verify remote PostgreSQL reachability for docker-compose.dev.yml
#
# 1) TCP from this machine (Tailscale must work on the host)
# 2) psycopg2 from the backend container (same path as uvicorn uses)
#
# Usage: from repo root:  ./scripts/check_remote_db.sh
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${ROOT}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Missing .env (copy from .env.example)"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${DB_HOST:?Set DB_HOST in .env}"
: "${DB_INNER_PORT:?Set DB_INNER_PORT in .env}"
: "${ADMIN_DB_USER:?Set ADMIN_DB_USER in .env}"
: "${ADMIN_DB_PASSWORD:?Set ADMIN_DB_PASSWORD in .env}"
: "${DB_NAME:?Set DB_NAME in .env}"

echo "=============================================="
echo "Remote DB target (from .env)"
echo "  Host: ${DB_HOST}"
echo "  Port: ${DB_INNER_PORT}"
echo "  Database: ${DB_NAME}"
echo "  User: ${ADMIN_DB_USER}"
echo "=============================================="

# --- 1) Host TCP ---
echo ""
echo "[1/2] TCP from host → ${DB_HOST}:${DB_INNER_PORT}"
if command -v nc >/dev/null 2>&1; then
  if nc -z -w 8 "$DB_HOST" "$DB_INNER_PORT" 2>/dev/null; then
    echo "      OK (nc: port is open)"
  else
    echo "      FAILED — nothing accepted the connection."
    echo "      Fix: Tailscale connected? VM up? Postgres listening on ${DB_INNER_PORT}?"
    echo "      (host:5433 maps to container:5432 only if docker compose exposes it on the VM)"
    exit 1
  fi
elif timeout 8 bash -c "echo >/dev/tcp/${DB_HOST}/${DB_INNER_PORT}" 2>/dev/null; then
  echo "      OK (/dev/tcp)"
else
  echo "      SKIP (install netcat 'nc' for a TCP check, or rely on step 2)"
fi

# --- 2) Same as backend container ---
echo ""
echo "[2/2] PostgreSQL from backend container (compose env + DATABASE_URL)"
if ! command -v docker >/dev/null 2>&1; then
  echo "      SKIP (docker not in PATH)"
  exit 0
fi

COMPOSE=(docker compose -f docker-compose.dev.yml)
if ! "${COMPOSE[@]}" run --rm --no-deps --entrypoint python backend -c "
import os, sys
url = os.environ.get('DATABASE_URL', '')
if not url:
    print('ERROR: DATABASE_URL not set in container')
    sys.exit(1)
# Avoid printing password
safe = url
if '@' in url:
    pre, rest = url.split('@', 1)
    userinfo = pre.split('://', 1)[-1]
    if ':' in userinfo:
        u = userinfo.split(':', 1)[0]
        safe = url.split('://', 1)[0] + '://' + u + ':****@' + rest
print('      DATABASE_URL:', safe)
import psycopg2
conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute('select 1')
cur.close()
conn.close()
print('      OK (psycopg2 connected and SELECT 1)')
"; then
  echo ""
  echo "=============================================="
  echo "Container check failed."
  echo "If [1] passed but [2] failed: Docker’s network may not reach Tailscale IPs."
  echo "Try: update Tailscale, or use Docker Desktop with host routing to Tailscale,"
  echo "or run the API on the host (venv) instead of inside Docker."
  echo "=============================================="
  exit 1
fi

echo ""
echo "All checks passed."
