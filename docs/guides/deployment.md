# Deployment Guide

Last updated: 2026-05-21

## Overview

Production runs on the Oracle Cloud ARM VM via Docker Compose (`docker-compose.prod.yml`). Public access uses **Caddy** for HTTPS on ports 80/443. The Next.js frontend proxies `/api/*` to FastAPI inside the Docker network.

## Prerequisites

- SSH access to the production VM: `opc@<REMOTE_VM_IP>`
- Repository cloned on the VM
- A free Dynu account ([dynu.com](https://www.dynu.com)) — Dynu is more reliable than DuckDNS (multi-server DNS, no monthly confirmation required)
- The VM public IP (Oracle Cloud Console → Compute → Instance → Public IPv4)
- `.env` configured (copy from `.env.example`)

## First-time public HTTPS setup

### 1. Register a free Dynu hostname

1. Sign up at [dynu.com](https://www.dynu.com/en-US/ControlPanel/CreateAccount) (free, email verification only).
2. Go to **Control Panel → DDNS Services → Add**.
3. Pick a hostname under any free Dynu domain — `freeddns.org`, `mywire.org`, `ddnsfree.com`, etc. Example: `homeyai.freeddns.org`.
4. In the hostname's **DNS Records** tab, set the **A record (IPv4 Address)** to the VM's **public** IP (the Oracle Cloud public IP, **not** the Tailscale IP).
5. Leave AAAA (IPv6) empty unless your VM has IPv6.
6. Save. Propagation is usually under 5 minutes; verify with `dig homeyai.freeddns.org +short` from your laptop — it should return the VM public IP.

> Oracle Cloud Always Free instances keep their public IP across reboots only if you **reserve** it (Compute → Instance → Public IPv4 → "Reserve"). Do this once so the Dynu A record stays valid. A static IP makes a DDNS update client unnecessary.

### 2. Set environment variables

In `.env` on the VM:

```bash
PUBLIC_DOMAIN=homeyai.freeddns.org
REMOTE_VM_IP=<your-vm-public-ip>
# Leave empty so the browser uses same-origin /api (proxied by Next.js):
NEXT_PUBLIC_API_URL=
BACKEND_INTERNAL_ORIGIN=http://backend:8000
CORS_EXTRA_ORIGINS=https://homeyai.freeddns.org
```

### 3. Open firewall (ports 80 and 443)

Already done on this VM. If rebuilding the VM:

- **Oracle Cloud Console:** VCN → Subnet → Security List → add ingress rules for TCP **80** and **443** from `0.0.0.0/0`.
- **On the VM (Oracle Linux firewalld):** `./scripts/open_https_firewall.sh`

### 4. Start the stack

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

Caddy obtains a Let's Encrypt certificate automatically on first request to `https://<PUBLIC_DOMAIN>`. Watch the logs once:

```bash
docker compose -f docker-compose.prod.yml logs -f caddy
```

You should see `certificate obtained successfully` within a minute.

### 5. Verify

```bash
curl -I https://homeyai.freeddns.org
curl https://homeyai.freeddns.org/api/version
```

Confirm HTTPS works and the API responds. Open `https://homeyai.freeddns.org` in a browser — the Next.js login page should load.

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `dig` returns no IP | DNS not propagated yet, or wrong record type | Wait 5 min; verify A record in Dynu Control Panel |
| Caddy log: `no IP address found` | Hostname A record not reachable | Check Dynu A record points to **public** IP, not Tailscale |
| Caddy log: `connection refused on :80` | Firewall blocking | Re-run `./scripts/open_https_firewall.sh`; verify Oracle Security List |
| HTTPS works but `/api/*` 502 | Backend container down | `docker compose -f docker-compose.prod.yml logs backend` |
| Browser HTTPS works, API CORS error | `CORS_EXTRA_ORIGINS` missing the domain | Set `CORS_EXTRA_ORIGINS=https://<PUBLIC_DOMAIN>`, rebuild backend |

## Deploy updates

SSH into the VM, pull latest code, run migrations, rebuild app containers:

```bash
ssh opc@<REMOTE_VM_IP>
cd /path/to/FYP-HomeyAI
git pull origin main
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
docker compose -f docker-compose.prod.yml up --build backend frontend caddy -d
```

Verify:

```bash
curl https://<PUBLIC_DOMAIN>/api/version
curl https://<PUBLIC_DOMAIN>/admin/health
```

## Rollback Procedure

**When to rollback:** After a critical bug, broken deploy, or unexpected production issue.

1. SSH into the VM and change to the project directory.
2. Run the rollback script with a known-good tag:

```bash
./scripts/rollback.sh <tag>
```

Example: `./scripts/rollback.sh v1.1.0`

3. Verify after rollback:

```bash
curl https://<PUBLIC_DOMAIN>/api/version
```

4. Investigate the issue on a feature branch, fix, test, and deploy again when ready.

## Versioning and Releases

- **Git tags**: Created manually at milestones (e.g. `v1.0.0`, `v1.1.0`). Tags are optional; not every deploy requires a new tag.
- **GitHub Releases**: Auto-generated changelog from PR titles. Used for release notes and archive.

## Targeted Deploys

To rebuild only the application containers and leave databases and Prefect running:

```bash
docker compose -f docker-compose.prod.yml up --build backend frontend caddy -d
```

This updates backend, frontend, and Caddy without touching `db`, `minio`, or `prefect-server` services.

## Seeding the Dev Database

One-time setup: copy schema and sample data from production to the development database.

From the project directory on the VM:

```bash
./scripts/seed_dev_db.sh
```

This script:

- Dumps the schema from the production database
- Applies it to the dev database
- Copies the first 10,000 `hdb_resale_transactions` and `users` as sample data

Run once after the dev database container is set up and running.
