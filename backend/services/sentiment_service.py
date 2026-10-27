"""
Sentiment Service
=================
Fetches the three market signals and assembles the MarketSentimentData dict
expected by GET /api/market/sentiment.

Signals
-------
1. HDB Resale Price Index (RPI)  — data.gov.sg (public, no key needed)
2. MAS Interest Rates (SORA)     — MAS API      (requires MAS_API_KEY in .env)
3. Transaction Volume            — hdb_resale_transactions table (live DB query)

Caching
-------
External API results are cached in MinIO (datasets bucket) for 7 days so the
endpoint stays fast and we do not hammer external APIs on every request.

    datasets/raw/hdb_rpi.csv
    datasets/intermediate/interest_rates_cache.csv
"""

from __future__ import annotations

import io
import json
import os
import time
import urllib3
from datetime import datetime, timedelta, timezone


import pandas as pd
import requests
from minio import Minio
from minio.error import S3Error
from sqlalchemy import func

from models import HdbResaleTransaction, SessionLocal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUCKET = "datasets"
RPI_KEY = "raw/hdb_rpi.csv"
RATES_KEY = "intermediate/interest_rates_cache_v108.csv"
CACHE_TTL_DAYS = 7

# ---------------------------------------------------------------------------
# MinIO helpers  (same pattern as minio_catalog.py)
# ---------------------------------------------------------------------------


def _minio() -> Minio:
    return Minio(
        os.getenv("MINIO_ENDPOINT", "minio:9000"),
        access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "password123"),
        secure=False,
    )


def _is_fresh(client: Minio, key: str) -> bool:
    """True if the object exists in MinIO and is younger than CACHE_TTL_DAYS."""
    try:
        stat = client.stat_object(BUCKET, key)
        if stat.last_modified is None:
            return False
        age = datetime.now(timezone.utc) - stat.last_modified
        return age < timedelta(days=CACHE_TTL_DAYS)
    except S3Error:
        return False


def _read_csv(client: Minio, key: str) -> pd.DataFrame:
    resp = client.get_object(BUCKET, key)
    try:
        return pd.read_csv(io.BytesIO(resp.read()))
    finally:
        resp.close()
        resp.release_conn()


def _write_csv(client: Minio, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    size = buf.tell()
    buf.seek(0)
    if not client.bucket_exists(BUCKET):
        client.make_bucket(BUCKET)
    client.put_object(BUCKET, key, buf, size, content_type="text/csv")


# ---------------------------------------------------------------------------
# Signal 1 — HDB Resale Price Index
# ---------------------------------------------------------------------------


def _enrich_rpi(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("quarter").reset_index(drop=True)
    df["index"] = pd.to_numeric(df["index"], errors="coerce")
    df["rpi_qoq_pct"] = df["index"].pct_change() * 100
    return df


def fetch_rpi_data() -> pd.DataFrame:
    """Return DataFrame[quarter, index, rpi_qoq_pct]. Checks MinIO first."""
    # The local bootstrap already populated this authoritative serving table.
    # Prefer it to expiring caches / a retired download API.
    try:
        from models import HdbResalePriceIndex
        with SessionLocal() as db:
            rows = db.query(HdbResalePriceIndex).order_by(HdbResalePriceIndex.period_start).all()
            if rows:
                return _enrich_rpi(pd.DataFrame([{"quarter": r.quarter_label, "index": float(r.index_value)} for r in rows]))
    except Exception:
        pass  # Legacy installations can still use the existing cache/API chain.
    client = _minio()
    try:
        if _is_fresh(client, RPI_KEY):
            print("RPI: loading from MinIO cache")
            return _enrich_rpi(_read_csv(client, RPI_KEY))
    except Exception as e:
        print(f"RPI: MinIO read failed ({e}), fetching from API")

    print("RPI: fetching from data.gov.sg")
    dataset_id = "d_14f63e595975691e7c24a27ae4c07c79"
    url = f"https://data.gov.sg/api/action/datastore_search?resource_id={dataset_id}&limit=1000"

    for attempt in range(5):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                records = resp.json().get("result", {}).get("records", [])
                if records:
                    df = pd.DataFrame(records)[["quarter", "index"]].copy()
                    df["index"] = pd.to_numeric(df["index"], errors="coerce")
                    df = df.dropna(subset=["index"]).sort_values("quarter").reset_index(drop=True)
                    try:
                        _write_csv(client, RPI_KEY, df)
                        print("RPI: saved to MinIO cache")
                    except Exception as e:
                        print(f"RPI: MinIO write failed ({e})")
                    return _enrich_rpi(df)
            elif resp.status_code == 429:
                print("RPI: rate limited — waiting 15 s")
                time.sleep(15)
        except Exception as e:
            print(f"RPI: attempt {attempt + 1} failed: {e}")
            time.sleep(5)

    print("RPI: all attempts failed")
    return pd.DataFrame(columns=["quarter", "index", "rpi_qoq_pct"])


# ---------------------------------------------------------------------------
# Signal 2 — MAS Interest Rates
# ---------------------------------------------------------------------------


def fetch_interest_rates() -> pd.DataFrame:
    """Return DataFrame[end_of_day, daily_rate] using Daily MAS API."""
    client = _minio()
    try:
        # Use the constant defined at the top
        if _is_fresh(client, RATES_KEY):
            print(f"Interest rates: loading from MinIO cache ({RATES_KEY})")
            df = _read_csv(client, RATES_KEY)
            df["end_of_day"] = pd.to_datetime(df["end_of_day"])
            return df
    except Exception as e:
        print(f"Interest rates: MinIO read failed ({e}), fetching from API")

    api_key = os.getenv("MAS_API_KEY")
    if not api_key:
        print("Interest rates: MAS_API_KEY not set — skipping")
        return pd.DataFrame(columns=["end_of_day", "daily_rate"])

    print("Interest rates: fetching from MAS Daily API (Newest First)")
    # Correct parameter is $orderby, not sort
    # We only need the latest ~100 records to calculate this month vs last month
    url = (
        "https://eservices.mas.gov.sg/apimg-gw/server/"
        "monthly_statistical_bulletin_non610mssql/"
        "domestic_interest_rates_daily/views/domestic_interest_rates_daily"
        "?$orderby=end_of_day%20desc&$limit=100"
    )
    try:
        http = urllib3.PoolManager()
        resp = http.request("GET", url, headers={"keyid": api_key})
        if resp.status != 200:
            print(f"Interest rates: MAS API returned {resp.status}")
            return pd.DataFrame(columns=["end_of_day", "daily_rate"])

        records = json.loads(resp.data.decode("utf-8")).get("elements", [])
        if not records:
            return pd.DataFrame(columns=["end_of_day", "daily_rate"])

        df = pd.DataFrame(records)
        df["end_of_day"] = pd.to_datetime(df["end_of_day"])

        df["daily_rate"] = float("nan")
        for col in ["comp_sora_3m", "comp_sora_1m", "sora"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
                df["daily_rate"] = df["daily_rate"].fillna(df[col])

        df = df.dropna(subset=["daily_rate"]).sort_values("end_of_day")
        df = df.set_index("end_of_day")
        monthly = df[["daily_rate"]].resample("ME").mean().reset_index()

        if not monthly.empty:
            latest_date = monthly["end_of_day"].iloc[-1].strftime("%Y-%m-%d")
            latest_val = monthly["daily_rate"].iloc[-1]
            print(f"!!! SUCCESS !!! Interest rates reached {latest_date}: {latest_val}%")

        try:
            _write_csv(client, RATES_KEY, monthly)
        except Exception as e:
            print(f"Interest rates: MinIO write failed ({e})")

        return monthly
    except Exception as e:
        print(f"Interest rates: exception: {e}")
        return pd.DataFrame(columns=["end_of_day", "daily_rate"])
    except Exception as e:
        print(f"Interest rates: exception: {e}")
        return pd.DataFrame(columns=["end_of_day", "daily_rate"])


# ---------------------------------------------------------------------------
# Signal 3 — Transaction Volume  (live DB query, no caching needed)
# ---------------------------------------------------------------------------


def get_txn_volume_signal() -> dict:
    """Query hdb_resale_transactions for current-month count + 6-month z-score."""
    db = SessionLocal()
    try:
        # Use the LAST COMPLETED month for the primary volume signal
        # (Latest month in DB might be partial data for the current month)
        latest_month = db.query(func.max(HdbResaleTransaction.month)).scalar()
        if not latest_month:
            return {"txn_volume": 0, "txn_volume_z": 0.0, "txn_volume_label": "Normal Activity"}

        # Use penultimate month as the 'current' reference to ensure we have full-month data
        all_months = db.query(HdbResaleTransaction.month).distinct().order_by(HdbResaleTransaction.month.desc()).limit(2).all()
        target_month = all_months[1][0] if len(all_months) > 1 else latest_month

        current_count = (
            db.query(func.count(HdbResaleTransaction.id))
            .filter(HdbResaleTransaction.month == target_month)
            .scalar() or 0
        )

        # 6 months ending just before our target month
        rows = (
            db.query(
                HdbResaleTransaction.month,
                func.count(HdbResaleTransaction.id).label("cnt"),
            )
            .filter(HdbResaleTransaction.month < target_month)
            .group_by(HdbResaleTransaction.month)
            .order_by(HdbResaleTransaction.month.desc())
            .limit(6)
            .all()
        )

        if len(rows) < 2:
            return {"txn_volume": current_count, "txn_volume_z": 0.0, "txn_volume_label": "Normal Activity"}

        counts = [r.cnt for r in rows]
        mean_6m = sum(counts) / len(counts)
        std_6m = (sum((c - mean_6m) ** 2 for c in counts) / len(counts)) ** 0.5 or 1.0
        z = round((current_count - mean_6m) / std_6m, 2)

        label = "High Conviction" if z > 1.0 else ("Low Conviction" if z < -1.0 else "Normal Activity")
        return {"txn_volume": current_count, "txn_volume_z": z, "txn_volume_label": label}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------


def _rpi_label(normalised: float) -> str:
    if normalised > 70:
        return "Overheated"
    if normalised >= 40:
        return "Neutral"
    return "Undervalued"


def _rate_label(delta: float) -> str:
    if delta > 0.05:
        return "Tightening"
    if delta < -0.05:
        return "Easing"
    return "Stable"


# ---------------------------------------------------------------------------
# Composite insight
# ---------------------------------------------------------------------------

_INSIGHTS: dict[tuple, str] = {
    ("Overheated", "High Conviction", "Tightening"): (
        "Resale prices are above historical norms and buyer activity confirms genuine demand — "
        "but rising interest rates are narrowing borrowing capacity, which may slow price growth ahead."
    ),
    ("Overheated", "High Conviction", "Easing"): (
        "The RPI is elevated and strong transaction volumes validate real buyer demand; "
        "easing interest rates are further expanding affordability, sustaining upward price pressure."
    ),
    ("Overheated", "High Conviction", "Stable"): (
        "Prices are above their long-run baseline with robust buyer activity; "
        "stable rates mean affordability is not yet a headwind, but the market is running hot."
    ),
    ("Overheated", "Normal Activity", "Tightening"): (
        "The RPI is above its historical benchmark and rising rates are narrowing buyer budgets — "
        "the market may be approaching a natural ceiling as affordability tightens."
    ),
    ("Overheated", "Normal Activity", "Easing"): (
        "Resale prices are elevated, but falling rates and steady transaction activity "
        "suggest the market can sustain current levels without an immediate correction."
    ),
    ("Overheated", "Normal Activity", "Stable"): (
        "Prices are above their long-run average with moderate activity; "
        "the market is warm but not at a level that signals imminent correction."
    ),
    ("Overheated", "Low Conviction", "Tightening"): (
        "Prices are elevated but thin trading volumes and rising rates are a cautionary signal — "
        "current price levels may not be well-supported if volumes remain subdued."
    ),
    ("Overheated", "Low Conviction", "Easing"): (
        "Despite an elevated RPI, low transaction volumes suggest buyer hesitation; "
        "falling rates may gradually draw more activity back into the market."
    ),
    ("Overheated", "Low Conviction", "Stable"): (
        "Prices are above trend but low trading activity raises questions about whether "
        "current levels are truly demand-driven or simply the result of limited supply."
    ),
    ("Neutral", "High Conviction", "Easing"): (
        "A well-balanced market: prices are in line with historical norms, transaction volumes "
        "are strong, and falling rates are broadening affordability — favourable for buyers."
    ),
    ("Neutral", "High Conviction", "Tightening"): (
        "Prices are fairly valued and buyer activity is healthy, though rising rates "
        "may gradually dampen purchasing power over the coming months."
    ),
    ("Neutral", "High Conviction", "Stable"): (
        "The market is in equilibrium — prices, volumes, and rates are all within normal ranges, "
        "offering a stable and predictable environment for both buyers and sellers."
    ),
    ("Neutral", "Normal Activity", "Stable"): (
        "Market conditions are broadly balanced with no strong signal in either direction; "
        "a steady environment for buyers who are not under time pressure."
    ),
    ("Neutral", "Low Conviction", "Tightening"): (
        "Prices are fair but thinning volumes combined with rising rates suggest buyer caution — "
        "there may be more room to negotiate than headline prices imply."
    ),
    ("Neutral", "Low Conviction", "Easing"): (
        "Prices are in line with historical norms and falling rates should support demand; "
        "lower volumes may simply reflect seasonal patterns rather than structural weakness."
    ),
    ("Undervalued", "High Conviction", "Easing"): (
        "The RPI is below its long-run baseline, transaction volumes are strong, and rates are falling — "
        "this combination could represent a favourable window before the market recovers."
    ),
    ("Undervalued", "High Conviction", "Tightening"): (
        "Prices are below trend and buyer activity is solid, but rising rates are offsetting some of "
        "the value; recovery may be slower than the volume signal alone suggests."
    ),
    ("Undervalued", "Normal Activity", "Easing"): (
        "Prices have softened below their historical average and easing rates are improving affordability — "
        "buyers with a long-term view may find value at current levels."
    ),
    ("Undervalued", "Low Conviction", "Tightening"): (
        "Prices are below trend and market activity is thin, compounded by rising rates — "
        "the market is in a cautious phase and recovery timing remains uncertain."
    ),
    ("Undervalued", "Low Conviction", "Easing"): (
        "Prices are below their long-run baseline and volumes are subdued; "
        "easing rates may be the catalyst needed to attract buyers back and support a gradual recovery."
    ),
}


def _composite_insight(rpi_lbl: str, vol_lbl: str, rate_lbl: str) -> str:
    key = (rpi_lbl, vol_lbl, rate_lbl)
    return _INSIGHTS.get(
        key,
        (
            f"The HDB Resale Price Index is {rpi_lbl.lower()}, transaction volumes indicate "
            f"{vol_lbl.lower()} market conditions, and interest rates are {rate_lbl.lower()} — "
            "weigh these signals together before making a property decision."
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_market_sentiment() -> dict:
    """
    Top-level function called by GET /api/market/sentiment.
    Returns the full MarketSentimentData dict expected by the frontend.
    """
    # ── 1. HDB RPI ──────────────────────────────────────────────────────────
    rpi_df = fetch_rpi_data()
    if rpi_df.empty or "index" not in rpi_df.columns:
        raise RuntimeError("HDB price-index data is unavailable; import the RPI dataset before using market signals")
    else:
        rpi_raw = round(float(rpi_df["index"].iloc[-1]), 1)
        rpi_min = float(rpi_df["index"].min())
        rpi_max = float(rpi_df["index"].max())
        span = rpi_max - rpi_min if rpi_max != rpi_min else 1.0
        rpi_normalised = round((rpi_raw - rpi_min) / span * 100, 1)
        rpi_qoq = round(float(rpi_df["rpi_qoq_pct"].iloc[-1]), 2) if "rpi_qoq_pct" in rpi_df.columns else 0.0

    rpi_lbl = _rpi_label(rpi_normalised)

    # ── 2. Interest Rates ────────────────────────────────────────────────────
    rates_df = fetch_interest_rates()
    if rates_df.empty or len(rates_df) < 2:
        interest_rate = None
        interest_delta = 0.0
        rate_lbl = None
    else:
        rates_df = rates_df.sort_values("end_of_day")
        interest_rate = round(float(rates_df["daily_rate"].iloc[-1]), 4)
        interest_delta = round(
            float(rates_df["daily_rate"].iloc[-1]) - float(rates_df["daily_rate"].iloc[-2]), 4
        )
        rate_lbl = _rate_label(interest_delta)

    # ── 3. Transaction Volume ────────────────────────────────────────────────
    vol = get_txn_volume_signal()

    # ── 4. Composite ─────────────────────────────────────────────────────────
    insight = (_composite_insight(rpi_lbl, vol["txn_volume_label"], rate_lbl) if rate_lbl else
        f"HDB price-index signal: {rpi_lbl.lower()}; transaction-volume signal: {vol['txn_volume_label'].lower()}. "
        "Interest-rate data is unavailable and is excluded from this rule-based summary.")

    return {
        # RPI — two values so the frontend can show both the gauge and the real index
        "rsi_value": rpi_normalised,     # 0-100 normalised (drives gauge arc)
        "rsi_raw": rpi_raw,              # Actual HDB index number e.g. 187.4
        "rsi_qoq_pct": rpi_qoq,         # Quarter-on-quarter % change
        "rsi_label": rpi_lbl,
        # Transaction volume
        "txn_volume": vol["txn_volume"],
        "txn_volume_label": vol["txn_volume_label"],
        "txn_volume_z": vol["txn_volume_z"],
        # Interest rates
        "interest_rate": interest_rate,
        "interest_rate_delta": interest_delta,
        "interest_rate_label": rate_lbl,
        # Synthesis
        "composite_insight": insight,
        "last_updated": datetime.utcnow().isoformat(),
    }
