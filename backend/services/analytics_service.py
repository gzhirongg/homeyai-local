from typing import Dict, List, Optional, Any

from sqlalchemy import func, desc, and_, cast, Float, String, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from models import SessionLocal, HdbResaleTransaction, HdbAddressEnrichmentOnemap


def _completeness_ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 6)


def _pct_unfilled(gap: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    g = max(0, gap)
    return round(min(g, denominator) / denominator, 6)


_HDB_ENRICHMENT_COMPLETENESS_SQL = text("""
WITH mrt_addrs AS MATERIALIZED (
    SELECT DISTINCT r.hdb_addr_id AS aid
    FROM hdb_mrt_routes r
    WHERE r.hdb_addr_id IS NOT NULL
),
bld_addrs AS MATERIALIZED (
    SELECT DISTINCT e.id AS aid
    FROM hdb_address_enrichment_onemap e
    INNER JOIN hdb_buildings b ON
        LENGTH(TRIM(COALESCE(e.postal_code, ''))) > 0
        AND LENGTH(TRIM(COALESCE(b.postal_cod, ''))) > 0
        AND LPAD(TRIM(COALESCE(b.postal_cod, '')), 6, '0')
            = LPAD(TRIM(COALESCE(e.postal_code, '')), 6, '0')
),
txs AS (
    SELECT
        UPPER(TRIM(COALESCE(t.block, ''))) AS blk,
        UPPER(TRIM(COALESCE(t.street_name, ''))) AS st,
        t.enriched_addr_id AS eid,
        (oe.id IS NOT NULL) AS has_complete_onemap,
        (
            oe.id IS NOT NULL AND m.aid IS NOT NULL
        ) AS has_mrt,
        (
            oe.id IS NOT NULL AND bd.aid IS NOT NULL
        ) AS has_building
    FROM hdb_resale_transactions t
    LEFT JOIN hdb_address_enrichment_onemap oe ON
        oe.id = t.enriched_addr_id
        AND oe.postal_code IS NOT NULL
        AND oe.latitude IS NOT NULL
        AND oe.longitude IS NOT NULL
    LEFT JOIN mrt_addrs m ON m.aid = t.enriched_addr_id
    LEFT JOIN bld_addrs bd ON bd.aid = t.enriched_addr_id
),
loc_agg AS (
    SELECT
        blk,
        st,
        BOOL_OR(has_complete_onemap) AS has_complete_onemap,
        BOOL_OR(has_mrt) AS has_mrt,
        BOOL_OR(has_building) AS has_building
    FROM txs
    GROUP BY blk, st
),
loc_stats AS (
    SELECT
        COUNT(*)::bigint AS unique_locations_total,
        COUNT(*) FILTER (WHERE has_complete_onemap)::bigint AS unique_locations_onemap_complete,
        COUNT(*) FILTER (WHERE has_mrt)::bigint AS unique_locations_with_mrt_routes,
        COUNT(*) FILTER (WHERE has_building)::bigint AS unique_locations_with_hdb_building,
        COUNT(*) FILTER (WHERE has_complete_onemap AND has_mrt AND has_building)::bigint
            AS unique_locations_with_all_three
    FROM loc_agg
),
txn_stats AS (
    SELECT
        COUNT(*)::bigint AS total_transactions,
        COUNT(*) FILTER (WHERE has_complete_onemap)::bigint AS records_onemap_complete,
        COUNT(*) FILTER (WHERE has_mrt)::bigint AS with_mrt_routes,
        COUNT(*) FILTER (WHERE has_building)::bigint AS with_hdb_building,
        COUNT(*) FILTER (WHERE has_complete_onemap AND has_mrt AND has_building)::bigint AS with_all_three
    FROM txs
)
SELECT
    txn_stats.total_transactions,
    txn_stats.records_onemap_complete,
    txn_stats.with_mrt_routes,
    txn_stats.with_hdb_building,
    txn_stats.with_all_three,
    loc_stats.unique_locations_total,
    loc_stats.unique_locations_onemap_complete,
    loc_stats.unique_locations_with_mrt_routes,
    loc_stats.unique_locations_with_hdb_building,
    loc_stats.unique_locations_with_all_three
FROM txn_stats
CROSS JOIN loc_stats
""")


def _gap_unique_locations(uniq_total: int, uniq_covered: int) -> int:
    return max(0, uniq_total - uniq_covered)


def get_hdb_enrichment_completeness(db: Any) -> Dict[str, Any]:
    """Aggregate HDB resale rows vs OneMap/MRT/building enrichment (PostgreSQL)."""
    from datetime import datetime, timezone

    total_transactions = int(db.query(func.count(HdbResaleTransaction.id)).scalar() or 0)
    computed_at = datetime.now(timezone.utc).isoformat()

    bind = db.get_bind() if hasattr(db, "get_bind") else getattr(db, "bind", None)
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "") or ""

    if dialect_name != "postgresql":
        return {
            "computed_at": computed_at,
            "enrichment_breakdown_available": False,
            "onemap_complete_definition": None,
            "note": "Enrichment breakdown requires PostgreSQL (PostGIS-backed deployment).",
            "total_transactions": total_transactions,
            "with_onemap": None,
            "with_mrt_routes": None,
            "with_hdb_building": None,
            "with_all_three": None,
            "pct_onemap": None,
            "pct_mrt_routes": None,
            "pct_hdb_building": None,
            "pct_all_three": None,
            "unique_locations_total": None,
            "unique_locations_with_onemap": None,
            "unique_locations_with_mrt_routes": None,
            "unique_locations_with_hdb_building": None,
            "unique_locations_with_all_three": None,
            "gap_unique_locations_onemap": None,
            "gap_unique_locations_mrt_routes": None,
            "gap_unique_locations_hdb_building": None,
            "gap_unique_locations_all_three": None,
            "pct_unfilled_transactions_onemap": None,
            "pct_unfilled_transactions_mrt_routes": None,
            "pct_unfilled_transactions_hdb_building": None,
            "pct_unfilled_transactions_all_three": None,
            "pct_unfilled_unique_locations_onemap": None,
            "pct_unfilled_unique_locations_mrt_routes": None,
            "pct_unfilled_unique_locations_hdb_building": None,
            "pct_unfilled_unique_locations_all_three": None,
            "records_onemap_complete": None,
            "unique_locations_onemap_complete": None,
            "pct_filled_records_onemap": None,
            "pct_filled_unique_locations_onemap": None,
        }

    try:
        row = db.execute(_HDB_ENRICHMENT_COMPLETENESS_SQL).fetchone()
    except (ProgrammingError, OperationalError):
        db.rollback()
        return {
            "computed_at": computed_at,
            "enrichment_breakdown_available": False,
            "onemap_complete_definition": None,
            "note": "Could not query enrichment tables; schema may be incomplete.",
            "total_transactions": total_transactions,
            "with_onemap": None,
            "with_mrt_routes": None,
            "with_hdb_building": None,
            "with_all_three": None,
            "pct_onemap": None,
            "pct_mrt_routes": None,
            "pct_hdb_building": None,
            "pct_all_three": None,
            "unique_locations_total": None,
            "unique_locations_with_onemap": None,
            "unique_locations_with_mrt_routes": None,
            "unique_locations_with_hdb_building": None,
            "unique_locations_with_all_three": None,
            "gap_unique_locations_onemap": None,
            "gap_unique_locations_mrt_routes": None,
            "gap_unique_locations_hdb_building": None,
            "gap_unique_locations_all_three": None,
            "pct_unfilled_transactions_onemap": None,
            "pct_unfilled_transactions_mrt_routes": None,
            "pct_unfilled_transactions_hdb_building": None,
            "pct_unfilled_transactions_all_three": None,
            "pct_unfilled_unique_locations_onemap": None,
            "pct_unfilled_unique_locations_mrt_routes": None,
            "pct_unfilled_unique_locations_hdb_building": None,
            "pct_unfilled_unique_locations_all_three": None,
            "records_onemap_complete": None,
            "unique_locations_onemap_complete": None,
            "pct_filled_records_onemap": None,
            "pct_filled_unique_locations_onemap": None,
        }

    if row is None:
        return {
            "computed_at": computed_at,
            "enrichment_breakdown_available": False,
            "onemap_complete_definition": None,
            "note": "Completeness aggregate returned no row.",
            "total_transactions": total_transactions,
            "with_onemap": None,
            "with_mrt_routes": None,
            "with_hdb_building": None,
            "with_all_three": None,
            "pct_onemap": None,
            "pct_mrt_routes": None,
            "pct_hdb_building": None,
            "pct_all_three": None,
            "unique_locations_total": None,
            "unique_locations_with_onemap": None,
            "unique_locations_with_mrt_routes": None,
            "unique_locations_with_hdb_building": None,
            "unique_locations_with_all_three": None,
            "gap_unique_locations_onemap": None,
            "gap_unique_locations_mrt_routes": None,
            "gap_unique_locations_hdb_building": None,
            "gap_unique_locations_all_three": None,
            "pct_unfilled_transactions_onemap": None,
            "pct_unfilled_transactions_mrt_routes": None,
            "pct_unfilled_transactions_hdb_building": None,
            "pct_unfilled_transactions_all_three": None,
            "pct_unfilled_unique_locations_onemap": None,
            "pct_unfilled_unique_locations_mrt_routes": None,
            "pct_unfilled_unique_locations_hdb_building": None,
            "pct_unfilled_unique_locations_all_three": None,
            "records_onemap_complete": None,
            "unique_locations_onemap_complete": None,
            "pct_filled_records_onemap": None,
            "pct_filled_unique_locations_onemap": None,
        }

    total = int(row[0])
    rec_complete = int(row[1])
    wt_mrt = int(row[2])
    wt_bld = int(row[3])
    wt_all = int(row[4])
    uniq_total = int(row[5])
    uniq_complete = int(row[6])
    uniq_mrt = int(row[7])
    uniq_bld = int(row[8])
    uniq_all = int(row[9])

    gap_tx_onemap = total - rec_complete
    gap_tx_mrt = total - wt_mrt
    gap_tx_bld = total - wt_bld
    gap_tx_all = total - wt_all
    gap_ul_onemap = _gap_unique_locations(uniq_total, uniq_complete)
    gap_ul_mrt = _gap_unique_locations(uniq_total, uniq_mrt)
    gap_ul_bld = _gap_unique_locations(uniq_total, uniq_bld)
    gap_ul_all = _gap_unique_locations(uniq_total, uniq_all)

    pct_records_fill = _completeness_ratio(rec_complete, total)
    pct_locations_fill = _completeness_ratio(uniq_complete, uniq_total)

    return {
        "computed_at": computed_at,
        "enrichment_breakdown_available": True,
        "note": None,
        "onemap_complete_definition": (
            "Resale rows linked to hdb_address_enrichment_onemap where postal_code, "
            "latitude, and longitude are all non-NULL."
        ),
        "total_transactions": total,
        "records_onemap_complete": rec_complete,
        "pct_filled_records_onemap": pct_records_fill,
        "unique_locations_total": uniq_total,
        "unique_locations_onemap_complete": uniq_complete,
        "pct_filled_unique_locations_onemap": pct_locations_fill,
        # Deprecated aliases (same counts): FK-linked completeness counted strictly via postal/lat/lon above.
        "with_onemap": rec_complete,
        "pct_onemap": pct_records_fill,
        "unique_locations_with_onemap": uniq_complete,
        "with_mrt_routes": wt_mrt,
        "with_hdb_building": wt_bld,
        "with_all_three": wt_all,
        "pct_mrt_routes": _completeness_ratio(wt_mrt, total),
        "pct_hdb_building": _completeness_ratio(wt_bld, total),
        "pct_all_three": _completeness_ratio(wt_all, total),
        "unique_locations_with_mrt_routes": uniq_mrt,
        "unique_locations_with_hdb_building": uniq_bld,
        "unique_locations_with_all_three": uniq_all,
        "gap_unique_locations_onemap": gap_ul_onemap,
        "gap_unique_locations_mrt_routes": gap_ul_mrt,
        "gap_unique_locations_hdb_building": gap_ul_bld,
        "gap_unique_locations_all_three": gap_ul_all,
        "pct_unfilled_transactions_onemap": _pct_unfilled(gap_tx_onemap, total),
        "pct_unfilled_transactions_mrt_routes": _pct_unfilled(gap_tx_mrt, total),
        "pct_unfilled_transactions_hdb_building": _pct_unfilled(gap_tx_bld, total),
        "pct_unfilled_transactions_all_three": _pct_unfilled(gap_tx_all, total),
        "pct_unfilled_unique_locations_onemap": _pct_unfilled(gap_ul_onemap, uniq_total),
        "pct_unfilled_unique_locations_mrt_routes": _pct_unfilled(gap_ul_mrt, uniq_total),
        "pct_unfilled_unique_locations_hdb_building": _pct_unfilled(gap_ul_bld, uniq_total),
        "pct_unfilled_unique_locations_all_three": _pct_unfilled(gap_ul_all, uniq_total),
    }

def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

def get_singapore_summary() -> Dict:
    db = SessionLocal()
    try:
        # 1. Overall Stats
        total_transactions = db.query(func.count(HdbResaleTransaction.id)).scalar() or 0
        avg_price = float(db.query(func.avg(HdbResaleTransaction.resale_price)).scalar() or 0)
        avg_area = float(db.query(func.avg(HdbResaleTransaction.floor_area_sqm)).scalar() or 1)
        avg_psf = int((avg_price / avg_area) * 0.092903) if avg_area > 0 else 0

        # 2. Top Growth Towns (Mock growth metric as town distribution for now, or use actual growth if multiple years exist)
        town_counts = db.query(
            HdbResaleTransaction.town, 
            func.count(HdbResaleTransaction.id).label('count'),
            func.avg(HdbResaleTransaction.resale_price).label('avg_price')
        ).group_by(HdbResaleTransaction.town).order_by(desc('avg_price')).limit(5).all()

        top_growth = [
            {"district": t.town, "growth_pct": round((t.avg_price / 500000) * 10, 1)} # Mocked growth relative to base
            for t in town_counts
        ]

        # 3. New Feature: Flat Type Distribution (Volume)
        flat_type_dist = db.query(
            HdbResaleTransaction.flat_type,
            func.count(HdbResaleTransaction.id).label('count')
        ).group_by(HdbResaleTransaction.flat_type).all()

        return {
            "top_growth_districts": top_growth,
            "stats": {
                "total_projects": db.query(func.count(func.distinct(HdbResaleTransaction.street_name))).scalar() or 0,
                "new_projects_ytd": int(total_transactions * 0.05), # Mock
                "avg_psf_sg": avg_psf,
                "total_transactions_ytd": total_transactions,
                "flat_type_distribution": [{"type": f.flat_type, "count": f.count} for f in flat_type_dist]
            }
        }
    finally:
        db.close()

def get_district_analytics(district_name: str) -> Dict:
    db = SessionLocal()
    district_name = district_name.upper()
    try:
        # Fallback to first available town if district not found
        exists = db.query(HdbResaleTransaction).filter(HdbResaleTransaction.town == district_name).first()
        if not exists:
            first_town = db.query(HdbResaleTransaction.town).first()
            district_name = first_town[0] if first_town else "BEDOK"

        # 1. Historical Trend
        # Extract year from 'month' (YYYY-MM)
        trend_data = db.query(
            func.substr(HdbResaleTransaction.month, 1, 4).label('year'),
            func.avg(HdbResaleTransaction.resale_price).label('avg_price')
        ).filter(HdbResaleTransaction.town == district_name).group_by('year').order_by('year').all()

        historical_trend = [
            {"year": t.year, "price": int(t.avg_price), "sg_avg": int(float(t.avg_price) * 0.95)} 
            for t in trend_data
        ]

        # 2. Notable Projects (Recent Transactions in the town)
        projects_data = db.query(
            HdbResaleTransaction.street_name,
            HdbResaleTransaction.block,
            HdbResaleTransaction.flat_type,
            func.avg(HdbResaleTransaction.resale_price).label('avg_price'),
            func.avg(HdbResaleTransaction.floor_area_sqm).label('avg_area'),
            func.count(HdbResaleTransaction.id).label('txn_count')
        ).filter(HdbResaleTransaction.town == district_name).group_by(
            HdbResaleTransaction.street_name, HdbResaleTransaction.block, HdbResaleTransaction.flat_type
        ).limit(10).all()

        projects = [
            {
                "name": f"{p.street_name} Blk {p.block}",
                "type": p.flat_type,
                "avg_psf": int((float(p.avg_price) / float(p.avg_area)) * 0.092903) if p.avg_area > 0 else 0,
                "transactions": p.txn_count
            }
            for p in projects_data
        ]

        return {
            "district": district_name,
            "historical_trend": historical_trend,
            "projects": projects
        }
    finally:
        db.close()

def get_area_historical_trend(town: str) -> List[Dict]:
    """Helper for valuation results to show specific town trend."""
    db = SessionLocal()
    try:
        trend_data = db.query(
            func.substr(HdbResaleTransaction.month, 1, 4).label('year'),
            func.avg(HdbResaleTransaction.resale_price).label('avg_price')
        ).filter(HdbResaleTransaction.town == town.upper()).group_by('year').order_by('year').all()

        return [
            {"year": t.year, "price": int(t.avg_price)} 
            for t in trend_data
        ]
    finally:
        db.close()


def get_filter_options() -> Dict:
    """Return available values for each filter dimension."""
    db = SessionLocal()
    try:
        towns = [r[0] for r in db.query(HdbResaleTransaction.town).distinct().order_by(HdbResaleTransaction.town).all()]
        flat_types = [r[0] for r in db.query(HdbResaleTransaction.flat_type).distinct().order_by(HdbResaleTransaction.flat_type).all()]
        storey_ranges = [r[0] for r in db.query(HdbResaleTransaction.storey_range).distinct().order_by(HdbResaleTransaction.storey_range).all() if r[0]]

        date_range = db.query(
            func.min(HdbResaleTransaction.month),
            func.max(HdbResaleTransaction.month)
        ).first()

        price_range = db.query(
            func.min(HdbResaleTransaction.resale_price),
            func.max(HdbResaleTransaction.resale_price)
        ).first()

        return {
            "towns": towns,
            "flat_types": flat_types,
            "storey_ranges": storey_ranges,
            "date_range": {"min": date_range[0], "max": date_range[1]} if date_range else {},
            "price_range": {"min": price_range[0], "max": price_range[1]} if price_range else {},
        }
    finally:
        db.close()


STOREY_LEVEL_MAP = {
    "Low": ["01 TO 03", "01 TO 05", "04 TO 06", "06 TO 10"],
    "Mid": ["07 TO 09", "10 TO 12", "11 TO 15"],
    "High": ["13 TO 15", "16 TO 18", "16 TO 20"],
    "Very High": ["19 TO 21", "21 TO 25", "22 TO 24", "25 TO 27", "26 TO 30",
                  "28 TO 30", "31 TO 33", "31 TO 35", "34 TO 36", "36 TO 40",
                  "37 TO 39", "40 TO 42", "43 TO 45", "46 TO 48", "49 TO 51"],
}


def query_transactions(
    towns: Optional[List[str]] = None,
    flat_types: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    floor_levels: Optional[List[str]] = None,
    floor_area_min: Optional[float] = None,
    floor_area_max: Optional[float] = None,
    lease_remaining_min: Optional[int] = None,
    lease_remaining_max: Optional[int] = None,
    postal_code: Optional[str] = None,
    property_name: Optional[str] = None,
    group_by: str = "month",
    metrics: Optional[List[str]] = None,
) -> Dict:
    """
    Flexible analytics query against hdb_resale_transactions.
    Returns time-series data, summary stats, and breakdowns.
    """
    db = SessionLocal()
    try:
        filters = []
        if towns:
            filters.append(HdbResaleTransaction.town.in_([t.upper() for t in towns]))
        if flat_types:
            filters.append(HdbResaleTransaction.flat_type.in_(flat_types))
        if date_from:
            filters.append(HdbResaleTransaction.month >= date_from)
        if date_to:
            filters.append(HdbResaleTransaction.month <= date_to)
        if price_min is not None:
            filters.append(HdbResaleTransaction.resale_price >= price_min)
        if price_max is not None:
            filters.append(HdbResaleTransaction.resale_price <= price_max)
        if floor_levels:
            storey_values = []
            for level in floor_levels:
                storey_values.extend(STOREY_LEVEL_MAP.get(level, []))
            if storey_values:
                filters.append(HdbResaleTransaction.storey_range.in_(storey_values))
                
        if floor_area_min is not None:
            filters.append(HdbResaleTransaction.floor_area_sqm >= floor_area_min)
        if floor_area_max is not None:
            filters.append(HdbResaleTransaction.floor_area_sqm <= floor_area_max)
            
        if lease_remaining_min is not None or lease_remaining_max is not None:
            import datetime
            current_year = datetime.date.today().year
            if lease_remaining_min is not None:
                min_commence_year = current_year - 99 + lease_remaining_min
                filters.append(HdbResaleTransaction.lease_commence_date >= min_commence_year)
            if lease_remaining_max is not None:
                max_commence_year = current_year - 99 + lease_remaining_max
                filters.append(HdbResaleTransaction.lease_commence_date <= max_commence_year)

        if postal_code:
            pc_digits = "".join(c for c in str(postal_code) if c.isdigit())
            if pc_digits:
                filters.append(HdbAddressEnrichmentOnemap.postal_code.like(f"{pc_digits}%"))

        if property_name:
            filters.append(
                func.lower(HdbAddressEnrichmentOnemap.query_sent) == property_name.lower()
            )

        base_q = db.query(
            HdbResaleTransaction,
            HdbAddressEnrichmentOnemap.postal_code,
            HdbAddressEnrichmentOnemap.latitude,
            HdbAddressEnrichmentOnemap.longitude
        ).outerjoin(
            HdbAddressEnrichmentOnemap,
            HdbResaleTransaction.enriched_addr_id == HdbAddressEnrichmentOnemap.id,
        )
        if filters:
            base_q = base_q.filter(and_(*filters))

        # --- Summary stats ---
        total = base_q.count()
        if total == 0:
            return {"time_series": [], "summary": {"total": 0}, "by_town": [], "by_flat_type": []}

        avg_price = float(base_q.with_entities(func.avg(HdbResaleTransaction.resale_price)).scalar() or 0)
        avg_area = float(base_q.with_entities(func.avg(HdbResaleTransaction.floor_area_sqm)).scalar() or 1)
        min_price = int(base_q.with_entities(func.min(HdbResaleTransaction.resale_price)).scalar() or 0)
        max_price = int(base_q.with_entities(func.max(HdbResaleTransaction.resale_price)).scalar() or 0)
        avg_psf = round((avg_price / avg_area) * 0.092903, 2) if avg_area > 0 else 0

        # --- Time series ---
        if group_by == "year":
            period_expr = func.substr(HdbResaleTransaction.month, 1, 4)
        elif group_by == "quarter":
            period_expr = func.concat(
                func.substr(HdbResaleTransaction.month, 1, 4),
                "-Q",
                cast(func.ceil(cast(func.substr(HdbResaleTransaction.month, 6, 2), Float) / 3), String),
            )
        else:
            period_expr = HdbResaleTransaction.month

        ts_q = base_q.with_entities(
            period_expr.label("period"),
            func.count(HdbResaleTransaction.id).label("txn_count"),
            func.avg(HdbResaleTransaction.resale_price).label("avg_price"),
            func.avg(HdbResaleTransaction.resale_price / HdbResaleTransaction.floor_area_sqm * 0.092903).label("avg_psf"),
            func.min(HdbResaleTransaction.resale_price).label("min_price"),
            func.max(HdbResaleTransaction.resale_price).label("max_price"),
        )
        ts_q = ts_q.group_by("period").order_by("period")

        time_series = [
            {
                "period": str(r.period),
                "txn_count": r.txn_count,
                "avg_price": round(float(r.avg_price)),
                "avg_psf": round(float(r.avg_psf), 2),
                "min_price": int(r.min_price),
                "max_price": int(r.max_price),
            }
            for r in ts_q.all()
        ]

        # --- Breakdown by town ---
        town_q = base_q.with_entities(
            HdbResaleTransaction.town,
            func.count(HdbResaleTransaction.id).label("txn_count"),
            func.avg(HdbResaleTransaction.resale_price).label("avg_price"),
        )
        by_town = [
            {"town": r.town, "txn_count": r.txn_count, "avg_price": round(float(r.avg_price))}
            for r in town_q.group_by(HdbResaleTransaction.town).order_by(desc("txn_count")).all()
        ]

        # --- Breakdown by flat type ---
        ft_q = base_q.with_entities(
            HdbResaleTransaction.flat_type,
            func.count(HdbResaleTransaction.id).label("txn_count"),
            func.avg(HdbResaleTransaction.resale_price).label("avg_price"),
        )
        by_flat_type = [
            {"flat_type": r.flat_type, "txn_count": r.txn_count, "avg_price": round(float(r.avg_price))}
            for r in ft_q.group_by(HdbResaleTransaction.flat_type).order_by(desc("txn_count")).all()
        ]

        # --- Raw Data (Limit 100) ---
        raw_data = []
        raw_q = base_q.order_by(desc(HdbResaleTransaction.month)).limit(100)
        for txn, postal, lat, lng in raw_q.all():
            raw_data.append({
                "month": txn.month,
                "town": txn.town,
                "block": txn.block,
                "street_name": txn.street_name,
                "flat_type": txn.flat_type,
                "storey_range": txn.storey_range,
                "floor_area_sqm": float(txn.floor_area_sqm) if txn.floor_area_sqm else 0,
                "resale_price": int(txn.resale_price) if txn.resale_price else 0,
                "postal_code": postal,
                "latitude": lat,
                "longitude": lng,
                "lease_commence_date": txn.lease_commence_date,
            })

        return {
            "time_series": time_series,
            "summary": {
                "total": total,
                "avg_price": round(avg_price),
                "avg_psf": avg_psf,
                "min_price": min_price,
                "max_price": max_price,
            },
            "by_town": by_town,
            "by_flat_type": by_flat_type,
            "raw_data": raw_data,
        }
    finally:
        db.close()

