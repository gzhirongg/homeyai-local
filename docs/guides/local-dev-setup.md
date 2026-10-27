# Local Development Setup Guide

Last updated: 2026-03-18

## Prerequisites

- **Docker Desktop**: Required to run the application and its dependencies. Ensure it is installed and running.
- **Tailscale**: Required to connect to the Oracle VM databases and MinIO.
  - Download and install from [tailscale.com/download](https://tailscale.com/download)
  - Sign in with Google
  - Ask the team admin to approve your device at [login.tailscale.com/admin](https://login.tailscale.com/admin)
  - Tailscale runs in the background automatically; no manual tunnel commands are needed.

## Step 1: Clone

```bash
git clone -b bryan-dev-poc https://github.com/weixiantay/CSIT321-FYP-PredictingHomePrices.git .
```

## Step 2: Configure Environment

1. Copy the environment template:

```bash
cp .env.example .env
```

2. Edit `.env` and activate **Mode C** (recommended for daily development):

   - Uncomment the lines under `--- MODE C: LOCAL → DEVELOPMENT DB (via Tailscale) ---`
   - Comment out or remove the active Mode A section
   - Fill in your `URA_API_KEY` and any other required keys

**Environment modes:**

| Mode | Use case | Description |
|------|----------|-------------|
| **Mode A** | Production (on VM) | Backend connects to the internal `db` container. Default when running on the Oracle VM. |
| **Mode B** | Local to production DB | Connects to the production database via Tailscale. Use only for verification against prod; not for daily development. |
| **Mode C** | Local to development DB | Connects to the isolated dev database via Tailscale. Recommended for daily local development. |

## Step 3: Verify Tailscale

Before starting the application, confirm your machine can reach the VM:

```bash
ping -c 3 <REMOTE_VM_IP>
```

You should see successful responses. If not, open the Tailscale app and ensure it shows "Connected".

## Step 4: Run

From the project root, use the **dev compose file** (starts only frontend + backend):

```bash
docker compose -f docker-compose.dev.yml up --build
```

This starts only the frontend and backend containers. Databases, MinIO, and Prefect run on the VM and are accessed via Tailscale — no need to run them locally.

## Step 5: Verify

1. Open [http://localhost:3000](http://localhost:3000) in your browser.
2. Log in with `admin@homeyai.com` / `admin123`.
3. Navigate to `/admin/health` and confirm the system health page loads correctly.

## Troubleshooting

**Cannot connect to database or VM**

- Run `ping -c 3 <REMOTE_VM_IP>` (the value of `REMOTE_VM_IP` in `.env`) to verify Tailscale is active.
- Open the Tailscale app and ensure it shows "Connected".

**Docker issues**

- Ensure Docker Desktop is running.

**New team member cannot connect**

- Ask the admin to approve your device at [login.tailscale.com/admin](https://login.tailscale.com/admin).

## VM Services (via Tailscale)

All centralised services run on the VM and are accessible via Tailscale:

| Service | URL | Purpose |
|---------|-----|---------|
| MinIO Console | `http://<REMOTE_VM_IP>:9001` | Browse/upload datasets and models |
| Prefect Dev Dashboard | `http://<REMOTE_VM_IP>:4201` | Test and monitor pipeline runs |
| Prefect Prod Dashboard | `http://<REMOTE_VM_IP>:4200` | Production pipeline monitoring |

## Docker Compose Files

| File | Usage | Command |
|------|-------|---------|
| `docker-compose.dev.yml` | Local development (frontend + backend only) | `docker compose -f docker-compose.dev.yml up --build` |
| `docker-compose.yml` | VM server (all services) | `docker compose up --build` |
