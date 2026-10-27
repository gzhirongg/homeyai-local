#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker Desktop is required. Install it and start Docker before continuing.' >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo 'Start Docker Desktop, wait until it is ready, then retry.' >&2
  exit 1
fi
if [ ! -f .env.local ]; then
  cp .env.local.example .env.local
fi
docker compose --env-file .env.local -f docker-compose.local.yml "$@"
