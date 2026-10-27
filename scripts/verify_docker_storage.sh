#!/usr/bin/env bash
# Run on the Docker host (e.g. Oracle VM) to confirm engine data lives on the large data volume.
# Expects: Docker Root Dir under /mnt/docker_data (symlink /mnt/docker-data is OK).
set -euo pipefail

ROOT_DIR=$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)
if [[ -z "$ROOT_DIR" ]]; then
  echo "ERROR: docker info failed — is Docker running?"
  exit 1
fi

echo "Docker Root Dir: $ROOT_DIR"
REAL=$(readlink -f "$ROOT_DIR" 2>/dev/null || echo "$ROOT_DIR")
# Oracle VM / HomeyAI commonly uses /mnt/data/docker (daemon.json data-root); older docs used /mnt/docker_data.
if [[ "$REAL" != /mnt/docker_data* && "$REAL" != /mnt/data/docker* ]]; then
  echo "WARNING: data-root is not under /mnt/docker_data or /mnt/data/docker (see /etc/docker/daemon.json data-root)." >&2
fi

echo ""
echo "Filesystem usage (boot vs data volume):"
df -h / /mnt/data /mnt/docker_data 2>/dev/null || df -h / /mnt/docker-data 2>/dev/null || df -h / 2>/dev/null
