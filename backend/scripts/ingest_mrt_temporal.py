import os
import sys
import json
import pandas as pd
from datetime import datetime, date
from pathlib import Path
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from tempfile import NamedTemporaryFile

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from models import (  # noqa: E402
    DATABASE_URL,
    MrtPhysicalStation,
    MrtStationLine,
)
from ingestion import _make_minio_client, BUCKET_DATASETS, PROCESSED_PREFIX  # noqa: E402

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
QUALITY_PATH = LOG_DIR / "mrt_data_quality.json"


def parse_date(date_str, is_announcement: bool) -> tuple:
    """
    Returns (parsed_date | None, confidence token).
    confidence ∈ EXACT | YEAR | HALF | MID | TBA | NONE
    """
    if pd.isna(date_str) or str(date_str).strip() in ["TBA", "Unknown", "nan", ""]:
        return None, (
            "TBA" if pd.notna(date_str) and str(date_str).strip().upper() == "TBA" else "NONE"
        )

    date_str = str(date_str).strip()

    if pd.Series([date_str]).str.match(r"^\d{4}-\d{2}-\d{2}$").iloc[0]:
        return datetime.strptime(date_str, "%Y-%m-%d").date(), "EXACT"

    if pd.Series([date_str]).str.match(r"^\d{4}$").iloc[0]:
        year = int(date_str)
        if is_announcement:
            return datetime(year, 1, 1).date(), "YEAR"
        return datetime(year, 12, 31).date(), "YEAR"

    try:
        dt = datetime.strptime(date_str, "%B %Y")
        if is_announcement:
            return dt.date(), "MID"
        next_month = dt.replace(day=28) + pd.Timedelta(days=4)
        return (next_month - pd.Timedelta(days=next_month.day)).date(), "MID"
    except ValueError:
        pass

    if "1H" in date_str:
        year = int(date_str.replace("1H", "").strip())
        return datetime(year, 6, 30).date(), "HALF"
    if "2H" in date_str:
        year = int(date_str.replace("2H", "").strip())
        return datetime(year, 12, 31).date(), "HALF"

    if "mid-" in date_str.lower():
        year_str = date_str.lower().replace("mid-", "").replace("s", "").strip()
        year = int(year_str)
        if "2030" in year_str:
            year = 2035
        return datetime(year, 6, 30).date(), "MID"

    logger.warning(f"Unmatched date format: {date_str}, falling back to NULL")
    return None, "NONE"


def compute_derived_state(
    opening_date,
    expected_completion,
    announcement_date,
    as_of: date | None = None,
) -> str:
    as_of_d = as_of or date.today()
    if opening_date is not None and opening_date <= as_of_d:
        return "OPERATIONAL"
    if opening_date is not None and opening_date > as_of_d:
        return "COMMITTED_DATED"
    if opening_date is None and expected_completion is not None:
        return "COMMITTED_ESTIMATED"
    if opening_date is None and announcement_date is not None:
        return "ANNOUNCED_UNDATED"
    return "UNKNOWN"


def ingest_mrt_temporal_data(csv_path: str):
    logger.info("Loading data from %s...", csv_path)
    df = pd.read_csv(csv_path)

    engine = create_engine(DATABASE_URL)

    logger.info("Uploading to MinIO processed bucket...")
    client = _make_minio_client()
    if not client.bucket_exists(BUCKET_DATASETS):
        client.make_bucket(BUCKET_DATASETS)

    parquet_filename = "mrt_stations_enriched.parquet"
    with NamedTemporaryFile(suffix=".parquet") as tmp:
        df.to_parquet(tmp.name, engine="pyarrow", compression="snappy")
        parquet_minio_path = f"{PROCESSED_PREFIX}/{parquet_filename}"
        try:
            client.fput_object(BUCKET_DATASETS, parquet_minio_path, tmp.name)
            logger.info("Uploaded %s", parquet_minio_path)
        except Exception as exc:
            logger.error("Could not upload parquet to MinIO: %s", exc)

    quality = {"opened_without_opening_date": [], "coord_divergence_same_name": []}
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Parsing dates and inserting physical + line rows...")
    with Session(engine) as session:
        session.query(MrtStationLine).delete()
        session.query(MrtPhysicalStation).delete()

        rows_for_coord_check = []

        physical_by_canonical: dict[str, MrtPhysicalStation] = {}

        for _, row in df.iterrows():
            name_raw = row.get("station_name")
            station_norm = (
                str(name_raw).strip().upper()
                if pd.notna(name_raw) and str(name_raw).strip()
                else None
            )

            geom = None
            if pd.notna(row["lat"]) and pd.notna(row["long"]):
                geom = func.ST_SetSRID(func.ST_MakePoint(row["long"], row["lat"]), 4326)

            ann_dt, _ = parse_date(row.get("announcement_date"), is_announcement=True)
            exp_dt, _ = parse_date(row.get("expected_completion"), is_announcement=False)
            op_dt, _ = parse_date(row.get("opening_date"), is_announcement=False)

            stat = str(row.get("station_status", "")).lower().strip()
            if stat == "open" and op_dt is None:
                quality["opened_without_opening_date"].append(
                    {
                        "station_code": row.get("station_code"),
                        "station_name": station_norm,
                    }
                )

            lat = row.get("lat") if pd.notna(row.get("lat")) else None
            lon = row.get("long") if pd.notna(row.get("long")) else None

            if not station_norm:
                logger.warning(
                    "Skipping row with blank station_name (code=%s)", row.get("station_code")
                )
                continue

            if station_norm not in physical_by_canonical:
                physical_by_canonical[station_norm] = MrtPhysicalStation(
                    canonical_name=station_norm,
                    lat=float(lat) if lat is not None else None,
                    long=float(lon) if lon is not None else None,
                    geom=geom,
                    is_interchange=False,
                )
            if station_norm and lat is not None and lon is not None:
                rows_for_coord_check.append(
                    {"station_name": station_norm, "lat": float(lat), "long": float(lon)}
                )

        session.add_all(physical_by_canonical.values())
        session.flush()

        lines_inserted = 0
        for idx, (_, row) in enumerate(df.iterrows()):
            name_raw = row.get("station_name")
            station_norm = (
                str(name_raw).strip().upper()
                if pd.notna(name_raw) and str(name_raw).strip()
                else None
            )
            if not station_norm or station_norm not in physical_by_canonical:
                continue

            ann_dt, _ = parse_date(row.get("announcement_date"), is_announcement=True)
            exp_dt, _ = parse_date(row.get("expected_completion"), is_announcement=False)
            op_dt, op_conf = parse_date(row.get("opening_date"), is_announcement=False)
            opening_conf = op_conf

            derived = compute_derived_state(op_dt, exp_dt, ann_dt)

            raw_line = row.get("network_line")
            nl = (
                str(raw_line).strip()
                if pd.notna(raw_line) and str(raw_line).strip()
                else "UNKNOWN_LINE"
            )

            code_raw = row.get("station_code")
            raw_code_str = (
                str(code_raw).strip() if pd.notna(code_raw) and str(code_raw).strip() else ""
            )
            code_str = raw_code_str if raw_code_str else f"__MISSING_{idx}"

            phy = physical_by_canonical[station_norm]

            ml = MrtStationLine(
                physical_station_id=phy.id,
                network_line=nl,
                subproject_or_stage=row.get("subproject_or_stage"),
                station_code=code_str[:50],
                station_name=station_norm,
                station_status=row.get("station_status"),
                working_name_flag=row.get("working_name_flag"),
                code_source_type=row.get("code_source_type"),
                announcement_date_raw=str(row.get("announcement_date"))
                if pd.notna(row.get("announcement_date"))
                else None,
                announcement_date=ann_dt,
                expected_completion_raw=str(row.get("expected_completion"))
                if pd.notna(row.get("expected_completion"))
                else None,
                expected_completion=exp_dt,
                opening_date_raw=str(row.get("opening_date"))
                if pd.notna(row.get("opening_date"))
                else None,
                opening_date=op_dt,
                dates_source_type=row.get("dates_source_type"),
                phase2_review_priority=row.get("phase2_review_priority"),
                source_url=row.get("source_url"),
                source_note=row.get("source_note"),
                search_term=row.get("search_term"),
                found=int(row["found"]) if pd.notna(row.get("found")) else None,
                api_response=row.get("api_response"),
                opening_date_confidence=opening_conf,
                derived_state=derived,
            )
            session.add(ml)
            session.flush()  # Bulk ORM INSERT hit bad float8 binds on PostgreSQL with this mapper.
            lines_inserted += 1

        # pairwise same-name coord check
        from collections import defaultdict

        by_name = defaultdict(list)
        for rc in rows_for_coord_check:
            by_name[rc["station_name"]].append(rc)
        for name, lst in by_name.items():
            if len(lst) < 2:
                continue
            for i, a in enumerate(lst):
                for b in lst[i + 1 :]:
                    dx = abs(a["lat"] - b["lat"]) * 111_000
                    dy = abs(a["long"] - b["long"]) * 85_000
                    approx = (dx * dx + dy * dy) ** 0.5
                    if approx > 50:
                        quality["coord_divergence_same_name"].append(
                            {"station_name": name, "approx_m": round(approx, 1)}
                        )

        QUALITY_PATH.write_text(json.dumps(quality, indent=2))

        dialect = session.get_bind().dialect.name if session.get_bind() else ""
        if dialect == "postgresql":
            logger.info("Setting is_interchange from distinct network_line count per physical stop...")
            session.execute(
                text(
                    """
                    UPDATE mrt_physical_stations ps
                    SET is_interchange = sub.has_ix
                    FROM (
                        SELECT
                            l.physical_station_id AS pid,
                            (
                                COUNT(DISTINCT TRIM(BOTH FROM l.network_line)) >= 2
                            ) AS has_ix
                        FROM mrt_station_lines l
                        WHERE l.network_line IS NOT NULL
                          AND TRIM(BOTH FROM l.network_line) <> ''
                        GROUP BY l.physical_station_id
                    ) sub
                    WHERE ps.id = sub.pid
                    """
                )
            )
        else:
            logger.warning("Non-PostgreSQL DB: skipping is_interchange batch update.")

        session.commit()

    logger.info(
        "Ingested %s physical sites and %s line rows.",
        len(physical_by_canonical),
        lines_inserted,
    )


if __name__ == "__main__":
    current_dir = os.path.dirname(__file__)
    csv_path = os.path.abspath(os.path.join(current_dir, "../../data/Full_MRT_Stn_Enriched_Latlong.csv"))
    if not os.path.exists(csv_path):
        logger.error("Cannot find CSV at %s", csv_path)
        sys.exit(1)

    ingest_mrt_temporal_data(csv_path)
