"""Load ``.env`` and resolve an admin Postgres URL.

Resolution order:

1. ``DATABASE_URL_ADMIN`` (preferred explicit admin URL).
2. ``DATABASE_URL`` (legacy / Docker Compose assembled URL).
3. ``ADMIN_DB_USER`` / ``ADMIN_DB_PASSWORD`` + ``DB_HOST`` or ``REMOTE_VM_IP`` + port + ``DB_NAME``.
4. libpq-style: ``PGUSER``, ``PGPASSWORD``, ``PGHOST``, ``PGDATABASE``, optional ``PGPORT``.

Returns a SQLAlchemy-friendly string (``postgresql+psycopg2://...``). Use
``psycopg2_connect_dsn()`` for ``psycopg2.connect``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote_plus


def load_repo_env(repo_root: Path) -> None:
    """Populate ``os.environ`` from repo ``.env`` files (non-destructive: ``setdefault``)."""
    for p in (repo_root / ".env", repo_root / "backend" / ".env"):
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
    expand_env_placeholders()


def expand_env_placeholders(max_passes: int = 8) -> None:
    def sub(s: str) -> str:
        return re.sub(
            r"\$\{([^}]+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            s,
        )

    for _ in range(max_passes):
        changed = False
        for k, val in list(os.environ.items()):
            if "${" not in str(val):
                continue
            new_val = sub(str(val))
            if new_val != val:
                os.environ[k] = new_val
                changed = True
        if not changed:
            break


def resolve_admin_database_url() -> str:
    """Admin URL for migrations / ingest / FastAPI (SQLAlchemy + psycopg2)."""
    url = (
        (os.environ.get("DATABASE_URL_ADMIN") or "").strip()
        or (os.environ.get("DATABASE_URL") or "").strip()
    )
    if url:
        return _normalize_sqlalchemy_url(url)

    user = (os.environ.get("ADMIN_DB_USER") or os.environ.get("PGUSER") or "").strip()
    password = (os.environ.get("ADMIN_DB_PASSWORD") or os.environ.get("PGPASSWORD") or "").strip()
    host = (
        os.environ.get("DB_HOST")
        or os.environ.get("REMOTE_VM_IP")
        or os.environ.get("PGHOST")
        or ""
    ).strip()
    port = (
        os.environ.get("DB_INNER_PORT")
        or os.environ.get("DB_PORT")
        or os.environ.get("PGPORT")
        or "5432"
    ).strip()
    db = (os.environ.get("DB_NAME") or os.environ.get("PGDATABASE") or "").strip()

    if user and password and host and db:
        u, p = quote_plus(user), quote_plus(password)
        return f"postgresql+psycopg2://{u}:{p}@{host}:{port}/{db}"

    raise RuntimeError(
        "Admin database not configured. Set one of:\n"
        "  - DATABASE_URL_ADMIN (preferred), or\n"
        "  - DATABASE_URL (legacy), or\n"
        "  - ADMIN_DB_USER, ADMIN_DB_PASSWORD, DB_HOST (or REMOTE_VM_IP), "
        "DB_INNER_PORT or DB_PORT, DB_NAME, or\n"
        "  - PGUSER, PGPASSWORD, PGHOST, PGDATABASE [, PGPORT]."
    )


def _normalize_sqlalchemy_url(url: str) -> str:
    u = url.strip()
    if u.startswith("postgres://"):
        return "postgresql+psycopg2://" + u[len("postgres://") :]
    if u.startswith("postgresql://") and "+psycopg2" not in u.split("://", 1)[0]:
        return "postgresql+psycopg2://" + u[len("postgresql://") :]
    return u


def psycopg2_connect_dsn(sqlalchemy_url: str) -> str:
    """Strip ``+psycopg2`` for ``psycopg2.connect(dsn=...)``."""
    return sqlalchemy_url.replace("postgresql+psycopg2://", "postgresql://", 1)
