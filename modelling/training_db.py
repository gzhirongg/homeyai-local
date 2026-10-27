"""Load training data using the read-only DB role (`DATABASE_URL_READ_ONLY` or `READ_ONLY_DB_*`)."""

from __future__ import annotations

import logging
import os
import re
import threading
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse, urlunparse

import pandas as pd
from sqlalchemy import Text, create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _load_env_file() -> None:
    """Populate os.environ using python-dotenv (supports interpolation).

    Walks plausible roots: `/app` (docker-compose backend) then every ancestor of this file.
    Avoids indexing ``parents[2]``: when ``modelling`` is mounted alone at ``/modelling``,
    ``training_db.py`` only has ``parents`` ``/modelling`` and ``/``.
    """

    dirs: list[Path] = [Path("/app")]
    for p in Path(__file__).resolve().parents:
        dirs.append(p)

    seen: set[str] = set()
    for d in dirs:
        key = str(d.resolve())
        if key in seen:
            continue
        seen.add(key)
        candidate = d / ".env"
        if candidate.is_file():
            load_dotenv(dotenv_path=candidate)
            return

    load_dotenv()


def get_mrt_pit_min_years() -> int:
    """Rolling window of resale months for MRT-PIT training (calendar years, env override)."""
    _load_env_file()
    raw = (os.environ.get("MRT_PIT_MIN_YEARS") or "5").strip()
    try:
        y = int(raw)
    except ValueError:
        y = 5
    return max(1, min(y, 50))


def get_training_window_summary(engine: Engine, min_years: int | None = None) -> dict[str, Any]:
    """Counts done job-months inside the rolling window and eligible transactions."""
    my = min_years if min_years is not None else get_mrt_pit_min_years()
    sql = text(
        f"""
        WITH bounds AS (
            SELECT to_char(CURRENT_DATE - ({my} * INTERVAL '1 year'), 'YYYY-MM') AS start_m
        )
        SELECT
            (SELECT start_m FROM bounds) AS window_start_month,
            (SELECT COUNT(DISTINCT j.tx_year_month)::bigint
             FROM mrt_pit_build_jobs j
             WHERE j.status = 'done'
               AND j.tx_year_month >= (SELECT start_m FROM bounds)
            ) AS n_done_months_in_window,
            (SELECT COUNT(*)::bigint
             FROM hdb_resale_transactions t
             INNER JOIN mrt_pit_build_jobs j
               ON j.tx_year_month = t.month AND j.status = 'done'
             INNER JOIN hdb_address_enrichment_onemap oe
               ON oe.id = t.enriched_addr_id
              AND oe.latitude IS NOT NULL
              AND oe.longitude IS NOT NULL
             WHERE t.month >= (SELECT start_m FROM bounds)
            ) AS n_eligible_tx
        """
    )
    with engine.connect() as conn:
        row = dict(conn.execute(sql).mappings().one())
    row["min_years"] = my
    row["expected_min_months"] = my * 12 - 2
    return row


def _postgres_url_replace_loopback(url: str) -> str:
    """Rewrite loopback host in ``DATABASE_URL_READ_ONLY`` for in-network Docker Postgres.

    Laptop ``.env`` often uses ``localhost`` / ``127.0.0.1`` with the host-mapped port; inside a
    worker container the DB listens on ``DB_HOST`` (e.g. ``db-dev``) at ``DB_INNER_PORT`` (5432).
    Opt-in via ``TRAINING_REPLACE_LOOPBACK_PG_HOST`` (Compose sets this for ``prefect-worker-dev``).
    """
    flag = os.environ.get("TRAINING_REPLACE_LOOPBACK_PG_HOST", "").lower()
    if flag not in ("1", "true", "yes"):
        return url
    new_host = (os.environ.get("DB_HOST") or "").strip()
    if not new_host:
        return url
    parsed = urlparse(url)
    if not parsed.scheme.startswith("postgres"):
        return url
    host = (parsed.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        return url
    inner = (os.environ.get("DB_INNER_PORT") or "").strip()
    if inner.isdigit():
        new_port = int(inner)
    elif parsed.port is not None:
        new_port = parsed.port
    else:
        new_port = 5432
    userinfo = ""
    if parsed.username is not None:
        u = quote_plus(parsed.username)
        p_enc = quote_plus(parsed.password or "")
        userinfo = f"{u}:{p_enc}@"
    netloc = f"{userinfo}{new_host}:{new_port}"
    return urlunparse((parsed.scheme, netloc, parsed.path or "", "", "", ""))


def get_training_database_url() -> str:
    """Return the read-only training URL; never fall back to admin ``DATABASE_URL``."""
    _load_env_file()
    url = os.environ.get("DATABASE_URL_READ_ONLY", "").strip()
    if url:
        return _postgres_url_replace_loopback(url)
    user = (os.environ.get("READ_ONLY_DB_USER") or "").strip()
    password = (os.environ.get("READ_ONLY_DB_PASSWORD") or "").strip()
    host = (os.environ.get("DB_HOST") or os.environ.get("REMOTE_VM_IP") or "").strip()
    port = (
        os.environ.get("DB_PORT") or os.environ.get("DB_INNER_PORT") or "5432"
    ).strip()
    db = (os.environ.get("DB_NAME") or "").strip()
    if user and password and host and db:
        u, p = quote_plus(user), quote_plus(password)
        return f"postgresql://{u}:{p}@{host}:{port}/{db}"
    raise RuntimeError(
        "Read-only training DB is not configured. Set DATABASE_URL_READ_ONLY, or set "
        "READ_ONLY_DB_USER, READ_ONLY_DB_PASSWORD, DB_HOST (or REMOTE_VM_IP), "
        "DB_INNER_PORT or DB_PORT, and DB_NAME. Do not use DATABASE_URL_ADMIN or DATABASE_URL for training. "
        "Prefect workers load READ_ONLY_* from the repo-root .env via docker-compose env_file — "
        "see .env.example (ML training / create_ml_readonly_role.sql)."
    )


def create_training_engine() -> Engine:
    return create_engine(get_training_database_url())


_training_engine_singleton: Engine | None = None
_training_engine_lock = threading.Lock()


def get_training_engine() -> Engine:
    """Pooled read-only engine for inference-time lookups (estate maturity, etc.)."""
    global _training_engine_singleton
    if _training_engine_singleton is not None:
        return _training_engine_singleton
    with _training_engine_lock:
        if _training_engine_singleton is None:
            _training_engine_singleton = create_engine(
                get_training_database_url(),
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=2,
            )
        return _training_engine_singleton


def load_hdb_rpi_index_levels(engine: Engine | None = None) -> pd.DataFrame:
    """Quarterly HDB RPI levels from ``hdb_resale_price_index`` (canonical ingest table).

    Columns: ``quarter`` (``YYYY-Q[1-4]``), ``index`` (float). Empty if table missing/empty or on error.
    """
    sql = text(
        """
        SELECT quarter_label AS quarter,
               CAST(index_value AS DOUBLE PRECISION) AS index
          FROM hdb_resale_price_index
         ORDER BY period_start
        """
    )
    own_engine = engine is None
    eng = engine or create_training_engine()
    try:
        df = pd.read_sql_query(sql, eng)
        if df.empty:
            return df
        lc = {str(c).lower(): c for c in df.columns}
        qcol, icol = lc.get("quarter"), lc.get("index")
        if not qcol or not icol:
            return pd.DataFrame(columns=["quarter", "index"])
        out = df[[qcol, icol]].copy()
        out.columns = ["quarter", "index"]
        return out
    except Exception as exc:
        logger.warning("load_hdb_rpi_index_levels skipped: %s", exc)
        return pd.DataFrame(columns=["quarter", "index"])
    finally:
        if own_engine:
            eng.dispose()


# Master Plan Land Use PIT (normalized: per-address × revision_year; joined via catalog).
_HDB_RESALE_MASTERPLAN_SELECT = """
        mp.nearby_high_density_score,
        mp.area_comm_500m,
        mp.area_comm_1000m,
        mp.area_comm_1500m,
        mp.area_park_500m,
        mp.area_park_1000m,
        mp.area_park_1500m,
        mp.area_sports_500m,
        mp.area_sports_1000m,
        mp.area_sports_1500m,
        mp.area_health_500m,
        mp.area_health_1000m,
        mp.area_health_1500m,
        mp.area_worship_500m,
        mp.area_worship_1000m,
        mp.area_worship_1500m,
        mp.dist_cbd,
        mp.dist_airport,
        mp.dist_to_nearest_b2_zone,
        mp.b2_zoning_ratio_1km,
        mp.dist_to_nearest_business_park,
        mp.dist_to_nearest_cemetery,
        mp.dist_to_nearest_special_use"""

_HDB_RESALE_MASTERPLAN_JOIN = """
    LEFT JOIN masterplan_landuse_pit_scalars mp
      ON mp.enriched_addr_id = t.enriched_addr_id
     AND mp.revision_year = (
         SELECT MAX(rc.revision_year)::smallint
         FROM masterplan_revision_catalog rc
         WHERE rc.effective_from <= t.month
     )"""


def _window_start_month_sql(min_years: int) -> str:
    """SQL expression for first month string (YYYY-MM) in the rolling training window."""
    return f"to_char(CURRENT_DATE - ({min_years} * INTERVAL '1 year'), 'YYYY-MM')"


def _resale_jobs_oe_where_fragment(min_years: int) -> str:
    ws = _window_start_month_sql(min_years)
    return f"""
    FROM hdb_resale_transactions t
    INNER JOIN mrt_pit_build_jobs jobs
      ON jobs.tx_year_month = t.month
     AND jobs.status = 'done'
    INNER JOIN hdb_address_enrichment_onemap oe
      ON oe.id = t.enriched_addr_id
     AND oe.latitude IS NOT NULL
     AND oe.longitude IS NOT NULL
    WHERE t.month >= {ws}
    """


def ensure_mrt_training_window_or_raise(engine: Engine, *, min_years: int | None = None) -> None:
    """Raise if the rolling MRT-PIT window is incomplete unless ML_TRAINING_SKIP_MRT_WINDOW_CHECK is set."""
    from sqlalchemy.exc import ProgrammingError

    skip_win = os.environ.get("ML_TRAINING_SKIP_MRT_WINDOW_CHECK", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if skip_win:
        return
    my = min_years if min_years is not None else get_mrt_pit_min_years()
    try:
        summary = get_training_window_summary(engine, min_years=my)
    except ProgrammingError as exc:
        err = str(exc).lower()
        if "mrt_pit_build_jobs" in err or "undefinedtable" in err.replace(" ", ""):
            raise RuntimeError(
                "Table mrt_pit_build_jobs is missing. Run: cd backend && alembic upgrade head "
                "(revision a1b2c3d4e5f6), then populate jobs via build_mrt_pit_snapshot.py."
            ) from exc
        raise
    need = int(summary["expected_min_months"])
    got = int(summary["n_done_months_in_window"])
    if got < need:
        raise RuntimeError(
            f"MRT PIT window incomplete: only {got} fully-built months in the last "
            f"{summary['min_years']} year window (need >= {need} per "
            f"MRT_PIT_MIN_YEARS — complete more months with batch snapshot build, "
            f"or set ML_TRAINING_SKIP_MRT_WINDOW_CHECK=1 to bypass)."
        )


def query_baseline_resale_dataframe(engine: Engine, *, min_years: int | None = None) -> pd.DataFrame:
    """Resale + geocode only (no MRT pit snapshot join, no masterplan join).

    Used by build-on-the-fly dataset assembly so feature pillars merge only what they need.
    """
    my = min_years if min_years is not None else get_mrt_pit_min_years()
    ensure_mrt_training_window_or_raise(engine, min_years=my)
    sql = f"""
    SELECT
        t.month,
        t.town,
        t.flat_type,
        t.block,
        t.street_name,
        t.storey_range,
        t.floor_area_sqm,
        t.flat_model,
        t.lease_commence_date,
        t.remaining_lease_years,
        t.resale_price,
        t.enriched_addr_id,
        oe.latitude AS lat,
        oe.longitude AS lon
    {_resale_jobs_oe_where_fragment(my)}
    ORDER BY t.month NULLS LAST, t.id
    """
    return pd.read_sql(text(sql), engine)


def query_mrt_pit_features_window_dataframe(engine: Engine, *, min_years: int | None = None) -> pd.DataFrame:
    """MRT PIT snapshot rows restricted to the resale training window (by transaction month)."""
    my = min_years if min_years is not None else get_mrt_pit_min_years()
    ws = _window_start_month_sql(my)
    sql = f"""
    SELECT
        f.hdb_addr_id AS enriched_addr_id,
        f.tx_year_month AS month,
        f.dist_to_nearest_op_mrt,
        f.travel_time_to_active_mrt,
        f.pt_time_savings_vs_walk,
        f.line_connectivity_index,
        f.nearest_op_lines,
        f.days_since_mrt_announcement,
        f.days_to_mrt_opening,
        f.speculative_upside_score,
        f.has_future_upside,
        f.nearest_planned_lines,
        f.is_proximity_nuisance,
        f.num_unique_lines_within_1km,
        f.nearest_planned_mrt_dist
    FROM hdb_mrt_features_pit_snapshot f
    WHERE f.tx_year_month >= {ws}
    ORDER BY f.tx_year_month NULLS LAST, f.hdb_addr_id NULLS LAST
    """
    try:
        return pd.read_sql(text(sql), engine)
    except Exception as exc:
        if _snapshot_denied(exc):
            raise RuntimeError(
                "Dynamic dataset build requires SELECT on hdb_mrt_features_pit_snapshot. "
                "Run backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql as a superuser."
            ) from exc
        raise


def query_masterplan_landuse_window_dataframe(engine: Engine, *, min_years: int | None = None) -> pd.DataFrame:
    """Masterplan land-use PIT scalars joined to resale rows in the training window (keys + mp columns)."""
    my = min_years if min_years is not None else get_mrt_pit_min_years()
    ensure_mrt_training_window_or_raise(engine, min_years=my)
    ws = _window_start_month_sql(my)
    sql = f"""
    SELECT
        t.enriched_addr_id,
        t.month,
        {_HDB_RESALE_MASTERPLAN_SELECT}
    FROM hdb_resale_transactions t
    INNER JOIN mrt_pit_build_jobs jobs
      ON jobs.tx_year_month = t.month
     AND jobs.status = 'done'
    INNER JOIN hdb_address_enrichment_onemap oe
      ON oe.id = t.enriched_addr_id
     AND oe.latitude IS NOT NULL
     AND oe.longitude IS NOT NULL
    LEFT JOIN masterplan_landuse_pit_scalars mp
      ON mp.enriched_addr_id = t.enriched_addr_id
     AND mp.revision_year = (
         SELECT MAX(rc.revision_year)::smallint
         FROM masterplan_revision_catalog rc
         WHERE rc.effective_from <= t.month
     )
    WHERE t.month >= {ws}
    ORDER BY t.month NULLS LAST, t.id
    """
    return pd.read_sql(text(sql), engine)


_ESTATE_MATURITY_SELECT = """
        em.avg_residential_block_age_years,
        em.town_completed_residential_units_stock,
        em.town_land_area_km2,
        em.town_dwelling_unit_density,
        em.town_units_under_construction,
        em.town_hdb_completed_units_roll36m,
        em.town_supply_maturity_ratio
"""


def query_estate_maturity_window_dataframe(engine: Engine, *, min_years: int | None = None) -> pd.DataFrame:
    """Estate maturity panel: one row per ``(town_normalized, year_month)``.

    Must stay at **panel grain** (same PK as ``hdb_estate_maturity_by_town_month``). Returning
    one row per resale transaction and merging in pandas on ``(town, month)`` would Cartesian-
    multiply rows (~avg transactions per town-month).
    """
    my = min_years if min_years is not None else get_mrt_pit_min_years()
    ensure_mrt_training_window_or_raise(engine, min_years=my)
    ws = _window_start_month_sql(my)
    sql = f"""
    SELECT
        em.town_normalized,
        em.year_month AS month,
        {_ESTATE_MATURITY_SELECT}
    FROM hdb_estate_maturity_by_town_month em
    WHERE em.year_month >= {ws}
    ORDER BY em.year_month NULLS LAST, em.town_normalized NULLS LAST
    """
    return pd.read_sql(text(sql), engine)


def _hdb_resale_select_core(*, min_years: int, lateral_fn: bool) -> str:
    f_join = (
        """LEFT JOIN LATERAL (
        SELECT * FROM hdb_mrt_features_at(
            t.enriched_addr_id,
            (t.month || '-01')::date
        )
    ) f ON (t.enriched_addr_id IS NOT NULL AND t.month IS NOT NULL)"""
        if lateral_fn
        else """LEFT JOIN hdb_mrt_features_pit_snapshot f
      ON f.hdb_addr_id = t.enriched_addr_id
     AND f.tx_year_month = t.month"""
    )
    return f"""
    SELECT
        t.month,
        t.town,
        t.flat_type,
        t.block,
        t.street_name,
        t.storey_range,
        t.floor_area_sqm,
        t.flat_model,
        t.lease_commence_date,
        t.remaining_lease_years,
        t.resale_price,
        t.enriched_addr_id,
        oe.latitude AS lat,
        oe.longitude AS lon,
        f.dist_to_nearest_op_mrt,
        f.travel_time_to_active_mrt,
        f.pt_time_savings_vs_walk,
        f.line_connectivity_index,
        f.nearest_op_lines,
        f.days_since_mrt_announcement,
        f.days_to_mrt_opening,
        f.speculative_upside_score,
        f.has_future_upside,
        f.nearest_planned_lines,
        f.is_proximity_nuisance,
        f.num_unique_lines_within_1km,
        f.nearest_planned_mrt_dist,
{_HDB_RESALE_MASTERPLAN_SELECT}
    FROM hdb_resale_transactions t
    INNER JOIN mrt_pit_build_jobs jobs
      ON jobs.tx_year_month = t.month
     AND jobs.status = 'done'
    INNER JOIN hdb_address_enrichment_onemap oe
      ON oe.id = t.enriched_addr_id
     AND oe.latitude IS NOT NULL
     AND oe.longitude IS NOT NULL
    {f_join}
{_HDB_RESALE_MASTERPLAN_JOIN}
    WHERE t.month >= to_char(CURRENT_DATE - ({min_years} * INTERVAL '1 year'), 'YYYY-MM')
    """


def get_hdb_resale_query(*, min_years: int | None = None) -> Text:
    my = min_years if min_years is not None else get_mrt_pit_min_years()
    return text(
        _hdb_resale_select_core(min_years=my, lateral_fn=False)
        + """
    ORDER BY t.month NULLS LAST, t.id
    """
    )


def get_hdb_resale_query_via_function(*, min_years: int | None = None) -> Text:
    my = min_years if min_years is not None else get_mrt_pit_min_years()
    return text(
        _hdb_resale_select_core(min_years=my, lateral_fn=True)
        + """
    ORDER BY t.month NULLS LAST, t.id
    """
    )


# Back-compat: default window at import time (prefer ``get_hdb_resale_query()`` in new code).
HDB_RESALE_QUERY = get_hdb_resale_query()
HDB_RESALE_QUERY_VIA_FUNCTION = get_hdb_resale_query_via_function()


def get_hdb_resale_bootstrap_query(limit: int) -> Text:
    """Newest ``limit`` resale rows in rolling window + joins (fast Modal/smoke snapshots).

    Uses ``hdb_mrt_features_pit_snapshot`` (same as full training export). Prefer this over
    wrapping the full ordered query in ``LIMIT`` — Postgres would still sort/scan the full
    join before the limit applies.

    Requires SELECT on ``hdb_mrt_features_pit_snapshot`` plus
    ``masterplan_revision_catalog`` and ``masterplan_landuse_pit_scalars``
    for the read-only role (see ``grant_ml_readonly_mrt_snapshot.sql``). For environments without that grant, set
    ``ML_TRAINING_BOOTSTRAP_USE_LATERAL=1`` to use per-row ``hdb_mrt_features_at()`` instead
    (much slower).
    """
    use_lat = os.environ.get("ML_TRAINING_BOOTSTRAP_USE_LATERAL", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if use_lat:
        return text(_hdb_resale_sql_via_function_limited(limit))
    return text(_hdb_resale_sql_pit_snapshot_limited(limit))


def _hdb_resale_sql_pit_snapshot_limited(n: int) -> str:
    """Same columns as ``get_hdb_resale_query`` but restricted to N newest window txs first."""
    if n < 500 or n > 2_000_000:
        raise ValueError("limit must be between 500 and 2000000")
    my = get_mrt_pit_min_years()
    return f"""
    WITH txs AS (
        SELECT * FROM hdb_resale_transactions
        WHERE month >= to_char(CURRENT_DATE - ({my} * INTERVAL '1 year'), 'YYYY-MM')
        ORDER BY month DESC NULLS LAST, id DESC
        LIMIT {int(n)}
    )
    SELECT
        t.month,
        t.town,
        t.flat_type,
        t.block,
        t.street_name,
        t.storey_range,
        t.floor_area_sqm,
        t.flat_model,
        t.lease_commence_date,
        t.remaining_lease_years,
        t.resale_price,
        t.enriched_addr_id,
        oe.latitude AS lat,
        oe.longitude AS lon,
        f.dist_to_nearest_op_mrt,
        f.travel_time_to_active_mrt,
        f.pt_time_savings_vs_walk,
        f.line_connectivity_index,
        f.nearest_op_lines,
        f.days_since_mrt_announcement,
        f.days_to_mrt_opening,
        f.speculative_upside_score,
        f.has_future_upside,
        f.nearest_planned_lines,
        f.is_proximity_nuisance,
        f.num_unique_lines_within_1km,
        f.nearest_planned_mrt_dist,{_HDB_RESALE_MASTERPLAN_SELECT}
    FROM txs t
    INNER JOIN mrt_pit_build_jobs jobs
      ON jobs.tx_year_month = t.month
     AND jobs.status = 'done'
    INNER JOIN hdb_address_enrichment_onemap oe
      ON oe.id = t.enriched_addr_id
     AND oe.latitude IS NOT NULL
     AND oe.longitude IS NOT NULL
    LEFT JOIN hdb_mrt_features_pit_snapshot f
      ON f.hdb_addr_id = t.enriched_addr_id
     AND f.tx_year_month = t.month
{_HDB_RESALE_MASTERPLAN_JOIN}
    ORDER BY t.month NULLS LAST, t.id
    """


def _hdb_resale_sql_via_function_limited(n: int) -> str:
    """N newest rows by transaction time, then chronological order for temporal CV."""
    if n < 500 or n > 2_000_000:
        raise ValueError("limit must be between 500 and 2000000")
    my = get_mrt_pit_min_years()
    return f"""
    WITH txs AS (
        SELECT * FROM hdb_resale_transactions
        WHERE month >= to_char(CURRENT_DATE - ({my} * INTERVAL '1 year'), 'YYYY-MM')
        ORDER BY month DESC NULLS LAST, id DESC
        LIMIT {int(n)}
    )
    SELECT
        t.month,
        t.town,
        t.flat_type,
        t.block,
        t.street_name,
        t.storey_range,
        t.floor_area_sqm,
        t.flat_model,
        t.lease_commence_date,
        t.remaining_lease_years,
        t.resale_price,
        t.enriched_addr_id,
        oe.latitude AS lat,
        oe.longitude AS lon,
        f.dist_to_nearest_op_mrt,
        f.travel_time_to_active_mrt,
        f.pt_time_savings_vs_walk,
        f.line_connectivity_index,
        f.nearest_op_lines,
        f.days_since_mrt_announcement,
        f.days_to_mrt_opening,
        f.speculative_upside_score,
        f.has_future_upside,
        f.nearest_planned_lines,
        f.is_proximity_nuisance,
        f.num_unique_lines_within_1km,
        f.nearest_planned_mrt_dist,{_HDB_RESALE_MASTERPLAN_SELECT}
    FROM txs t
    INNER JOIN mrt_pit_build_jobs jobs
      ON jobs.tx_year_month = t.month AND jobs.status = 'done'
    INNER JOIN hdb_address_enrichment_onemap oe
      ON oe.id = t.enriched_addr_id
     AND oe.latitude IS NOT NULL
     AND oe.longitude IS NOT NULL
    LEFT JOIN LATERAL (
        SELECT * FROM hdb_mrt_features_at(
            t.enriched_addr_id,
            (t.month || '-01')::date
        )
    ) f ON (t.enriched_addr_id IS NOT NULL AND t.month IS NOT NULL)
{_HDB_RESALE_MASTERPLAN_JOIN}
    ORDER BY t.month NULLS LAST, t.id
    """


def _snapshot_denied(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "hdb_mrt_features_pit_snapshot" in msg and ("permission denied" in msg or "insufficientprivilege" in msg.replace(" ", ""))


def load_hdb_resale_dataframe_from_db(engine: Engine | None = None) -> pd.DataFrame:
    """Load the same HDB columns as the parquet pipeline expects."""
    own_engine = engine is None
    if own_engine:
        engine = create_training_engine()
    try:
        force_fn = os.environ.get("ML_TRAINING_USE_MRT_FUNCTION", "").lower() in ("1", "true", "yes")
        ensure_mrt_training_window_or_raise(engine)
        if force_fn:
            warnings.warn(
                "ML_TRAINING_USE_MRT_FUNCTION: computing MRT columns via hdb_mrt_features_at() per row — "
                "very slow on full history; prefer GRANT SELECT on hdb_mrt_features_pit_snapshot "
                "(see backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql).",
                stacklevel=2,
            )
            return pd.read_sql(get_hdb_resale_query_via_function(), engine)
        try:
            return pd.read_sql(get_hdb_resale_query(), engine)
        except Exception as exc:
            if not _snapshot_denied(exc):
                raise
            lim_raw = os.environ.get("ML_TRAINING_FALLBACK_LATERAL_LIMIT", "").strip()
            if lim_raw.isdigit():
                n = int(lim_raw)
                warnings.warn(
                    f"Snapshot table not readable for read-only role; loading {n} newest rows with "
                    "hdb_mrt_features_at() per row. Grant SELECT on hdb_mrt_features_pit_snapshot for "
                    "full-history snapshot loads (see backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql).",
                    stacklevel=2,
                )
                try:
                    return pd.read_sql(text(_hdb_resale_sql_via_function_limited(n)), engine)
                except Exception as lateral_exc:
                    raise RuntimeError(
                        "Could not load training data. (1) Prefer: run as superuser "
                        "backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql so the read-only role "
                        "can SELECT hdb_mrt_features_pit_snapshot. "
                        "(2) Lateral fallback failed because hdb_mrt_features_at runs as the invoker "
                        "and may need SELECT on hdb_mrt_routes and other MRT tables — see comments in "
                        "that SQL file, or define the function SECURITY DEFINER (DB change)."
                    ) from lateral_exc
            raise RuntimeError(
                "Read-only user lacks SELECT on public.hdb_mrt_features_pit_snapshot. "
                "As a superuser or table owner run:\n"
                "  psql … -f backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql\n"
                "Or set ML_TRAINING_FALLBACK_LATERAL_LIMIT=80000 to try hdb_mrt_features_at() on the "
                "N newest rows only (requires additional table privileges; snapshot GRANT is simpler)."
            ) from exc
    finally:
        if own_engine:
            engine.dispose()


def load_hdb_mrt_pit_snapshot_dataframe(engine: Engine | None = None) -> pd.DataFrame:
    """Whole-table export of ``hdb_mrt_features_pit_snapshot`` (for parquet sidecars uploaded to MinIO)."""
    own_engine = engine is None
    if own_engine:
        engine = create_training_engine()
    try:
        return pd.read_sql(
            text(
                """
                SELECT *
                FROM hdb_mrt_features_pit_snapshot
                ORDER BY hdb_addr_id NULLS LAST, tx_year_month NULLS LAST
                """
            ),
            engine,
        )
    finally:
        if own_engine:
            engine.dispose()
