# Infrastructure

Last updated: 2026-03-18

## Oracle Cloud VM

Production compute runs on an Oracle Cloud virtual machine with the following characteristics:

- **Compute type**: ARM-based (Ampere)
- **Reachable VM address**: set **`REMOTE_VM_IP`** in `.env` to whichever hostname or IP your team uses (often the Tailscale address for private access or the cloud public IP for internet access—they are intentionally a single knob in configuration).

Depending on routing, inbound web traffic may use public DNS or Tailscale mesh; **`REMOTE_VM_IP`** is whatever address you bake into Compose, CORS, and client hints for that deployment.

## Tailscale VPN

### Overview

Tailscale provides a private mesh VPN for developer access. The VM joins the Tailscale network and receives a stable Tailscale IP (`REMOTE_VM_IP`), which allows developers to connect to internal services without SSH tunnels or port forwarding.

### How Developers Connect

1. Install the Tailscale client on your development machine.
2. Sign in with the same identity used for the project.
3. Once authenticated, reach internal services at your VM Tailscale IP (`REMOTE_VM_IP` from `.env`) using the appropriate ports.

### Network Configuration

- **Invite-only network**: Only members explicitly invited to the Tailscale tailnet can reach the VM's Tailscale IP.
- **No SSH tunnels needed**: Direct TCP connections to the VM Tailscale IP work once connected to Tailscale.

### Key Expiry for the VM

The VM runs Tailscale as a client. Tailscale auth keys expire by default. If the key used to join the VM expires, the VM may lose its Tailscale connection. To avoid this:

1. Use a reusable, pre-authorized key when provisioning the VM.
2. Or renew the VM's Tailscale authentication before the key expires.
3. Check Tailscale admin for the VM's key policy and expiry settings.

## Docker Compose Files

The project uses two compose files:

| File | Purpose | Command |
|------|---------|---------|
| `docker-compose.yml` | **VM/Server** — all services (databases, MinIO, Prefect, backend, frontend) | `docker compose up --build` |
| `docker-compose.dev.yml` | **Local dev** — frontend + backend only (connects to VM services via Tailscale) | `docker compose -f docker-compose.dev.yml up --build` |

## Service Topology

All services below are defined in `docker-compose.yml` (VM stack). The dev stack (`docker-compose.dev.yml`) contains only backend and frontend.

### db (Production Database)

- **Image**: kartoza/postgis:15-3.3
- **Container**: sg_real_estate_db
- **Port**: 5432
- **Purpose**: Production PostgreSQL with PostGIS
- **Volume**: postgres_data

### db-dev (Development Database)

- **Image**: kartoza/postgis:15-3.3
- **Container**: sg_real_estate_db_dev
- **Port**: 5433 (mapped from internal 5432)
- **Purpose**: Isolated development and testing database
- **Volume**: postgres_data_dev

### minio

- **Image**: minio/minio:latest
- **Container**: sg_real_estate_minio
- **Ports**: 9000 (API), 9001 (Console)
- **Purpose**: Object storage for datasets and ML models
- **Volume**: minio_data
- **Command**: `server /data --console-address ":9001"`

### minio-init

- **Image**: minio/mc:latest
- **Container**: sg_real_estate_minio_init
- **Purpose**: One-time setup; creates `datasets` and `models` buckets
- **Depends on**: minio (waits for healthy)

### backend

- **Build**: ./backend
- **Container**: fastapi_backend
- **Port**: 8000 (Docker network only; not published to the host in prod)
- **Purpose**: FastAPI API server
- **Connects to**: db (PostgreSQL), minio (MinIO)
- **Environment**: DATABASE_URL, MINIO_*, URA_API_KEY, MODEL_ENV

### frontend

- **Build**: ./frontend
- **Container**: nextjs_frontend
- **Port**: 3000 (Docker network only; not published to the host in prod)
- **Purpose**: Next.js web application; proxies `/api/*` to backend via `BACKEND_INTERNAL_ORIGIN`
- **Depends on**: backend

### caddy

- **Image**: caddy:2-alpine
- **Container**: caddy_proxy
- **Ports**: 80, 443 (public HTTPS entry point)
- **Purpose**: Reverse proxy to frontend; auto Let's Encrypt via `PUBLIC_DOMAIN`
- **Depends on**: frontend

### prefect-server (Production)

- **Image**: prefecthq/prefect:3-python3.11
- **Container**: prefect_server
- **Port**: 4200
- **Purpose**: Production workflow orchestration — scheduled pipelines
- **Volume**: prefect_data

### prefect-server-dev (Development)

- **Image**: prefecthq/prefect:3-python3.11
- **Container**: prefect_server_dev
- **Port**: 4201 (mapped from internal 4200)
- **Purpose**: Shared development Prefect — developers test pipelines here
- **Volume**: prefect_data_dev

## Port Map

| Port | Service | Purpose |
|------|---------|---------|
| 80 | caddy | HTTP (redirect / ACME challenge) |
| 443 | caddy | HTTPS — public web UI |
| 3000 | frontend | Next.js (internal Docker network) |
| 4200 | prefect-server | Prefect production dashboard |
| 4201 | prefect-server-dev | Prefect development dashboard |
| 5432 | db | PostgreSQL + PostGIS (production) |
| 5433 | db-dev | PostgreSQL + PostGIS (development) |
| 8000 | backend | FastAPI REST API (internal Docker network) |
| 9000 | minio | MinIO S3-compatible API |
| 9001 | minio | MinIO Web Console |

## Network Access

### Public (Internet-accessible)

- **Caddy** (ports 80, 443): HTTPS web application at `https://<PUBLIC_DOMAIN>`
- API is reached at `https://<PUBLIC_DOMAIN>/api/*` via the Next.js proxy (backend is not exposed directly)

Open Oracle Cloud Security List **and** OS firewalld for TCP 80/443. See [`scripts/open_https_firewall.sh`](../../scripts/open_https_firewall.sh) and [Deployment Guide](../guides/deployment.md).

### Tailscale-only (Internal)

- **PostgreSQL** (ports 5432, 5433): Databases
- **MinIO** (ports 9000, 9001): Object storage
- **Prefect** (ports 4200, 4201): Pipeline orchestration dashboards

Access from developer machines requires a Tailscale connection to reach the VM at `REMOTE_VM_IP`.

## Volume Persistence

| Volume | Service(s) | Purpose |
|--------|------------|---------|
| postgres_data | db | Production database files |
| postgres_data_dev | db-dev | Development database files |
| minio_data | minio | Object storage (buckets, objects) |
| prefect_data | prefect-server | Production Prefect state |
| prefect_data_dev | prefect-server-dev | Development Prefect state |
