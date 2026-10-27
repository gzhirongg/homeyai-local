"""Re-load core datasets from MinIO into Postgres (HDB resale, URA master plan, MRT, buildings).

Run inside the **docker-compose.dev.yml** backend container (remote DB / MinIO from ``.env``), e.g.:

    ./scripts/docker_dev_backend.sh python /app/scripts/reingest_from_minio.py

    docker compose -f docker-compose.dev.yml exec backend env PYTHONPATH=/:/app bash -lc \\
        'cd / && python /app/scripts/reingest_from_minio.py'

Requires ``DATABASE_URL_ADMIN`` or ``DATABASE_URL`` (and MinIO_*); same resolution as the FastAPI app via ``models.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Bootstrap path + .env (same pattern as other scripts)
_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
for _root in [_BACKEND, _BACKEND.parent]:
    _env = _root / ".env"
    if _env.exists():
        for line in _env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        break

from sqlalchemy import text

from models import SessionLocal, DATABASE_URL
from ingestion import run_ingestion, ingest_master_plan_data, _make_minio_client


def _truncate_optional(db, table: str) -> None:
    try:
        db.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
        db.commit()
        print(f"Truncated {table}.")
    except Exception as e:
        db.rollback()
        print(f"(skip) {table}: {e}")


def main() -> None:
    if "sqlite" in (DATABASE_URL or "").lower():
        sys.exit(
            "ERROR: PostgreSQL is not configured. Set DATABASE_URL_ADMIN or DATABASE_URL "
            "(see backend/models.py and backend/scripts/db_env.py)."
        )

    print("=== Re-ingest from MinIO (HDB resale + URA master plan) ===")
    db = SessionLocal()
    try:
        # If present, clear routes that depend on mrt_station_exits before MRT reload.
        _truncate_optional(db, "hdb_mrt_routes")

        run_ingestion(db, force=True)
        mc = _make_minio_client()
        ingest_master_plan_data(db, mc, force=True)
    finally:
        db.close()

    import subprocess

    print("=== MRT station exits (GeoJSON from MinIO) ===")
    subprocess.check_call(
        [sys.executable, str(_BACKEND / "scripts" / "ingest_mrt_stations.py")],
        cwd=str(_BACKEND),
        env=os.environ.copy(),
    )

    print("=== HDB buildings (GeoJSON from MinIO) ===")
    subprocess.check_call(
        [sys.executable, str(_BACKEND / "scripts" / "ingest_hdb_buildings.py")],
        cwd=str(_BACKEND),
        env=os.environ.copy(),
    )

    print("=== Done re-ingest from MinIO ===")


if __name__ == "__main__":
    main()
