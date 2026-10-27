#!/usr/bin/env python3
"""Smoke-test read-only training DB access: SELECT, PostGIS, and denied writes.

Resolves URL via ``training_db.get_training_database_url()`` (`DATABASE_URL_READ_ONLY`
or `READ_ONLY_DB_*` + `DB_HOST` / `DB_INNER_PORT` / `DB_NAME`).

Usage (from repo root):
  python modelling/verify_readonly_connection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure `import training_db` works when run as `python modelling/verify_readonly_connection.py`
_MODELLING_DIR = Path(__file__).resolve().parent
if str(_MODELLING_DIR) not in sys.path:
    sys.path.insert(0, str(_MODELLING_DIR))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import ProgrammingError  # noqa: E402

import training_db  # noqa: E402


def main() -> int:
    try:
        training_db.get_training_database_url()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    engine = training_db.create_training_engine()

    with engine.connect() as conn:
        one = conn.execute(text("SELECT 1 AS ok")).scalar()
        assert one == 1

        ro = conn.execute(text("SHOW transaction_read_only")).scalar()
        print(f"transaction_read_only={ro!r}")

        try:
            pgv = conn.execute(text("SELECT PostGIS_Version() AS v")).scalar()
            print(f"PostGIS_Version={pgv!r}")
        except Exception as exc:  # pragma: no cover - depends on image
            print(f"PostGIS_Version check failed (non-fatal): {exc}")

        try:
            n = conn.execute(text("SELECT COUNT(*) FROM hdb_resale_transactions")).scalar()
            print(f"hdb_resale_transactions.count={n}")
            write_probe = (
                "UPDATE hdb_resale_transactions SET resale_price = resale_price WHERE false"
            )
        except ProgrammingError:
            print("hdb_resale_transactions: absent (skipped row count; migrations not applied?)")
            # PostGIS images always ship spatial_ref_sys in public — probe UPDATE denial there.
            write_probe = "UPDATE spatial_ref_sys SET auth_name = auth_name WHERE false"

    denied = False
    with engine.connect() as conn:
        try:
            conn.execute(text(write_probe))
            conn.commit()
        except Exception as exc:
            msg = str(exc).lower()
            denied = "permission" in msg or "read-only" in msg or "readonly" in msg
            if not denied:
                raise
            print(f"Write blocked as expected: {exc!r}")

    if not denied:
        print("ERROR: UPDATE unexpectedly succeeded for read-only role", file=sys.stderr)
        return 1

    print("verify_readonly_connection: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
