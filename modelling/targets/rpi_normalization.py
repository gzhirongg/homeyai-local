"""RPI-adjusted resale target: Postgres ``hdb_resale_price_index`` first, MinIO/API fallback."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

_RPI_DB_LEVELS_LOCK = threading.Lock()
# TTL cache keyed by Postgres URL — avoids reconnect + full-table scan each valuation.
_RPI_DB_LEVELS_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_RPI_DB_CACHE_TTL_SEC = float(os.getenv("HOMEYAI_RPI_DB_CACHE_TTL_SEC", "300"))

_RPI_SERIES_FALLBACK_LOCK = threading.Lock()
_RPI_SERIES_FALLBACK_CACHE: dict[str, tuple[float, pd.DataFrame, str]] = {}
_RPI_SERIES_FALLBACK_TTL_SEC = float(os.getenv("HOMEYAI_RPI_SERIES_FALLBACK_CACHE_TTL_SEC", "300"))


TARGET_NORMALIZATION_RPI_BASELINE_100 = "rpi_baseline_100"
TARGET_COLUMN_TRAIN_ADJUSTED = "resale_price_rpi_adj"


def repo_root_default() -> Path:
    return Path(__file__).resolve().parents[2]


def _manifest_cfg(project_root: Path | None) -> dict[str, Any] | None:
    try:
        from modelling.config.minio_sources import load_minio_sources_dict

        return load_minio_sources_dict(project_root or repo_root_default())
    except (FileNotFoundError, KeyError, OSError, ValueError):
        return None


def _csv_macro_from_minio(project_root: Path, logical: str) -> pd.DataFrame | None:
    mc = _manifest_cfg(project_root)
    if mc is None:
        return None
    try:
        from modelling.config.minio_sources import resolve_object
        from modelling.storage.minio_io import load_csv_dataframe, object_exists

        bk = resolve_object(mc, logical)
        if not object_exists(bk.bucket, bk.key):
            return None
        return load_csv_dataframe(bk.bucket, bk.key)
    except KeyError:
        return None


def sale_quarter_labels(months: pd.Series | pd.Index | np.ndarray) -> np.ndarray:
    """Map ``YYYY-MM`` month strings to ``YYYY-Qn`` labels."""
    ts = pd.to_datetime(pd.Series(months).astype(str), format="%Y-%m", errors="coerce")
    out = ts.dt.year.astype(str) + "-Q" + ts.dt.quarter.astype(str)
    return out.fillna("").to_numpy(dtype=object)


def _normalize_levels_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    lc = {str(c).lower(): c for c in df.columns}
    qc, ic = lc.get("quarter"), lc.get("index")
    if not qc or not ic:
        return pd.DataFrame(columns=["quarter", "index"])
    out = df[[qc, ic]].rename(columns={qc: "quarter", ic: "index"})
    out["index"] = pd.to_numeric(out["index"], errors="coerce")
    out = out.dropna(subset=["index", "quarter"])
    out = out[out["quarter"].astype(str).str.len() > 0]
    out["quarter"] = out["quarter"].astype(str)
    out = out.drop_duplicates(subset=["quarter"], keep="first").sort_values("quarter")
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=["index"])
    out = out[out["index"] > 0]
    return out.reset_index(drop=True)


def _best_rpi_index_for_valuation_quarter(lev: pd.DataFrame, ql: str) -> tuple[float | None, bool]:
    """Return ``(index_value, used_carry_forward)``.

    Prefer an exact quarter match on ``ql``. If missing (in-flight quarter not yet published),
    use the latest row whose ``quarter`` label compares ``<= ql`` lexicographically
    ("YYYY-Q1".."YYYY-Q4"; ``lev`` is sorted ascending).

    Returns ``(None, False)`` if no qualifying row exists.
    """
    if lev.empty:
        return None, False
    q = str(ql).strip() if ql else ""
    if not q:
        return None, False

    work = lev.assign(_q=lambda d: d["quarter"].astype(str))
    exact = work.loc[work["_q"] == q, "index"]
    if len(exact):
        try:
            val = float(exact.iloc[0])
            if np.isfinite(val) and val > 0:
                return val, False
        except (TypeError, ValueError):
            pass

    cand = work.loc[work["_q"] <= q]
    if cand.empty:
        return None, False
    last_idx = cand["index"].iloc[-1]
    try:
        val = float(last_idx)
    except (TypeError, ValueError):
        return None, False
    if not np.isfinite(val) or val <= 0:
        return None, False
    used_fallback = cand["_q"].iloc[-1] != q
    if used_fallback:
        logger.info(
            "rpi_inference_carry_forward requested_quarter=%s using_quarter=%s index=%s",
            q,
            cand["_q"].iloc[-1],
            val,
        )
    return val, used_fallback


def load_rpi_levels_minio(project_root: Path | None = None) -> pd.DataFrame:
    """RPI quarterly levels from MinIO manifest key ``macro_rpi_csv`` (``quarter``, ``index``)."""
    root = project_root or repo_root_default()
    got = _csv_macro_from_minio(root, "macro_rpi_csv")
    if got is None:
        return pd.DataFrame(columns=["quarter", "index"])
    return _normalize_levels_dataframe(got)


def load_rpi_levels_api(*, verbose: bool = False) -> pd.DataFrame:
    """Fetch RPI quarterly levels from data.gov.sg (last resort offline training)."""
    dataset_id = "d_14f63e595975691e7c24a27ae4c07c79"
    url = f"https://data.gov.sg/api/action/datastore_search?resource_id={dataset_id}&limit=10000"
    max_attempts = int(os.getenv("HOMEYAI_MACRO_RPI_MAX_ATTEMPTS", "5"))
    fail_fast = os.getenv("HOMEYAI_MACRO_FETCH_FAIL_FAST", "").lower() in ("1", "true", "yes")

    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                payload = resp.json()
                records = payload.get("result", {}).get("records", [])
                if not records:
                    break
                df = pd.DataFrame(records)[["quarter", "index"]].copy()
                df["index"] = pd.to_numeric(df["index"], errors="coerce")
                lev = _normalize_levels_dataframe(df)
                if not lev.empty and verbose:
                    print(f"Fetched {len(lev)} RPI quarters from data.gov.sg")
                return lev
            if resp.status_code == 429:
                time.sleep(15)
                continue
        except (requests.ConnectionError, requests.Timeout, TimeoutError, OSError) as exc:
            logger.warning(
                "load_rpi_levels_api: network error (%s/%s): %s",
                attempt + 1,
                max_attempts,
                exc,
            )
            if fail_fast:
                raise RuntimeError(
                    "RPI HTTP fetch failed with HOMEYAI_MACRO_FETCH_FAIL_FAST set. "
                    "Use hdb_resale_price_index Postgres ingest or macro_rpi_csv in MinIO."
                ) from exc
        except Exception as exc:
            logger.warning(
                "load_rpi_levels_api: unexpected error (%s/%s): %s",
                attempt + 1,
                max_attempts,
                exc,
                exc_info=True,
            )
            if fail_fast:
                raise
        time.sleep(5)

    logger.warning(
        "load_rpi_levels_api: giving up after %s attempts — empty RPI series",
        max_attempts,
    )
    return pd.DataFrame(columns=["quarter", "index"])


def load_rpi_levels_database(database_url: str) -> pd.DataFrame:
    """Load levels using an explicit Postgres URL (inference backend)."""
    url_key = str(database_url or "").strip()
    if not url_key or url_key.startswith("sqlite"):
        return pd.DataFrame(columns=["quarter", "index"])

    now_mono = time.monotonic()
    with _RPI_DB_LEVELS_LOCK:
        cached = _RPI_DB_LEVELS_CACHE.get(url_key)
        if cached is not None and cached[0] > now_mono:
            return cached[1].copy()

    eng = create_engine(url_key)
    try:
        sql = text(
            """
            SELECT quarter_label AS quarter,
                   CAST(index_value AS DOUBLE PRECISION) AS index
              FROM hdb_resale_price_index
             ORDER BY period_start
            """
        )
        df = pd.read_sql_query(sql, eng)
        out = _normalize_levels_dataframe(df)
    except Exception:
        logger.warning("load_rpi_levels_database: query failed — treat as unavailable", exc_info=True)
        out = pd.DataFrame(columns=["quarter", "index"])
    finally:
        eng.dispose()

    if not out.empty:
        ttl = max(10.0, _RPI_DB_CACHE_TTL_SEC)
        expiry = now_mono + ttl
        with _RPI_DB_LEVELS_LOCK:
            _RPI_DB_LEVELS_CACHE[url_key] = (expiry, out.copy())
    return out


def load_rpi_index_series(
    project_root: Path | None = None,
    *,
    database_url: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """Return ``(levels_df, source_name)`` with columns ``quarter``, ``index``.

    Order: explicit ``database_url`` → training read-only DB → MinIO → data.gov.sg.
    """
    root = project_root or repo_root_default()

    if database_url and not str(database_url).startswith("sqlite"):
        db_df = load_rpi_levels_database(str(database_url).strip())
        if not db_df.empty:
            return db_df, "postgres"

    root_key = str(root.resolve())
    now_mono_fallback = time.monotonic()
    with _RPI_SERIES_FALLBACK_LOCK:
        fb = _RPI_SERIES_FALLBACK_CACHE.get(root_key)
        if fb is not None and fb[0] > now_mono_fallback:
            return fb[1].copy(), fb[2]

    resolved: tuple[pd.DataFrame, str] | None = None

    try:
        from modelling.training_db import load_hdb_rpi_index_levels

        db_df = load_hdb_rpi_index_levels()
        if not db_df.empty:
            norm = _normalize_levels_dataframe(db_df)
            if not norm.empty:
                resolved = (norm, "postgres")
    except RuntimeError:
        logger.info("load_rpi_index_series: read-only Postgres unavailable; falling back to MinIO/API")
    except Exception:
        logger.warning("load_rpi_index_series: Postgres RPI lookup failed — trying MinIO/API", exc_info=True)

    if resolved is None:
        minio_df = load_rpi_levels_minio(root)
        if not minio_df.empty:
            resolved = (minio_df, "minio")

    if resolved is None:
        api_df = load_rpi_levels_api(verbose=False)
        if not api_df.empty:
            resolved = (api_df, "api")

    if resolved is None:
        out_df = pd.DataFrame(columns=["quarter", "index"])
        return out_df, "none"

    out_df, src = resolved
    if not out_df.empty:
        ttl = max(30.0, _RPI_SERIES_FALLBACK_TTL_SEC)
        expire_at = now_mono_fallback + ttl
        with _RPI_SERIES_FALLBACK_LOCK:
            _RPI_SERIES_FALLBACK_CACHE[root_key] = (expire_at, out_df.copy(), src)
    return out_df, src


def align_rpi_index_to_months(months: pd.Series, rpi_df: pd.DataFrame) -> np.ndarray:
    """One RPI index per row, aligned to calendar quarter of ``month`` (``YYYY-MM``)."""
    n = int(len(months))
    if n == 0:
        return np.zeros(0, dtype=float)
    if rpi_df.empty:
        return np.full(n, np.nan, dtype=float)

    q = sale_quarter_labels(months)
    work = pd.DataFrame({"month": months.values, "quarter": q, "_ord": np.arange(n, dtype=int)})
    src = rpi_df[["quarter", "index"]].drop_duplicates(subset=["quarter"]).copy()
    src["quarter"] = src["quarter"].astype(str)
    m = work.merge(src, on="quarter", how="left", validate="m:1")
    m["_ts"] = pd.to_datetime(m["month"], format="%Y-%m", errors="coerce")
    ms = m.sort_values("_ts").copy()
    filled = pd.to_numeric(ms["index"], errors="coerce").ffill().bfill()
    ms["_filled"] = filled.to_numpy(dtype=float)
    out = ms.sort_values("_ord")["_filled"].to_numpy(dtype=float)
    return out


def validate_rpi_alignment(aligned: np.ndarray, *, context: str, max_missing_rate: float = 0.01) -> None:
    """Ensure at most ``max_missing_rate`` rows lack a positive finite RPI after merge+fill."""
    if len(aligned) == 0:
        return
    bad = ~np.isfinite(aligned) | (aligned <= 0)
    rate = float(np.mean(bad))
    if rate > max_missing_rate:
        raise RuntimeError(
            f"{context}: {rate:.1%} of rows lack a valid RPI index (max allowed {max_missing_rate:.1%}). "
            "Run backend/scripts/ingest_hdb_rpi.py and ensure MinIO macro_rpi_csv or DB is populated."
        )


def adjust_prices_to_baseline100(
    prices: np.ndarray | pd.Series | float,
    rpi_index: np.ndarray | float,
) -> np.ndarray | float:
    """Constant 2009-Q1=100 dollars: ``price / RPI * 100``."""
    p = np.asarray(prices, dtype=float)
    r = np.asarray(rpi_index, dtype=float)
    if np.any(~np.isfinite(r)) | np.any(r <= 0):
        raise ValueError("adjust_prices_to_baseline100: RPI indices must be finite and positive")
    return (p / r) * 100.0


def rescale_adjusted_to_nominal(
    adjusted_prices: np.ndarray | pd.Series | float,
    rpi_index: np.ndarray | float,
) -> np.ndarray | float:
    """Map model output (adjusted SGD) back to nominal resale dollars."""
    adj = np.asarray(adjusted_prices, dtype=float)
    r = np.asarray(rpi_index, dtype=float)
    if np.any(~np.isfinite(r)) | np.any(r <= 0):
        raise ValueError("rescale_adjusted_to_nominal: RPI indices must be finite and positive")
    return (adj * r) / 100.0


def quarter_label_from_month(valuation_month: str) -> str:
    ym = valuation_month.strip() if valuation_month else pd.Timestamp.utcnow().strftime("%Y-%m")
    ts = pd.to_datetime(pd.Series([ym]), format="%Y-%m", errors="coerce").iloc[0]
    if pd.isna(ts):
        ts = pd.Timestamp.utcnow()
    return f"{int(ts.year)}-Q{int(ts.quarter)}"


def rpi_index_for_valuation_month(
    valuation_month: str,
    *,
    project_root: Path | None = None,
    database_url: str | None = None,
) -> tuple[float | None, str]:
    """Return ``(index_value, source)`` for rescaling nominal SGD predictions.

    Uses the quarterly RPI matching the valuation month calendar quarter when published.
    When that quarter is missing (ahead of latest open-data release), carries forward the
    latest published quarter strictly on or before that calendar quarter — see §9 Modelling_System_Design.
    """
    root = project_root or repo_root_default()
    ql = quarter_label_from_month(valuation_month)
    seen: set[str] = set()
    urls_ordered: list[str] = []

    def _enqueue(url: str | None) -> None:
        if not url or url.startswith("sqlite"):
            return
        u = url.strip()
        if u and u not in seen:
            seen.add(u)
            urls_ordered.append(u)

    def _with_carry_tag(base: str, carry: bool) -> str:
        if carry and base and base != "none":
            return f"{base}_carryforward"
        return base if base else "none"

    _enqueue(database_url)
    _enqueue(os.getenv("DATABASE_URL_ADMIN"))
    _enqueue(os.getenv("DATABASE_URL"))
    _enqueue(os.getenv("DATABASE_URL_READ_ONLY"))

    for url in urls_ordered:
        lev = load_rpi_levels_database(url)
        idx, cf = _best_rpi_index_for_valuation_quarter(lev, ql)
        if idx is not None:
            return idx, _with_carry_tag("postgres", cf)

    series, src = load_rpi_index_series(root, database_url=None)
    if not series.empty:
        idx, cf = _best_rpi_index_for_valuation_quarter(series, ql)
        if idx is not None:
            return idx, _with_carry_tag(src, cf)

    return None, "none"


__all__ = [
    "TARGET_COLUMN_TRAIN_ADJUSTED",
    "TARGET_NORMALIZATION_RPI_BASELINE_100",
    "adjust_prices_to_baseline100",
    "align_rpi_index_to_months",
    "load_rpi_index_series",
    "load_rpi_levels_api",
    "load_rpi_levels_database",
    "load_rpi_levels_minio",
    "quarter_label_from_month",
    "rescale_adjusted_to_nominal",
    "repo_root_default",
    "rpi_index_for_valuation_month",
    "sale_quarter_labels",
    "validate_rpi_alignment",
]
