"""Recorded HDB resale comparables; never synthesize sales from a model prediction."""

from __future__ import annotations

from collections import Counter
from datetime import date
from math import asin, cos, isfinite, radians, sin, sqrt
from statistics import mean

from sqlalchemy import func
from sqlalchemy.orm import Session

from hdb_storey import parse_storey_range_bounds
from models import HdbAddressEnrichmentOnemap, HdbResaleTransaction

RADIUS_M = 1000
LOOKBACK_MONTHS = 12
AREA_TOLERANCE = 0.15
LEASE_TOLERANCE_YEARS = 10
STOREY_TOLERANCE = 6
MAX_COMPARABLES = 10
MAX_PER_BUILDING = 2


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(min(1.0, max(0.0, h))))


def find_comparable_sales(
    db: Session,
    *,
    predicted_price: float,
    floor_area_sqm: float,
    flat_type: str,
    flat_model: str,
    storey_midpoint: int,
    remaining_lease_years: int,
    latitude: float | None,
    longitude: float | None,
    valuation_month: str,
    subject_postal_code: str | None = None,
) -> dict:
    """Return up to ten actual sales, with at most two records from one building.

    Candidate selection is independent of predicted price. It requires matching
    flat type, a 1 km radius, the last 12 calendar months, area ±15%, estimated
    current lease ±10 years, and storey-band midpoint ±6 floors. Similarity,
    recency, distance, and transaction ID provide deterministic ranking.
    """
    as_of = date.fromisoformat(valuation_month + "-01")
    first_month_number = as_of.year * 12 + as_of.month - LOOKBACK_MONTHS
    first_year, first_month = divmod(first_month_number, 12)
    date_from = f"{first_year:04d}-{first_month + 1:02d}"
    result = {
        "status": "no_matches",
        "source": {
            "name": "HDB recorded resale transactions",
            "url": "https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view",
        },
        "criteria": {
            "radius_m": RADIUS_M, "date_from": date_from, "date_to": valuation_month,
            "flat_type": flat_type, "area_tolerance_pct": int(AREA_TOLERANCE * 100),
            "lease_tolerance_years": LEASE_TOLERANCE_YEARS,
            "storey_midpoint_tolerance": STOREY_TOLERANCE,
            "max_per_building": MAX_PER_BUILDING,
        },
        "subject_property": {
            "price": round(predicted_price, 2), "floor_area": floor_area_sqm,
            "price_per_sqm": round(predicted_price / floor_area_sqm, 2) if floor_area_sqm > 0 else None,
        },
        "similar_properties": [],
        "match_count": 0,
        "average_neighbor_price": None,
        "average_price_per_sqm": None,
        "market_position": None,
        "price_percentile": None,
    }
    if (latitude is None or longitude is None or not isfinite(latitude) or not isfinite(longitude)
            or not (-90 <= latitude <= 90 and -180 <= longitude <= 180)):
        result.update(status="unavailable", reason="location_missing")
        return result
    if not isfinite(floor_area_sqm) or floor_area_sqm <= 0 or not isfinite(predicted_price) or predicted_price <= 0:
        result.update(status="unavailable", reason="invalid_unit_details")
        return result

    lat_delta = RADIUS_M / 110_500
    lon_delta = RADIUS_M / (110_500 * max(abs(cos(radians(latitude))), 0.01))
    normalized_type = " ".join(flat_type.upper().replace("-", " ").split())
    candidates = (
        db.query(HdbResaleTransaction, HdbAddressEnrichmentOnemap)
        .join(HdbAddressEnrichmentOnemap, HdbResaleTransaction.enriched_addr_id == HdbAddressEnrichmentOnemap.id)
        .filter(
            HdbResaleTransaction.month.between(date_from, valuation_month),
            func.upper(func.replace(func.trim(HdbResaleTransaction.flat_type), "-", " ")) == normalized_type,
            HdbResaleTransaction.floor_area_sqm.between(floor_area_sqm * (1 - AREA_TOLERANCE), floor_area_sqm * (1 + AREA_TOLERANCE)),
            HdbResaleTransaction.resale_price > 0,
            HdbAddressEnrichmentOnemap.latitude.between(latitude - lat_delta, latitude + lat_delta),
            HdbAddressEnrichmentOnemap.longitude.between(longitude - lon_delta, longitude + lon_delta),
        )
        .all()
    )
    ranked = []
    for sale, address in candidates:
        if not isfinite(address.latitude) or not isfinite(address.longitude):
            continue
        distance = _distance_m(latitude, longitude, address.latitude, address.longitude)
        if distance > RADIUS_M:
            continue
        try:
            sale_month = date.fromisoformat(sale.month + "-01")
        except (TypeError, ValueError):
            continue
        storeys = parse_storey_range_bounds(sale.storey_range)
        if not storeys:
            continue
        floor_gap = abs((storeys[0] + storeys[1]) / 2 - storey_midpoint)
        if floor_gap > STOREY_TOLERANCE:
            continue
        if sale.lease_commence_date is not None:
            current_lease = max(0, min(99, 99 - (as_of.year - sale.lease_commence_date)))
        elif sale.remaining_lease_years is not None:
            elapsed_years = ((as_of.year - sale_month.year) * 12 + as_of.month - sale_month.month) / 12
            current_lease = max(0, sale.remaining_lease_years - elapsed_years)
        else:
            continue
        lease_gap = abs(current_lease - remaining_lease_years)
        if lease_gap > LEASE_TOLERANCE_YEARS:
            continue
        age_months = (as_of.year - sale_month.year) * 12 + as_of.month - sale_month.month
        area_gap = abs(sale.floor_area_sqm - floor_area_sqm) / floor_area_sqm
        same_model = (sale.flat_model or "").strip().upper() == flat_model.strip().upper()
        score = (area_gap / AREA_TOLERANCE + floor_gap / STOREY_TOLERANCE
                 + lease_gap / LEASE_TOLERANCE_YEARS + distance / RADIUS_M
                 + age_months / LOOKBACK_MONTHS + (0 if same_model else 0.5))
        building = address.postal_code or f"{sale.block} {sale.street_name}"
        row = {
            "transaction_id": sale.id,
            "address": f"{sale.block or ''} {sale.street_name or ''}".strip(),
            "postal_code": address.postal_code,
            "sale_month": sale.month,
            "storey_range": sale.storey_range,
            "flat_type": sale.flat_type,
            "flat_model": sale.flat_model,
            "floor_area": sale.floor_area_sqm,
            "price": sale.resale_price,
            "price_per_sqm": round(sale.resale_price / sale.floor_area_sqm, 2),
            "distance_m": round(distance),
            "same_building": bool(subject_postal_code and address.postal_code == subject_postal_code),
            "difference_pct": round((sale.resale_price / predicted_price - 1) * 100, 1),
        }
        ranked.append(((score, -sale_month.toordinal(), distance, sale.id), building, row))

    counts = Counter()
    selected = []
    for _score, building, row in sorted(ranked, key=lambda item: item[0]):
        if counts[building] >= MAX_PER_BUILDING:
            continue
        counts[building] += 1
        selected.append(row)
        if len(selected) == MAX_COMPARABLES:
            break
    if not selected:
        return result

    average = mean(row["price"] for row in selected)
    average_psm = mean(row["price"] / row["floor_area"] for row in selected)
    subject_psm = predicted_price / floor_area_sqm
    gap = (subject_psm / average_psm - 1) * 100
    position = "In line with comparable sales" if abs(gap) <= 5 else (
        "Above comparable sales" if gap > 0 else "Below comparable sales"
    )
    result.update(
        status="ok", similar_properties=selected, match_count=len(ranked),
        average_neighbor_price=round(average, 2), average_price_per_sqm=round(average_psm, 2),
        market_position=position,
        price_percentile=round(100 * sum(row["price"] / row["floor_area"] <= subject_psm for row in selected) / len(selected), 1),
    )
    return result
