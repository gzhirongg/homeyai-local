"""Macro numeric features aligned to resale rows (lagged volume, rates).

RPI is **not** a model input: target resale prices are normalized by RPI separately
(`modelling.targets.rpi_normalization`).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd


try:
    import urllib3

    _HAVE_URllib3 = True
except ImportError:
    urllib3 = None  # type: ignore[assignment]
    _HAVE_URllib3 = False

logger = logging.getLogger(__name__)

MACRO_NUMERIC_FEATURES = ["volume_lagged_3m", "interest_rate_lagged"]

_MACRO_MINIO_CACHE_LOCK = threading.Lock()
_MACRO_MINIO_DF_CACHE: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}
_MACRO_CACHE_TTL_SEC = float(os.getenv("HOMEYAI_MACRO_CACHE_TTL_SEC", "300"))
_MACRO_INFERENCE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _cached_minio_dataframe(
    bucket: str,
    object_key: str,
    *,
    fmt: Literal["csv", "parquet"],
) -> pd.DataFrame | None:
    """Load a MinIO blob with process-local TTL cache keyed by ``(bucket, object_key)``."""
    from modelling.storage.minio_io import load_csv_dataframe, load_parquet_dataframe, object_exists

    ck = (bucket, object_key)
    now_mono = time.monotonic()
    with _MACRO_MINIO_CACHE_LOCK:
        ent = _MACRO_MINIO_DF_CACHE.get(ck)
        if ent is not None and ent[0] > now_mono:
            return ent[1].copy()

    if not object_exists(bucket, object_key):
        return None

    if fmt == "parquet":
        df = load_parquet_dataframe(bucket, object_key)
    else:
        df = load_csv_dataframe(bucket, object_key)

    ttl = max(10.0, _MACRO_CACHE_TTL_SEC)
    expire_at = now_mono + ttl
    with _MACRO_MINIO_CACHE_LOCK:
        _MACRO_MINIO_DF_CACHE[ck] = (expire_at, df.copy())
    return df


def repo_root_default() -> Path:
    return Path(__file__).resolve().parents[2]


def _manifest_cfg(project_root: Path | None) -> dict[str, Any] | None:
    try:
        from modelling.config.minio_sources import load_minio_sources_dict

        return load_minio_sources_dict(project_root or repo_root_default())
    except (FileNotFoundError, KeyError, OSError, ValueError):
        return None


def _volume_from_minio_manifest(project_root: Path) -> pd.DataFrame | None:
    mc = _manifest_cfg(project_root)
    if mc is None:
        return None
    try:
        from modelling.config.minio_sources import resolve_object

        bk = resolve_object(mc, "global_volume_monthly")
        return _cached_minio_dataframe(bk.bucket, bk.key, fmt="parquet")
    except KeyError:
        return None


def _csv_macro_from_minio(project_root: Path, logical: str) -> pd.DataFrame | None:
    mc = _manifest_cfg(project_root)
    if mc is None:
        return None
    try:
        from modelling.config.minio_sources import resolve_object

        bk = resolve_object(mc, logical)
        return _cached_minio_dataframe(bk.bucket, bk.key, fmt="csv")
    except KeyError:
        return None


def fetch_interest_rates(project_root: Path | None = None, *, verbose: bool = False) -> pd.DataFrame:
    """Monthly lagged blended rate columns ``year_month``, ``interest_rate_lagged``."""
    root = project_root or repo_root_default()
    mo = _csv_macro_from_minio(root, "macro_interest_csv")
    if mo is not None:
        lc = {str(c).lower(): c for c in mo.columns}
        ed, dr = lc.get("end_of_day"), lc.get("daily_rate")
        if ed and dr:
            slab = mo[[ed, dr]].copy()
            slab.columns = ["end_of_day", "daily_rate"]
            return _process_interest_rates(slab)

    api_key = (os.getenv("MAS_API_KEY") or "").strip()
    if not api_key or not _HAVE_URllib3:
        if verbose and not api_key:
            print("MAS_API_KEY not set — macro interest_rate_lagged will be zeros unless MinIO CSV is present.")
        return pd.DataFrame(columns=["year_month", "interest_rate_lagged"])

    url = (
        "https://eservices.mas.gov.sg/apimg-gw/server/monthly_statistical_bulletin_non610mssql/"
        "domestic_interest_rates_daily/views/domestic_interest_rates_daily"
    )
    if verbose:
        print("Fetching MAS domestic rates…")
    try:
        http = urllib3.PoolManager()
        response = http.request("GET", url, headers={"keyid": api_key}, timeout=30.0)
        if response.status != 200:
            logger.warning(
                "fetch_interest_rates: MAS HTTP status %s — interest_rate_lagged will be zeros",
                response.status,
            )
            return pd.DataFrame(columns=["year_month", "interest_rate_lagged"])
        raw = json.loads(response.data.decode("utf-8"))
        records = raw.get("elements", []) if isinstance(raw, dict) else []
        if not records:
            logger.warning("fetch_interest_rates: MAS returned empty elements")
            return pd.DataFrame(columns=["year_month", "interest_rate_lagged"])
        df = pd.DataFrame(records)
        df["end_of_day"] = pd.to_datetime(df["end_of_day"])
        cols = ["comp_sora_3m", "interbank_3m", "sora"]
        for col in cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "comp_sora_3m" in df.columns and "interbank_3m" in df.columns:
            df["daily_rate"] = df["comp_sora_3m"].fillna(df["interbank_3m"])
        elif "interbank_3m" in df.columns:
            df["daily_rate"] = df["interbank_3m"]
        elif "sora" in df.columns:
            df["daily_rate"] = df["sora"]
        else:
            df["daily_rate"] = 0.0
        df = df.dropna(subset=["daily_rate"])
        df = df.set_index("end_of_day")
        monthly_rates = df[["daily_rate"]].resample("ME").mean().reset_index()
        return _process_interest_rates(monthly_rates)
    except Exception as exc:
        logger.warning(
            "fetch_interest_rates: MAS API request failed (%s): %s — "
            "interest_rate_lagged will be zeros unless macro_interest_csv exists in MinIO",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        fail_fast = os.getenv("HOMEYAI_MACRO_FETCH_FAIL_FAST", "").lower() in ("1", "true", "yes")
        if fail_fast:
            raise RuntimeError(
                "fetch_interest_rates failed while HOMEYAI_MACRO_FETCH_FAIL_FAST is set. "
                "Fix MAS egress/API key or upload macro_interest_csv to MinIO."
            ) from exc
        return pd.DataFrame(columns=["year_month", "interest_rate_lagged"])


def _process_interest_rates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["year_month", "interest_rate_lagged"])
    df = df.copy()
    df["end_of_day"] = pd.to_datetime(df["end_of_day"], errors="coerce")
    df = df.dropna(subset=["end_of_day"])
    df["year_month"] = df["end_of_day"].dt.to_period("M").astype(str)
    df["interest_rate_lagged"] = pd.to_numeric(df["daily_rate"], errors="coerce").shift(3)
    return df[["year_month", "interest_rate_lagged"]].copy()


def build_global_volume_series(frame: pd.DataFrame, *, out_path: Path | None = None) -> pd.DataFrame:
    """Nationwide resale counts by month plus 3-month lag (training-time reproducible baseline)."""
    if "month" not in frame.columns:
        raise ValueError("Training frame needs 'month' for volume lag")
    tx = pd.to_datetime(frame["month"], format="%Y-%m", errors="coerce")
    ym = tx.dt.to_period("M").astype(str)
    volume_df = ym.value_counts().sort_index().reset_index()
    volume_df.columns = ["year_month", "monthly_volume"]
    volume_df["volume_lagged_3m"] = volume_df["monthly_volume"].shift(3)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        volume_df.to_parquet(out_path, index=False)
    return volume_df


def _load_volume_lookup(project_root: Path) -> pd.DataFrame:
    mq = _volume_from_minio_manifest(project_root)
    if mq is not None and len(mq) and "volume_lagged_3m" in mq.columns:
        return mq[["year_month", "volume_lagged_3m"]].copy()
    return pd.DataFrame(columns=["year_month", "volume_lagged_3m"])


def compute_macro_aligned_to_raw(raw: pd.DataFrame, *, project_root: Path) -> pd.DataFrame:
    """Return dataframe indexed like ``raw`` with macro columns."""
    ts = pd.to_datetime(raw["month"], format="%Y-%m", errors="coerce")
    year_month = ts.dt.to_period("M").astype(str)

    out = pd.DataFrame(index=raw.index)

    volume_df = _load_volume_lookup(project_root)
    if volume_df.empty and len(raw.index) >= 500:
        volume_df = build_global_volume_series(raw, out_path=None)
    vy = pd.DataFrame({"year_month": year_month.values}).merge(
        volume_df[["year_month", "volume_lagged_3m"]], on="year_month", how="left"
    )
    out["volume_lagged_3m"] = vy["volume_lagged_3m"].values.astype(float)

    ir_df = fetch_interest_rates(project_root)
    if ir_df.empty:
        out["interest_rate_lagged"] = 0.0
    else:
        ry = pd.DataFrame({"year_month": year_month.values}).merge(ir_df, on="year_month", how="left")
        out["interest_rate_lagged"] = (
            pd.to_numeric(ry["interest_rate_lagged"], errors="coerce").fillna(0.0).values.astype(float)
        )

    return out.replace([np.inf, -np.inf], np.nan)


def append_macro_features(
    base: pd.DataFrame,
    raw_frame: pd.DataFrame,
    *,
    project_root: Path | None = None,
) -> pd.DataFrame:
    root = project_root or repo_root_default()
    macros = compute_macro_aligned_to_raw(raw_frame, project_root=root)
    merged = base.copy()
    for col in MACRO_NUMERIC_FEATURES:
        merged[col] = macros[col].values
    return merged


def engineer_macro_frame(
    raw: pd.DataFrame,
    *,
    categorical_style: str = "legacy",
    project_root: Path | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Baseline engineered frame + macro numerics."""
    from modelling.features.base import engineer_base_features

    root = project_root or repo_root_default()
    b = engineer_base_features(
        raw,
        categorical_style=categorical_style,  # type: ignore[arg-type]
        include_months_since_2015=bool(kwargs.get("include_months_since_2015")),
    )
    return append_macro_features(b, raw, project_root=root)


def macro_inference_override(*, valuation_month: str, project_root: Path) -> dict[str, Any]:
    """Single-row overrides for valuation API (parity with snapshot training path)."""
    ym = valuation_month.strip() if valuation_month else pd.Timestamp.utcnow().strftime("%Y-%m")
    ym = ym[:7]
    now_mono = time.monotonic()
    with _MACRO_MINIO_CACHE_LOCK:
        ent = _MACRO_INFERENCE_CACHE.get(ym)
        if ent is not None and ent[0] > now_mono:
            return dict(ent[1])

    row = pd.DataFrame([{"month": ym}])
    vec = compute_macro_aligned_to_raw(row, project_root=project_root)
    out: dict[str, Any] = {}
    for c in MACRO_NUMERIC_FEATURES:
        out[c] = float(vec.iloc[0][c]) if c in vec.columns else 0.0

    ttl = max(10.0, _MACRO_CACHE_TTL_SEC)
    with _MACRO_MINIO_CACHE_LOCK:
        _MACRO_INFERENCE_CACHE[ym] = (now_mono + ttl, dict(out))
    return out


# Back-compat stubs (historical parquet-on-disk workflows removed).
def macro_cache_dir(project_root: Path | None = None) -> Path:
    d = (project_root or repo_root_default()) / "data" / "macro"
    d.mkdir(parents=True, exist_ok=True)
    return d


def volume_lookup_parquet(project_root: Path | None = None) -> Path:
    """Deprecated — macro volume is read from MinIO (manifest) or derived in-memory."""
    return macro_cache_dir(project_root or repo_root_default()) / "global_volume_monthly.parquet"

